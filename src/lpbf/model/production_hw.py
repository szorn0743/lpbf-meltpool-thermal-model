"""Patch 22.3.7 laser-associated production H/W semantics.

The accepted thermal/numerical core remains untouched.  This module instruments
its already-existing observation diagnostics at observation time, measures H/W
only on the validated laser-associated liquid component, and replaces the
returned *observation values* after the accepted thermal loop has completed.

Patch 22.3.7 selects the laser-associated component by beam-power share
(``select_laser_associated_component_by_beam_share``).  The continuous source
center, surface-cell spacing and realized Gaussian radius are captured at the
existing heat-source interface.  ``NO_LASER_ASSOCIATED_MELT`` is a prediction
and yields H = W = 0 (owner decision D1, 2026-10-14); tied shares, unenclosed
contours and unavailable geometry stay undefined.

The accepted core's historical global/all-component H/W is retained only as
explicitly named telemetry.  It no longer drives production H/W.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
import math
from pathlib import Path
from typing import Any, Iterator

import numpy as np

from lpbf.model._accepted_core import comparison as accepted_comparison
from lpbf.model.execution_interfaces import InMemoryExecutionInterfaces
from lpbf.model.laser_component_association import (
    BEAM_SHARE_FLOOR,
    NO_LASER_ASSOCIATED_MELT_STATUS,
    POLICY_VERSION,
    select_laser_associated_component_by_beam_share,
)

PRODUCTION_HW_SEMANTICS_VERSION = "22.3.7"
PRODUCTION_HW_DEFINITION = "laser_associated_component_interpolated_liquidus_contour"
NO_LASER_ASSOCIATED_MELT_POLICY = "scored as H=0,W=0 (owner decision D1, 2026-10-14; Patch 22.3.7)"
GEOMETRY_UNAVAILABLE_STATUS = "FAIL_CLOSED_SOURCE_GEOMETRY_UNAVAILABLE"
ZERO_SCORED_STATUSES = frozenset({"ZERO_FOOTPRINT", NO_LASER_ASSOCIATED_MELT_STATUS})


class LaserAssociatedHWEvaluationError(RuntimeError):
    """Raised when production H/W cannot be defined under the association policy."""


def _finite_positive_pair(h: Any, w: Any) -> bool:
    try:
        hf = float(h)
        wf = float(w)
    except (TypeError, ValueError):
        return False
    return math.isfinite(hf) and math.isfinite(wf) and hf > 0.0 and wf > 0.0


def _readonly(values: np.ndarray) -> np.ndarray:
    array = np.asarray(values, dtype=np.float64).copy()
    array.setflags(write=False)
    return array


def _geometry_unavailable_selection() -> dict[str, Any]:
    return {
        "status": GEOMETRY_UNAVAILABLE_STATUS,
        "selected_label": None,
        "selection_mode": "fail_closed",
        "min_distance_cells": None,
        "min_distance_mm": None,
        "tie_count": 0,
        "beam_share": None,
        "beam_share_floor": BEAM_SHARE_FLOOR,
        "beam_share_on_liquid_total": None,
        "contains_beam_cell": None,
        "gaussian_radius_mm": None,
        "component_count": None,
        "policy_version": POLICY_VERSION,
        "distance_metric": None,
    }


@contextmanager
def laser_associated_observation_instrumentation(
    execution_interfaces: Any | None = None,
) -> Iterator[InMemoryExecutionInterfaces]:
    """Temporarily add production association measurements to accepted diagnostics.

    This is scoped to one execution call and restored in ``finally``.  No solver,
    heat-source, moving-window, or temperature-update function is replaced.
    """

    original_top = accepted_comparison.top_surface_liquid_component_diagnostics
    original_component_hw = accepted_comparison.interpolated_component_contour_hw_diagnostic
    state: dict[str, Any] = {}
    source_geometry: dict[str, Any] | None = None

    base_interfaces = execution_interfaces or InMemoryExecutionInterfaces()
    original_heat_source = getattr(base_interfaces, "heat_source_for_row", None)
    if original_heat_source is None:
        original_heat_source = accepted_comparison.build_centered_heat_source_for_row

    def associated_heat_source(*args: Any, **kwargs: Any) -> Any:
        """Record source geometry without changing the accepted source result."""

        nonlocal source_geometry
        result = original_heat_source(*args, **kwargs)
        params = kwargs.get("params")
        if params is None and args:
            params = args[0]
        try:
            source_x = 0.5 * float(params.geometry.Lx_mm) + float(
                kwargs.get("accumulated_subcell_x_mm", 0.0)
            )
            source_y = 0.5 * float(params.geometry.Ly_mm) + float(
                kwargs.get("accumulated_subcell_y_mm", 0.0)
            )
            spacing_x = float(params.geometry.Lx_mm) / float(params.grid.Nx)
            spacing_y = float(params.geometry.Ly_mm) / float(params.grid.Ny)
        except (AttributeError, TypeError, ValueError, ZeroDivisionError):
            # A custom test double may not expose the full geometry contract.
            # The production accepted runtime always does; leaving this unset
            # makes the selector fail closed rather than inventing coordinates.
            source_geometry = None
        else:
            radius = None
            try:
                radius_value = getattr(result[1], "gaussian_radius_mm", None)
                if radius_value is not None:
                    radius = float(radius_value)
                    if not math.isfinite(radius) or radius <= 0.0:
                        radius = None
            except (TypeError, ValueError, IndexError):
                radius = None
            source_geometry = {
                "source_center_x_mm": source_x,
                "source_center_y_mm": source_y,
                "cell_spacing_x_mm": spacing_x,
                "cell_spacing_y_mm": spacing_y,
                "gaussian_radius_mm": radius,
                "source_geometry_origin": "accepted_core_heat_source_call",
            }
        return result

    def associated_top(
        liquid_mask: np.ndarray,
        *,
        beam_i: int,
        beam_j: int,
    ) -> dict[str, Any]:
        diagnostics = original_top(liquid_mask, beam_i=beam_i, beam_j=beam_j)
        geometry = None if source_geometry is None else dict(source_geometry)
        if geometry is None or geometry.get("gaussian_radius_mm") is None:
            selection = _geometry_unavailable_selection()
            selected_mask = None
        else:
            selection, selected_mask = select_laser_associated_component_by_beam_share(
                liquid_mask,
                beam_i=beam_i,
                beam_j=beam_j,
                source_center_x_mm=geometry["source_center_x_mm"],
                source_center_y_mm=geometry["source_center_y_mm"],
                cell_spacing_x_mm=geometry["cell_spacing_x_mm"],
                cell_spacing_y_mm=geometry["cell_spacing_y_mm"],
                gaussian_radius_mm=geometry["gaussian_radius_mm"],
            )
        status = str(selection["status"])
        diagnostics.update(
            {
                "production_hw_definition": PRODUCTION_HW_DEFINITION,
                "production_hw_semantics_version": PRODUCTION_HW_SEMANTICS_VERSION,
                "production_hw_association_policy_version": POLICY_VERSION,
                "production_hw_association_status": status,
                "production_hw_association_mode": selection["selection_mode"],
                "production_hw_association_selected_label": selection.get("selected_label"),
                "production_hw_association_min_distance_cells": selection.get("min_distance_cells"),
                "production_hw_association_min_distance_mm": selection.get("min_distance_mm"),
                "production_hw_association_distance_metric": selection.get("distance_metric"),
                "production_hw_association_tie_count": int(selection.get("tie_count", 0)),
                "production_hw_association_beam_share": selection.get("beam_share"),
                "production_hw_association_beam_share_floor": float(BEAM_SHARE_FLOOR),
                "production_hw_association_beam_share_on_liquid_total": selection.get(
                    "beam_share_on_liquid_total"
                ),
                "production_hw_association_contains_beam_cell": selection.get("contains_beam_cell"),
                "production_hw_association_gaussian_radius_mm": selection.get("gaussian_radius_mm"),
                "production_hw_association_component_count": selection.get("component_count"),
                "production_hw_association_source_geometry_available": (
                    geometry is not None and geometry.get("gaussian_radius_mm") is not None
                ),
                "production_hw_association_fail_closed": status.startswith("FAIL_CLOSED"),
                "laser_associated_component_drives_production_hw": True,
            }
        )
        state.clear()
        state.update(
            {
                "diagnostics": diagnostics,
                "selection": dict(selection),
                "selected_mask": (
                    None
                    if selected_mask is None
                    else np.asarray(selected_mask, dtype=bool).copy()
                ),
                "source_geometry": geometry,
            }
        )
        return diagnostics

    def associated_component_hw(
        top_surface_temperature_K: np.ndarray,
        component_mask: np.ndarray,
        *,
        liquidus_temperature_K: float,
        cell_size_um: float,
        experimental_pixel_size_um: float,
    ) -> dict[str, Any]:
        # Preserve the pre-existing strict beam diagnostic exactly.
        beam_result = original_component_hw(
            top_surface_temperature_K,
            component_mask,
            liquidus_temperature_K=liquidus_temperature_K,
            cell_size_um=cell_size_um,
            experimental_pixel_size_um=experimental_pixel_size_um,
        )
        diagnostics = state.get("diagnostics")
        selection = state.get("selection")
        if not isinstance(diagnostics, dict) or not isinstance(selection, dict):
            raise LaserAssociatedHWEvaluationError(
                "production association instrumentation lost observation context"
            )

        selected_mask = state.get("selected_mask")
        status = str(selection["status"])
        if status in ZERO_SCORED_STATUSES:
            selected_result = {
                "status": status,
                "available": True,
                "contour_enclosed": True,
                "H_pixels": 0.0,
                "W_pixels": 0.0,
                "H_over_W": None,
                "boundary_sides": [],
            }
        elif selected_mask is None:
            selected_result = {
                "status": status,
                "available": False,
                "contour_enclosed": None,
                "H_pixels": None,
                "W_pixels": None,
                "H_over_W": None,
                "boundary_sides": [],
            }
        else:
            selected_result = original_component_hw(
                top_surface_temperature_K,
                selected_mask,
                liquidus_temperature_K=liquidus_temperature_K,
                cell_size_um=cell_size_um,
                experimental_pixel_size_um=experimental_pixel_size_um,
            )

        diagnostics.update(
            {
                "production_hw_component_status": selected_result["status"],
                "production_hw_component_available": bool(selected_result["available"]),
                "production_hw_component_contour_enclosed": selected_result[
                    "contour_enclosed"
                ],
                "production_hw_component_boundary_sides": list(
                    selected_result["boundary_sides"]
                ),
                "production_hw_simulated_H_pixels": selected_result["H_pixels"],
                "production_hw_simulated_W_pixels": selected_result["W_pixels"],
                "production_hw_simulated_H_over_W": selected_result["H_over_W"],
            }
        )
        return beam_result

    accepted_comparison.top_surface_liquid_component_diagnostics = associated_top
    accepted_comparison.interpolated_component_contour_hw_diagnostic = associated_component_hw
    instrumented_interfaces = InMemoryExecutionInterfaces(
        heat_source_for_row=associated_heat_source,
        thermal_step_numba=getattr(base_interfaces, "thermal_step_numba", None),
        thermal_step_numpy=getattr(base_interfaces, "thermal_step_numpy", None),
        temperature_trace_callback=getattr(base_interfaces, "temperature_trace_callback", None),
        observation_capture_callback=getattr(base_interfaces, "observation_capture_callback", None),
        moving_window_update_callback=getattr(base_interfaces, "moving_window_update_callback", None),
    )
    try:
        yield instrumented_interfaces
    finally:
        accepted_comparison.top_surface_liquid_component_diagnostics = original_top
        accepted_comparison.interpolated_component_contour_hw_diagnostic = original_component_hw


def _production_values_from_diagnostic(
    diagnostic: dict[str, Any],
    *,
    invalid_policy: str,
) -> tuple[float, float, str]:
    status = str(diagnostic.get("production_hw_association_status", ""))
    component_status = str(diagnostic.get("production_hw_component_status", ""))
    if status in ZERO_SCORED_STATUSES:
        # A zero footprint and "no laser-associated melt" are both predictions
        # of no pool under the beam; they are scored, not undefined (D1).
        return 0.0, 0.0, status
    h = diagnostic.get("production_hw_simulated_H_pixels")
    w = diagnostic.get("production_hw_simulated_W_pixels")
    if status == "SELECTED" and bool(diagnostic.get("production_hw_component_available")):
        if _finite_positive_pair(h, w):
            return float(h), float(w), "FINITE_MELT"
        component_status = component_status or "DEGENERATE_ASSOCIATED_COMPONENT"

    diagnostic["production_hw_invalid_reason"] = component_status or status or "UNRESOLVED"
    if invalid_policy == "raise":
        raise LaserAssociatedHWEvaluationError(
            "laser-associated production H/W is undefined: "
            f"association={status!r}, component={component_status!r}"
        )
    return float("nan"), float("nan"), "UNENCLOSED" if "UNENCLOSED" in component_status else "ASSOCIATION_FAILED"


def apply_laser_associated_production_hw(
    result: Any,
    *,
    invalid_policy: str,
    expose_diagnostics: bool,
) -> Any:
    """Replace returned global H/W with laser-associated-component H/W."""

    if invalid_policy not in {"raise", "record_nan"}:
        raise ValueError("invalid_policy must be 'raise' or 'record_nan'")
    diagnostics = [dict(item) for item in result.observation_diagnostics]
    count = len(result.frame_index)
    if len(diagnostics) != count:
        raise LaserAssociatedHWEvaluationError(
            "production H/W integration requires one observation diagnostic per result row"
        )

    global_h = np.asarray(result.simulated_H_pixels, dtype=np.float64)
    global_w = np.asarray(result.simulated_W_pixels, dtype=np.float64)
    production_h = np.empty(count, dtype=np.float64)
    production_w = np.empty(count, dtype=np.float64)
    association_failure_count = 0
    associated_unenclosed_count = 0
    selected_count = 0
    beam_cell_liquid_count = 0
    no_melt_count = 0
    zero_count = 0

    for index, diagnostic in enumerate(diagnostics):
        frame = int(result.frame_index[index])
        row = int(result.mapped_process_row[index])
        if int(diagnostic.get("frame_index", frame)) != frame or int(
            diagnostic.get("mapped_process_row", row)
        ) != row:
            raise LaserAssociatedHWEvaluationError(
                "production H/W diagnostics are not aligned with result arrays"
            )

        global_h_value = float(global_h[index])
        global_w_value = float(global_w[index])
        diagnostic["global_all_component_classification"] = diagnostic.get("classification")
        diagnostic["global_all_component_boundary_sides"] = list(
            diagnostic.get("boundary_sides") or []
        )
        diagnostic["global_all_component_liquidus_contour_boundary_contact"] = diagnostic.get(
            "liquidus_contour_boundary_contact"
        )
        diagnostic["global_all_component_simulated_H_pixels"] = (
            global_h_value if math.isfinite(global_h_value) else None
        )
        diagnostic["global_all_component_simulated_W_pixels"] = (
            global_w_value if math.isfinite(global_w_value) else None
        )
        diagnostic["global_all_component_simulated_H_over_W"] = (
            None
            if not math.isfinite(global_h_value)
            or not math.isfinite(global_w_value)
            or global_w_value == 0.0
            else float(global_h_value / global_w_value)
        )

        h, w, classification = _production_values_from_diagnostic(
            diagnostic, invalid_policy=invalid_policy
        )
        production_h[index] = h
        production_w[index] = w
        contains_beam_cell = bool(diagnostic.get("production_hw_association_contains_beam_cell"))
        if classification == "ZERO_FOOTPRINT":
            zero_count += 1
        elif classification == NO_LASER_ASSOCIATED_MELT_STATUS:
            no_melt_count += 1
        elif classification == "FINITE_MELT":
            selected_count += 1
            if contains_beam_cell:
                beam_cell_liquid_count += 1
        else:
            association_failure_count += 1
            if "UNENCLOSED" in str(diagnostic.get("production_hw_component_status", "")):
                associated_unenclosed_count += 1

        diagnostic["classification"] = classification
        diagnostic["boundary_sides"] = list(
            diagnostic.get("production_hw_component_boundary_sides") or []
        )
        diagnostic["liquidus_contour_boundary_contact"] = bool(
            diagnostic.get("production_hw_component_boundary_sides")
        )
        diagnostic["beam_component_diagnostic_drives_production_hw"] = (
            contains_beam_cell and classification == "FINITE_MELT"
        )
        diagnostic["production_hw_spans_multiple_liquid_components"] = False
        diagnostic["production_hw_definition_changed"] = True

    experimental_h = np.asarray(result.experimental_H_pixels, dtype=np.float64)
    experimental_w = np.asarray(result.experimental_W_pixels, dtype=np.float64)
    metadata = dict(result.metadata)
    legacy_global_unenclosed = int(
        metadata.get("hw_extraction_unenclosed_contour_failure_count", 0)
    )
    metadata.update(
        {
            "production_hw_definition": PRODUCTION_HW_DEFINITION,
            "production_hw_semantics_version": PRODUCTION_HW_SEMANTICS_VERSION,
            "production_hw_association_policy_version": POLICY_VERSION,
            "production_hw_association_beam_share_floor": float(BEAM_SHARE_FLOOR),
            "no_laser_associated_melt_policy": NO_LASER_ASSOCIATED_MELT_POLICY,
            "production_hw_definition_changed": True,
            "laser_associated_component_drives_production_hw": True,
            "global_all_component_hw_drives_production": False,
            "legacy_global_hw_extraction_unenclosed_contour_failure_count": legacy_global_unenclosed,
            "hw_extraction_unenclosed_contour_failure_count": int(associated_unenclosed_count),
            "production_hw_association_failure_count": int(association_failure_count),
            "production_hw_selected_count": int(selected_count),
            "production_hw_beam_cell_liquid_count": int(beam_cell_liquid_count),
            "production_hw_no_laser_associated_melt_count": int(no_melt_count),
            "production_hw_zero_footprint_count": int(zero_count),
            "bbox_algorithm": (
                "cv2.minAreaRect on linearly interpolated T=T_liquidus crossings "
                "of the laser-associated 4-neighbor liquid component selected by "
                "beam-power share; H=major, W=minor"
            ),
        }
    )

    return replace(
        result,
        simulated_H_pixels=_readonly(production_h),
        simulated_W_pixels=_readonly(production_w),
        H_difference_pixels=_readonly(production_h - experimental_h),
        W_difference_pixels=_readonly(production_w - experimental_w),
        metadata=metadata,
        observation_diagnostics=(tuple(diagnostics) if expose_diagnostics else ()),
    )


def run_in_memory_layer_melt_pool_comparison(
    params: Any,
    preloaded: Any,
    max_rows: int | None = None,
    *,
    observation_frame_indices: np.ndarray | None = None,
    workspace: Any | None = None,
    unenclosed_contour_policy: str = "raise",
    absorbed_power_treatment: Any | None = None,
    capture_observation_diagnostics: bool = False,
    execution_interfaces: Any | None = None,
) -> Any:
    """Run accepted thermal physics and return Patch 22.3.7 production H/W.

    The accepted core is always asked to *record* a legacy global-contour
    failure so a remote/global component cannot abort before the associated
    component is evaluated.  The caller's requested ``unenclosed_contour_policy``
    is then applied to the associated component result.
    """

    if unenclosed_contour_policy not in {"raise", "record_nan"}:
        raise ValueError("unenclosed_contour_policy must be 'raise' or 'record_nan'")
    with laser_associated_observation_instrumentation(
        execution_interfaces=execution_interfaces
    ) as instrumented_interfaces:
        result = accepted_comparison.run_in_memory_layer_melt_pool_comparison(
            params,
            preloaded,
            max_rows=max_rows,
            observation_frame_indices=observation_frame_indices,
            workspace=workspace,
            unenclosed_contour_policy="record_nan",
            absorbed_power_treatment=absorbed_power_treatment,
            capture_observation_diagnostics=True,
            execution_interfaces=instrumented_interfaces,
        )
    return apply_laser_associated_production_hw(
        result,
        invalid_policy=unenclosed_contour_policy,
        expose_diagnostics=bool(capture_observation_diagnostics),
    )


def run_layer_melt_pool_comparison(
    params: Any | None = None,
    max_rows: int | None = None,
    *,
    observation_frame_indices: np.ndarray | None = None,
) -> Any:
    """Run the supported persistent comparison with Patch 22.3.7 H/W.

    File I/O and verification are delegated to the accepted implementation; only
    the simulated observation arrays supplied to the writer are replaced by the
    laser-associated production values.
    """

    if params is None:
        params = accepted_comparison.get_params()
    else:
        params.validate()
    if not params.comparison.enabled:
        raise ValueError("Melt-pool comparison is disabled in parameters.py.")

    input_path = accepted_comparison.resolve_h5_path(params)
    output_path = Path(params.output.output_directory) / params.comparison.output_h5_filename
    print("Running experimental/simulated melt-pool H/W comparison.")
    print(f"  Input:  {input_path}")
    print(f"  Layer:  {params.comparison.layer_name}")
    print(f"  Output: {output_path}")
    preloaded = accepted_comparison.preload_layer_melt_pool_comparison(params)
    result = run_in_memory_layer_melt_pool_comparison(
        params,
        preloaded,
        max_rows=max_rows,
        observation_frame_indices=observation_frame_indices,
        unenclosed_contour_policy="raise",
        capture_observation_diagnostics=False,
    )
    accepted_comparison._write_layer_melt_pool_comparison_h5(
        input_path=input_path,
        output_path=output_path,
        layer_name=params.comparison.layer_name,
        sim_h=np.asarray(result.simulated_H_pixels, dtype=np.float64),
        sim_w=np.asarray(result.simulated_W_pixels, dtype=np.float64),
        metadata=dict(result.metadata),
        params=params,
        observation_frame_indices=observation_frame_indices,
    )
    accepted_comparison._verify_layer_melt_pool_comparison_h5(
        output_path=output_path,
        source_path=input_path,
        layer_name=params.comparison.layer_name,
    )
    print("Melt-pool H/W comparison complete.")
    print(f"  HDF5 file: {output_path}")
    return output_path


__all__ = [
    "GEOMETRY_UNAVAILABLE_STATUS",
    "LaserAssociatedHWEvaluationError",
    "NO_LASER_ASSOCIATED_MELT_POLICY",
    "PRODUCTION_HW_DEFINITION",
    "PRODUCTION_HW_SEMANTICS_VERSION",
    "apply_laser_associated_production_hw",
    "laser_associated_observation_instrumentation",
    "run_in_memory_layer_melt_pool_comparison",
    "run_layer_melt_pool_comparison",
]
