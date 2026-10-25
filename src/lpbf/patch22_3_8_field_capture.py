"""Patch 22.3.8 Step 1: capture the model's top-surface temperature field at every scored frame (ledger O13).

Diagnostic only.  The unchanged Patch 22.3.7 Stage-A unit job runs inside
``field_capture_instrumentation``, which records, without altering any result,
the 99 x 99 top-surface temperature field, the beam cell, the source geometry and
the production association outcome at every requested (scored) frame.  Production
H/W semantics, the association policy, the scored-frame rule and every constant are
unchanged; held-out members are refused; the campaign dispatch path is never used.

Workers write nothing: the captured arrays travel back in the payload and the
parent writes one compressed ``.npz`` per unit, then drops them from memory.
``evaluate_capture_gate`` is the predeclared Step-1 regression gate (G1-G5 in
``docs/patches/22.3.8/PATCH_22_3_8_PLAN.md``).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import platform
import subprocess
import sys
import zipfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Sequence

import numpy as np

import lpbf.patch22_3_7_stage_a as stage_a
from lpbf.execution.parallel import execute_parallel_jobs
from lpbf.execution.work_units import SimulationResult, execute_serial_jobs
from lpbf.infrastructure import write_json
from lpbf.model import current_execution
from lpbf.model._accepted_core import comparison as accepted_comparison
from lpbf.model.laser_component_association import POLICY_VERSION
from lpbf.model.observation_diagnostics import _label_liquid_components
from lpbf.model.observation_diagnostics import interpolated_component_contour_hw_diagnostic as _pristine_component_hw
from lpbf.model.production_hw import PRODUCTION_HW_SEMANTICS_VERSION, ZERO_SCORED_STATUSES
from lpbf.patch22_3_5_1_frozen_revalidation import _member_map
from lpbf.patch22_3_8_camera_step0 import calibration_member_identities, require_calibration_members
from lpbf.patch22_4_3_parallel_coarse_calibration_execution import _find_frame_file, _json_safe, _portable_frame_rows
from lpbf.scored_frame_rule import SCORED_FRAME_RULE_VERSION

PATCH_VERSION = "22.3.8"
STEP_ID = "step1_field_capture"
SCHEMA = "lpbf_patch22_3_8_field_capture"
DEFAULT_OUTPUT_DIRECTORY = "patch22_3_8_capture_output"
DEFAULT_WORKERS = 4
MANIFEST_NAME = "field_capture_manifest.json"
GATE_NAME = "field_capture_gate.json"
GATE_PASS = "PASS_PATCH_22_3_8_FIELD_CAPTURE_GATE"
GATE_FAIL = "FAIL_PATCH_22_3_8_FIELD_CAPTURE_GATE"

REPO_ROOT = Path(__file__).resolve().parents[2]
STAGE_A_FRAMES_CSV = REPO_ROOT / "docs" / "patches" / "22.3.7" / "evidence" / "PATCH_22_3_7_STAGE_A_FRAMES.csv"
CENSUS_FRAMES_CSV = REPO_ROOT / "docs" / "patches" / "22.3.6" / "evidence" / "PATCH_22_3_6_ASSOCIATION_CENSUS_FRAMES.csv"
CORE_HASHES_JSON = REPO_ROOT / "PATCH_22_3_4_ACCEPTED_CORE_HASHES.json"
PLAN_PATH = REPO_ROOT / "docs" / "patches" / "22.3.8" / "PATCH_22_3_8_PLAN.md"

SELECTED_STATUS = "SELECTED"
NO_LABEL = -1
CORNER_MEMBERS = ("20260904:part_1", "20260904:part_3", "20260904:part_4", "20260904:part_6")
STEP1_UNITS = (("anchor_center", "20260730:part_1"),)
STAGE_A_COMPARE_COLUMNS = (
    "status",
    "exclusion_reason",
    "undefined_reason",
    "simulated_H_pixels",
    "simulated_W_pixels",
    "production_status",
    "production_mode",
    "production_selected_label",
    "production_beam_share",
    "production_contains_beam_cell",
    "melt_classification",
)


def step2_units() -> tuple[tuple[str, str], ...]:
    """Predeclared Step-2 units: anchor_center on every calibration member; t_min/t_max on the four corners."""

    units = {("anchor_center", member) for member in calibration_member_identities()}
    units |= {(candidate, member) for candidate in ("anchor_t_min", "anchor_t_max") for member in CORNER_MEMBERS}
    return tuple(sorted(units))


STEP2_CANDIDATES = ("anchor_center", "anchor_t_min", "anchor_t_max")


def step4_units() -> tuple[tuple[str, str], ...]:
    """Predeclared Step-4 units: every other frozen coarse-design candidate on the four corners."""

    candidates = sorted(set(stage_a._candidate_coordinates()) - set(STEP2_CANDIDATES))
    return tuple(sorted((candidate, member) for candidate in candidates for member in CORNER_MEMBERS))


class FieldCaptureError(RuntimeError):
    """Fail-closed error for the Patch 22.3.8 field capture."""


# ---------------------------------------------------------------------- instrumentation


@contextmanager
def field_capture_instrumentation() -> Iterator[dict[str, Any]]:
    """Record the top-surface field at every observation without changing any result.

    Enter it *outside* ``laser_associated_observation_instrumentation`` (it is, when it
    wraps ``_stage_a_unit_job``): the production wrapper then captures these wrappers
    as its originals.  Per observation the production wrapper calls the component-H/W
    seam first with the beam-connected mask, by which time the production association
    status and selected label are already in the diagnostics record; only that first
    call is captured.
    """

    original_builder = current_execution.build_centered_heat_source_for_row_with_deposition_depth
    original_top = accepted_comparison.top_surface_liquid_component_diagnostics
    original_component_hw = accepted_comparison.interpolated_component_contour_hw_diagnostic
    original_evaluate = stage_a.evaluate_calibration_trial
    state: dict[str, Any] = {"builds": [], "observation": None, "captures": [], "evaluation_frames": None}

    def capture_builder(*args: Any, **kwargs: Any) -> Any:
        result = original_builder(*args, **kwargs)
        source = result[1]
        state["builds"].append(
            {
                "row_index": None if kwargs.get("row_index") is None else int(kwargs["row_index"]),
                "laser_on": bool(kwargs.get("laser_on", False)),
                "center_x_mm": _optional_float(getattr(source, "center_x_mm", None)),
                "center_y_mm": _optional_float(getattr(source, "center_y_mm", None)),
                "gaussian_radius_mm": _optional_float(getattr(source, "gaussian_radius_mm", None)),
                "deposited_power_W": _optional_float(getattr(source, "deposited_power_W", None)),
            }
        )
        del state["builds"][:-2]  # the current build and the one that heated the field
        return result

    def capture_top(liquid_mask: np.ndarray, *, beam_i: int, beam_j: int) -> dict[str, Any]:
        diagnostics = original_top(liquid_mask, beam_i=beam_i, beam_j=beam_j)
        builds = state["builds"]
        state["observation"] = {
            "diagnostics": diagnostics,
            "beam_i": int(beam_i),
            "beam_j": int(beam_j),
            "liquid_cells": int(np.count_nonzero(liquid_mask)),
            "source": dict(builds[-1]) if builds else None,
            "heating": dict(builds[-2]) if len(builds) > 1 else None,
            "pending": True,
        }
        return diagnostics

    def capture_component_hw(
        top_surface_temperature_K: np.ndarray,
        component_mask: np.ndarray,
        *,
        liquidus_temperature_K: float,
        cell_size_um: float,
        experimental_pixel_size_um: float,
    ) -> dict[str, Any]:
        result = original_component_hw(
            top_surface_temperature_K,
            component_mask,
            liquidus_temperature_K=liquidus_temperature_K,
            cell_size_um=cell_size_um,
            experimental_pixel_size_um=experimental_pixel_size_um,
        )
        observation = state["observation"]
        if observation is None or not observation["pending"]:
            return result
        observation["pending"] = False
        diagnostics = observation["diagnostics"]
        label = diagnostics.get("production_hw_association_selected_label")
        state["captures"].append(
            {
                # the seam receives a view of the live solver array: copy it
                "field": np.array(top_surface_temperature_K, dtype=np.float64, copy=True),
                "beam_i": observation["beam_i"],
                "beam_j": observation["beam_j"],
                "liquid_cells": observation["liquid_cells"],
                "beam_component_cells": int(np.count_nonzero(component_mask)),
                "source": observation["source"],
                "heating": observation["heating"],
                "production_status": diagnostics.get("production_hw_association_status"),
                "selected_label": NO_LABEL if label is None else int(label),
                "liquidus_temperature_K": float(liquidus_temperature_K),
                "cell_size_um": float(cell_size_um),
                "experimental_pixel_size_um": float(experimental_pixel_size_um),
            }
        )
        return result

    def capture_evaluate(*args: Any, **kwargs: Any) -> Any:
        result = original_evaluate(*args, **kwargs)
        observations = list((result.to_dict() or {}).get("observations") or [])
        state["evaluation_frames"] = [
            (int(item["frame_index"]), int(item["mapped_process_row"]))
            for item in observations
            if isinstance(item, Mapping) and item.get("frame_index") is not None and item.get("mapped_process_row") is not None
        ]
        return result

    current_execution.build_centered_heat_source_for_row_with_deposition_depth = capture_builder
    accepted_comparison.top_surface_liquid_component_diagnostics = capture_top
    accepted_comparison.interpolated_component_contour_hw_diagnostic = capture_component_hw
    stage_a.evaluate_calibration_trial = capture_evaluate
    try:
        yield state
    finally:
        current_execution.build_centered_heat_source_for_row_with_deposition_depth = original_builder
        accepted_comparison.top_surface_liquid_component_diagnostics = original_top
        accepted_comparison.interpolated_component_contour_hw_diagnostic = original_component_hw
        stage_a.evaluate_calibration_trial = original_evaluate


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _source_value(capture: Mapping[str, Any], which: str, key: str) -> float:
    record = capture.get(which) or {}
    value = record.get(key)
    return float("nan") if value is None else float(value)


def assemble_unit_capture(state: Mapping[str, Any], payload: Mapping[str, Any]) -> tuple[dict[str, np.ndarray] | None, list[str]]:
    """Key the captures by frame and fail closed unless every requested frame is captured exactly once."""

    requested = sorted(int(row["frame_index"]) for row in payload.get("frame_records") or [] if row.get("scored_frame"))
    pairs = state.get("evaluation_frames")
    if pairs is None:
        return None, ["evaluation_not_observed"]
    failures: set[str] = set()
    frame_to_row: dict[int, int] = {}
    for frame, row in pairs:
        if frame in frame_to_row:
            failures.add("duplicate_evaluation_frame")
        frame_to_row[int(frame)] = int(row)
    if sorted(frame_to_row) != requested:
        failures.add("evaluation_frames_differ_from_requested")
    by_row: dict[int, Mapping[str, Any]] = {}
    for capture in state.get("captures") or []:
        source = capture.get("source") or {}
        if source.get("row_index") is None:
            failures.add("capture_without_source_row")
            continue
        row = int(source["row_index"])
        if row in by_row:
            failures.add("duplicate_capture_row")
            continue
        by_row[row] = capture
    expected_rows = {frame_to_row[frame] for frame in requested if frame in frame_to_row}
    if set(by_row) - expected_rows:
        failures.add("unexpected_capture")
    ordered: list[tuple[int, int, Mapping[str, Any]]] = []
    for frame in requested:
        row = frame_to_row.get(frame)
        capture = None if row is None else by_row.get(row)
        if capture is None:
            failures.add("missing_capture")
            continue
        ordered.append((frame, row, capture))
    if not ordered:
        failures.add("no_captures")
    for key in ("liquidus_temperature_K", "cell_size_um", "experimental_pixel_size_um"):
        if len({float(capture[key]) for _, _, capture in ordered}) > 1:
            failures.add(f"inconsistent_{key}")
    if failures:
        return None, sorted(failures)
    first = ordered[0][2]
    heating_rows = [(capture.get("heating") or {}).get("row_index") for _, _, capture in ordered]
    capture_arrays = {
        "frame_index": np.array([frame for frame, _, _ in ordered], dtype=np.int64),
        "mapped_process_row": np.array([row for _, row, _ in ordered], dtype=np.int64),
        "top_surface_temperature_K": np.stack([capture["field"] for _, _, capture in ordered]).astype(np.float64, copy=False),
        "beam_i": np.array([capture["beam_i"] for _, _, capture in ordered], dtype=np.int64),
        "beam_j": np.array([capture["beam_j"] for _, _, capture in ordered], dtype=np.int64),
        "liquid_cells": np.array([capture["liquid_cells"] for _, _, capture in ordered], dtype=np.int64),
        "beam_component_cells": np.array([capture["beam_component_cells"] for _, _, capture in ordered], dtype=np.int64),
        "source_center_x_mm": np.array([_source_value(c, "source", "center_x_mm") for _, _, c in ordered]),
        "source_center_y_mm": np.array([_source_value(c, "source", "center_y_mm") for _, _, c in ordered]),
        "source_gaussian_radius_mm": np.array([_source_value(c, "source", "gaussian_radius_mm") for _, _, c in ordered]),
        "source_laser_on": np.array([bool((c.get("source") or {}).get("laser_on")) for _, _, c in ordered]),
        "heating_row_index": np.array([NO_LABEL if value is None else int(value) for value in heating_rows], dtype=np.int64),
        "heating_center_x_mm": np.array([_source_value(c, "heating", "center_x_mm") for _, _, c in ordered]),
        "heating_center_y_mm": np.array([_source_value(c, "heating", "center_y_mm") for _, _, c in ordered]),
        "heating_deposited_power_W": np.array([_source_value(c, "heating", "deposited_power_W") for _, _, c in ordered]),
        "production_status": np.array([str(capture["production_status"] or "") for _, _, capture in ordered]),
        "selected_label": np.array([capture["selected_label"] for _, _, capture in ordered], dtype=np.int64),
        "liquidus_temperature_K": np.array(float(first["liquidus_temperature_K"])),
        "cell_size_um": np.array(float(first["cell_size_um"])),
        "experimental_pixel_size_um": np.array(float(first["experimental_pixel_size_um"])),
    }
    return capture_arrays, []


def _field_capture_unit_job(job: Any) -> dict[str, Any]:
    """Spawn-safe worker: the unchanged Stage-A unit job, run inside the capture instrumentation."""

    with field_capture_instrumentation() as state:
        payload = stage_a._stage_a_unit_job(job)
    payload = dict(payload)
    capture, failures = assemble_unit_capture(state, payload)
    payload.update(
        {
            "field_capture_schema": SCHEMA,
            "field_capture_patch": PATCH_VERSION,
            "capture_gate_failures": failures,
            "captured_frame_count": 0 if capture is None else int(capture["frame_index"].size),
            "capture": capture,
        }
    )
    return payload


# ---------------------------------------------------------------------- parent-side storage and runner


def unit_file_stem(candidate_id: str, member_id: str) -> str:
    return f"{candidate_id}__{member_id.replace(':', '_')}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_npz_deterministic(path: Path, arrays: Mapping[str, np.ndarray]) -> None:
    """A compressed ``.npz`` whose bytes depend only on the arrays (``np.savez`` stamps the wall clock)."""

    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(arrays):
            info = zipfile.ZipInfo(f"{name}.npy", date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            buffer = io.BytesIO()
            np.lib.format.write_array(buffer, np.asarray(arrays[name]), allow_pickle=False)
            archive.writestr(info, buffer.getvalue())


def store_unit_fields(output: Path, payload: dict[str, Any]) -> None:
    """Write the unit's captured arrays to ``fields/<unit>.npz`` and drop them from the payload."""

    capture = payload.pop("capture", None)
    if capture is None:
        payload["capture_file"] = None
        return
    stem = unit_file_stem(str(payload["candidate_id"]), str(payload["member_identity"]))
    path = Path(output) / "fields" / f"{stem}.npz"
    path.parent.mkdir(parents=True, exist_ok=True)
    write_npz_deterministic(path, capture)
    payload["capture_file"] = {"path": f"fields/{stem}.npz", "sha256": _sha256(path), "frames": int(capture["frame_index"].size)}


