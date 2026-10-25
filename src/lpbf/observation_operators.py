"""Patch 22.4.3.2 reading S: the Patch 22.3.8 synthetic camera on the selected candidate's captured fields.

Secondary and descriptive, as predeclared in ``docs/patches/22.4.3.2/PATCH_22_4_3_2_PLAN.md`` ("S, secondary
synthetic camera"). This module was written and committed after the selection freeze and before the evaluation stage
opened any held-out member. The rules below are fixed in code:

* **Settings.** Two cases of the 22.3.8 Step-3 machinery: 850 nm, uniform emissivity, PSF sigma 0 and 2.0 px.
* **Camera side.** Each member's own layer-53 frames, read only at that member's scored frames (the evaluate unit's
  frame records) and measured with the Step-0 convention: threshold levels, the largest 8-connected component and
  ``minAreaRect``.
* **T150.** Fixed once per case on the 9 calibration members by the 22.3.8 closest-approach rule: the grid T150
  where the median model/camera H/W at threshold 150 is closest to 1, with synthetic coverage of at least 95 %.
  - The held-out and out-of-window members are rendered at that T150 only, so nothing about them can move it.
  - A case with no grid point at that coverage is reported unavailable and is not evaluated.
* **Per frame.** The threshold-150 synthetic H/W against the camera's threshold-150 H/W, through objective contract
  22.4.3.2's log-ratio hierarchy with its 1 px floor.
  - A frame whose camera blob is absent or touches the image edge is ineligible: excluded and counted.
  - A frame whose synthetic blob is absent or touches an edge is undefined: it counts against coverage (A23 floor
    95 %, flagged) and is never fabricated.
* **Reported.** Per group (calibration, in-window held-out, the cross-campaign member, out-of-window examined and
  blind) and per out-of-window coupon, beside the production liquidus operator on the same evaluate units.

Only the evaluation stage's members are read, and only after the committed freeze verifies and the evaluate stage is
complete for it. No thermal model runs and no parameter is fitted or selected. T150 is set by the predeclared rule
above, never by a held-out member. Production semantics are untouched.
"""
from __future__ import annotations

import argparse
import json
import math
import platform
import sys
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import cv2
import numpy as np

import lpbf.calibration as w
import lpbf.synthetic_camera as cam
from lpbf.camera_observations import PRODUCTION_LAYER, _read_member_frames, measure_blob
from lpbf.camera_observations import calibration_member_identities as step0_members
from lpbf.execution.parallel import execute_parallel_jobs
from lpbf.execution.work_units import SimulationJob, SimulationResult, execute_serial_jobs
from lpbf.hierarchical_objective import COVERAGE_FLOOR, HierarchicalObjectiveError
from lpbf.infrastructure import git_metadata, sha256_file
from lpbf.log_ratio_objective import OBJECTIVE_CONTRACT_VERSION, PIXEL_FLOOR, aggregate_log_ratio_records

STAGE = "synthetic"
SCHEMA = "lpbf_patch22_4_3_2_synthetic_camera"
S_CASE_IDS = ("lam850_uniform_sig0.0", "lam850_uniform_sig2.0")
REFERENCE_THRESHOLD = cam.REFERENCE_THRESHOLD
T150_RULE = "22.3.8 closest approach on the 9 calibration members: |ln(median model/camera H/W at 150)| minimal, coverage at 150 >= 95 %"
GROUPS = (
    ("calibration", w.CALIBRATION_MEMBERS),
    ("in_window_held_out", w.IN_WINDOW_HELD_OUT),
    ("cross_campaign_20260904_part_5", (w.CROSS_CAMPAIGN_HELD_OUT,)),
    ("out_of_window_examined", w.OUT_OF_WINDOW_EXAMINED),
    ("out_of_window_blind", w.OUT_OF_WINDOW_BLIND),
)
PAIRED = "PAIRED"
SYNTHETIC_ABSENT = "SYNTHETIC_ABSENT"
SYNTHETIC_EDGE = "SYNTHETIC_EDGE"
CAMERA_INVALID = "CAMERA_BLOB_150_ABSENT_OR_EDGE"
READING_S = "S_DESCRIPTIVE"
READING_S_UNAVAILABLE = "S_UNAVAILABLE"
RECORD_KEYS = (
    "acquisition_set_id",
    "exact_condition_id",
    "frame_index",
    "member_identity",
    "observation_eligible",
    "observation_status",
    "part_number",
    "power_W",
    "speed_mm_s",
    "scan_track_id",
    "scored_frame",
    "scored_frame_rule_version",
    "status",
    "experimental_H_pixels",
    "experimental_W_pixels",
)

