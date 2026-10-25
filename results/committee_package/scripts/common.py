"""Shared inputs, frame table and hierarchy for the committee statistical-output package.

Descriptive and read-only: no thermal run, no fitting, no selection. Everything uses the frozen Patch 22.4.3.2
candidate ``confirm_c1`` exactly as recorded in its evaluate unit files. Run from the repo root with
``PYTHONPATH=src`` (the package is not installed).

The hierarchy is the one of objective contract 22.4.3.2 (ledger A10, A26): frame -> scan track -> coupon ->
exact-condition replicate -> unique condition, every level an unweighted mean of squared log ratios. Means use
``math.fsum`` / n, as in ``lpbf.log_ratio_objective``, so the recomputation equals the manifests exactly.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import math
import os
from pathlib import Path
from statistics import median
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from lpbf.configuration import BOILING_K  # strict ">" as in the calibration runner
from lpbf.dataset_split import (
    CALIBRATION_MEMBERS,
    CROSS_CAMPAIGN_HELD_OUT,
    HATCH_MM,
    IN_WINDOW_HELD_OUT,
    LAYER_MM,
    OUT_OF_WINDOW_BLIND,
    OUT_OF_WINDOW_EXAMINED,
    VED_WINDOW_J_MM3,
)
from lpbf.hierarchical_objective import PIXEL_SIZE_UM as UM_PER_PX  # nominal camera scale (A24); display only
from lpbf.log_ratio_objective import PIXEL_FLOOR

REPO = Path(__file__).resolve().parents[3]
PACKAGE = Path(__file__).resolve().parents[1]
DATA_DIR = PACKAGE / "data"
TABLES_DIR = PACKAGE / "tables"
FIGURES_DIR = PACKAGE / "figures"
REGISTERS_DIR = PACKAGE / "registers"

RESULTS = REPO / "results"
RECORDED_RUN = REPO / "runs" / "recorded_calibration"  # the data bundle's run outputs (gitignored)
UNITS_DIR = RECORDED_RUN / "evaluate" / "units"
FIELDS_DIR = RECORDED_RUN / "evaluate" / "fields"
EVIDENCE = RESULTS / "calibration"
EVALUATE_MANIFEST = EVIDENCE / "evaluate" / "stage_manifest.json"
CALIBRATE_MANIFEST = EVIDENCE / "calibrate" / "stage_manifest.json"
CONFIRM_MANIFEST = EVIDENCE / "confirm" / "stage_manifest.json"
CALIBRATION_READING = EVIDENCE / "calibration_reading.json"
SELECTION_FREEZE = EVIDENCE / "selection_freeze.json"
SYNTHETIC_FRAMES = EVIDENCE / "synthetic" / "synthetic_frames.csv.gz"
CAMERA_DIAGNOSTIC = RESULTS / "camera_diagnostic"
STEP0_TRENDS = CAMERA_DIAGNOSTIC / "step0" / "step0_trends.json"
CHARACTERIZATION = REPO / "data" / "characterization" / "patch21_3_full_characterization_20261012_011936"
PROCESS_RECORD = REPO / "docs" / "reference" / "LPBF_Process_Parameters.csv"
DATASET_MANIFEST = REPO / "src" / "lpbf" / "data" / "full_coupon_dataset_manifest.json"
CORE_HASHES = REPO / "src" / "lpbf" / "data" / "accepted_core_hashes.json"

# Pass-2 inputs.
SYNTHETIC_MANIFEST = EVIDENCE / "synthetic" / "stage_manifest.json"
SMOKE_GATE = EVIDENCE / "smoke" / "smoke_gate.json"
CALIBRATE_UNITS_DIR = RECORDED_RUN / "calibrate" / "units"
CONFIRM_UNITS_DIR = RECORDED_RUN / "confirm" / "units"
STEP0_FAMILY = CAMERA_DIAGNOSTIC / "step0" / "step0_threshold_family.csv"
STEP3_LEVEL_FREE = CAMERA_DIAGNOSTIC / "step3" / "step3_level_free.json"
STEP4_CANDIDATES = CAMERA_DIAGNOSTIC / "step4" / "step4_candidates.csv"
STEP4_VERDICT = CAMERA_DIAGNOSTIC / "step4" / "step4_verdict.json"
SYNC_AUDIT_22_3_6 = RESULTS / "synchronization_audit" / "track_start_audit.json"
SYNC_AUDIT_22_3_6_TRACKS = RESULTS / "synchronization_audit" / "track_start_audit_tracks.csv"
# The 24 coupon HDF5 files (data bundle, read only); used by F13 alone. Override with LPBF_COUPON_DATA_DIR.
COUPON_DATA_DIR = Path(os.environ.get("LPBF_COUPON_DATA_DIR", REPO / "data" / "coupons"))

CANDIDATE = "confirm_c1"
NO_POOL_STATUSES = ("NO_LASER_ASSOCIATED_MELT", "ZERO_FOOTPRINT")
SEED = 20261019
BOOTSTRAP_REPLICATES = 4000
CONFIDENCE = 0.95

ROLE_MEMBERS = {
    "calibration": tuple(CALIBRATION_MEMBERS),
    "in_window_held_out": tuple(IN_WINDOW_HELD_OUT),
    "out_of_window_examined": tuple(OUT_OF_WINDOW_EXAMINED),
    "out_of_window_blind": tuple(OUT_OF_WINDOW_BLIND),
}
ROLE_ORDER = tuple(ROLE_MEMBERS)
ROLE_LABEL = {
    "calibration": "Calibration",
    "in_window_held_out": "In-window held out",
    "out_of_window_examined": "Out of window, examined",
    "out_of_window_blind": "Out of window, blind",
}
ROLE = {member: role for role, members in ROLE_MEMBERS.items() for member in members}
A8_HELD_OUT = frozenset(IN_WINDOW_HELD_OUT) | frozenset(OUT_OF_WINDOW_BLIND)
CROSS_CAMPAIGN = CROSS_CAMPAIGN_HELD_OUT

VERSIONS = {
    "production_hw_association_policy_version": "22.3.7",
    "production_hw_semantics_version": "22.3.7",
    "scored_frame_rule_version": "22.3.7",
    "objective_contract_version": "22.4.3.2",
}


# ---------------------------------------------------------------------- small helpers


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fmean(values: Sequence[float]) -> float:
    if not values:
        raise ValueError("cannot average an empty sequence")
    return math.fsum(values) / len(values)


def log_ratio(simulated: float, experimental: float) -> float:
    """r = ln(max(sim, 1) / max(exp, 1)), objective contract 22.4.3.2 (A26)."""

    return math.log(max(float(simulated), PIXEL_FLOOR) / max(float(experimental), PIXEL_FLOOR))


def member_key(member: str) -> tuple[str, int]:
    acquisition_set, part = member.split(":")
    return acquisition_set, int(part.split("_")[1])


def ved(power_W: float, speed_mm_s: float) -> float:
    return float(power_W) / (float(speed_mm_s) * HATCH_MM * LAYER_MM)


def load_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def percentile_ci(draws: np.ndarray, axis: int = 0) -> tuple[Any, Any]:
    alpha = 100.0 * (1.0 - CONFIDENCE) / 2.0
    lo, hi = np.nanpercentile(draws, [alpha, 100.0 - alpha], axis=axis)
    return lo, hi


def fmt(value: Any) -> str:
    """Full-precision CSV cell: repr for floats, '' for None/NaN."""

    if value is None:
        return ""
    if isinstance(value, (bool, np.bool_)):
        return "true" if value else "false"
    if isinstance(value, (float, np.floating)):
        return "" if not math.isfinite(float(value)) else repr(float(value))
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    return str(value)


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]], fieldnames: Sequence[str] | None = None) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Union of keys in order of first appearance, so heterogeneous rows (groups, conditions, coupons) lose no column.
    fields = list(fieldnames) if fieldnames else list(dict.fromkeys(key for row in rows for key in row))
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: fmt(row.get(key)) for key in fields})
    data = buffer.getvalue().encode("utf-8")
    if path.suffix == ".gz":
        # mtime=0 and no file name keep the gzip bytes deterministic.
        with open(path, "wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as handle:
            handle.write(data)
    else:
        path.write_bytes(data)
    return path


def read_csv(path: Path) -> list[dict[str, str]]:
    path = Path(path)
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_json(path: Path, payload: Any) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------- process record and roster


def process_record() -> dict[str, dict[str, Any]]:
    """The A17 record (read only), keyed by member identity."""

    out: dict[str, dict[str, Any]] = {}
    for row in read_csv(PROCESS_RECORD):
        month, day, year = (int(item) for item in row["Date"].split("/"))
        acquisition_set = f"{year:04d}{month:02d}{day:02d}"
        part = int(row["Part Number"])
        member = f"{acquisition_set}:part_{part}"
        power, speed = float(row["Power (W)"]), float(row["Travel Speed (mm/s)"])
        out[member] = {
            "member": member,
            "acquisition_set": acquisition_set,
            "acquisition_date": f"{year:04d}-{month:02d}-{day:02d}",
            "part": part,
            "power_W": power,
            "speed_mm_s": speed,
            "spot_mm": float(row["Spot Size (mm)"]),
            "areal_energy_J_mm2_record": float(row["Area Power Density (J/mm2)"]),
            "ved_J_mm3_record": float(row["Volumetric Power Density (J/mm3)"]),
            "ved_J_mm3": ved(power, speed),
            "condition": f"P{int(power)}_V{int(speed)}",
        }
    if len(out) != 24:
        raise RuntimeError(f"process record has {len(out)} members, expected 24")
    return dict(sorted(out.items(), key=lambda item: member_key(item[0])))


def acquisition_set_roles() -> dict[str, str]:
    manifest = load_json(DATASET_MANIFEST)
    return {item["acquisition_set_id"]: item["role"] for item in manifest["acquisition_sets"]}


# ---------------------------------------------------------------------- unit files -> frame table


def evaluate_manifest() -> dict[str, Any]:
    return load_json(EVALUATE_MANIFEST)


def unit_path(member: str) -> Path:
    return UNITS_DIR / f"{CANDIDATE}__{member.replace(':', '_')}.json"


def units_available() -> bool:
    return all(unit_path(member).is_file() for member in ROLE)


def load_units(*, verify: bool = True) -> dict[str, dict[str, Any]]:
    """The 24 c1 evaluate unit files, each checked against its sha256 in the evaluate manifest."""

    manifest = evaluate_manifest()
    expected = {item["work_unit_id"]: item["unit_sha256"] for item in manifest["units"]}
    units: dict[str, dict[str, Any]] = {}
    for member in sorted(ROLE, key=member_key):
        raw = unit_path(member).read_bytes()
        payload = json.loads(raw)
        if verify:
            digest = hashlib.sha256(raw).hexdigest()
            want = expected[f"22.4.3.2:{CANDIDATE}@{member}"]
            if digest != want:
                raise RuntimeError(f"{member}: unit sha256 {digest} != manifest {want}")
            for key, value in VERSIONS.items():
                if key != "objective_contract_version" and payload[key] != value:
                    raise RuntimeError(f"{member}: {key} {payload[key]} != {value}")
            if payload["candidate_id"] != CANDIDATE or payload["evaluation_status"] != "PASS":
                raise RuntimeError(f"{member}: unexpected unit identity or status")
        units[member] = payload
    return units


def characterization_rows(member: str) -> dict[int, dict[str, str]]:
    acquisition_set, part = member_key(member)
    path = CHARACTERIZATION / "members" / f"{acquisition_set}_part_{part}_layer53" / "frame_observations.csv"
    return {int(row["frame_index"]): row for row in read_csv(path)}


def characterization_audit(member: str) -> dict[str, Any]:
    acquisition_set, part = member_key(member)
    return load_json(CHARACTERIZATION / "members" / f"{acquisition_set}_part_{part}_layer53" / "member_audit.json")


def field_process_rows(member: str) -> dict[int, int]:
    """frame_index -> mapped_process_row from the c1 field capture (scored frames only; fields not loaded)."""

    with np.load(FIELDS_DIR / f"{CANDIDATE}__{member.replace(':', '_')}.npz", allow_pickle=False) as npz:
        return {int(f): int(r) for f, r in zip(npz["frame_index"], npz["mapped_process_row"])}


def frame_table(units: Mapping[str, Mapping[str, Any]], *, process_rows: bool = True) -> list[dict[str, Any]]:
    """One row per frame record of every c1 unit (eligible, excluded, ineligible and scored)."""

    record = process_record()
    rows: list[dict[str, Any]] = []
    for member, unit in units.items():
        proc = record[member]
        peaks = {int(k): float(v) for k, v in unit["peak_surface_temperature_K_by_frame"].items()}
        char = characterization_rows(member) if process_rows else {}
        fields = field_process_rows(member) if process_rows else {}
        for rec in unit["frame_records"]:
            if float(rec["power_W"]) != proc["power_W"] or float(rec["speed_mm_s"]) != proc["speed_mm_s"]:
                raise RuntimeError(f"{member}: unit process condition disagrees with the A17 record")
            frame = int(rec["frame_index"])
            scored = bool(rec.get("scored_frame")) and rec["status"] == "PASS"
            position = rec.get("track_position") or {}
            row: dict[str, Any] = {
                "member": member,
                "acquisition_set": proc["acquisition_set"],
                "part": proc["part"],
                "condition": rec["exact_condition_id"],
                "power_W": proc["power_W"],
                "speed_mm_s": proc["speed_mm_s"],
                "ved_J_mm3": proc["ved_J_mm3"],
                "role": ROLE[member],
                "scan_track_id": int(rec["scan_track_id"]),
                "frame_index": frame,
                "track_position": position.get("position"),
                "track_eligible_frames": position.get("track_frame_count"),
                "edge_class": position.get("edge_class"),
                "record_status": rec["status"],
                "exclusion_reason": rec.get("exclusion_reason"),
                "observation_status": rec.get("observation_status"),
                "scored": scored,
                "production_status": rec.get("production_status"),
                "production_beam_share": rec.get("production_beam_share"),
                "cam_H_px": rec.get("experimental_H_pixels"),
                "cam_W_px": rec.get("experimental_W_pixels"),
                "sim_H_px": rec.get("simulated_H_pixels") if scored else None,
                "sim_W_px": rec.get("simulated_W_pixels") if scored else None,
            }
            if process_rows:
                char_row = char.get(frame)
                char_process = int(char_row["mapped_process_row"]) if char_row and char_row["mapped_process_row"] else None
                if scored and fields.get(frame) != char_process:
                    raise RuntimeError(f"{member} frame {frame}: field process row {fields.get(frame)} != characterization {char_process}")
                row["process_row"] = char_process
            if scored:
                sim_h, sim_w = float(rec["simulated_H_pixels"]), float(rec["simulated_W_pixels"])
                cam_h, cam_w = float(rec["experimental_H_pixels"]), float(rec["experimental_W_pixels"])
                row.update(
                    {
                        "r_H": log_ratio(sim_h, cam_h),
                        "r_W": log_ratio(sim_w, cam_w),
                        "floored": min(sim_h, sim_w, cam_h, cam_w) < PIXEL_FLOOR,
                        "no_pool": rec.get("production_status") in NO_POOL_STATUSES,
                        "peak_surface_K": peaks[frame],
                        "peak_above_boiling": peaks[frame] > BOILING_K,
                    }
                )
            rows.append(row)
    return rows


def scored_frames(frames: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [row for row in frames if row["scored"]]


# ---------------------------------------------------------------------- hierarchy (contract 22.4.3.2)


def track_rows(scored: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    by_track: dict[tuple[str, int], list[Mapping[str, Any]]] = {}
    for row in sorted(scored, key=lambda r: (member_key(r["member"]), r["scan_track_id"], r["frame_index"])):
        by_track.setdefault((row["member"], row["scan_track_id"]), []).append(row)
    out = []
    for (member, track), group in by_track.items():
        out.append(
            {
                "member": member,
                "scan_track_id": track,
                "condition": group[0]["condition"],
                "scored_frames": len(group),
                "H_mean_sq_log": fmean([r["r_H"] ** 2 for r in group]),
                "W_mean_sq_log": fmean([r["r_W"] ** 2 for r in group]),
                "H_mean_log": fmean([r["r_H"] for r in group]),
                "W_mean_log": fmean([r["r_W"] for r in group]),
                "frames": group,
            }
        )
    return out


def level(rows: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    h_sq = fmean([r["H_mean_sq_log"] for r in rows])
    w_sq = fmean([r["W_mean_sq_log"] for r in rows])
    return {
        "H_mean_sq_log": h_sq,
        "W_mean_sq_log": w_sq,
        "H_mean_log": fmean([r["H_mean_log"] for r in rows]),
        "W_mean_log": fmean([r["W_mean_log"] for r in rows]),
        "e_H": math.sqrt(h_sq),
        "e_W": math.sqrt(w_sq),
        "J": 0.5 * h_sq + 0.5 * w_sq,
    }


def frame_summary(frames: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Pooled descriptive statistics of scored frames, defined as in ``lpbf.log_ratio_objective``."""

    pool = [r for r in frames if not r["no_pool"]]
    return {
        "scored_frames": len(frames),
        "median_r_H": float(median([r["r_H"] for r in frames])),
        "median_r_W": float(median([r["r_W"] for r in frames])),
        "median_H_ratio": float(median([math.exp(r["r_H"]) for r in frames])),
        "median_W_ratio": float(median([math.exp(r["r_W"]) for r in frames])),
        "cam_H_px_median": float(median([float(r["cam_H_px"]) for r in frames])),
        "cam_W_px_median": float(median([float(r["cam_W_px"]) for r in frames])),
        "cam_HW_median": float(median([float(r["cam_H_px"]) / float(r["cam_W_px"]) for r in frames])),
        "sim_H_px_median_pool": float(median([float(r["sim_H_px"]) for r in pool])) if pool else float("nan"),
        "sim_W_px_median_pool": float(median([float(r["sim_W_px"]) for r in pool])) if pool else float("nan"),
        "sim_HW_median_pool": float(median([float(r["sim_H_px"]) / float(r["sim_W_px"]) for r in pool])) if pool else float("nan"),
        "no_pool_frames": len(frames) - len(pool),
        "no_laser_associated_melt_frames": sum(1 for r in frames if r["production_status"] == "NO_LASER_ASSOCIATED_MELT"),
        "zero_footprint_frames": sum(1 for r in frames if r["production_status"] == "ZERO_FOOTPRINT"),
        "floored_frames": sum(1 for r in frames if r["floored"]),
        "peak_above_boiling_fraction": sum(1 for r in frames if r["peak_above_boiling"]) / len(frames),
        "median_peak_surface_K": float(median([r["peak_surface_K"] for r in frames])),
    }