def _validated_workers(workers: Any) -> int:
    if isinstance(workers, bool) or not isinstance(workers, int) or workers < 1:
        raise FieldCaptureError(f"workers must be a positive integer, got {workers!r}")
    return workers


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], capture_output=True, text=True, check=True, cwd=REPO_ROOT).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def run_field_capture(
    *,
    data_directory: str | Path,
    characterization_directory: str | Path,
    output_directory: str | Path,
    units: Sequence[tuple[str, str]],
    workers: int = DEFAULT_WORKERS,
    progress: Callable[[int, int, str, str], None] | None = None,
) -> dict[str, Any]:
    """Replay the units on calibration members with field capture; write units/, fields/ and the manifest."""

    workers = _validated_workers(workers)
    unit_list = sorted({(str(candidate), str(member)) for candidate, member in units})
    if not unit_list:
        raise FieldCaptureError("no units requested")
    member_ids = require_calibration_members([member for _, member in unit_list])
    output = Path(output_directory).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    characterization = Path(characterization_directory).expanduser().resolve()
    member_map = _member_map(data_directory)
    frame_rows_by_member: dict[str, list[dict[str, Any]]] = {}
    for member_id in member_ids:
        member = member_map.get(member_id)
        if member is None:
            raise FieldCaptureError(f"dataset member is missing: {member_id}")
        frame_rows_by_member[member_id] = list(_portable_frame_rows(_find_frame_file(characterization, member), member))
    jobs = stage_a.build_stage_a_jobs(unit_list, member_map, frame_rows_by_member, characterization_directory=characterization)
    total = len(jobs)
    finished = 0

    def on_result(result: SimulationResult) -> None:
        nonlocal finished
        store_unit_fields(output, result.payload)
        finished += 1
        if progress is not None:
            progress(finished, total, str(result.payload["candidate_id"]), str(result.payload["member_identity"]))

    effective_workers = max(1, min(workers, total))
    if effective_workers == 1:
        completed = execute_serial_jobs(jobs, _field_capture_unit_job, on_result=on_result)
    else:
        completed = execute_parallel_jobs(jobs, _field_capture_unit_job, workers=effective_workers, on_result=on_result)

    unit_rows: list[dict[str, Any]] = []
    for result in sorted(completed, key=lambda item: item.job.case_index):
        payload = _json_safe(result.payload)
        stem = unit_file_stem(str(payload["candidate_id"]), str(payload["member_identity"]))
        write_json(output / "units" / f"{stem}.json", payload)
        unit_rows.append(
            {
                "candidate_id": payload["candidate_id"],
                "member_identity": payload["member_identity"],
                "unit_file": f"units/{stem}.json",
                "requested_frame_count": payload.get("requested_frame_count"),
                "returned_frame_count": payload.get("returned_frame_count"),
                "captured_frame_count": payload.get("captured_frame_count"),
                "stage_a_gate_failures": list(payload.get("gate_failures") or []),
                "capture_gate_failures": list(payload.get("capture_gate_failures") or []),
                "evaluation_status": payload.get("evaluation_status"),
                "capture_file": payload.get("capture_file"),
            }
        )
    manifest = {
        "schema": SCHEMA,
        "patch_version": PATCH_VERSION,
        "step": STEP_ID,
        "git_commit": _git("rev-parse", "HEAD"),
        "git_worktree_dirty": bool(_git("status", "--porcelain")),
        "module_sha256": _sha256(Path(__file__)),
        "plan_sha256": _sha256(PLAN_PATH) if PLAN_PATH.is_file() else "unavailable",
        "production_hw_semantics_version": PRODUCTION_HW_SEMANTICS_VERSION,
        "production_hw_association_policy_version": POLICY_VERSION,
        "scored_frame_rule_version": SCORED_FRAME_RULE_VERSION,
        "execution": {"workers": effective_workers, "start_method": "serial" if effective_workers == 1 else "spawn"},
        "member_sha256": {member_id: member_map[member_id].sha256 for member_id in member_ids},
        "units": unit_rows,
        "field_dtype": "float64",
        "runtime": {"python": sys.version.split()[0], "numpy": np.__version__, "platform": platform.platform()},
        "guardrails": {
            "held_out_members_used": False,
            "parameter_fitting_performed": False,
            "parameter_selection_performed": False,
            "full_campaign_dispatched": False,
            "production_semantics_changed": False,
            "workers_wrote_files": False,
        },
    }
    write_json(output / MANIFEST_NAME, manifest)
    return manifest