ProgressCallback = Callable[[int, int, str, str], None]


class SyntheticCameraError(RuntimeError):
    """Fail-closed error for reading S."""


# ---------------------------------------------------------------------- camera side


def measure_camera_frames(images: Sequence[np.ndarray], frame_indices: Sequence[int]) -> dict[str, list[Any]]:
    """Step-0 convention on each frame's raw image, laid out like ``patch22_3_8_synthetic_camera.load_camera_frames``."""

    nan = float("nan")
    entry: dict[str, list[Any]] = {"frame_index": [], "centroid_x": [], "centroid_y": [], "sat": [], "has_blob_150": []}
    entry.update({f"{key}_{t}": [] for t in cam.MATCH_THRESHOLDS for key in ("H", "W", "edge")})
    if len(images) != len(frame_indices):
        raise SyntheticCameraError("image count does not match the frame count")
    for frame, image in zip(frame_indices, images):
        image = np.asarray(image)
        if image.shape != (cam.CAMERA_ROWS, cam.CAMERA_COLS):
            raise SyntheticCameraError(f"camera frame {frame} is {image.shape}, expected {(cam.CAMERA_ROWS, cam.CAMERA_COLS)}")
        entry["frame_index"].append(int(frame))
        for t in cam.MATCH_THRESHOLDS:
            blob = measure_blob(image, t)
            entry[f"H_{t}"].append(blob["H_px"] if blob else nan)
            entry[f"W_{t}"].append(blob["W_px"] if blob else nan)
            entry[f"edge_{t}"].append(bool(blob["touches_edge"]) if blob else False)
            if t == REFERENCE_THRESHOLD:
                entry["has_blob_150"].append(blob is not None)
                entry["centroid_x"].append(blob["centroid_x"] if blob else nan)
                entry["centroid_y"].append(blob["centroid_y"] if blob else nan)
                entry["sat"].append(blob["saturated_px"] / blob["area_px"] if blob else nan)
    return entry


# ---------------------------------------------------------------------- synthetic side


def synthesize_unit(
    arrays: Mapping[str, np.ndarray],
    camera_entry: Mapping[str, Sequence[Any]],
    *,
    mapping_constant_deg: float,
    t150_grid: Sequence[float],
    case_ids: Sequence[str] = S_CASE_IDS,
) -> dict[str, Any]:
    """Per-frame threshold-150 synthetic and camera H/W, plus the 22.3.8 member aggregate (pure; no file access)."""

    frames = [int(value) for value in np.asarray(arrays["frame_index"])]
    position = {int(frame): k for k, frame in enumerate(camera_entry["frame_index"])}
    if len(position) != len(camera_entry["frame_index"]) or len(set(frames)) != len(frames) or set(frames) != set(position):
        raise SyntheticCameraError("captured frames differ from the measured camera frames")
    camera = cam.camera_arrays(camera_entry, [position[frame] for frame in frames])
    fields = np.asarray(arrays["top_surface_temperature_K"], dtype=np.float64)
    liquidus = float(arrays["liquidus_temperature_K"])
    cell_um = float(arrays["cell_size_um"])
    offsets = cam.subsample_offsets_um(mapping_constant_deg)
    default_centroid = (float(np.nanmedian(camera["centroid_x"])), float(np.nanmedian(camera["centroid_y"])))
    stacked: dict[str, list[np.ndarray]] = {"H": [], "W": [], "edge": [], "sat": []}
    for f in range(len(frames)):
        t_sub, inside_sub = cam.render_temperature_subsamples(
            fields[f],
            source_x_mm=float(arrays["source_center_x_mm"][f]),
            source_y_mm=float(arrays["source_center_y_mm"][f]),
            cell_um=cell_um,
            offsets=offsets,
        )
        cx, cy = float(camera["centroid_x"][f]), float(camera["centroid_y"][f])
        centroid = (cx, cy) if math.isfinite(cx) and math.isfinite(cy) else default_centroid
        out = cam.synthesize_frame(t_sub, inside_sub, liquidus_K=liquidus, camera_centroid=centroid, t150_grid=t150_grid, case_ids=case_ids)
        for key in stacked:
            stacked[key].append(out[key])
    synthetic = {key: np.stack(values) for key, values in stacked.items()}
    ref = cam.MATCH_THRESHOLDS.index(REFERENCE_THRESHOLD)
    return {
        "frame_index": frames,
        "t150_grid": [float(value) for value in t150_grid],
        "case_ids": [case["case_id"] for case in cam.select_cases(case_ids)],
        "liquidus_K": liquidus,
        "aggregate": cam.aggregate_member(synthetic, camera),
        "H150": synthetic["H"][..., ref],
        "W150": synthetic["W"][..., ref],
        "edge150": synthetic["edge"][..., ref],
        "camera_H150": camera["H"][:, ref],
        "camera_W150": camera["W"][:, ref],
        "camera_valid150": camera["valid"][:, ref],
    }


