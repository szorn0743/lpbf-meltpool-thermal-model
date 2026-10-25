"""Patch 22.3.6 association census: measure the failure mechanisms before any semantic change.

Diagnostic only.  This module runs the accepted thermal path under the current
Patch 22.3.5 production semantics and records, for every eligible camera frame,
per-liquid-component geometry (cell count, beam-power share, distances to the
source from cell centers and from the interpolated liquidus contour, boundary
contact, and the component's own interpolated-contour H/W) together with the
source position that produced the field.  Candidate association rules are then
evaluated offline on those identical fields.

It changes no production code path: the census rides on the same two
diagnostic seams that Patch 22.3.5 instruments, one level further out, so the
22.3.5 outcome of every frame is computed exactly as in production.  Undefined
production H/W stays ``None``; it is never converted to zero here.  The 272-work
unit campaign is never dispatched.
"""
from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Sequence

import numpy as np

from lpbf.calibration_contract import (
    COEFFICIENT_ORDER,
    Patch21GlobalParameterPolicy,
    calibration_member_identities,
    member_identity,
)
from lpbf.execution.parallel import execute_parallel_jobs
from lpbf.execution.work_units import SimulationJob, SimulationResult, execute_serial_jobs
from lpbf.experiments.current_framework import CalibrationExecutionScope, evaluate_calibration_trial
from lpbf.experiments.dataset import DatasetMember
from lpbf.infrastructure import write_json
from lpbf.model import current_execution
from lpbf.model._accepted_core import comparison as accepted_comparison
from lpbf.model.laser_component_association import POLICY_VERSION, surface_beam_profile
from lpbf.model.observation_diagnostics import (
    _label_liquid_components,
    interpolated_component_contour_hw_diagnostic as _pristine_component_hw_diagnostic,
)
from lpbf.scored_frame_rule import label_track_positions
from lpbf.model.production_hw import PRODUCTION_HW_DEFINITION, PRODUCTION_HW_SEMANTICS_VERSION
from lpbf.patch22_3_5_1_frozen_revalidation import _candidate_coordinates, _member_map
from lpbf.patch22_4_3_parallel_coarse_calibration_execution import (
    WINDOW_CELLS,
    _dataset_member_context,
    _dataset_member_from_context,
    _find_frame_file,
    _json_safe,
    _portable_frame_rows,
)

PATCH_VERSION = "22.3.6"
CENSUS_SCHEMA = "lpbf_patch22_3_6_association_census"
CENSUS_STATUS_PASS = "PASS_PATCH_22_3_6_ASSOCIATION_CENSUS_COMPLETE"
CENSUS_STATUS_FAIL = "FAIL_PATCH_22_3_6_ASSOCIATION_CENSUS_INCOMPLETE"
EVALUATION_STATUS_PASS = "PASS_PATCH_22_3_6_CENSUS_EVALUATION"
SYNC_AUDIT_STATUS_PASS = "PASS_PATCH_22_3_6_SYNC_TRACK_START_AUDIT"
DEFAULT_CENSUS_WORKERS = 4
STAGE_A_CANDIDATES = ("anchor_center", "anchor_t_min", "anchor_t_max", "halton_04", "halton_11")
STAGE_A_MEMBERS = ("20260730:part_1", "20260730:part_3")
# Predeclared evaluation grids.  They are reporting grids for the Stage-1 memo,
# not tolerances: no production rule is changed by this module.
BEAM_SHARE_FLOORS = (0.005, 0.01, 0.02, 0.05, 0.10, 0.135, 0.25)
CONTOUR_RADII_CELLS = (1.0, 1.5, 2.0, 2.5)
RULE_STATUSES = ("SELECTED", "ZERO_FOOTPRINT", "NO_LASER_ASSOCIATED_MELT", "AMBIGUOUS", "UNENCLOSED", "DEGENERATE")
UNDEFINED_STATUSES = frozenset({"AMBIGUOUS", "UNENCLOSED", "DEGENERATE"})
SCORED_AS_ZERO_STATUSES = frozenset({"ZERO_FOOTPRINT", "NO_LASER_ASSOCIATED_MELT"})
ORTHOGONAL_DISTANCE_TOLERANCE = 1.0e-9

REPORT_NAME = "PATCH_22_3_6_ASSOCIATION_CENSUS_REPORT.json"
FRAMES_CSV_NAME = "PATCH_22_3_6_ASSOCIATION_CENSUS_FRAMES.csv"
COMPONENTS_CSV_NAME = "PATCH_22_3_6_ASSOCIATION_CENSUS_COMPONENTS.csv"
EVALUATION_NAME = "PATCH_22_3_6_CENSUS_EVALUATION.json"
RESIDUAL_CSV_NAME = "PATCH_22_3_6_CENSUS_RESIDUAL_CASES.csv"
SYNC_AUDIT_NAME = "PATCH_22_3_6_SYNC_TRACK_START_AUDIT.json"
SYNC_AUDIT_CSV_NAME = "PATCH_22_3_6_SYNC_TRACK_START_AUDIT_TRACKS.csv"

ProgressCallback = Callable[[int, int, Mapping[str, Any]], None]


class AssociationCensusError(RuntimeError):
    """Raised when the census input or execution cannot be trusted."""


def _optional_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _finite_positive(h: Any, w: Any) -> bool:
    hf, wf = _optional_float(h), _optional_float(w)
    return hf is not None and wf is not None and hf > 0.0 and wf > 0.0


# --------------------------------------------------------------------------- geometry


# ``surface_beam_profile`` moved to ``lpbf.model.laser_component_association`` in
# Patch 22.3.7 (it is now the production beam-share profile); re-exported here.


def component_contour_points_mm(
    top_surface_temperature_K: np.ndarray,
    component_mask: np.ndarray,
    *,
    liquidus_temperature_K: float,
    spacing_mm: float,
) -> np.ndarray:
    """Linearly interpolated T = T_liquidus crossings on the component boundary, in mm.

    Same center-to-center interpolation as the production contour diagnostic;
    only the units differ (mm here, camera pixels there).
    """

    top = np.asarray(top_surface_temperature_K, dtype=np.float64)
    component = np.asarray(component_mask, dtype=bool)
    if top.ndim != 2 or top.shape != component.shape:
        raise ValueError("top-surface temperature and component mask must be matching 2-D arrays")
    level = float(liquidus_temperature_K)
    spacing = float(spacing_mm)
    nx, ny = top.shape
    centers_x = (np.arange(nx, dtype=np.float64) + 0.5) * spacing
    centers_y = (np.arange(ny, dtype=np.float64) + 0.5) * spacing
    points: list[tuple[float, float]] = []
    for i in range(nx - 1):
        for j in range(ny):
            if bool(component[i, j]) == bool(component[i + 1, j]):
                continue
            t0, t1 = float(top[i, j]), float(top[i + 1, j])
            if (t0 >= level) == (t1 >= level):
                raise ValueError("component boundary crossed an edge that does not cross T_liquidus")
            fraction = (level - t0) / (t1 - t0)
            points.append((centers_x[i] + fraction * spacing, centers_y[j]))
    for i in range(nx):
        for j in range(ny - 1):
            if bool(component[i, j]) == bool(component[i, j + 1]):
                continue
            t0, t1 = float(top[i, j]), float(top[i, j + 1])
            if (t0 >= level) == (t1 >= level):
                raise ValueError("component boundary crossed an edge that does not cross T_liquidus")
            fraction = (level - t0) / (t1 - t0)
            points.append((centers_x[i], centers_y[j] + fraction * spacing))
    return np.asarray(points, dtype=np.float64).reshape(-1, 2)


def _boundary_sides(component: np.ndarray) -> list[str]:
    return [
        side
        for side, contacted in (
            ("x_min", np.any(component[0, :])),
            ("x_max", np.any(component[-1, :])),
            ("y_min", np.any(component[:, 0])),
            ("y_max", np.any(component[:, -1])),
        )
        if bool(contacted)
    ]


def _min_distance_cells(points_mm: np.ndarray, x_mm: float, y_mm: float, spacing_mm: float) -> float | None:
    if points_mm is None or len(points_mm) == 0:
        return None
    return float(np.min(np.hypot(points_mm[:, 0] - x_mm, points_mm[:, 1] - y_mm)) / spacing_mm)