def coupon_rows(tracks: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    by_member: dict[str, list[Mapping[str, Any]]] = {}
    for row in tracks:
        by_member.setdefault(row["member"], []).append(row)
    out = {}
    for member, group in sorted(by_member.items(), key=lambda item: member_key(item[0])):
        frames = [f for t in group for f in t["frames"]]
        out[member] = {"member": member, "condition": group[0]["condition"], "tracks_scored": len(group), **level(group), **frame_summary(frames)}
    return out


def group_hierarchy(coupons: Mapping[str, Mapping[str, Any]], members: Sequence[str], frames_by_member: Mapping[str, Sequence[Mapping[str, Any]]]) -> dict[str, Any]:
    """Coupon -> exact-condition replicate -> unique condition, as in ``aggregate_log_ratio_records``."""

    by_condition: dict[str, list[Mapping[str, Any]]] = {}
    for member in members:
        by_condition.setdefault(coupons[member]["condition"], []).append(coupons[member])
    conditions = {cid: level(rows) for cid, rows in sorted(by_condition.items())}
    top = level(list(conditions.values()))
    frames = [f for member in members for f in frames_by_member[member]]
    return {
        **top,
        **frame_summary(frames),
        "coupons": len(members),
        "conditions": len(conditions),
        "tracks_scored": sum(coupons[m]["tracks_scored"] for m in members),
        "condition_rows": conditions,
    }


WEIGHTINGS = ("contract", "frame", "track", "coupon")


def contract_errors(frames: Iterable[Mapping[str, Any]], *, weighting: str = "contract") -> dict[str, Any]:
    """e_H, e_W and J of frame records (member, scan_track_id, condition, r_H, r_W) under one weighting.

    ``contract`` is the 22.4.3.2 hierarchy (frame -> track -> coupon -> condition -> group, each an unweighted mean;
    equal to ``coupon_rows``/``group_hierarchy`` exactly). ``frame``, ``track`` and ``coupon`` weight every frame,
    every track or every coupon equally instead (sensitivity only).
    """

    tracks: dict[tuple[str, int], list[Mapping[str, Any]]] = {}
    for f in frames:
        tracks.setdefault((f["member"], int(f["scan_track_id"])), []).append(f)
    if not tracks:
        raise ValueError("no frames")

    def msq(rows: Sequence[Mapping[str, Any]], q: str) -> float:
        return fmean([float(r[f"r_{q}"]) ** 2 for r in rows])

    track_msq = {key: {q: msq(rows, q) for q in ("H", "W")} for key, rows in tracks.items()}
    coupons: dict[str, list[dict[str, float]]] = {}
    condition_of: dict[str, str] = {}
    for (member, _), value in track_msq.items():
        coupons.setdefault(member, []).append(value)
        condition_of[member] = next(iter(tracks[(member, _)]))["condition"]
    coupon_msq = {m: {q: fmean([t[q] for t in ts]) for q in ("H", "W")} for m, ts in coupons.items()}
    if weighting == "frame":
        everything = [f for rows in tracks.values() for f in rows]
        top = {q: msq(everything, q) for q in ("H", "W")}
    elif weighting == "track":
        top = {q: fmean([t[q] for t in track_msq.values()]) for q in ("H", "W")}
    elif weighting == "coupon":
        top = {q: fmean([c[q] for c in coupon_msq.values()]) for q in ("H", "W")}
    elif weighting == "contract":
        conditions: dict[str, list[dict[str, float]]] = {}
        for member, value in coupon_msq.items():
            conditions.setdefault(condition_of[member], []).append(value)
        condition_msq = [{q: fmean([c[q] for c in cs]) for q in ("H", "W")} for cs in conditions.values()]
        top = {q: fmean([c[q] for c in condition_msq]) for q in ("H", "W")}
    else:
        raise ValueError(f"unknown weighting {weighting!r}")
    return {
        "e_H": math.sqrt(top["H"]),
        "e_W": math.sqrt(top["W"]),
        "J": 0.5 * top["H"] + 0.5 * top["W"],
        "H_mean_sq_log": top["H"],
        "W_mean_sq_log": top["W"],
        "frames": sum(len(rows) for rows in tracks.values()),
        "tracks": len(tracks),
        "coupons": len(coupons),
        "conditions": len(set(condition_of.values())),
        "coupon_msq": coupon_msq,
    }


def group_members() -> dict[str, tuple[str, ...]]:
    """The analysis groups used throughout pass 2 (A25 roles plus the reading-V part_5 and the VED sides)."""

    record = process_record()
    oow = ROLE_MEMBERS["out_of_window_examined"] + ROLE_MEMBERS["out_of_window_blind"]
    return {
        "calibration": ROLE_MEMBERS["calibration"],
        "in_window_held_out": ROLE_MEMBERS["in_window_held_out"],
        "cross_campaign_20260904_part_5": (CROSS_CAMPAIGN,),
        "out_of_window_examined": ROLE_MEMBERS["out_of_window_examined"],
        "out_of_window_blind": ROLE_MEMBERS["out_of_window_blind"],
        "out_of_window_all": oow,
        "out_of_window_low_ved": tuple(m for m in oow if record[m]["ved_J_mm3"] < VED_WINDOW_J_MM3[0]),
        "out_of_window_high_ved": tuple(m for m in oow if record[m]["ved_J_mm3"] > VED_WINDOW_J_MM3[1]),
        "all_24": tuple(sorted(ROLE, key=member_key)),
    }


GROUP_LABEL = {
    "calibration": "Calibration (9)",
    "in_window_held_out": "In-window held out (5)",
    "cross_campaign_20260904_part_5": "20260904:part_5",
    "out_of_window_examined": "Out of window, examined (7)",
    "out_of_window_blind": "Out of window, blind (3)",
    "out_of_window_all": "Out of window, all (10)",
    "out_of_window_low_ved": "Out of window, VED < 65 (6)",
    "out_of_window_high_ved": "Out of window, VED > 85 (4)",
    "all_24": "All 24 coupons",
}


def spearman(x: Sequence[float], y: Sequence[float]) -> float:
    """Spearman's rho with average ranks for ties (equal to ``lpbf.calibration.spearman_rho``)."""

    def ranks(values: Sequence[float]) -> np.ndarray:
        values = np.asarray(values, dtype=float)
        order = np.argsort(values, kind="stable")
        out = np.empty(values.size)
        out[order] = np.arange(values.size, dtype=float)
        for v in np.unique(values):
            idx = values == v
            if idx.sum() > 1:
                out[idx] = out[idx].mean()
        return out

    rx, ry = ranks(x), ranks(y)
    if rx.std() == 0 or ry.std() == 0:
        return float("nan")
    return float(np.corrcoef(rx, ry)[0, 1])


# ---------------------------------------------------------------------- bootstrap primitives


def rng(family: int, index: int = 0) -> np.random.Generator:
    """One generator per statistic family and unit index, from the package seed (recorded in METHODS_MANIFEST.json)."""

    return np.random.default_rng([SEED, family, index])


def weighted_group_components(coupon_h: np.ndarray, coupon_w: np.ndarray, condition_index: np.ndarray, counts: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Hierarchy on a resampled coupon set: ``counts`` (R x n) are draw multiplicities per coupon.

    A condition's value is the multiplicity-weighted mean of its drawn coupons; the group value is the mean over the
    conditions present in the draw. With all counts 1 this equals the contract hierarchy exactly.
    """

    n_cond = int(condition_index.max()) + 1
    onehot = np.zeros((coupon_h.size, n_cond))
    onehot[np.arange(coupon_h.size), condition_index] = 1.0
    weight = counts @ onehot  # R x C
    present = weight > 0
    with np.errstate(invalid="ignore", divide="ignore"):
        cond_h = (counts * coupon_h) @ onehot / weight
        cond_w = (counts * coupon_w) @ onehot / weight
    cond_h[~present] = 0.0
    cond_w[~present] = 0.0
    n_present = present.sum(axis=1)
    return cond_h.sum(axis=1) / n_present, cond_w.sum(axis=1) / n_present


def draw_counts(generator: np.random.Generator, n: int, replicates: int) -> np.ndarray:
    picks = generator.integers(0, n, size=(replicates, n))
    counts = np.zeros((replicates, n), dtype=np.int64)
    np.add.at(counts, (np.repeat(np.arange(replicates), n), picks.ravel()), 1)
    return counts