# ---------------------------------------------------------------------- offline round trip and gate


def remeasure_production_hw(
    field: np.ndarray,
    selected_label: int,
    *,
    liquidus_temperature_K: float,
    cell_size_um: float,
    experimental_pixel_size_um: float,
) -> dict[str, Any]:
    """Re-measure production H/W from a saved field: the selector's labelling, then the pristine contour measure."""

    field = np.asarray(field, dtype=np.float64)
    labels, sizes = _label_liquid_components(field >= float(liquidus_temperature_K))
    if not 1 <= int(selected_label) <= len(sizes):
        raise FieldCaptureError(f"selected label {selected_label} is not a liquid component of the saved field")
    return _pristine_component_hw(
        field,
        labels == int(selected_label),
        liquidus_temperature_K=float(liquidus_temperature_K),
        cell_size_um=float(cell_size_um),
        experimental_pixel_size_um=float(experimental_pixel_size_um),
    )


def _same(a: Any, b: Any) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return float(a) == float(b)


def verify_round_trip(arrays: Mapping[str, np.ndarray], records: Mapping[int, Mapping[str, Any]]) -> dict[str, Any]:
    """G3: the saved fields reproduce production H/W bit for bit (SELECTED) and the status on every frame."""

    liquidus = float(arrays["liquidus_temperature_K"])
    cell = float(arrays["cell_size_um"])
    pixel = float(arrays["experimental_pixel_size_um"])
    mismatches: list[dict[str, Any]] = []
    selected = exact = 0
    for i, frame in enumerate(np.asarray(arrays["frame_index"]).tolist()):
        record = records.get(int(frame))
        field = np.asarray(arrays["top_surface_temperature_K"][i])
        status = str(arrays["production_status"][i])
        problem = None
        if record is None:
            problem = "frame_record_missing"
        elif str(record.get("production_status") or "") != status:
            problem = "status_differs"
        elif int(np.count_nonzero(field >= liquidus)) != int(arrays["liquid_cells"][i]):
            problem = "liquid_cell_count_differs"
        elif status == SELECTED_STATUS:
            selected += 1
            try:
                measured = remeasure_production_hw(
                    field, int(arrays["selected_label"][i]), liquidus_temperature_K=liquidus, cell_size_um=cell, experimental_pixel_size_um=pixel
                )
            except FieldCaptureError:
                problem = "selected_label_not_in_saved_field"
            else:
                if _same(measured.get("H_pixels"), record.get("simulated_H_pixels")) and _same(measured.get("W_pixels"), record.get("simulated_W_pixels")):
                    exact += 1
                else:
                    problem = "selected_hw_differs"
        elif status in ZERO_SCORED_STATUSES:
            if not (_same(record.get("simulated_H_pixels"), 0.0) and _same(record.get("simulated_W_pixels"), 0.0)):
                problem = "zero_scored_hw_not_zero"
        elif record.get("simulated_H_pixels") is not None or record.get("simulated_W_pixels") is not None:
            problem = "fail_closed_hw_not_undefined"
        if problem is not None:
            mismatches.append({"frame_index": int(frame), "problem": problem, "production_status": status})
    frames = int(np.asarray(arrays["frame_index"]).size)
    return {
        "frames": frames,
        "selected_frames": selected,
        "selected_hw_bit_identical": exact,
        "mismatch_count": len(mismatches),
        "mismatches": mismatches[:50],
        "pass": bool(frames > 0 and not mismatches and exact == selected),
    }