def per_component_telemetry(
    liquid_mask: np.ndarray,
    top_surface_temperature_K: np.ndarray,
    *,
    spacing_mm: float,
    liquidus_temperature_K: float,
    experimental_pixel_size_um: float,
    source_center_x_mm: float,
    source_center_y_mm: float,
    gaussian_radius_mm: float,
    beam_i: int,
    beam_j: int,
    heating_center_x_mm: float | None = None,
    heating_center_y_mm: float | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Describe every 4-neighbor liquid component relative to the beam.

    Pure geometry on an already-computed field.  Nothing is selected here.
    """

    mask = np.asarray(liquid_mask, dtype=bool)
    top = np.asarray(top_surface_temperature_K, dtype=np.float64)
    if mask.ndim != 2 or top.shape != mask.shape:
        raise AssociationCensusError("liquid mask and top-surface temperature must be matching 2-D arrays")
    spacing = float(spacing_mm)
    labels, sizes = _label_liquid_components(mask)
    nx, ny = mask.shape
    profile = surface_beam_profile(
        nx,
        ny,
        spacing_mm=spacing,
        center_x_mm=source_center_x_mm,
        center_y_mm=source_center_y_mm,
        gaussian_radius_mm=gaussian_radius_mm,
    )
    bi = min(max(int(beam_i), 0), nx - 1)
    bj = min(max(int(beam_j), 0), ny - 1)
    beam_label = int(labels[bi, bj])
    peak = np.unravel_index(int(np.argmax(profile)), profile.shape)
    heating_available = heating_center_x_mm is not None and heating_center_y_mm is not None

    components: list[dict[str, Any]] = []
    for label in range(1, len(sizes) + 1):
        component = labels == label
        ij = np.argwhere(component)
        centers_x = (ij[:, 0].astype(np.float64) + 0.5) * spacing
        centers_y = (ij[:, 1].astype(np.float64) + 0.5) * spacing
        center_distance = float(np.min(np.hypot(centers_x - source_center_x_mm, centers_y - source_center_y_mm)) / spacing)
        sides = _boundary_sides(component)
        try:
            hw = _pristine_component_hw_diagnostic(
                top,
                component,
                liquidus_temperature_K=liquidus_temperature_K,
                cell_size_um=spacing * 1000.0,
                experimental_pixel_size_um=experimental_pixel_size_um,
            )
            contour_status = str(hw["status"])
            h_pixels, w_pixels = _optional_float(hw["H_pixels"]), _optional_float(hw["W_pixels"])
        except ValueError:
            contour_status, h_pixels, w_pixels = "INCONSISTENT_CONTOUR", None, None
        try:
            points = component_contour_points_mm(
                top, component, liquidus_temperature_K=liquidus_temperature_K, spacing_mm=spacing
            )
        except ValueError:
            points = np.empty((0, 2), dtype=np.float64)
        record: dict[str, Any] = {
            "label": int(label),
            "cell_count": int(sizes[label - 1]),
            "contains_beam_cell": bool(label == beam_label),
            "touches_boundary": bool(sides),
            "boundary_sides": sides,
            "beam_share": float(profile[component].sum()),
            "centroid_i": float(ij[:, 0].mean()),
            "centroid_j": float(ij[:, 1].mean()),
            "min_cell_center_distance_cells": center_distance,
            "min_contour_distance_cells": _min_distance_cells(points, source_center_x_mm, source_center_y_mm, spacing),
            "min_cell_center_distance_from_heating_center_cells": (
                float(np.min(np.hypot(centers_x - heating_center_x_mm, centers_y - heating_center_y_mm)) / spacing)
                if heating_available
                else None
            ),
            "min_contour_distance_from_heating_center_cells": (
                _min_distance_cells(points, heating_center_x_mm, heating_center_y_mm, spacing) if heating_available else None
            ),
            "contour_point_count": int(len(points)),
            "contour_status": contour_status,
            "H_pixels": h_pixels,
            "W_pixels": w_pixels,
        }
        components.append(record)

    summary = {
        "component_count": int(len(sizes)),
        "liquid_cell_count": int(np.count_nonzero(mask)),
        "beam_cell_label": beam_label if beam_label > 0 else None,
        "beam_share_on_liquid_total": float(sum(item["beam_share"] for item in components)),
        "profile_peak_cell": [int(peak[0]), int(peak[1])],
        "profile_peak_cell_is_liquid": bool(mask[peak]),
    }
    return components, summary


# ---------------------------------------------------------------------- rule evaluation


def _rule_outcome(
    status: str,
    *,
    selected: Mapping[str, Any] | None,
    beam_share: float | None,
    distance_cells: float | None,
) -> dict[str, Any]:
    if status not in RULE_STATUSES:
        raise AssociationCensusError(f"unknown rule status {status!r}")
    scored = status == "SELECTED" or status in SCORED_AS_ZERO_STATUSES
    if status == "SELECTED":
        assert selected is not None
        h, w = float(selected["H_pixels"]), float(selected["W_pixels"])
    elif status in SCORED_AS_ZERO_STATUSES:
        # Owner decision D1 (2026-10-14): "no melt under the beam" is a prediction and is scored as zero.
        h, w = 0.0, 0.0
    else:
        h = w = None  # undefined stays undefined; never fabricated as zero
    return {
        "status": status,
        "selected_label": None if selected is None or status != "SELECTED" else int(selected["label"]),
        "beam_share": beam_share,
        "distance_cells": distance_cells,
        "scored": bool(scored),
        "scored_H_pixels": h,
        "scored_W_pixels": w,
        "undefined_reason": None if scored else status,
    }


def _component_contour_distance(component: Mapping[str, Any]) -> float:
    distance = component.get("min_contour_distance_cells")
    if distance is None:
        distance = component.get("min_cell_center_distance_cells")
    return float(distance)


def _selected_outcome(component: Mapping[str, Any], *, beam_share: float | None, distance_cells: float | None) -> dict[str, Any]:
    if bool(component.get("touches_boundary")) or str(component.get("contour_status")) == "UNENCLOSED_BEAM_COMPONENT":
        return _rule_outcome("UNENCLOSED", selected=component, beam_share=beam_share, distance_cells=distance_cells)
    if not _finite_positive(component.get("H_pixels"), component.get("W_pixels")):
        return _rule_outcome("DEGENERATE", selected=component, beam_share=beam_share, distance_cells=distance_cells)
    return _rule_outcome("SELECTED", selected=component, beam_share=beam_share, distance_cells=distance_cells)


def evaluate_beam_share_rule(
    components: Sequence[Mapping[str, Any]],
    *,
    floor: float,
    tie_rel_tol: float = 1.0e-6,
) -> dict[str, Any]:
    """Candidate rule F2: the component receiving the largest share of beam power."""

    try:
        floor_value = float(floor)
    except (TypeError, ValueError) as exc:
        raise AssociationCensusError("floor must be a number in [0, 1)") from exc
    if not math.isfinite(floor_value) or not (0.0 <= floor_value < 1.0):
        raise AssociationCensusError("floor must be a number in [0, 1)")
    if not components:
        return _rule_outcome("ZERO_FOOTPRINT", selected=None, beam_share=None, distance_cells=None)
    shares = [(float(item["beam_share"]), item) for item in components]
    best_share = max(share for share, _ in shares)
    best = max(shares, key=lambda pair: pair[0])[1]
    best_distance = _component_contour_distance(best)
    if best_share < floor_value:
        return _rule_outcome("NO_LASER_ASSOCIATED_MELT", selected=None, beam_share=best_share, distance_cells=best_distance)
    tied = [item for share, item in shares if math.isclose(share, best_share, rel_tol=tie_rel_tol, abs_tol=1.0e-12)]
    if len(tied) != 1:
        return _rule_outcome("AMBIGUOUS", selected=None, beam_share=best_share, distance_cells=best_distance)
    return _selected_outcome(tied[0], beam_share=best_share, distance_cells=best_distance)


def evaluate_contour_distance_rule(
    components: Sequence[Mapping[str, Any]],
    *,
    radius_cells: float,
    tie_abs_tol: float = 1.0e-9,
) -> dict[str, Any]:
    """Alternative rule: nearest interpolated contour within a radius of the source."""

    radius = float(radius_cells)
    if not math.isfinite(radius) or radius <= 0.0:
        raise AssociationCensusError("radius_cells must be positive")
    if not components:
        return _rule_outcome("ZERO_FOOTPRINT", selected=None, beam_share=None, distance_cells=None)
    # A source inside a component is at distance 0 from it, not at the distance to its far edge.
    distances = [
        (0.0 if bool(item.get("contains_beam_cell")) else _component_contour_distance(item), item)
        for item in components
    ]
    best_distance = min(distance for distance, _ in distances)
    best = min(distances, key=lambda pair: pair[0])[1]
    if best_distance > radius:
        return _rule_outcome("NO_LASER_ASSOCIATED_MELT", selected=None, beam_share=float(best["beam_share"]), distance_cells=best_distance)
    tied = [item for distance, item in distances if abs(distance - best_distance) <= tie_abs_tol]
    if len(tied) != 1:
        return _rule_outcome("AMBIGUOUS", selected=None, beam_share=float(best["beam_share"]), distance_cells=best_distance)
    return _selected_outcome(tied[0], beam_share=float(tied[0]["beam_share"]), distance_cells=best_distance)


# ``label_track_positions`` moved to ``lpbf.scored_frame_rule`` in Patch 22.3.7; re-exported here.


# ---------------------------------------------------------------------- instrumentation


@contextmanager
def association_census_instrumentation() -> Iterator[dict[str, Any]]:
    """Record per-component telemetry on every observation without changing production semantics.

    Entered *outside* ``laser_associated_observation_instrumentation``: the
    production wrapper then captures these wrappers as its originals, so the
    22.3.5 selection runs unchanged and the census keys are added to the same
    observation diagnostics record.  The heat-source seam is the calibration
    runtime's deposition-depth builder, looked up by name at call time.
    """

    original_builder = current_execution.build_centered_heat_source_for_row_with_deposition_depth
    original_top = accepted_comparison.top_surface_liquid_component_diagnostics
    original_component_hw = accepted_comparison.interpolated_component_contour_hw_diagnostic
    state: dict[str, Any] = {"builds": [], "observation": None}

    def census_builder(*args: Any, **kwargs: Any) -> Any:
        result = original_builder(*args, **kwargs)
        source = result[1]
        center_x = getattr(source, "center_x_mm", None)
        center_y = getattr(source, "center_y_mm", None)
        build = {
            "row_index": None if kwargs.get("row_index") is None else int(kwargs["row_index"]),
            "laser_on": bool(kwargs.get("laser_on", False)),
            "center_x_mm": None if center_x is None else float(center_x),
            "center_y_mm": None if center_y is None else float(center_y),
            "gaussian_radius_mm": float(getattr(source, "gaussian_radius_mm", float("nan"))),
            "deposited_power_W": _optional_float(getattr(source, "deposited_power_W", None)),
        }
        builds = state["builds"]
        builds.append(build)
        del builds[:-2]  # the current build and the one that heated the field
        return result

    def census_top(liquid_mask: np.ndarray, *, beam_i: int, beam_j: int) -> dict[str, Any]:
        diagnostics = original_top(liquid_mask, beam_i=beam_i, beam_j=beam_j)
        builds = state["builds"]
        state["observation"] = {
            "diagnostics": diagnostics,
            "mask": np.asarray(liquid_mask, dtype=bool).copy(),
            "beam_i": int(beam_i),
            "beam_j": int(beam_j),
            "source": builds[-1] if builds else None,
            "heating": builds[-2] if len(builds) > 1 else None,
            "telemetry_pending": True,
        }
        return diagnostics

    def census_component_hw(
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
        observation = state.get("observation")
        if observation is None or not observation["telemetry_pending"]:
            return result
        observation["telemetry_pending"] = False
        diagnostics = observation["diagnostics"]
        source = observation["source"]
        spacing_mm = float(cell_size_um) / 1000.0
        if source is None or source["center_x_mm"] is None or source["center_y_mm"] is None:
            diagnostics.update(
                {
                    "census_patch": PATCH_VERSION,
                    "census_telemetry_available": False,
                    "census_components": [],
                    "census_component_count": None,
                }
            )
            return result
        heating = observation["heating"]
        heating_x = None if heating is None else heating["center_x_mm"]
        heating_y = None if heating is None else heating["center_y_mm"]
        components, summary = per_component_telemetry(
            observation["mask"],
            top_surface_temperature_K,
            spacing_mm=spacing_mm,
            liquidus_temperature_K=liquidus_temperature_K,
            experimental_pixel_size_um=experimental_pixel_size_um,
            source_center_x_mm=source["center_x_mm"],
            source_center_y_mm=source["center_y_mm"],
            gaussian_radius_mm=source["gaussian_radius_mm"],
            beam_i=observation["beam_i"],
            beam_j=observation["beam_j"],
            heating_center_x_mm=heating_x,
            heating_center_y_mm=heating_y,
        )
        diagnostics.update(
            {
                "census_patch": PATCH_VERSION,
                "census_telemetry_available": True,
                "census_components": components,
                "census_component_count": summary["component_count"],
                "census_liquid_cell_count": summary["liquid_cell_count"],
                "census_beam_cell_label": summary["beam_cell_label"],
                "census_beam_share_on_liquid_total": summary["beam_share_on_liquid_total"],
                "census_profile_peak_cell": summary["profile_peak_cell"],
                "census_profile_peak_cell_is_liquid": summary["profile_peak_cell_is_liquid"],
                "census_spacing_mm": spacing_mm,
                "census_beam_cell_i": observation["beam_i"],
                "census_beam_cell_j": observation["beam_j"],
                "census_source_center_x_mm": source["center_x_mm"],
                "census_source_center_y_mm": source["center_y_mm"],
                "census_source_row_index": source["row_index"],
                "census_source_laser_on": source["laser_on"],
                "census_gaussian_radius_mm": source["gaussian_radius_mm"],
                "census_heating_center_x_mm": heating_x,
                "census_heating_center_y_mm": heating_y,
                "census_heating_row_index": None if heating is None else heating["row_index"],
                "census_heating_laser_on": None if heating is None else heating["laser_on"],
                "census_heating_deposited_power_W": None if heating is None else heating["deposited_power_W"],
                "census_production_selected_label": diagnostics.get("production_hw_association_selected_label"),
            }
        )
        return result

    current_execution.build_centered_heat_source_for_row_with_deposition_depth = census_builder
    accepted_comparison.top_surface_liquid_component_diagnostics = census_top
    accepted_comparison.interpolated_component_contour_hw_diagnostic = census_component_hw
    try:
        yield state
    finally:
        current_execution.build_centered_heat_source_for_row_with_deposition_depth = original_builder
        accepted_comparison.top_surface_liquid_component_diagnostics = original_top
        accepted_comparison.interpolated_component_contour_hw_diagnostic = original_component_hw


# -------------------------------------------------------------------- jobs and execution


def _validated_workers(workers: Any) -> int:
    if isinstance(workers, bool) or not isinstance(workers, int) or workers < 1:
        raise AssociationCensusError("workers must be a positive integer")
    return workers


def _read_scan_tracks(frame_path: Path) -> dict[str, dict[str, int]]:
    """Per-track process-row bounds from the characterization ``scan_tracks.csv`` beside the frame file."""

    path = Path(frame_path).with_name("scan_tracks.csv")
    if not path.is_file():
        raise AssociationCensusError(f"scan_tracks.csv is missing beside {frame_path}")
    tracks: dict[str, dict[str, int]] = {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        for raw in csv.DictReader(handle):
            tracks[str(raw["scan_track_id"])] = {
                "process_row_start": int(float(raw["process_row_start"])),
                "process_row_end": int(float(raw["process_row_end"])),
                "process_row_count": int(float(raw["process_row_count"])),
                "eligible_frame_count": int(float(raw.get("eligible_frame_count") or 0)),
            }
    if not tracks:
        raise AssociationCensusError(f"no scan tracks found in {path}")
    return tracks


def build_census_jobs(
    units: Sequence[tuple[str, str]],
    members: Mapping[str, DatasetMember],
    frame_rows_by_member: Mapping[str, Sequence[Mapping[str, Any]]],
    track_rows_by_member: Mapping[str, Mapping[str, Any]],
    *,
    characterization_directory: str | Path,
) -> tuple[SimulationJob, ...]:
    """One spawn-safe job per (candidate, member) unit, numbered in sorted order."""

    coordinates = _candidate_coordinates()
    characterization = str(Path(characterization_directory).expanduser().resolve())
    ordered = sorted({(str(candidate), str(member_id)) for candidate, member_id in units})
    jobs: list[SimulationJob] = []
    for ordinal, (candidate_id, member_id) in enumerate(ordered):
        member = members.get(member_id)
        if member is None:
            raise AssociationCensusError(f"dataset member is missing: {member_id}")
        if candidate_id not in coordinates:
            raise AssociationCensusError(f"candidate is not in the frozen coarse design: {candidate_id}")
        rows = [dict(row) for row in frame_rows_by_member.get(member_id, ()) if bool(row.get("observation_eligible"))]
        if not rows:
            raise AssociationCensusError(f"no eligible frames for {member_id}")
        frames = sorted({int(row["frame_index"]) for row in rows})
        jobs.append(
            SimulationJob(
                case_index=ordinal,
                member_identity=member_id,
                frame_index=frames[0],
                window_cells=WINDOW_CELLS,
                candidate_coordinates=coordinates[candidate_id],
                experiment_context={
                    "candidate_id": candidate_id,
                    "dataset_member_json": json.dumps(_dataset_member_context(member)),
                    "frame_rows_json": json.dumps(rows),
                    "track_rows_json": json.dumps(dict(track_rows_by_member.get(member_id, {}))),
                    "characterization_directory": characterization,
                },
            )
        )
    return tuple(jobs)


def _census_scope(candidate_id: str, member: DatasetMember, frame_indices: Sequence[int]) -> CalibrationExecutionScope:
    coordinates = _candidate_coordinates()[candidate_id]
    return CalibrationExecutionScope(
        scope_id=f"patch22_3_6:association_census:{candidate_id}:{member_identity(member.acquisition_set_id, member.coupon_position)}",
        observation_frame_indices=tuple(sorted(set(int(value) for value in frame_indices))),
        trial_context={
            "patch": PATCH_VERSION,
            "objective_branch": "association_census_diagnostic",
            "diagnostic_only": True,
            "candidate_id": candidate_id,
            "candidate_coordinates": coordinates,
            "production_hw_definition": PRODUCTION_HW_DEFINITION,
            "production_hw_semantics_version": PRODUCTION_HW_SEMANTICS_VERSION,
            "production_hw_association_policy_version": POLICY_VERSION,
            "validation_partition_used": False,
            "parameter_selection_performed": False,
            "parameter_fitting_performed": False,
            "full_campaign_dispatched": False,
        },
        unenclosed_contour_policy="record_nan",
        window_cells=WINDOW_CELLS,
    )


def _process_row_context(member: DatasetMember, rows: Sequence[int], warnings: list[str]) -> dict[int, dict[str, Any]]:
    """Machine XY and laser drive at the requested process rows (read-only HDF5 telemetry)."""

    if not rows:
        return {}
    try:
        import h5py

        with h5py.File(member.path, "r") as handle:
            layer = handle[member.layer_name]
            names = [name.decode() if isinstance(name, bytes) else str(name) for name in layer["names"][:]]
            data = layer["data"]
            index = {name: position for position, name in enumerate(names)}
            x = np.asarray(data[index["X-Machine"], :], dtype=np.float64)
            y = np.asarray(data[index["Y-Machine"], :], dtype=np.float64)
            drive = np.asarray(data[index["Laser Drive"], :], dtype=np.float64)
    except Exception as exc:  # telemetry only: the thermal result does not depend on it
        warnings.append(f"process-row XY telemetry unavailable: {type(exc).__name__}: {exc}")
        return {}
    count = int(len(x))
    context: dict[int, dict[str, Any]] = {}
    for row in rows:
        if 0 <= int(row) < count:
            context[int(row)] = {"x_mm": float(x[row]), "y_mm": float(y[row]), "laser_drive": float(drive[row])}
    return context


def _frame_record(
    observation: Mapping[str, Any],
    *,
    frame_row: Mapping[str, Any],
    position: Mapping[str, Any] | None,
    track_rows: Mapping[str, Any],
    row_context: Mapping[int, Mapping[str, Any]],
) -> dict[str, Any]:
    diagnostics = observation.get("observation_diagnostics") or {}
    row = int(observation["mapped_process_row"])
    track_id = str(frame_row.get("scan_track_id"))
    track = track_rows.get(track_id) or {}
    start = track.get("process_row_start")
    end = track.get("process_row_end")
    source_x = _optional_float(diagnostics.get("source_center_local_x_mm"))
    census_x = _optional_float(diagnostics.get("census_source_center_x_mm"))
    previous, current, following = (row_context.get(row - 1), row_context.get(row), row_context.get(row + 1))
    record: dict[str, Any] = {
        "frame_index": int(observation["frame_index"]),
        "mapped_process_row": row,
        "scan_track_id": track_id,
        "track_position": dict(position) if position else None,
        "experimental_H_pixels": _optional_float(observation.get("experimental_H_pixels", frame_row.get("experimental_H_pixels"))),
        "experimental_W_pixels": _optional_float(observation.get("experimental_W_pixels", frame_row.get("experimental_W_pixels"))),
        "melt_classification": observation.get("melt_classification"),
        "production_status": diagnostics.get("production_hw_association_status"),
        "production_mode": diagnostics.get("production_hw_association_mode"),
        "production_min_distance_cells": _optional_float(diagnostics.get("production_hw_association_min_distance_cells")),
        "production_selected_label": diagnostics.get("production_hw_association_selected_label"),
        "production_component_status": diagnostics.get("production_hw_component_status"),
        "production_boundary_contact": diagnostics.get("liquidus_contour_boundary_contact"),
        "production_H_pixels": _optional_float(observation.get("simulated_H_pixels")),
        "production_W_pixels": _optional_float(observation.get("simulated_W_pixels")),
        "global_all_component_H_pixels": _optional_float(diagnostics.get("global_all_component_simulated_H_pixels")),
        "global_all_component_W_pixels": _optional_float(diagnostics.get("global_all_component_simulated_W_pixels")),
        "num_cells_above_liquidus": diagnostics.get("num_cells_above_liquidus"),
        "liquidus_component_count": diagnostics.get("liquidus_component_count"),
        "largest_liquidus_component_cell_count": diagnostics.get("largest_liquidus_component_cell_count"),
        "T_peak_surface_K": _optional_float(diagnostics.get("T_peak_surface_K")),
        "T_peak_surface_over_T_liquidus": _optional_float(diagnostics.get("T_peak_surface_over_T_liquidus")),
        "peak_surface_radial_distance_from_laser_mm": _optional_float(diagnostics.get("peak_surface_radial_distance_from_laser_mm")),
        "peak_surface_delta_x_from_laser_mm": _optional_float(diagnostics.get("peak_surface_delta_x_from_laser_mm")),
        "peak_surface_delta_y_from_laser_mm": _optional_float(diagnostics.get("peak_surface_delta_y_from_laser_mm")),
        "moving_window_reset_flag": diagnostics.get("moving_window_reset_flag"),
        "moving_window_shift_x_cells": diagnostics.get("moving_window_shift_x_cells"),
        "moving_window_shift_y_cells": diagnostics.get("moving_window_shift_y_cells"),
        "source_center_local_x_mm": source_x,
        "source_center_local_y_mm": _optional_float(diagnostics.get("source_center_local_y_mm")),
        "census_source_center_matches_core": (
            None if source_x is None or census_x is None else bool(abs(source_x - census_x) <= 1.0e-12)
        ),
        "track_process_row_start": start,
        "track_process_row_end": end,
        "rows_since_track_start": None if start is None else row - int(start),
        "rows_to_track_end": None if end is None else int(end) - row,
        "process_row_x_mm": None if current is None else current["x_mm"],
        "process_row_y_mm": None if current is None else current["y_mm"],
        "process_row_laser_drive": None if current is None else current["laser_drive"],
        "previous_row_x_mm": None if previous is None else previous["x_mm"],
        "previous_row_y_mm": None if previous is None else previous["y_mm"],
        "previous_row_laser_drive": None if previous is None else previous["laser_drive"],
        "next_row_x_mm": None if following is None else following["x_mm"],
        "next_row_y_mm": None if following is None else following["y_mm"],
        "next_row_laser_drive": None if following is None else following["laser_drive"],
    }
    for key, value in diagnostics.items():
        if str(key).startswith("census_"):
            record[str(key)] = value
    return record


def _census_unit_job(job: SimulationJob) -> dict[str, Any]:
    """Spawn-safe worker: one candidate on one member over all its eligible frames."""

    context = job.experiment_context_dict
    candidate_id = str(context["candidate_id"])
    member = _dataset_member_from_context(json.loads(context["dataset_member_json"]))
    frame_rows = json.loads(context["frame_rows_json"])
    track_rows = json.loads(context["track_rows_json"])
    member_id = member_identity(member.acquisition_set_id, member.coupon_position)
    frames = sorted({int(row["frame_index"]) for row in frame_rows})
    positions = label_track_positions(frame_rows)
    coordinates = _candidate_coordinates()[candidate_id]
    base = {
        "schema": CENSUS_SCHEMA,
        "patch": PATCH_VERSION,
        "candidate_id": candidate_id,
        "member_identity": member_id,
        "candidate_coordinates": coordinates,
        "requested_frame_count": len(frames),
        "production_hw_semantics_version": PRODUCTION_HW_SEMANTICS_VERSION,
        "association_policy_version": POLICY_VERSION,
        "thermal_execution_performed": True,
        "track_rows": track_rows,
    }
    policy = Patch21GlobalParameterPolicy.from_values(*(float(coordinates[name]) for name in COEFFICIENT_ORDER))
    scope = _census_scope(candidate_id, member, frames)
    warnings: list[str] = []
    try:
        with association_census_instrumentation():
            evaluation = evaluate_calibration_trial(member, policy, scope).to_dict()
    except Exception as exc:  # fail closed: no frames are fabricated for a unit that did not evaluate
        return {
            **base,
            "returned_frame_count": 0,
            "missing_frames": frames[:16],
            "evaluation_status": "EXCEPTION",
            "evaluation_stage": "census_worker",
            "evaluation_failure": {"type": type(exc).__name__, "message": str(exc)},
            "frames": [],
            "warnings": warnings,
        }
    observations = {
        int(item["frame_index"]): item
        for item in list(evaluation.get("observations") or [])
        if isinstance(item, Mapping) and item.get("frame_index") is not None
    }
    rows_by_frame = {int(row["frame_index"]): row for row in frame_rows}
    needed_rows = sorted(
        {int(item["mapped_process_row"]) + offset for item in observations.values() for offset in (-1, 0, 1)}
    )
    row_context = _process_row_context(member, needed_rows, warnings)
    records = [
        _frame_record(
            observations[frame],
            frame_row=rows_by_frame[frame],
            position=positions.get(frame),
            track_rows=track_rows,
            row_context=row_context,
        )
        for frame in frames
        if frame in observations
    ]
    return {
        **base,
        "returned_frame_count": len(records),
        "missing_frames": [frame for frame in frames if frame not in observations][:16],
        "evaluation_status": evaluation.get("status"),
        "evaluation_stage": evaluation.get("stage"),
        "evaluation_failure": evaluation.get("failure"),
        "frames": records,
        "warnings": warnings,
    }


FRAME_CSV_COLUMNS = (
    "candidate_id",
    "member_identity",
    "frame_index",
    "mapped_process_row",
    "scan_track_id",
    "track_edge_class",
    "track_position",
    "track_frame_count",
    "rows_since_track_start",
    "rows_to_track_end",
    "experimental_H_pixels",
    "experimental_W_pixels",
    "production_status",
    "production_mode",
    "production_min_distance_cells",
    "production_H_pixels",
    "production_W_pixels",
    "melt_classification",
    "census_component_count",
    "census_beam_share_on_liquid_total",
    "census_source_center_x_mm",
    "census_source_center_y_mm",
    "census_heating_center_x_mm",
    "census_heating_center_y_mm",
    "census_heating_laser_on",
    "num_cells_above_liquidus",
    "T_peak_surface_over_T_liquidus",
    "peak_surface_radial_distance_from_laser_mm",
    "moving_window_reset_flag",
    "moving_window_shift_x_cells",
    "moving_window_shift_y_cells",
    "process_row_x_mm",
    "process_row_y_mm",
    "previous_row_x_mm",
    "previous_row_y_mm",
    "next_row_x_mm",
    "next_row_y_mm",
)
COMPONENT_CSV_COLUMNS = (
    "candidate_id",
    "member_identity",
    "frame_index",
    "label",
    "cell_count",
    "contains_beam_cell",
    "touches_boundary",
    "beam_share",
    "min_cell_center_distance_cells",
    "min_contour_distance_cells",
    "min_cell_center_distance_from_heating_center_cells",
    "min_contour_distance_from_heating_center_cells",
    "contour_status",
    "H_pixels",
    "W_pixels",
)


def _csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, float):
        return repr(value)
    return value


def _write_census_csvs(output: Path, payloads: Sequence[Mapping[str, Any]]) -> tuple[Path, Path]:
    frames_path = output / FRAMES_CSV_NAME
    components_path = output / COMPONENTS_CSV_NAME
    with frames_path.open("w", encoding="utf-8", newline="") as frames_handle, components_path.open(
        "w", encoding="utf-8", newline=""
    ) as components_handle:
        frames_writer = csv.writer(frames_handle, lineterminator="\n")
        components_writer = csv.writer(components_handle, lineterminator="\n")
        frames_writer.writerow(FRAME_CSV_COLUMNS)
        components_writer.writerow(COMPONENT_CSV_COLUMNS)
        for payload in payloads:
            identity = {"candidate_id": payload["candidate_id"], "member_identity": payload["member_identity"]}
            for frame in sorted(payload.get("frames") or [], key=lambda item: int(item["frame_index"])):
                position = frame.get("track_position") or {}
                flat = {
                    **identity,
                    **frame,
                    "track_edge_class": position.get("edge_class"),
                    "track_position": position.get("position"),
                    "track_frame_count": position.get("track_frame_count"),
                }
                frames_writer.writerow([_csv_value(flat.get(column)) for column in FRAME_CSV_COLUMNS])
                for component in sorted(frame.get("census_components") or [], key=lambda item: int(item["label"])):
                    row = {**identity, "frame_index": frame["frame_index"], **component}
                    components_writer.writerow([_csv_value(row.get(column)) for column in COMPONENT_CSV_COLUMNS])
    return frames_path, components_path


def _unit_file_name(candidate_id: str, member_id: str) -> str:
    return f"{candidate_id}__{member_id.replace(':', '_')}.json"


def run_association_census(
    *,
    data_directory: str | Path,
    characterization_directory: str | Path,
    output_directory: str | Path,
    candidates: Sequence[str] = STAGE_A_CANDIDATES,
    member_identities: Sequence[str] = STAGE_A_MEMBERS,
    workers: int = DEFAULT_CENSUS_WORKERS,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Run the census units (default: 5 Stage-A candidates x 2 members) and write the per-unit records."""

    workers = _validated_workers(workers)
    output = Path(output_directory).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    (output / "units").mkdir(exist_ok=True)
    members = _member_map(data_directory)
    characterization = Path(characterization_directory).expanduser().resolve()
    frame_rows_by_member: dict[str, list[dict[str, Any]]] = {}
    track_rows_by_member: dict[str, dict[str, Any]] = {}
    for member_id in sorted(set(str(value) for value in member_identities)):
        member = members.get(member_id)
        if member is None:
            raise AssociationCensusError(f"dataset member is missing: {member_id}")
        frame_path = _find_frame_file(characterization, member)
        frame_rows_by_member[member_id] = list(_portable_frame_rows(frame_path, member))
        track_rows_by_member[member_id] = dict(_read_scan_tracks(frame_path))
    units = [(str(candidate), str(member_id)) for candidate in candidates for member_id in member_identities]
    jobs = build_census_jobs(
        units, members, frame_rows_by_member, track_rows_by_member, characterization_directory=characterization
    )
    total = len(jobs)
    effective_workers = max(1, min(workers, total))
    finished = 0

    def report_progress(result: SimulationResult) -> None:
        nonlocal finished
        finished += 1
        if progress_callback is not None:
            payload = result.payload
            progress_callback(
                finished,
                total,
                {
                    "candidate_id": payload["candidate_id"],
                    "member_identity": payload["member_identity"],
                    "requested_frame_count": payload["requested_frame_count"],
                    "returned_frame_count": payload["returned_frame_count"],
                },
            )

    if effective_workers == 1:
        completed = execute_serial_jobs(jobs, _census_unit_job, on_result=report_progress)
    else:
        completed = execute_parallel_jobs(jobs, _census_unit_job, workers=effective_workers, on_result=report_progress)

    payloads: list[dict[str, Any]] = []
    units_out: list[dict[str, Any]] = []
    failures: list[str] = []
    frame_count = 0
    for result in sorted(completed, key=lambda item: item.job.case_index):
        payload = _json_safe(result.payload)
        candidate_id, member_id = payload["candidate_id"], payload["member_identity"]
        unit_file = _unit_file_name(candidate_id, member_id)
        write_json(output / "units" / unit_file, payload)
        payloads.append(payload)
        requested, returned = int(payload["requested_frame_count"]), int(payload["returned_frame_count"])
        if returned != requested:
            failures.append(f"{candidate_id} / {member_id}: returned {returned} of {requested} frames")
        frame_count += returned
        frames = payload.get("frames") or []
        units_out.append(
            {
                "candidate_id": candidate_id,
                "member_identity": member_id,
                "unit_file": unit_file,
                "requested_frame_count": requested,
                "returned_frame_count": returned,
                "evaluation_status": payload.get("evaluation_status"),
                "evaluation_stage": payload.get("evaluation_stage"),
                "production_selected_frames": sum(1 for frame in frames if frame.get("production_status") == "SELECTED"),
                "production_zero_footprint_frames": sum(1 for frame in frames if frame.get("production_status") == "ZERO_FOOTPRINT"),
                "production_undefined_frames": sum(
                    1 for frame in frames if frame.get("production_H_pixels") is None and frame.get("production_status") != "ZERO_FOOTPRINT"
                ),
                "warnings": list(payload.get("warnings") or []),
            }
        )
    frames_csv, components_csv = _write_census_csvs(output, payloads)
    report: dict[str, Any] = {
        "schema": CENSUS_SCHEMA,
        "schema_version": PATCH_VERSION,
        "patch": PATCH_VERSION,
        "status": CENSUS_STATUS_PASS if not failures else CENSUS_STATUS_FAIL,
        "diagnostic_only": True,
        "semantics_changed": False,
        "production_hw_definition": PRODUCTION_HW_DEFINITION,
        "production_hw_semantics_version": PRODUCTION_HW_SEMANTICS_VERSION,
        "production_hw_association_policy_version": POLICY_VERSION,
        "window_cells": WINDOW_CELLS,
        "candidates": [str(value) for value in candidates],
        "member_identities": [str(value) for value in member_identities],
        "unit_count": total,
        "frame_count": frame_count,
        "units": units_out,
        "failures": failures,
        "census_execution": {
            "execution_patch": PATCH_VERSION,
            "requested_workers": workers,
            "workers": effective_workers,
            "start_method": "serial" if effective_workers == 1 else "spawn",
        },
        "thermal_replay_performed": True,
        "full_campaign_dispatched": False,
        "calibration_search_authorized": False,
        "parameter_selection_performed": False,
        "parameter_fitting_performed": False,
        "validation_partition_used": False,
        "frames_csv": str(frames_csv),
        "components_csv": str(components_csv),
    }
    write_json(output / REPORT_NAME, report)
    report["report_path"] = str(output / REPORT_NAME)
    return report


# ------------------------------------------------------------------- offline evaluation


def _load_census(census_directory: str | Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    root = Path(census_directory).expanduser().resolve()
    report_path = root / REPORT_NAME
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AssociationCensusError(f"cannot read census report: {report_path}") from exc
    units = []
    for unit in report.get("units") or []:
        path = root / "units" / str(unit["unit_file"])
        try:
            units.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError) as exc:
            raise AssociationCensusError(f"cannot read census unit: {path}") from exc
    if not units:
        raise AssociationCensusError("census report lists no units")
    return report, units


def _current_outcome(frame: Mapping[str, Any]) -> str:
    status = str(frame.get("production_status") or "")
    if status == "SELECTED" and _finite_positive(frame.get("production_H_pixels"), frame.get("production_W_pixels")):
        return "SELECTED"
    if status == "ZERO_FOOTPRINT":
        return "ZERO_FOOTPRINT"
    return "undefined"


def _empty_counts() -> dict[str, int]:
    return {**{status: 0 for status in RULE_STATUSES}, "undefined": 0, "scored": 0, "frames": 0}


def _add_count(table: dict[str, dict[str, int]], key: str, status: str) -> None:
    counts = table.setdefault(key, _empty_counts())
    counts["frames"] += 1
    if status in RULE_STATUSES:
        counts[status] += 1
    if status == "undefined" or status in UNDEFINED_STATUSES:
        counts["undefined"] += 1
    else:
        counts["scored"] += 1


def _edge_class(frame: Mapping[str, Any]) -> str:
    position = frame.get("track_position") or {}
    return str(position.get("edge_class") or "unknown")


def _rule_status_table(
    units: Sequence[Mapping[str, Any]],
    rule: Callable[[Sequence[Mapping[str, Any]]], Mapping[str, Any]],
) -> tuple[dict[str, Any], dict[tuple[str, str, int], str]]:
    by_candidate: dict[str, dict[str, int]] = {}
    by_position: dict[str, dict[str, int]] = {}
    totals: dict[str, dict[str, int]] = {}
    outcomes: dict[tuple[str, str, int], str] = {}
    for unit in units:
        candidate = str(unit["candidate_id"])
        member = str(unit["member_identity"])
        for frame in unit.get("frames") or []:
            status = str(rule(frame.get("census_components") or [])["status"])
            outcomes[(candidate, member, int(frame["frame_index"]))] = status
            _add_count(by_candidate, candidate, status)
            _add_count(by_position, _edge_class(frame), status)
            _add_count(totals, "all", status)
    return {"by_candidate": by_candidate, "by_track_position": by_position, "totals": totals["all"]}, outcomes


def _changed_outcomes(
    current: Mapping[tuple[str, str, int], str], proposed: Mapping[tuple[str, str, int], str]
) -> dict[str, int]:
    changed = {"undefined_to_scored": 0, "scored_to_undefined": 0, "unchanged_scored": 0, "unchanged_undefined": 0, "selected_to_no_melt": 0, "no_melt_to_selected": 0}
    for key, before in current.items():
        after = proposed.get(key)
        if after is None:
            continue
        before_undefined = before == "undefined"
        after_undefined = after in UNDEFINED_STATUSES
        if before_undefined and not after_undefined:
            changed["undefined_to_scored"] += 1
        elif not before_undefined and after_undefined:
            changed["scored_to_undefined"] += 1
        elif before_undefined:
            changed["unchanged_undefined"] += 1
        else:
            changed["unchanged_scored"] += 1
        if before == "SELECTED" and after == "NO_LASER_ASSOCIATED_MELT":
            changed["selected_to_no_melt"] += 1
        if before == "ZERO_FOOTPRINT" and after == "SELECTED":
            changed["no_melt_to_selected"] += 1
    return changed


def _load_old_run_observations(old_run_directory: Path, candidate_id: str, member_id: str) -> dict[int, dict[str, Any]] | None:
    for path in sorted(old_run_directory.rglob("result.json")):
        if path.parent.name != candidate_id:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8")).get("payload") or {}
        except (OSError, json.JSONDecodeError):
            continue
        if str(payload.get("member_identity")) != member_id:
            continue
        observations = (payload.get("atomic_failure_evaluation") or {}).get("observations") or []
        out: dict[int, dict[str, Any]] = {}
        for item in observations:
            diagnostics = item.get("observation_diagnostics") or {}
            out[int(item["frame_index"])] = {
                "mode": diagnostics.get("production_hw_association_mode"),
                "status": diagnostics.get("production_hw_association_status"),
                "distance_cells": _optional_float(diagnostics.get("production_hw_association_min_distance_cells")),
                "H_pixels": _optional_float(item.get("simulated_H_pixels")),
                "W_pixels": _optional_float(item.get("simulated_W_pixels")),
            }
        return out
    return None


def _old_run_regression(units: Sequence[Mapping[str, Any]], old_run_directory: Path) -> dict[str, Any]:
    """Join the interrupted 22.4.3 run (22.3.4 semantics; diagnostic only) frame by frame."""

    summary = {
        "old_run_directory": str(old_run_directory),
        "old_run_semantics": "Patch 22.3.4 production H/W, Patch 22.3.3 integer-grid association (diagnostic reference only; never merged)",
        "units_joined": 0,
        "units_without_old_result": [],
        "joined_frames": 0,
        "strict_center_frames": 0,
        "strict_center_hw_identical": 0,
        "strict_center_now_not_strict": 0,
        "strict_center_max_abs_hw_difference_pixels": None,
        "old_orthogonal_fallback_frames": 0,
        "old_orthogonal_fallback_now_selected": 0,
        "old_orthogonal_fallback_now_undefined": 0,
        "old_fail_closed_frames": 0,
        "old_fail_closed_now_selected": 0,
        "old_fail_closed_now_undefined": 0,
        "old_zero_footprint_frames": 0,
        "old_zero_footprint_now_zero": 0,
        "by_candidate": {},
    }
    max_difference = 0.0
    any_strict_comparison = False
    for unit in units:
        candidate, member = str(unit["candidate_id"]), str(unit["member_identity"])
        old = _load_old_run_observations(old_run_directory, candidate, member)
        if old is None:
            summary["units_without_old_result"].append(f"{candidate} / {member}")
            continue
        summary["units_joined"] += 1
        per = summary["by_candidate"].setdefault(
            candidate,
            {"joined_frames": 0, "old_orthogonal_fallback_frames": 0, "old_orthogonal_fallback_now_undefined": 0, "strict_center_frames": 0, "strict_center_hw_identical": 0},
        )
        for frame in unit.get("frames") or []:
            previous = old.get(int(frame["frame_index"]))
            if previous is None:
                continue
            summary["joined_frames"] += 1
            per["joined_frames"] += 1
            new_outcome = _current_outcome(frame)
            new_h, new_w = _optional_float(frame.get("production_H_pixels")), _optional_float(frame.get("production_W_pixels"))
            if previous["mode"] == "strict_center":
                summary["strict_center_frames"] += 1
                per["strict_center_frames"] += 1
                if frame.get("production_mode") != "strict_center":
                    summary["strict_center_now_not_strict"] += 1
                identical = (
                    frame.get("production_mode") == "strict_center"
                    and new_h is not None
                    and new_w is not None
                    and previous["H_pixels"] == new_h
                    and previous["W_pixels"] == new_w
                )
                if identical:
                    summary["strict_center_hw_identical"] += 1
                    per["strict_center_hw_identical"] += 1
                if new_h is not None and new_w is not None and previous["H_pixels"] is not None and previous["W_pixels"] is not None:
                    any_strict_comparison = True
                    max_difference = max(max_difference, abs(previous["H_pixels"] - new_h), abs(previous["W_pixels"] - new_w))
            elif previous["mode"] == "unique_nearest_fallback" and previous["distance_cells"] is not None and abs(previous["distance_cells"] - 1.0) <= ORTHOGONAL_DISTANCE_TOLERANCE:
                summary["old_orthogonal_fallback_frames"] += 1
                per["old_orthogonal_fallback_frames"] += 1
                if new_outcome == "SELECTED":
                    summary["old_orthogonal_fallback_now_selected"] += 1
                elif new_outcome == "undefined":
                    summary["old_orthogonal_fallback_now_undefined"] += 1
                    per["old_orthogonal_fallback_now_undefined"] += 1
            elif str(previous["status"] or "").startswith("FAIL_CLOSED"):
                summary["old_fail_closed_frames"] += 1
                if new_outcome == "SELECTED":
                    summary["old_fail_closed_now_selected"] += 1
                elif new_outcome == "undefined":
                    summary["old_fail_closed_now_undefined"] += 1
            elif previous["status"] == "ZERO_FOOTPRINT":
                summary["old_zero_footprint_frames"] += 1
                if new_outcome == "ZERO_FOOTPRINT":
                    summary["old_zero_footprint_now_zero"] += 1
    summary["strict_center_max_abs_hw_difference_pixels"] = max_difference if any_strict_comparison else None
    return summary


RESIDUAL_CSV_COLUMNS = (
    "candidate_id",
    "member_identity",
    "frame_index",
    "mapped_process_row",
    "scan_track_id",
    "track_edge_class",
    "rows_since_track_start",
    "rows_to_track_end",
    "current_outcome",
    "production_status",
    "production_min_distance_cells",
    "beam_share_outcome_at_lowest_floor",
    "nearest_component_beam_share",
    "nearest_component_contour_distance_cells",
    "nearest_component_contour_distance_mm",
    "nearest_component_center_distance_cells",
    "nearest_component_cell_count",
    "nearest_component_touches_boundary",
    "component_count",
    "liquid_cell_count",
    "source_center_x_mm",
    "source_center_y_mm",
    "heating_center_x_mm",
    "heating_center_y_mm",
    "heating_laser_on",
    "experimental_H_pixels",
    "experimental_W_pixels",
    "process_row_x_mm",
    "process_row_y_mm",
    "previous_row_x_mm",
    "previous_row_y_mm",
    "next_row_x_mm",
    "next_row_y_mm",
    "T_peak_surface_over_T_liquidus",
    "peak_surface_radial_distance_from_laser_mm",
    "moving_window_reset_flag",
)


def _residual_row(unit: Mapping[str, Any], frame: Mapping[str, Any], *, beam_status: str) -> dict[str, Any]:
    components = frame.get("census_components") or []
    nearest = min(components, key=_component_contour_distance) if components else None
    spacing = _optional_float(frame.get("census_spacing_mm")) or 0.016
    position = frame.get("track_position") or {}
    return {
        "candidate_id": unit["candidate_id"],
        "member_identity": unit["member_identity"],
        "frame_index": frame.get("frame_index"),
        "mapped_process_row": frame.get("mapped_process_row"),
        "scan_track_id": frame.get("scan_track_id"),
        "track_edge_class": position.get("edge_class"),
        "rows_since_track_start": frame.get("rows_since_track_start"),
        "rows_to_track_end": frame.get("rows_to_track_end"),
        "current_outcome": _current_outcome(frame),
        "production_status": frame.get("production_status"),
        "production_min_distance_cells": frame.get("production_min_distance_cells"),
        "beam_share_outcome_at_lowest_floor": beam_status,
        "nearest_component_beam_share": None if nearest is None else nearest.get("beam_share"),
        "nearest_component_contour_distance_cells": None if nearest is None else _component_contour_distance(nearest),
        "nearest_component_contour_distance_mm": None if nearest is None else _component_contour_distance(nearest) * spacing,
        "nearest_component_center_distance_cells": None if nearest is None else nearest.get("min_cell_center_distance_cells"),
        "nearest_component_cell_count": None if nearest is None else nearest.get("cell_count"),
        "nearest_component_touches_boundary": None if nearest is None else nearest.get("touches_boundary"),
        "component_count": frame.get("census_component_count", len(components)),
        "liquid_cell_count": frame.get("census_liquid_cell_count"),
        "source_center_x_mm": frame.get("census_source_center_x_mm", frame.get("source_center_local_x_mm")),
        "source_center_y_mm": frame.get("census_source_center_y_mm", frame.get("source_center_local_y_mm")),
        "heating_center_x_mm": frame.get("census_heating_center_x_mm"),
        "heating_center_y_mm": frame.get("census_heating_center_y_mm"),
        "heating_laser_on": frame.get("census_heating_laser_on"),
        "experimental_H_pixels": frame.get("experimental_H_pixels"),
        "experimental_W_pixels": frame.get("experimental_W_pixels"),
        "process_row_x_mm": frame.get("process_row_x_mm"),
        "process_row_y_mm": frame.get("process_row_y_mm"),
        "previous_row_x_mm": frame.get("previous_row_x_mm"),
        "previous_row_y_mm": frame.get("previous_row_y_mm"),
        "next_row_x_mm": frame.get("next_row_x_mm"),
        "next_row_y_mm": frame.get("next_row_y_mm"),
        "T_peak_surface_over_T_liquidus": frame.get("T_peak_surface_over_T_liquidus"),
        "peak_surface_radial_distance_from_laser_mm": frame.get("peak_surface_radial_distance_from_laser_mm"),
        "moving_window_reset_flag": frame.get("moving_window_reset_flag"),
    }


def evaluate_census(
    census_directory: str | Path,
    *,
    old_run_directory: str | Path | None = None,
    output_directory: str | Path | None = None,
    floors: Sequence[float] = BEAM_SHARE_FLOORS,
    radii: Sequence[float] = CONTOUR_RADII_CELLS,
) -> dict[str, Any]:
    """Offline, deterministic evaluation of the current and candidate rules on the census fields."""

    report, units = _load_census(census_directory)
    floors = tuple(float(value) for value in floors)
    radii = tuple(float(value) for value in radii)

    # the current (22.3.5) outcome is recorded by production, not re-derived from telemetry
    current_table: dict[str, Any] = {"by_candidate": {}, "by_track_position": {}, "totals": _empty_counts()}
    current_outcomes: dict[tuple[str, str, int], str] = {}
    for unit in units:
        candidate, member = str(unit["candidate_id"]), str(unit["member_identity"])
        for frame in unit.get("frames") or []:
            outcome = _current_outcome(frame)
            current_outcomes[(candidate, member, int(frame["frame_index"]))] = outcome
            _add_count(current_table["by_candidate"], candidate, outcome)
            _add_count(current_table["by_track_position"], _edge_class(frame), outcome)
            _add_count({"all": current_table["totals"]}, "all", outcome)

    beam_by_floor: dict[str, Any] = {}
    beam_outcomes: dict[str, dict[tuple[str, str, int], str]] = {}
    for floor in floors:
        key = f"{floor:g}"
        table, outcomes = _rule_status_table(units, lambda components, floor=floor: evaluate_beam_share_rule(components, floor=floor))
        beam_by_floor[key] = table
        beam_outcomes[key] = outcomes
    sensitivity: dict[str, dict[str, int]] = {}
    for lower, upper in zip(floors, floors[1:]):
        lower_key, upper_key = f"{lower:g}", f"{upper:g}"
        changed = sum(1 for key, status in beam_outcomes[lower_key].items() if beam_outcomes[upper_key].get(key) != status)
        sensitivity[f"{lower_key}->{upper_key}"] = {"changed_frames": changed}

    contour_by_radius: dict[str, Any] = {}
    contour_outcomes: dict[str, dict[tuple[str, str, int], str]] = {}
    for radius in radii:
        key = f"{radius:g}"
        table, outcomes = _rule_status_table(units, lambda components, radius=radius: evaluate_contour_distance_rule(components, radius_cells=radius))
        contour_by_radius[key] = table
        contour_outcomes[key] = outcomes

    correlation = []
    for candidate, counts in sorted(current_table["by_candidate"].items()):
        coordinates = next((unit.get("candidate_coordinates") or {} for unit in units if unit["candidate_id"] == candidate), {})
        correlation.append(
            {
                "candidate_id": candidate,
                "abs_depth_identifiable_coordinate": _optional_float(coordinates.get("abs_depth_identifiable_coordinate")),
                "frames": counts["frames"],
                "undefined_fraction_current_rule": counts["undefined"] / counts["frames"] if counts["frames"] else None,
                "undefined_fraction_beam_share_lowest_floor": (
                    beam_by_floor[f"{floors[0]:g}"]["by_candidate"].get(candidate, _empty_counts())["undefined"] / counts["frames"]
                    if counts["frames"] and floors
                    else None
                ),
            }
        )

    lowest_key = f"{floors[0]:g}" if floors else None
    residual_rows = []
    for unit in units:
        candidate, member = str(unit["candidate_id"]), str(unit["member_identity"])
        for frame in unit.get("frames") or []:
            key = (candidate, member, int(frame["frame_index"]))
            beam_status = beam_outcomes[lowest_key].get(key) if lowest_key else None
            if current_outcomes[key] == "undefined" or beam_status in UNDEFINED_STATUSES or beam_status == "NO_LASER_ASSOCIATED_MELT":
                residual_rows.append(_residual_row(unit, frame, beam_status=str(beam_status)))

    regression = None if old_run_directory is None else _old_run_regression(units, Path(old_run_directory).expanduser().resolve())
    evaluation: dict[str, Any] = {
        "schema": "lpbf_patch22_3_6_census_evaluation",
        "schema_version": PATCH_VERSION,
        "status": EVALUATION_STATUS_PASS,
        "census_directory": str(Path(census_directory).expanduser().resolve()),
        "census_status": report.get("status"),
        "unit_count": len(units),
        "frame_count": sum(len(unit.get("frames") or []) for unit in units),
        "semantics_changed": False,
        "current_rule": current_table,
        "beam_share_rule": {"floors": list(floors), "by_floor": beam_by_floor, "floor_sensitivity": sensitivity},
        "contour_distance_rule": {"radii": list(radii), "by_radius": contour_by_radius},
        "changed_outcomes_vs_current": {
            "beam_share_rule": {key: _changed_outcomes(current_outcomes, outcomes) for key, outcomes in beam_outcomes.items()},
            "contour_distance_rule": {key: _changed_outcomes(current_outcomes, outcomes) for key, outcomes in contour_outcomes.items()},
        },
        "undefined_correlation_with_t": correlation,
        "old_run_regression": regression,
        "residual_case_count": len(residual_rows),
    }
    if output_directory is not None:
        output = Path(output_directory).expanduser().resolve()
        output.mkdir(parents=True, exist_ok=True)
        residual_path = output / RESIDUAL_CSV_NAME
        with residual_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(RESIDUAL_CSV_COLUMNS)
            for row in residual_rows:
                writer.writerow([_csv_value(row.get(column)) for column in RESIDUAL_CSV_COLUMNS])
        evaluation["residual_cases_csv"] = str(residual_path)
        write_json(output / EVALUATION_NAME, _json_safe(evaluation))
        evaluation["evaluation_path"] = str(output / EVALUATION_NAME)
    return evaluation


# -------------------------------------------------------------------------- sync audit


def audit_member_tracks(
    *,
    frame_rows: Sequence[Mapping[str, Any]],
    track_rows: Mapping[str, Mapping[str, Any]],
    matched_edge_frames: np.ndarray,
    matched_edge_signs: np.ndarray,
    anchor_rows: np.ndarray,
    image_to_row: np.ndarray,
    gige_on: np.ndarray,
    gige_time_s: np.ndarray,
) -> dict[str, Any]:
    """Pure audit of one member's synchronization at scan-track edges."""

    rising = {int(frame) for frame, sign in zip(matched_edge_frames, matched_edge_signs) if int(sign) > 0}
    falling = {int(frame) for frame, sign in zip(matched_edge_frames, matched_edge_signs) if int(sign) < 0}
    anchors = {int(round(float(row))) for row in anchor_rows}
    image_to_row = np.asarray(image_to_row)
    gige_on = np.asarray(gige_on)
    gige_time_s = np.asarray(gige_time_s, dtype=np.float64)
    count = int(len(gige_on))
    by_track: dict[str, list[int]] = defaultdict(list)
    for row in frame_rows:
        if bool(row.get("observation_eligible", True)):
            by_track[str(row["scan_track_id"])].append(int(row["frame_index"]))

    def track_sort_key(track_id: str) -> tuple[int, str]:
        return (int(track_id), track_id) if track_id.isdigit() else (10**9, track_id)

    tracks = []
    for track_id in sorted(by_track, key=track_sort_key):
        frames = sorted(set(by_track[track_id]))
        first, last = frames[0], frames[-1]
        bounds = track_rows.get(track_id) or {}
        start, end = bounds.get("process_row_start"), bounds.get("process_row_end")
        row_first = int(image_to_row[first]) if 0 <= first < len(image_to_row) else None
        row_last = int(image_to_row[last]) if 0 <= last < len(image_to_row) else None
        back = first - 1
        while back >= 0 and gige_on[back]:
            back -= 1
        forward = last + 1
        while forward < count and gige_on[forward]:
            forward += 1
        tracks.append(
            {
                "scan_track_id": track_id,
                "eligible_frame_count": len(frames),
                "first_frame_index": first,
                "first_mapped_row": row_first,
                "track_process_row_start": start,
                "first_rows_after_track_start": None if row_first is None or start is None else row_first - int(start),
                "first_is_rising_edge_anchor": first in rising,
                "first_row_is_piecewise_anchor": row_first in anchors,
                "first_maps_to_track_start_row": None if row_first is None or start is None else row_first == int(start),
                "dark_frames_before_first": None if back < 0 else first - back,
                "dark_gap_before_first_s": None if back < 0 else float(gige_time_s[first] - gige_time_s[back]),
                "last_frame_index": last,
                "last_mapped_row": row_last,
                "track_process_row_end": end,
                "last_rows_before_track_end": None if row_last is None or end is None else int(end) - row_last,
                "last_is_falling_edge_anchor": last in falling,
                "last_row_is_piecewise_anchor": row_last in anchors,
                "last_maps_to_track_end_row": None if row_last is None or end is None else row_last == int(end),
                "dark_frames_after_last": None if forward >= count else forward - last,
                "dark_gap_after_last_s": None if forward >= count else float(gige_time_s[forward] - gige_time_s[last]),
            }
        )

    def fraction(key: str) -> float | None:
        values = [track[key] for track in tracks if track[key] is not None]
        return (sum(1 for value in values if value) / len(values)) if values else None

    gaps = [track["dark_gap_before_first_s"] for track in tracks if track["dark_gap_before_first_s"] is not None]
    summary = {
        "track_count": len(tracks),
        "eligible_frame_count": sum(track["eligible_frame_count"] for track in tracks),
        "first_frame_rising_edge_anchor_fraction": fraction("first_is_rising_edge_anchor"),
        "first_maps_to_track_start_fraction": fraction("first_maps_to_track_start_row"),
        "last_frame_falling_edge_anchor_fraction": fraction("last_is_falling_edge_anchor"),
        "last_maps_to_track_end_fraction": fraction("last_maps_to_track_end_row"),
        "dark_gap_before_first_median_s": float(np.median(gaps)) if gaps else None,
        "dark_gap_before_first_max_s": float(max(gaps)) if gaps else None,
        "short_track_count_lt_4_frames": sum(1 for track in tracks if track["eligible_frame_count"] < 4),
        "single_frame_track_count": sum(1 for track in tracks if track["eligible_frame_count"] == 1),
    }
    return {"tracks": tracks, "summary": summary}


def run_sync_track_start_audit(
    *,
    data_directory: str | Path,
    characterization_directory: str | Path,
    output_directory: str | Path,
) -> dict[str, Any]:
    """Audit synchronization at scan-track edges for the 16 calibration members only."""

    import h5py

    output = Path(output_directory).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    members = _member_map(data_directory)
    characterization = Path(characterization_directory).expanduser().resolve()
    calibration = sorted(calibration_member_identities())
    member_records = []
    track_rows_out: list[dict[str, Any]] = []
    for member_id in calibration:
        member = members.get(member_id)
        if member is None:
            raise AssociationCensusError(f"calibration member is missing from the data directory: {member_id}")
        frame_path = _find_frame_file(characterization, member)
        frame_rows = _portable_frame_rows(frame_path, member)
        tracks = _read_scan_tracks(frame_path)
        with h5py.File(member.path, "r") as handle:
            layer = handle[member.layer_name]
            sync = layer["sync"]
            mapping = sync["gige_image_to_data_index"]
            method = mapping.attrs.get("method", sync.attrs.get("method"))
            version = mapping.attrs.get("version", sync.attrs.get("version"))
            audit = audit_member_tracks(
                frame_rows=frame_rows,
                track_rows=tracks,
                matched_edge_frames=np.asarray(sync["matched_edge_gige_frame_index"][:]),
                matched_edge_signs=np.asarray(sync["matched_edge_sign"][:]),
                anchor_rows=np.asarray(sync["piecewise_anchor_data_index"][:]),
                image_to_row=np.asarray(mapping[:]),
                gige_on=np.asarray(sync["gige_on_raw"][:]),
                gige_time_s=np.asarray(layer["gige_time"][:], dtype=np.float64),
            )
        member_records.append(
            {
                "member_identity": member_id,
                "input_filename": member.path.name,
                "sync_method": None if method is None else str(method),
                "sync_version": None if version is None else str(version),
                "summary": audit["summary"],
            }
        )
        for track in audit["tracks"]:
            track_rows_out.append({"member_identity": member_id, **track})
    aggregate = {
        "member_count": len(member_records),
        "track_count": sum(record["summary"]["track_count"] for record in member_records),
        "eligible_frame_count": sum(record["summary"]["eligible_frame_count"] for record in member_records),
        "first_frame_rising_edge_anchor_fraction": (
            sum(1 for row in track_rows_out if row["first_is_rising_edge_anchor"]) / len(track_rows_out) if track_rows_out else None
        ),
        "first_maps_to_track_start_fraction": (
            sum(1 for row in track_rows_out if row["first_maps_to_track_start_row"]) / len(track_rows_out) if track_rows_out else None
        ),
        "last_frame_falling_edge_anchor_fraction": (
            sum(1 for row in track_rows_out if row["last_is_falling_edge_anchor"]) / len(track_rows_out) if track_rows_out else None
        ),
        "last_maps_to_track_end_fraction": (
            sum(1 for row in track_rows_out if row["last_maps_to_track_end_row"]) / len(track_rows_out) if track_rows_out else None
        ),
        "dark_gap_before_first_median_s": float(np.median([row["dark_gap_before_first_s"] for row in track_rows_out if row["dark_gap_before_first_s"] is not None]))
        if any(row["dark_gap_before_first_s"] is not None for row in track_rows_out)
        else None,
        "short_track_count_lt_4_frames": sum(1 for row in track_rows_out if row["eligible_frame_count"] < 4),
        "single_frame_track_count": sum(1 for row in track_rows_out if row["eligible_frame_count"] == 1),
    }
    csv_path = output / SYNC_AUDIT_CSV_NAME
    if track_rows_out:
        columns = list(track_rows_out[0].keys())
        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(columns)
            for row in track_rows_out:
                writer.writerow([_csv_value(row.get(column)) for column in columns])
    report = {
        "schema": "lpbf_patch22_3_6_sync_track_start_audit",
        "schema_version": PATCH_VERSION,
        "status": SYNC_AUDIT_STATUS_PASS,
        "diagnostic_only": True,
        "calibration_members_only": True,
        "held_out_members_opened": False,
        "members": member_records,
        "summary": aggregate,
        "tracks_csv": str(csv_path),
    }
    write_json(output / SYNC_AUDIT_NAME, _json_safe(report))
    report["report_path"] = str(output / SYNC_AUDIT_NAME)
    return report


__all__ = [
    "BEAM_SHARE_FLOORS",
    "CENSUS_STATUS_FAIL",
    "CENSUS_STATUS_PASS",
    "CONTOUR_RADII_CELLS",
    "DEFAULT_CENSUS_WORKERS",
    "EVALUATION_STATUS_PASS",
    "PATCH_VERSION",
    "RULE_STATUSES",
    "STAGE_A_CANDIDATES",
    "STAGE_A_MEMBERS",
    "SYNC_AUDIT_STATUS_PASS",
    "AssociationCensusError",
    "association_census_instrumentation",
    "audit_member_tracks",
    "build_census_jobs",
    "component_contour_points_mm",
    "evaluate_beam_share_rule",
    "evaluate_census",
    "evaluate_contour_distance_rule",
    "label_track_positions",
    "per_component_telemetry",
    "run_association_census",
    "run_sync_track_start_audit",
    "surface_beam_profile",
]