def _synthetic_unit_job(job: SimulationJob) -> dict[str, Any]:
    """Spawn-safe worker: one member's field file and its own camera frames; writes nothing."""

    context = job.experiment_context_dict
    field_file = Path(context["field_file"])
    if sha256_file(field_file) != context["field_sha256"]:
        raise SyntheticCameraError(f"field file hash differs from the evaluate unit record: {field_file}")
    with np.load(field_file, allow_pickle=False) as handle:
        arrays = {key: handle[key] for key in handle.files}
    frames = [int(value) for value in arrays["frame_index"]]
    if frames != [int(value) for value in context["frames"]]:
        raise SyntheticCameraError(f"{job.member_identity}: captured frames differ from the unit's scored frames")
    order = sorted(frames)
    raw = _read_member_frames(Path(context["member_path"]), PRODUCTION_LAYER, order)
    by_frame = {frame: image for frame, image in zip(order, raw["images"])}
    camera_entry = measure_camera_frames([by_frame[frame] for frame in frames], frames)
    rows = np.asarray(arrays["mapped_process_row"], dtype=np.int64)
    maps_back = float(np.mean(np.asarray(raw["data_to_frame"])[rows] == np.asarray(frames)))
    result = synthesize_unit(
        arrays,
        camera_entry,
        mapping_constant_deg=float(context["mapping_constant_deg"]),
        t150_grid=tuple(float(value) for value in context["t150_grid"]),
        case_ids=tuple(context["case_ids"]),
    )
    result.update({"member_identity": job.member_identity, "camera": camera_entry, "row_maps_back_to_frame_fraction": maps_back})
    return result


# ---------------------------------------------------------------------- T150, frame records, scores


def fix_t150(calibration: Mapping[str, Mapping[str, Any]], members: Sequence[str], grid: Sequence[float]) -> dict[str, dict[str, Any]]:
    """Per case, the predeclared closest approach on the calibration members (first grid point on a tie)."""

    cases = cam.select_cases(S_CASE_IDS)
    scope = cam.evaluate_scope(list(members), calibration, with_trends=False)
    ref = cam.MATCH_THRESHOLDS.index(REFERENCE_THRESHOLD)
    out: dict[str, dict[str, Any]] = {}
    for c, case in enumerate(cases):
        value = np.asarray(scope["M1_value"][c, :, ref], dtype=np.float64)
        coverage = np.nan_to_num(np.asarray(scope["coverage"][c, :, ref], dtype=np.float64), nan=0.0)
        ok = np.isfinite(value) & (coverage >= cam.COVERAGE_FLOOR)
        item: dict[str, Any] = {"case": dict(case), "rule": T150_RULE, "max_coverage_150": float(coverage.max()) if coverage.size else None}
        if not ok.any():
            out[case["case_id"]] = {**item, "available": False, "T150_K": None}
            continue
        distance = np.where(ok, np.abs(np.log(np.where(ok, value, 1.0))), np.inf)
        k = int(np.argmin(distance))
        out[case["case_id"]] = {
            **item,
            "available": True,
            "T150_K": float(grid[k]),
            "grid_index": k,
            "M1_HW_ratio_150": float(value[k]),
            "coverage_150": float(coverage[k]),
            "M1_HW_ratio_by_threshold": {str(t): float(scope["M1_value"][c, k, i]) for i, t in enumerate(cam.MATCH_THRESHOLDS)},
        }
    return out