def _reference_rows(path: Path, columns: Sequence[str]) -> dict[tuple[str, str], dict[int, dict[str, str]]]:
    out: dict[tuple[str, str], dict[int, dict[str, str]]] = {}
    if not Path(path).is_file():
        return out
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            key = (str(row["candidate_id"]), str(row["member_identity"]))
            out.setdefault(key, {})[int(row["frame_index"])] = {column: row.get(column, "") for column in columns}
    return out


def compare_with_stage_a(records: Mapping[int, Mapping[str, Any]], reference: Mapping[int, Mapping[str, str]]) -> dict[str, Any]:
    """G2: frame records are bit-identical (repr) to the archived Patch 22.3.7 Stage-A rows."""

    mismatches: list[dict[str, Any]] = []
    for frame, expected in sorted(reference.items()):
        record = records.get(frame)
        if record is None:
            mismatches.append({"frame_index": frame, "column": "<row>", "expected": "present", "observed": "missing"})
            continue
        for column in STAGE_A_COMPARE_COLUMNS:
            observed = str(stage_a._csv_value(record.get(column)))
            if observed != expected[column]:
                mismatches.append({"frame_index": frame, "column": column, "expected": expected[column], "observed": observed})
    extra = sorted(set(records) - set(reference))
    return {
        "reference_rows": len(reference),
        "unit_rows": len(records),
        "extra_unit_rows": len(extra),
        "mismatch_count": len(mismatches),
        "mismatches": mismatches[:50],
        "pass": bool(reference and not mismatches and not extra),
    }


