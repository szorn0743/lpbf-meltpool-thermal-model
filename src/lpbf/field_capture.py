"""Capture of the model's top-surface temperature field at every scored frame, and the frozen-core check.

``field_capture_instrumentation`` wraps one trial evaluation and records, without altering any result, the 99 x 99
top-surface temperature field, the beam cell, the source geometry and the production association outcome at every
requested (scored) frame. Workers write nothing: the captured arrays travel back in the payload and the parent writes
one compressed ``.npz`` per unit (``store_unit_fields``). ``compare_with_smoke_reference`` is the smoke gate's
bit-identity comparison against the frozen reference frame records in ``results/smoke_reference/``, and
``frozen_core_check`` verifies the numerical core against its SHA-256 manifest.
"""
from __future__ import annotations

import csv
import io
import json
import math
import zipfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

import numpy as np

from lpbf import frame_records
from lpbf.infrastructure import sha256_file
from lpbf.model import current_execution
from lpbf.model._accepted_core import comparison as accepted_comparison
from lpbf.paths import repository_root

REPO_ROOT = repository_root()
SMOKE_REFERENCE_FRAMES_CSV = REPO_ROOT / "results" / "smoke_reference" / "frames.csv"
SMOKE_REFERENCE_REPORT_JSON = REPO_ROOT / "results" / "smoke_reference" / "report.json"
CORE_HASHES_JSON = Path(__file__).with_name("data") / "accepted_core_hashes.json"

SELECTED_STATUS = "SELECTED"
NO_LABEL = -1

# The 272-unit campaign dispatcher of the development code is not part of this package. The run records carry this
# check with ``CAMPAIGN_DISPATCH_AUTHORIZED_BY = None`` ("locked"); new manifests record the same, unchanged.
CAMPAIGN_DISPATCH_AUTHORIZED_BY: str | None = None

SMOKE_REFERENCE_COMPARE_COLUMNS = (
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
    original_evaluate = frame_records.evaluate_calibration_trial
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
    frame_records.evaluate_calibration_trial = capture_evaluate
    try:
        yield state
    finally:
        current_execution.build_centered_heat_source_for_row_with_deposition_depth = original_builder
        accepted_comparison.top_surface_liquid_component_diagnostics = original_top
        accepted_comparison.interpolated_component_contour_hw_diagnostic = original_component_hw
        frame_records.evaluate_calibration_trial = original_evaluate


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


# ---------------------------------------------------------------------- parent-side storage and runner


def unit_file_stem(candidate_id: str, member_id: str) -> str:
    return f"{candidate_id}__{member_id.replace(':', '_')}"


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
    payload["capture_file"] = {"path": f"fields/{stem}.npz", "sha256": sha256_file(path), "frames": int(capture["frame_index"].size)}


# ---------------------------------------------------------------------- offline round trip and gate


def _reference_rows(path: Path, columns: Sequence[str]) -> dict[tuple[str, str], dict[int, dict[str, str]]]:
    out: dict[tuple[str, str], dict[int, dict[str, str]]] = {}
    if not Path(path).is_file():
        return out
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            key = (str(row["candidate_id"]), str(row["member_identity"]))
            out.setdefault(key, {})[int(row["frame_index"])] = {column: row.get(column, "") for column in columns}
    return out


def compare_with_smoke_reference(records: Mapping[int, Mapping[str, Any]], reference: Mapping[int, Mapping[str, str]]) -> dict[str, Any]:
    """Frame records are bit-identical (repr) to the frozen reference rows of the smoke unit."""

    mismatches: list[dict[str, Any]] = []
    for frame, expected in sorted(reference.items()):
        record = records.get(frame)
        if record is None:
            mismatches.append({"frame_index": frame, "column": "<row>", "expected": "present", "observed": "missing"})
            continue
        for column in SMOKE_REFERENCE_COMPARE_COLUMNS:
            observed = str(frame_records._csv_value(record.get(column)))
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


def frozen_core_check() -> dict[str, Any]:
    payload = json.loads(CORE_HASHES_JSON.read_text(encoding="utf-8"))
    files = [{"path": item["path"], "expected": item["sha256"], "observed": sha256_file(REPO_ROOT / item["path"])} for item in payload["files"]]
    return {"files": len(files), "pass": bool(files and all(item["expected"] == item["observed"] for item in files))}


def dispatch_lock_check() -> dict[str, Any]:
    return {"CAMPAIGN_DISPATCH_AUTHORIZED_BY": CAMPAIGN_DISPATCH_AUTHORIZED_BY, "pass": CAMPAIGN_DISPATCH_AUTHORIZED_BY is None}