def synthetic_frame_records(unit_records: Sequence[Mapping[str, Any]], synthetic: Mapping[str, Any], *, case_index: int, grid_index: int) -> list[dict[str, Any]]:
    """The unit's frame records with the synthetic threshold-150 H/W as the prediction and the camera's as the observation."""

    position = {int(frame): k for k, frame in enumerate(synthetic["frame_index"])}
    out: list[dict[str, Any]] = []
    for record in unit_records:
        row = {key: record[key] for key in RECORD_KEYS if key in record}
        status = str(record.get("status"))
        if not bool(record.get("scored_frame")):
            out.append(row)
            continue
        if status not in ("PASS", "UNDEFINED"):
            raise SyntheticCameraError(f"scored frame {record.get('frame_index')} has status {status!r}")
        frame = int(record["frame_index"])
        if frame not in position:
            raise SyntheticCameraError(f"scored frame {frame} has no synthetic measurement")
        f = position[frame]
        h = float(synthetic["H150"][f, case_index, grid_index])
        wv = float(synthetic["W150"][f, case_index, grid_index])
        row["stored_experimental_H_pixels"] = record.get("experimental_H_pixels")
        row["stored_experimental_W_pixels"] = record.get("experimental_W_pixels")
        if not bool(synthetic["camera_valid150"][f]):
            row.update({"status": "UNDEFINED", "observation_eligible": False, "observation_status": "INELIGIBLE_" + CAMERA_INVALID, "synthetic_status": CAMERA_INVALID})
            out.append(row)
            continue
        row["experimental_H_pixels"] = float(synthetic["camera_H150"][f])
        row["experimental_W_pixels"] = float(synthetic["camera_W150"][f])
        if not (math.isfinite(h) and math.isfinite(wv)):
            row.update({"status": "UNDEFINED", "synthetic_status": SYNTHETIC_ABSENT})
        elif bool(synthetic["edge150"][f, case_index, grid_index]):
            row.update({"status": "UNDEFINED", "synthetic_status": SYNTHETIC_EDGE})
        else:
            row.update({"status": "PASS", "simulated_H_pixels": h, "simulated_W_pixels": wv, "synthetic_status": PAIRED})
        out.append(row)
    return out


def score_records(records: Sequence[Mapping[str, Any]], members: Sequence[str], label: str) -> dict[str, Any]:
    """Objective contract 22.4.3.2 over one member group (the same hierarchy, floor and coverage as the liquidus scores)."""

    conditions = sorted({w.member_records()[m]["condition_id"] for m in members})
    status_counts: dict[str, int] = {}
    for row in records:
        if "synthetic_status" in row:
            status_counts[row["synthetic_status"]] = status_counts.get(row["synthetic_status"], 0) + 1
    try:
        log = aggregate_log_ratio_records(records, member_ids=list(members), condition_ids=conditions, require_complete=True, candidate_id=label)
    except HierarchicalObjectiveError as exc:
        return {"status": f"ERROR: {exc}", "synthetic_status_counts": dict(sorted(status_counts.items()))}
    counts = log.get("counts") or {}
    return {
        "status": log["status"],
        "J": log["objective_value"],
        "e_H": log["e_H"],
        "e_W": log["e_W"],
        "coverage": counts.get("coverage"),
        "coverage_by_coupon": counts.get("coverage_by_coupon"),
        "coverage_flag": log.get("coverage_flag"),
        "low_coverage_coupons": log.get("low_coverage_coupons"),
        "scored_frame_count": counts.get("scored_frame_count"),
        "floored_frame_count": counts.get("floored_frame_count"),
        "synthetic_status_counts": dict(sorted(status_counts.items())),
        "condition_rows": [
            {key: row.get(key) for key in ("exact_condition_id", "member_identities", "e_H", "e_W", "median_H_ratio", "median_W_ratio", "H_mean_log", "W_mean_log")}
            for row in log.get("condition_rows") or []
        ],
        "coupon_rows": [
            {key: row.get(key) for key in ("member_identity", "exact_condition_id", "coverage", "scored_frame_count", "e_H", "e_W", "median_r_H", "median_r_W", "median_H_ratio", "median_W_ratio")}
            for row in log.get("coupon_rows") or []
        ],
    }