def compare_with_census(arrays: Mapping[str, np.ndarray], reference: Mapping[int, Mapping[str, str]]) -> dict[str, Any]:
    """G4: captured source and heating centres equal the 22.3.6 census telemetry at the same process row."""

    pairs = (
        ("source_center_x_mm", "census_source_center_x_mm"),
        ("source_center_y_mm", "census_source_center_y_mm"),
        ("heating_center_x_mm", "census_heating_center_x_mm"),
        ("heating_center_y_mm", "census_heating_center_y_mm"),
    )
    mismatches: list[dict[str, Any]] = []
    max_abs = 0.0
    frames = np.asarray(arrays["frame_index"]).tolist()
    for i, frame in enumerate(frames):
        expected = reference.get(int(frame))
        if expected is None:
            mismatches.append({"frame_index": int(frame), "field": "<row>"})
            continue
        if int(expected["mapped_process_row"]) != int(arrays["mapped_process_row"][i]):
            mismatches.append({"frame_index": int(frame), "field": "mapped_process_row"})
        for ours, theirs in pairs:
            observed, wanted = float(arrays[ours][i]), float(expected[theirs]) if expected[theirs] != "" else float("nan")
            if not (observed == wanted or (math.isnan(observed) and math.isnan(wanted))):
                mismatches.append({"frame_index": int(frame), "field": ours, "expected": wanted, "observed": observed})
                if math.isfinite(observed) and math.isfinite(wanted):
                    max_abs = max(max_abs, abs(observed - wanted))
    return {
        "frames_compared": len(frames),
        "mismatch_count": len(mismatches),
        "max_abs_difference_mm": max_abs,
        "mismatches": mismatches[:50],
        "pass": bool(frames and not mismatches),
    }