def _liquidus_summary(score: Mapping[str, Any]) -> dict[str, Any]:
    keys = ("status", "J", "e_H", "e_W", "coverage", "coverage_flag", "scored_frame_count", "floored_frame_count", "condition_rows", "coupon_rows")
    return {key: score.get(key) for key in keys}


def out_of_window_rows(synthetic_scores: Mapping[str, Mapping[str, Any]], liquidus_scores: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Per out-of-window coupon: both operators side by side, against P, v and VED."""

    records = w.member_records()
    rows = []
    for m in w.OUT_OF_WINDOW:
        s_row = ((synthetic_scores.get(m) or {}).get("coupon_rows") or [{}])[0]
        l_row = ((liquidus_scores.get(m) or {}).get("coupon_rows") or [{}])[0]
        rows.append(
            {
                "member_identity": m,
                "group": "blind" if m in w.OUT_OF_WINDOW_BLIND else "examined",
                **{key: records[m][key] for key in ("condition_id", "power_W", "speed_mm_s", "ved_J_mm3")},
                "synthetic_median_r_H": s_row.get("median_r_H"),
                "synthetic_median_r_W": s_row.get("median_r_W"),
                "synthetic_e_H": (synthetic_scores.get(m) or {}).get("e_H"),
                "synthetic_e_W": (synthetic_scores.get(m) or {}).get("e_W"),
                "synthetic_coverage": s_row.get("coverage"),
                "liquidus_median_r_H": l_row.get("median_r_H"),
                "liquidus_median_r_W": l_row.get("median_r_W"),
                "liquidus_e_H": (liquidus_scores.get(m) or {}).get("e_H"),
                "liquidus_e_W": (liquidus_scores.get(m) or {}).get("e_W"),
            }
        )
    return rows


def _spearman_on_ved(rows: Sequence[Mapping[str, Any]], key: str) -> float | None:
    usable = [r for r in rows if r.get(key) is not None]
    if len(usable) != len(rows) or len(usable) < 3:
        return None
    rho = w.spearman_rho([float(r["ved_J_mm3"]) for r in usable], [float(r[key]) for r in usable])
    return rho if math.isfinite(rho) else None


# ---------------------------------------------------------------------- stage


def _execute(jobs: Sequence[SimulationJob], workers: int, progress: ProgressCallback | None, phase: str) -> dict[str, dict[str, Any]]:
    total = len(jobs)
    done = {"count": 0}

    def on_result(result: SimulationResult) -> None:
        done["count"] += 1
        if progress is not None:
            progress(done["count"], total, phase, result.job.member_identity)

    effective = max(1, min(int(workers), total))
    if effective == 1:
        completed = execute_serial_jobs(jobs, _synthetic_unit_job, on_result=on_result)
    else:
        completed = execute_parallel_jobs(jobs, _synthetic_unit_job, workers=effective, on_result=on_result)
    return {result.job.member_identity: result.payload for result in completed}


def build_jobs(members: Sequence[str], payloads: Mapping[str, Mapping[str, Any]], member_paths: Mapping[str, str], evaluate_directory: Path, *, t150_grid: Sequence[float], mapping_constant_deg: float, offset: int = 0) -> list[SimulationJob]:
    jobs = []
    for index, m in enumerate(sorted(members)):
        payload = payloads[m]
        capture = payload.get("capture_file") or {}
        if not capture:
            raise SyntheticCameraError(f"evaluate unit for {m} has no field file")
        frames = sorted(int(r["frame_index"]) for r in payload["frame_records"] if r.get("scored_frame"))
        jobs.append(
            SimulationJob(
                case_index=offset + index,
                member_identity=m,
                frame_index=0,
                window_cells=w.WINDOW_CELLS,
                candidate_coordinates=(),
                experiment_context={
                    "field_file": str((evaluate_directory / capture["path"]).resolve()),
                    "field_sha256": str(capture["sha256"]),
                    "member_path": str(member_paths[m]),
                    "frames": frames,
                    "t150_grid": [float(value) for value in t150_grid],
                    "case_ids": list(S_CASE_IDS),
                    "mapping_constant_deg": float(mapping_constant_deg),
                },
                work_unit_id=f"{w.PATCH_VERSION}:{STAGE}:{payload['candidate_id']}@{m}",
            )
        )
    return jobs


def _check_evaluate_manifest(manifest: Mapping[str, Any], freeze: Mapping[str, Any], freeze_sha256: str) -> str:
    if manifest.get("stage") != "evaluate" or not manifest.get("complete"):
        raise SyntheticCameraError("the evaluate stage is not complete")
    if manifest.get("freeze_sha256") != str(freeze_sha256).strip().lower() or manifest.get("freeze_content_sha256") != freeze.get("content_sha256"):
        raise SyntheticCameraError("the evaluate stage was run against a different freeze")
    selected = str(freeze["selected"]["candidate_id"])
    if manifest.get("selected") != selected:
        raise SyntheticCameraError("the evaluate stage selected a different candidate")
    return selected


def run_synthetic(
    *,
    data_directory: str | Path,
    output_directory: str | Path,
    freeze_file: str | Path,
    freeze_sha256: str,
    workers: int = w.DEFAULT_WORKERS,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Reading S on the selected candidate's 24 captured units (9 calibration, then 15 evaluation members)."""

    workers = w._validated_workers(workers)
    freeze = w.verify_committed_freeze(freeze_file, freeze_sha256)
    output = Path(output_directory).expanduser().resolve()
    evaluate_directory = output / "evaluate"
    manifest_path = evaluate_directory / "stage_manifest.json"
    if not manifest_path.is_file():
        raise SyntheticCameraError(f"evaluate stage manifest not found: {manifest_path}")
    evaluate_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    selected = _check_evaluate_manifest(evaluate_manifest, freeze, freeze_sha256)
    member_ids = w.require_stage_members("evaluate", (*w.CALIBRATION_MEMBERS, *w.EVALUATION_MEMBERS), freeze_verified=True)
    loaded = w.load_units(evaluate_directory, [(selected, m) for m in member_ids])
    payloads = {m: loaded[(selected, m)] for m in member_ids}
    incomplete = sorted(m for m, p in payloads.items() if not w._unit_ok(p) or not p.get("capture_file"))
    if incomplete:
        raise SyntheticCameraError(f"evaluate units incomplete or without fields: {incomplete}")
    members = w.resolve_members(data_directory, member_ids)
    mismatched = sorted(m for m in member_ids if members[m].sha256 != payloads[m]["member_sha256"])
    if mismatched:
        raise SyntheticCameraError(f"coupon files differ from the ones the evaluate units read: {mismatched}")
    paths = {m: str(members[m].path) for m in member_ids}
    mapping = cam.load_image_mapping()
    constant = float(mapping["full_circle_constant_deg"])
    started = time.monotonic()

    calibration_jobs = build_jobs(w.CALIBRATION_MEMBERS, payloads, paths, evaluate_directory, t150_grid=cam.T150_GRID_K, mapping_constant_deg=constant)
    calibration = _execute(calibration_jobs, workers, progress, "calibration")
    t150 = fix_t150(calibration, w.CALIBRATION_MEMBERS, cam.T150_GRID_K)
    reference = cam._closest_approach(cam.evaluate_scope(list(w.CALIBRATION_MEMBERS), calibration, with_trends=False), cam.select_cases(S_CASE_IDS))
    for item in reference:
        if item["available"] != t150[item["case_id"]]["available"] or (item["available"] and item["T150_K"] != t150[item["case_id"]]["T150_K"]):
            raise SyntheticCameraError(f"T150 rule disagrees with the 22.3.8 closest approach for {item['case_id']}")
    available = [case_id for case_id in S_CASE_IDS if t150[case_id]["available"]]
    evaluation: dict[str, dict[str, Any]] = {}
    eval_grid = sorted({t150[case_id]["T150_K"] for case_id in available})
    if eval_grid:
        evaluation_jobs = build_jobs(w.EVALUATION_MEMBERS, payloads, paths, evaluate_directory, t150_grid=eval_grid, mapping_constant_deg=constant, offset=len(calibration_jobs))
        evaluation = _execute(evaluation_jobs, workers, progress, "evaluation")
    results = {**calibration, **evaluation}

    camera_checks = cam.check_camera_against_step0_evidence({m: results[m]["camera"] for m in results if m in set(step0_members())})
    cases: dict[str, Any] = {}
    frame_rows: list[dict[str, Any]] = []
    for c, case_id in enumerate(S_CASE_IDS):
        if case_id not in available:
            cases[case_id] = {"available": False, "t150": t150[case_id]}
            continue
        records: dict[str, list[dict[str, Any]]] = {}
        for m, result in results.items():
            grid_index = result["t150_grid"].index(t150[case_id]["T150_K"])
            records[m] = synthetic_frame_records(payloads[m]["frame_records"], result, case_index=c, grid_index=grid_index)
            for row in records[m]:
                if "synthetic_status" in row:
                    frame_rows.append(
                        {
                            "case_id": case_id,
                            "T150_K": t150[case_id]["T150_K"],
                            **{key: row.get(key) for key in ("member_identity", "scan_track_id", "frame_index", "synthetic_status", "simulated_H_pixels", "simulated_W_pixels", "experimental_H_pixels", "experimental_W_pixels", "stored_experimental_H_pixels", "stored_experimental_W_pixels")},
                        }
                    )
        groups = {name: score_records([r for m in group for r in records[m]], group, f"{selected}:{case_id}:{name}") for name, group in GROUPS}
        per_coupon = {m: score_records(records[m], [m], f"{selected}:{case_id}:{m}") for m in w.OUT_OF_WINDOW}
        cases[case_id] = {"available": True, "t150": t150[case_id], "groups": groups, "per_coupon": per_coupon}

    liquidus_groups = {}
    for name, group in GROUPS:
        conditions = sorted({w.member_records()[m]["condition_id"] for m in group})
        liquidus_groups[name] = _liquidus_summary(w.score_candidate(selected, [payloads[m] for m in group], member_ids=list(group), condition_ids=conditions))
    liquidus_per_coupon = {
        m: _liquidus_summary(w.score_candidate(selected, [payloads[m]], member_ids=[m], condition_ids=[w.member_records()[m]["condition_id"]])) for m in w.OUT_OF_WINDOW
    }
    for case_id in available:
        rows = out_of_window_rows(cases[case_id]["per_coupon"], liquidus_per_coupon)
        cases[case_id]["out_of_window"] = rows
        cases[case_id]["out_of_window_spearman_on_ved_descriptive"] = {
            key: _spearman_on_ved(rows, key) for key in ("synthetic_median_r_H", "synthetic_median_r_W", "liquidus_median_r_H", "liquidus_median_r_W")
        }

    stage_directory = output / STAGE
    stage_directory.mkdir(parents=True, exist_ok=True)
    if frame_rows:
        cam._write_csv(stage_directory / "synthetic_frames.csv.gz", frame_rows, compress=True)
    manifest = {
        "schema": SCHEMA,
        "patch": w.PATCH_VERSION,
        "stage": STAGE,
        "reading_S": READING_S if available else READING_S_UNAVAILABLE,
        "selected": selected,
        "cases": cases,
        "liquidus": {"groups": liquidus_groups, "per_coupon": liquidus_per_coupon},
        "units": [
            {
                "member_identity": m,
                "phase": "calibration" if m in w.CALIBRATION_MEMBERS else "evaluation",
                "t150_grid_size": len(results[m]["t150_grid"]),
                "frames": len(results[m]["frame_index"]),
                "row_maps_back_to_frame_fraction": results[m]["row_maps_back_to_frame_fraction"],
                "field_sha256": payloads[m]["capture_file"]["sha256"],
            }
            for m in sorted(results)
        ],
        "inputs": {
            "freeze_sha256": str(freeze_sha256).strip().lower(),
            "freeze_content_sha256": freeze["content_sha256"],
            "evaluate_manifest_sha256": sha256_file(manifest_path),
            "member_sha256": {m: members[m].sha256 for m in member_ids},
            "camera_checks_against_step0_evidence": camera_checks,
            "members_without_step0_reference": sorted(set(results) - set(step0_members())),
            "image_mapping": mapping,
        },
        "parameters": {
            "cases": [dict(case) for case in cam.select_cases(S_CASE_IDS)],
            "t150_rule": T150_RULE,
            "t150_calibration_grid_K": list(cam.T150_GRID_K),
            "reference_threshold": REFERENCE_THRESHOLD,
            "coverage_floor": COVERAGE_FLOOR,
            "synthetic_coverage_floor": cam.COVERAGE_FLOOR,
            "objective_contract_version": OBJECTIVE_CONTRACT_VERSION,
            "pixel_floor": PIXEL_FLOOR,
        },
        "execution": {
            "requested_workers": workers,
            "start_method": "serial" if workers == 1 else "spawn",
            "units": len(results),
            "wall_time_s": round(time.monotonic() - started, 1),
        },
        "provenance": {
            "git_commit": git_metadata(w.REPO_ROOT)["commit"],
            "git_worktree_dirty": git_metadata(w.REPO_ROOT)["worktree_dirty"],
            "module_sha256": sha256_file(Path(__file__)),
            "synthetic_camera_module_sha256": sha256_file(Path(cam.__file__)),
            "plan_sha256": sha256_file(w.PLAN_PATH) if w.PLAN_PATH.is_file() else "unavailable",
            "runtime": {"python": sys.version.split()[0], "numpy": np.__version__, "opencv": cv2.__version__, "platform": platform.platform()},
            "campaign_dispatch_lock": w.dispatch_lock_check(),
        },
        "guardrails": {
            "held_out_read_after_committed_freeze_and_complete_evaluate_only": True,
            "t150_fixed_on_calibration_members_only": True,
            "evaluation_members_rendered_at_fixed_t150_only": all(len(results[m]["t150_grid"]) == len(eval_grid) for m in evaluation),
            "thermal_model_run": False,
            "parameter_fitting_performed": False,
            "production_semantics_changed": False,
            "full_campaign_dispatched": False,
            "workers_wrote_files": False,
        },
    }
    cam._write_json(stage_directory / "stage_manifest.json", manifest)
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Patch 22.4.3.2 reading S: synthetic camera on the evaluate stage's captured fields")
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--output-dir", default=w.DEFAULT_OUTPUT_DIRECTORY)
    parser.add_argument("--freeze-file", required=True)
    parser.add_argument("--freeze-sha256", required=True)
    parser.add_argument("--workers", type=int, default=w.DEFAULT_WORKERS, help="Windows-spawn workers (default 4; 1 = serial)")
    args = parser.parse_args(argv)

    def progress(done: int, total: int, phase: str, member: str) -> None:
        print(f"{phase} unit {done}/{total}: {member}", flush=True)

    try:
        manifest = run_synthetic(
            data_directory=args.data_dir, output_directory=args.output_dir, freeze_file=args.freeze_file, freeze_sha256=args.freeze_sha256, workers=args.workers, progress=progress
        )
    except (w.WindowCalibrationError, SyntheticCameraError, cam.Step3Error) as exc:
        print(f"FAIL_PATCH_22_4_3_2_SYNTHETIC: {exc}", file=sys.stderr)
        return 1
    summary = {"reading_S": manifest["reading_S"], "t150": {k: v["t150"].get("T150_K") for k, v in manifest["cases"].items()}, "execution": manifest["execution"]}
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