def frozen_core_check() -> dict[str, Any]:
    payload = json.loads(CORE_HASHES_JSON.read_text(encoding="utf-8"))
    files = [{"path": item["path"], "expected": item["sha256"], "observed": _sha256(REPO_ROOT / item["path"])} for item in payload["files"]]
    return {"files": len(files), "pass": bool(files and all(item["expected"] == item["observed"] for item in files))}


def dispatch_lock_check() -> dict[str, Any]:
    from lpbf.patch22_4_3_parallel_coarse_calibration_execution import CAMPAIGN_DISPATCH_AUTHORIZED_BY

    return {"CAMPAIGN_DISPATCH_AUTHORIZED_BY": CAMPAIGN_DISPATCH_AUTHORIZED_BY, "pass": CAMPAIGN_DISPATCH_AUTHORIZED_BY is None}


def evaluate_capture_gate(
    output_directory: str | Path,
    *,
    stage_a_frames_csv: str | Path = STAGE_A_FRAMES_CSV,
    census_frames_csv: str | Path = CENSUS_FRAMES_CSV,
    require_references: bool = False,
) -> dict[str, Any]:
    """Evaluate G1-G4 per unit and G5 globally; write ``field_capture_gate.json``."""

    output = Path(output_directory).expanduser().resolve()
    manifest = json.loads((output / MANIFEST_NAME).read_text(encoding="utf-8"))
    stage_a_rows = _reference_rows(Path(stage_a_frames_csv), STAGE_A_COMPARE_COLUMNS)
    census_rows = _reference_rows(
        Path(census_frames_csv),
        ("mapped_process_row", "census_source_center_x_mm", "census_source_center_y_mm", "census_heating_center_x_mm", "census_heating_center_y_mm"),
    )
    units: list[dict[str, Any]] = []
    for unit in manifest["units"]:
        key = (str(unit["candidate_id"]), str(unit["member_identity"]))
        payload = json.loads((output / unit["unit_file"]).read_text(encoding="utf-8"))
        records = {int(row["frame_index"]): row for row in payload.get("frame_records") or []}
        requested, returned, captured = (int(payload.get(name) or 0) for name in ("requested_frame_count", "returned_frame_count", "captured_frame_count"))
        g1 = {
            "requested": requested,
            "returned": returned,
            "captured": captured,
            "stage_a_gate_failures": list(payload.get("gate_failures") or []),
            "capture_gate_failures": list(payload.get("capture_gate_failures") or []),
        }
        g1["pass"] = bool(requested > 0 and requested == returned == captured and not g1["stage_a_gate_failures"] and not g1["capture_gate_failures"])
        result: dict[str, Any] = {"candidate_id": key[0], "member_identity": key[1], "G1_counts": g1}
        capture_file = payload.get("capture_file")
        if capture_file is None:
            result["G3_round_trip"] = {"pass": False, "reason": "no capture file"}
            result["G4_census"] = None
        else:
            path = output / capture_file["path"]
            if _sha256(path) != capture_file["sha256"]:
                result["G3_round_trip"] = {"pass": False, "reason": "capture file hash differs from the payload"}
                result["G4_census"] = None
            else:
                with np.load(path) as data:
                    arrays = {name: data[name] for name in data.files}
                result["G3_round_trip"] = verify_round_trip(arrays, records)
                reference = census_rows.get(key)
                result["G4_census"] = None if reference is None else compare_with_census(arrays, reference)
        reference = stage_a_rows.get(key)
        result["G2_stage_a"] = None if reference is None else compare_with_stage_a(records, reference)
        checks = [g1["pass"], result["G3_round_trip"]["pass"]]
        checks += [item["pass"] for item in (result["G2_stage_a"], result["G4_census"]) if item is not None]
        if require_references:
            checks += [result["G2_stage_a"] is not None, result["G4_census"] is not None]
        result["pass"] = bool(all(checks))
        units.append(result)
    g5 = {"frozen_core": frozen_core_check(), "dispatch_lock": dispatch_lock_check()}
    g5["pass"] = bool(g5["frozen_core"]["pass"] and g5["dispatch_lock"]["pass"])
    passed = bool(units and all(unit["pass"] for unit in units) and g5["pass"])
    gate = {
        "schema": SCHEMA,
        "patch_version": PATCH_VERSION,
        "status": GATE_PASS if passed else GATE_FAIL,
        "require_references": bool(require_references),
        "units": units,
        "G5_global": g5,
        "full_test_suite": "run separately: python -m pytest -q",
    }
    write_json(output / GATE_NAME, _json_safe(gate))
    return gate


# ---------------------------------------------------------------------- CLI


def _parse_unit(text: str) -> tuple[str, str]:
    candidate, sep, member = str(text).partition("@")
    if not sep or not candidate or not member:
        raise argparse.ArgumentTypeError(f"unit must be candidate@member, got {text!r}")
    return candidate, member


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Patch 22.3.8 Step 1: field capture on calibration members")
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--characterization-dir", required=True)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIRECTORY)
    parser.add_argument("--preset", choices=("step1", "step2", "step4"), default=None)
    parser.add_argument("--units", nargs="+", type=_parse_unit, default=None, help="candidate@member, e.g. anchor_center@20260730:part_1")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    args = parser.parse_args(argv)
    if (args.preset is None) == (args.units is None):
        parser.error("give exactly one of --preset or --units")
    presets = {"step1": STEP1_UNITS, "step2": step2_units(), "step4": step4_units()}
    units = presets[args.preset] if args.preset is not None else tuple(args.units)

    def progress(done: int, total: int, candidate: str, member: str) -> None:
        print(f"unit {done}/{total} done: {candidate} {member}", flush=True)

    manifest = run_field_capture(
        data_directory=args.data_dir,
        characterization_directory=args.characterization_dir,
        output_directory=args.output_dir,
        units=units,
        workers=args.workers,
        progress=progress,
    )
    gate = evaluate_capture_gate(args.output_dir, require_references=args.preset == "step1")
    summary = {
        "status": gate["status"],
        "units": [
            {
                "unit": f"{unit['candidate_id']}@{unit['member_identity']}",
                "pass": unit["pass"],
                "G1": unit["G1_counts"]["pass"],
                "G2": None if unit["G2_stage_a"] is None else unit["G2_stage_a"]["pass"],
                "G3": unit["G3_round_trip"]["pass"],
                "G4": None if unit["G4_census"] is None else unit["G4_census"]["pass"],
            }
            for unit in gate["units"]
        ],
        "G5": gate["G5_global"]["pass"],
        "execution": manifest["execution"],
    }
    print(json.dumps(summary, indent=2))
    return 0 if gate["status"] == GATE_PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
