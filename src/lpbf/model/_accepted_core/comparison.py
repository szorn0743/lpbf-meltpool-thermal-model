"""Experimental/simulated melt-pool H/W comparison workflow.

This module owns simulated H/W extraction, OpenCV ``minAreaRect`` geometry,
including the Patch 9.5.5 optional interpolated liquidus-contour path,
comparison-channel writing, output verification, the comparison production
runner, and the Patch 10.3.2/10.3.3 preloaded in-memory calibration path. HDF5 process-channel interpretation is delegated to ``input_data.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from lpbf.model.execution_interfaces import InMemoryExecutionInterfaces
from lpbf.model.observation_diagnostics import (
    beam_connected_liquid_component_mask,
    interpolated_component_contour_hw_diagnostic,
    top_surface_liquid_component_diagnostics,
)

import h5py
import numpy as np

from lpbf.model._accepted_core.heat_source import HeatSourceFieldBuilder, build_centered_heat_source_for_row
from lpbf.model._accepted_core.moving_window import (
    MovingWindowState,
    apply_moving_window_update,
)
from lpbf.model._accepted_core.input_data import (
    LayerH5ProcessData,
    decode_h5_names,
    load_layer_h5_process_data,
    resolve_h5_path,
)
from lpbf.model._accepted_core.parameters import SimulationParameters, get_params
from lpbf.runtime.reproducibility import build_reproducibility_metadata, write_reproducibility_metadata
from lpbf.model._accepted_core.solver import (
    NUMBA_AVAILABLE,
    compute_stored_energy_relative_to_temperature_J,
    explicit_fvm_step,
    explicit_fvm_step_numba,
    warm_up_numba_solver,
)


def _params_with_dt(params: SimulationParameters, dt_s: float) -> SimulationParameters:
    return replace(
        params,
        time=replace(
            params.time,
            dt_s=float(dt_s),
            total_time_s=max(float(dt_s), params.time.total_time_s),
        ),
    )


# -------------------------------------------------------------------------
# Experimental melt-pool H/W comparison for layer-structured HDF5 input
# -------------------------------------------------------------------------

_COMPARISON_APPENDED_NAMES = (
    "Simulated H",
    "Simulated W",
    "H Difference",
    "W Difference",
)

_COMPARISON_GROUP_NAME = "comparison"
_COMPARISON_FRAME_FIELDS = (
    "frame_index",
    "gige_time_s",
    "mapped_process_row",
    "experimental_H_pixels",
    "experimental_W_pixels",
    "simulated_H_pixels",
    "simulated_W_pixels",
    "H_difference_pixels",
    "W_difference_pixels",
)

# Canonical upstream comparison definitions frozen for Patch 9.7 calibration.
# These are public constants because calibration provenance must refer to the
# same definitions used by the production comparison path rather than duplicate
# free-form strings in a separate fitting module.
HW_PHYSICAL_CONVENTION = "H=major side, W=minor side"
CAMERA_OBSERVATION_SAMPLING_CADENCE = "camera_observation_mapped_process_rows"
CANONICAL_GIGE_MAPPING_DATASET = "sync/gige_image_to_data_index"


class UnenclosedLiquidusContourError(ValueError):
    """The requested liquidus contour extends beyond the represented x/y field.

    This is a geometry-validity failure, not permission to change the frozen
    contour method or synthesize an arbitrary boundary closure. Calibration
    sweeps may record the parameter point as invalid and continue to the next
    predeclared point while preserving the production physics and domain.
    """

    def __init__(
        self,
        message: str,
        *,
        layer_name: str | None = None,
        process_row: int | None = None,
        frame_indices: tuple[int, ...] = (),
        boundary_sides: tuple[str, ...] = (),
        max_boundary_temperature_K: float | None = None,
        liquidus_temperature_K: float | None = None,
    ) -> None:
        super().__init__(message)
        self.layer_name = layer_name
        self.process_row = process_row
        self.frame_indices = tuple(int(value) for value in frame_indices)
        self.boundary_sides = tuple(str(value) for value in boundary_sides)
        self.max_boundary_temperature_K = max_boundary_temperature_K
        self.liquidus_temperature_K = liquidus_temperature_K


@dataclass(frozen=True)
class PreloadedLayerMeltPoolComparison:
    """Immutable layer/synchronization inputs reused across calibration trials.

    Patch 10.3.2 separates input preparation from repeated trial evaluation.
    ``layer_input`` is loaded and TED-calibrated once; trial-specific source
    parameters continue to be supplied through ``SimulationParameters``.
    """

    input_path: Path
    layer_name: str
    layer_input: LayerH5ProcessData
    preload_definition: tuple[tuple[str, Any], ...]


@dataclass(frozen=True)
class AbsorbedPowerTreatment:
    """Explicit row-wise absorbed-power treatment for diagnostic simulations.

    The ordinary production/comparison path does not construct this object and
    therefore retains the frozen legacy TED behavior. Diagnostic callers may
    provide a baseline absorbed-energy scale plus a dimensionless row-wise TED
    modulation. When supplied, physical laser state alone controls source
    enablement; a legacy TED-calibration-invalid row no longer shuts the source
    off and instead uses the supplied bounded modulation.
    """

    identifier: str
    alpha_base: float
    ted_modulation: np.ndarray
    metadata: dict[str, Any] | None = None


@dataclass
class InMemoryCalibrationTrialWorkspace:
    """Reusable large allocations and compiled-kernel state for fast trials.

    Patch 10.3.3 keeps the thermal state arrays and heat-source builder alive
    across sequential calibration evaluations.  The workspace is intentionally
    single-trial-at-a-time; bounded parallel calibration, if ever enabled, must
    allocate one independent workspace per worker.
    """

    workspace_definition: tuple[tuple[str, Any], ...]
    temperature_K: np.ndarray
    temperature_scratch_K: np.ndarray
    field_builder: HeatSourceFieldBuilder
    numba_warmed: bool = False
    trials_started: int = 0


def _calibration_trial_workspace_definition(
    params: SimulationParameters,
) -> tuple[tuple[str, Any], ...]:
    """Return the geometry/execution definition owned by a reusable workspace."""

    return (
        ("grid.Nx", int(params.grid.Nx)),
        ("grid.Ny", int(params.grid.Ny)),
        ("grid.Nz", int(params.grid.Nz)),
        ("geometry.Lx_mm", float(params.geometry.Lx_mm)),
        ("geometry.Ly_mm", float(params.geometry.Ly_mm)),
        ("geometry.Lz_mm", float(params.geometry.Lz_mm)),
        ("output.use_numba", bool(params.output.use_numba)),
    )


def prepare_in_memory_calibration_trial_workspace(
    params: SimulationParameters,
) -> InMemoryCalibrationTrialWorkspace:
    """Allocate the Patch 10.3.3 fast-trial workspace and warm FVM once.

    Only the compiled timestep used by the comparison loop is warmed here.  The
    generic production warm-up also prepares feature-analysis kernels that are
    not used by metrics-only calibration trials, so repeating it per trial would
    be avoidable setup work.
    """

    params.validate()
    shape = (params.grid.Nx, params.grid.Ny, params.grid.Nz)
    temperature_K = np.empty(shape, dtype=np.float64)
    temperature_scratch_K = np.empty_like(temperature_K)
    field_builder = HeatSourceFieldBuilder(params)
    workspace = InMemoryCalibrationTrialWorkspace(
        workspace_definition=_calibration_trial_workspace_definition(params),
        temperature_K=temperature_K,
        temperature_scratch_K=temperature_scratch_K,
        field_builder=field_builder,
    )

    if params.output.use_numba and NUMBA_AVAILABLE:
        bulk_temperature_K = float(params.initial_condition.initial_temperature_K)
        workspace.temperature_K.fill(bulk_temperature_K)
        workspace.field_builder.buffer.fill(0.0)
        explicit_fvm_step_numba(
            workspace.temperature_K,
            workspace.field_builder.buffer,
            params,
            temperature_out_K=workspace.temperature_scratch_K,
        )
        workspace.numba_warmed = True

    return workspace


def _validate_in_memory_calibration_trial_workspace(
    workspace: InMemoryCalibrationTrialWorkspace,
    params: SimulationParameters,
) -> None:
    current = _calibration_trial_workspace_definition(params)
    if current != workspace.workspace_definition:
        previous = dict(workspace.workspace_definition)
        changed = [name for name, value in current if previous.get(name) != value]
        raise ValueError(
            "In-memory calibration workspace is stale for the supplied trial "
            "parameters: "
            + ", ".join(changed)
            + ". Re-prepare the calibration evaluator before evaluating this trial."
        )


@dataclass(frozen=True)
class InMemoryMeltPoolComparisonResult:
    """Frame-rate H/W comparison values returned without persistent artifacts."""

    frame_index: np.ndarray
    mapped_process_row: np.ndarray
    experimental_H_pixels: np.ndarray
    experimental_W_pixels: np.ndarray
    simulated_H_pixels: np.ndarray
    simulated_W_pixels: np.ndarray
    H_difference_pixels: np.ndarray
    W_difference_pixels: np.ndarray
    metadata: dict[str, float | int | str]
    observation_diagnostics: tuple[dict[str, Any], ...] = ()


def _comparison_preload_definition(
    params: SimulationParameters,
) -> tuple[tuple[str, Any], ...]:
    """Return parameters that determine layer/synchronization preprocessing.

    The two Patch 10.4 source-fit degrees of freedom are intentionally absent:
    calibration factor and deposition depth do not affect HDF5 ingestion,
    synchronization, or TED calibration. Fixed beam geometry remains part of
    this immutable definition, as does incident power because the TED reflection
    reference depends on it.
    """

    threshold = params.input.laser_drive_threshold
    return (
        ("input.h5_path_select", str(params.input.h5_path_select)),
        ("comparison.layer_name", str(params.comparison.layer_name)),
        ("comparison.sample_frequency_hz", float(params.comparison.sample_frequency_hz)),
        (
            "input.laser_drive_threshold",
            None if threshold is None else float(threshold),
        ),
        ("input.h5_baseline_max_samples", int(params.input.h5_baseline_max_samples)),
        ("input.ted_baseline_policy", str(params.input.ted_baseline_policy)),
        (
            "input.ted_baseline_evidence_policy",
            str(params.input.ted_baseline_evidence_policy),
        ),
        (
            "input.ted_off_segment_outlier_sigma_multiplier",
            float(params.input.ted_off_segment_outlier_sigma_multiplier),
        ),
        ("input.ted_reference_slope", float(params.input.ted_reference_slope)),
        ("input.ted_reference_intercept", float(params.input.ted_reference_intercept)),
        ("heat_source.incident_power_W", float(params.heat_source.incident_power_W)),
        ("input.default_spot_size_um", float(params.input.default_spot_size_um)),
        (
            "moving_window.spot_size_um_is_diameter",
            bool(params.moving_window.spot_size_um_is_diameter),
        ),
        ("heat_source.gaussian_radius_mm", float(params.heat_source.gaussian_radius_mm)),
    )


def _freeze_preloaded_layer_arrays(layer_input: LayerH5ProcessData) -> None:
    """Make cached NumPy inputs read-only so trials cannot mutate shared state."""

    objects = [layer_input, layer_input.process]
    if layer_input.observation_table is not None:
        objects.append(layer_input.observation_table)
    for obj in objects:
        for value in vars(obj).values():
            if isinstance(value, np.ndarray):
                value.setflags(write=False)


def preload_layer_melt_pool_comparison(
    params: SimulationParameters,
) -> PreloadedLayerMeltPoolComparison:
    """Load immutable layer/synchronization/TED inputs once for Patch 10.3.2."""

    params.validate()
    if not params.comparison.enabled:
        raise ValueError("Melt-pool comparison is disabled in parameters.py.")
    input_path = resolve_h5_path(params)
    layer_name = str(params.comparison.layer_name)
    layer_input = load_layer_h5_process_data(
        path=input_path,
        layer_name=layer_name,
        params=params,
        require_camera_sync=True,
    )
    if layer_input.observation_table is None:
        raise ValueError(
            "Timestamp-based comparison requires a valid camera observation table."
        )
    _freeze_preloaded_layer_arrays(layer_input)
    return PreloadedLayerMeltPoolComparison(
        input_path=input_path,
        layer_name=layer_name,
        layer_input=layer_input,
        preload_definition=_comparison_preload_definition(params),
    )


def _validate_preloaded_layer_melt_pool_comparison(
    preloaded: PreloadedLayerMeltPoolComparison,
    params: SimulationParameters,
) -> None:
    """Reject reuse when a parameter would make cached preprocessing stale."""

    current = _comparison_preload_definition(params)
    if current != preloaded.preload_definition:
        previous = dict(preloaded.preload_definition)
        changed = [
            name
            for name, value in current
            if previous.get(name) != value
        ]
        raise ValueError(
            "Preloaded comparison inputs are stale for the supplied trial parameters: "
            + ", ".join(changed)
            + ". Re-preload the layer before evaluating this trial."
        )


def _readonly_array(values: np.ndarray, *, dtype: Any) -> np.ndarray:
    result = np.array(values, dtype=dtype, copy=True)
    result.setflags(write=False)
    return result


def _selected_observation_positions(
    available_frame_index: np.ndarray,
    requested_frame_index: np.ndarray | None,
) -> np.ndarray:
    """Return positions of an exact, ordered subset of valid camera frames.

    Patch 10.1.1 uses this narrow selection hook for the compact grid-convergence
    set. Normal production comparisons pass ``None`` and therefore retain every
    synchronization-valid observation exactly as before.
    """

    available = np.asarray(available_frame_index, dtype=np.int64)
    if available.ndim != 1:
        raise ValueError("available_frame_index must be one-dimensional.")
    if available.size and np.any(np.diff(available) <= 0):
        raise ValueError("available_frame_index must be strictly increasing.")

    if requested_frame_index is None:
        return np.arange(available.size, dtype=np.int64)

    requested = np.asarray(requested_frame_index, dtype=np.int64)
    if requested.ndim != 1 or requested.size == 0:
        raise ValueError(
            "observation_frame_indices must be a nonempty one-dimensional array."
        )
    if np.any(requested < 0) or np.any(np.diff(requested) <= 0):
        raise ValueError(
            "observation_frame_indices must be strictly increasing nonnegative frame indices."
        )

    positions = np.searchsorted(available, requested)
    in_bounds = positions < available.size
    matches = np.zeros(requested.shape, dtype=bool)
    if np.any(in_bounds):
        matches[in_bounds] = available[positions[in_bounds]] == requested[in_bounds]
    if not np.all(matches):
        missing = requested[~matches]
        preview = ", ".join(str(int(value)) for value in missing[:5])
        if missing.size > 5:
            preview += ", ..."
        raise ValueError(
            "observation_frame_indices contains frames that are not synchronization-valid: "
            + preview
        )
    return positions.astype(np.int64, copy=False)

# Internal aliases retained for the extraction implementation. These names
# describe physical major/minor sides, not OpenCV tuple orientation.
_EXPERIMENTAL_H_RECT_DIMENSION = "major"
_EXPERIMENTAL_W_RECT_DIMENSION = "minor"




def compute_top_surface_min_area_rect_hw_pixels(
    temperature_K: np.ndarray,
    liquidus_temperature_K: float,
    cell_size_um: float,
    experimental_pixel_size_um: float,
) -> tuple[float, float]:
    """Return simulated (H, W) using OpenCV ``minAreaRect``.

    Only top-surface cells satisfying ``T >= T_liquidus`` are used. Each liquid
    finite-volume cell contributes its complete square footprint, expressed in
    experimental-pixel units. The two sides returned by OpenCV are explicitly sorted
    so the function returns the canonical experimental convention ``H >= W``:
    ``H = major dimension`` and ``W = minor dimension``.
    """
    try:
        import cv2
    except ImportError as exc:  # pragma: no cover - depends on local environment
        raise ImportError(
            "The melt-pool comparison workflow requires OpenCV. "
            "Install it with 'pip install opencv-python'."
        ) from exc

    temperature_array_K = np.asarray(temperature_K)
    if temperature_array_K.ndim != 3:
        raise ValueError(
            "temperature_K must be a three-dimensional temperature field."
        )

    liquid_ij = np.argwhere(
        temperature_array_K[:, :, -1] >= float(liquidus_temperature_K)
    )
    if liquid_ij.size == 0:
        return 0.0, 0.0

    pixel_scale = float(cell_size_um) / float(experimental_pixel_size_um)
    points = np.empty((liquid_ij.shape[0] * 4, 2), dtype=np.float32)
    write = 0
    for i, j in liquid_ij:
        x0 = float(i) * pixel_scale
        x1 = float(i + 1) * pixel_scale
        y0 = float(j) * pixel_scale
        y1 = float(j + 1) * pixel_scale
        points[write + 0] = (x0, y0)
        points[write + 1] = (x1, y0)
        points[write + 2] = (x1, y1)
        points[write + 3] = (x0, y1)
        write += 4

    rect = cv2.minAreaRect(points)
    side_a_px, side_b_px = rect[1]
    major_px = float(max(side_a_px, side_b_px))
    minor_px = float(min(side_a_px, side_b_px))

    h_px = major_px
    w_px = minor_px
    return h_px, w_px


def compute_top_surface_interpolated_liquidus_contour_hw_pixels(
    temperature_K: np.ndarray,
    liquidus_temperature_K: float,
    cell_size_um: float,
    experimental_pixel_size_um: float,
) -> tuple[float, float]:
    """Return simulated (H, W) from a linearly interpolated liquidus contour.

    Top-surface finite-volume temperatures are interpreted at cell centers. For
    each x- or y-neighbor pair whose liquid classification differs, the exact
    ``T = T_liquidus`` crossing is found by linear interpolation along the edge
    connecting those centers. ``cv2.minAreaRect`` is then applied to all crossing
    points and its side lengths are sorted into the canonical experimental
    convention ``H = major`` and ``W = minor``.

    The contour must be enclosed by represented below-liquidus cell centers. If a
    liquid cell center lies on the computational x/y boundary, the isocontour can
    continue outside the local field and cannot be reconstructed without an
    arbitrary ghost-cell assumption, so this optional method raises explicitly.
    """
    try:
        import cv2
    except ImportError as exc:  # pragma: no cover - depends on local environment
        raise ImportError(
            "The melt-pool comparison workflow requires OpenCV. "
            "Install it with 'pip install opencv-python'."
        ) from exc

    temperature_array_K = np.asarray(temperature_K, dtype=np.float64)
    if temperature_array_K.ndim != 3:
        raise ValueError(
            "temperature_K must be a three-dimensional temperature field."
        )
    if not np.all(np.isfinite(temperature_array_K[:, :, -1])):
        raise ValueError(
            "Top-surface temperature field must be finite for interpolated "
            "liquidus-contour extraction."
        )

    level_K = float(liquidus_temperature_K)
    cell_size = float(cell_size_um)
    pixel_size = float(experimental_pixel_size_um)
    if not np.isfinite(level_K):
        raise ValueError("liquidus_temperature_K must be finite.")
    if not np.isfinite(cell_size) or cell_size <= 0.0:
        raise ValueError("cell_size_um must be finite and positive.")
    if not np.isfinite(pixel_size) or pixel_size <= 0.0:
        raise ValueError("experimental_pixel_size_um must be finite and positive.")

    top_surface_K = temperature_array_K[:, :, -1]
    liquid = top_surface_K >= level_K
    if not np.any(liquid):
        return 0.0, 0.0

    if top_surface_K.shape[0] < 2 or top_surface_K.shape[1] < 2:
        raise ValueError(
            "Interpolated liquidus-contour extraction requires at least two "
            "top-surface cell centers in both x and y."
        )
    if (
        np.any(liquid[0, :])
        or np.any(liquid[-1, :])
        or np.any(liquid[:, 0])
        or np.any(liquid[:, -1])
    ):
        raise UnenclosedLiquidusContourError(
            "Interpolated liquidus contour is not enclosed by the local "
            "top-surface field: at least one boundary cell center is at or "
            "above T_liquidus. H/W is undefined under the frozen "
            "interpolated_liquidus_contour geometry for this trial."
        )

    pixel_scale = cell_size / pixel_size
    x_centers_px = (
        np.arange(top_surface_K.shape[0], dtype=np.float64) + 0.5
    ) * pixel_scale
    y_centers_px = (
        np.arange(top_surface_K.shape[1], dtype=np.float64) + 0.5
    ) * pixel_scale
    contour_points: list[tuple[float, float]] = []

    # Crossings on x-directed center-to-center edges.
    for i in range(top_surface_K.shape[0] - 1):
        for j in range(top_surface_K.shape[1]):
            if bool(liquid[i, j]) == bool(liquid[i + 1, j]):
                continue
            t0 = float(top_surface_K[i, j])
            t1 = float(top_surface_K[i + 1, j])
            fraction = (level_K - t0) / (t1 - t0)
            x_px = x_centers_px[i] + fraction * (
                x_centers_px[i + 1] - x_centers_px[i]
            )
            contour_points.append((float(x_px), float(y_centers_px[j])))

    # Crossings on y-directed center-to-center edges.
    for i in range(top_surface_K.shape[0]):
        for j in range(top_surface_K.shape[1] - 1):
            if bool(liquid[i, j]) == bool(liquid[i, j + 1]):
                continue
            t0 = float(top_surface_K[i, j])
            t1 = float(top_surface_K[i, j + 1])
            fraction = (level_K - t0) / (t1 - t0)
            y_px = y_centers_px[j] + fraction * (
                y_centers_px[j + 1] - y_centers_px[j]
            )
            contour_points.append((float(x_centers_px[i]), float(y_px)))

    if not contour_points:
        raise ValueError(
            "A nonzero liquid footprint was present but no T_liquidus edge "
            "crossings were found. The interpolated contour is degenerate."
        )

    points = np.asarray(contour_points, dtype=np.float32)
    rect = cv2.minAreaRect(points)
    side_a_px, side_b_px = rect[1]
    major_px = float(max(side_a_px, side_b_px))
    minor_px = float(min(side_a_px, side_b_px))
    return major_px, minor_px


def _compute_top_surface_hw_pixels(
    temperature_K: np.ndarray,
    liquidus_temperature_K: float,
    cell_size_um: float,
    experimental_pixel_size_um: float,
    geometry_method: str,
) -> tuple[float, float]:
    """Dispatch the configured Patch 9.5.5 H/W geometry extraction method."""
    if geometry_method == "cell_footprint":
        return compute_top_surface_min_area_rect_hw_pixels(
            temperature_K=temperature_K,
            liquidus_temperature_K=liquidus_temperature_K,
            cell_size_um=cell_size_um,
            experimental_pixel_size_um=experimental_pixel_size_um,
        )
    if geometry_method == "interpolated_liquidus_contour":
        return compute_top_surface_interpolated_liquidus_contour_hw_pixels(
            temperature_K=temperature_K,
            liquidus_temperature_K=liquidus_temperature_K,
            cell_size_um=cell_size_um,
            experimental_pixel_size_um=experimental_pixel_size_um,
        )
    raise ValueError(f"Unsupported H/W geometry method: {geometry_method!r}.")


def _bbox_algorithm_description(geometry_method: str) -> str:
    if geometry_method == "cell_footprint":
        return (
            "cv2.minAreaRect on full top-surface liquid-cell footprints; "
            + HW_PHYSICAL_CONVENTION
        )
    if geometry_method == "interpolated_liquidus_contour":
        return (
            "cv2.minAreaRect on linearly interpolated top-surface "
            "T=T_liquidus cell-center edge crossings; "
            + HW_PHYSICAL_CONVENTION
        )
    raise ValueError(f"Unsupported H/W geometry method: {geometry_method!r}.")


def _simulate_preloaded_layer_melt_pool_hw(
    layer_input: LayerH5ProcessData,
    params: SimulationParameters,
    max_rows: int | None = None,
    observation_frame_indices: np.ndarray | None = None,
    workspace: InMemoryCalibrationTrialWorkspace | None = None,
    unenclosed_contour_policy: str = "raise",
    absorbed_power_treatment: AbsorbedPowerTreatment | None = None,
    observation_diagnostics: list[dict[str, Any]] | None = None,
    execution_interfaces: InMemoryExecutionInterfaces | None = None,
) -> tuple[np.ndarray, np.ndarray, dict[str, float | int | str]]:
    """Run one already-loaded layer and sample H/W at camera observations only.

    Patch 10.3.2 makes the thermal/HW core independent of persistent comparison
    output so calibration trials can reuse immutable layer and synchronization
    inputs. The numerical loop and H/W extraction are unchanged.
    """
    comparison = params.comparison
    interfaces = execution_interfaces or InMemoryExecutionInterfaces()
    heat_source_for_row = interfaces.heat_source_for_row or build_centered_heat_source_for_row
    thermal_step_numba = interfaces.thermal_step_numba or explicit_fvm_step_numba
    thermal_step_numpy = interfaces.thermal_step_numpy or explicit_fvm_step
    temperature_trace_callback = interfaces.temperature_trace_callback
    observation_capture_callback = interfaces.observation_capture_callback
    moving_window_update_callback = interfaces.moving_window_update_callback
    if unenclosed_contour_policy not in {"raise", "record_nan"}:
        raise ValueError(
            "unenclosed_contour_policy must be 'raise' or 'record_nan'."
        )
    unenclosed_contour_failure_count = 0
    process = layer_input.process
    observation_table = layer_input.observation_table
    if observation_table is None:
        raise ValueError(
            "Timestamp-based comparison requires a valid camera observation table."
        )
    process_time_s = np.asarray(process.time_s, dtype=np.float64)
    x_mm = process.laser_x_mm
    y_mm = process.laser_y_mm
    laser_on = process.laser_on
    ted_eta = np.asarray(process.effective_absorptivity, dtype=np.float64)
    ted_calibration_valid = np.asarray(
        process.ted_calibration_valid_flag, dtype=bool
    )
    drive_threshold = float(process.h5_laser_drive_threshold_used)

    total_rows = process.n_rows
    if process_time_s.shape != (total_rows,):
        raise ValueError(
            "Process time_s must contain exactly one timestamp per process row."
        )
    if not np.all(np.isfinite(process_time_s)):
        raise ValueError("Process time_s contains non-finite timestamps.")
    if total_rows > 1 and np.any(np.diff(process_time_s) <= 0.0):
        raise ValueError("Process time_s must be strictly increasing.")
    n_rows = total_rows if max_rows is None else min(total_rows, int(max_rows))
    if n_rows < 1:
        raise ValueError("Selected comparison layer contains no rows to simulate.")

    treatment_modulation: np.ndarray | None = None
    treatment_alpha_base: float | None = None
    if absorbed_power_treatment is not None:
        treatment_alpha_base = float(absorbed_power_treatment.alpha_base)
        if not np.isfinite(treatment_alpha_base) or not (0.0 <= treatment_alpha_base <= 1.0):
            raise ValueError("absorbed-power treatment alpha_base must be finite and within [0, 1].")
        treatment_modulation = np.asarray(
            absorbed_power_treatment.ted_modulation, dtype=np.float64
        )
        if treatment_modulation.shape != (total_rows,):
            raise ValueError(
                "absorbed-power treatment ted_modulation must contain exactly one value per process row."
            )
        if not np.all(np.isfinite(treatment_modulation)) or np.any(treatment_modulation < 0.0):
            raise ValueError(
                "absorbed-power treatment ted_modulation must be finite and nonnegative."
            )

    source_template = params.heat_source
    controls = params.moving_window
    bulk_temperature_K = float(params.initial_condition.initial_temperature_K)
    if workspace is None:
        T = np.full(
            (params.grid.Nx, params.grid.Ny, params.grid.Nz),
            bulk_temperature_K,
            dtype=np.float64,
        )
        T_scratch = np.empty_like(T)
        field_builder = HeatSourceFieldBuilder(params)
        if params.output.use_numba and NUMBA_AVAILABLE:
            warm_up_numba_solver(params)
    else:
        _validate_in_memory_calibration_trial_workspace(workspace, params)
        T = workspace.temperature_K
        T.fill(bulk_temperature_K)
        T_scratch = workspace.temperature_scratch_K
        field_builder = workspace.field_builder
        workspace.trials_started += 1

    q_dot = field_builder.buffer
    q_dot.fill(0.0)
    state = MovingWindowState(bulk_temperature_K=bulk_temperature_K)

    # Patch 9.2.5 samples in camera-observation space. Patch 9.2.6 writes these
    # samples canonically at frame rate while retaining a process-row compatibility
    # projection in the copied layer data. Patch 10.1.1 optionally selects an exact
    # predeclared subset for grid-convergence work; production behavior is unchanged
    # when no subset is supplied.
    selection_positions = _selected_observation_positions(
        np.asarray(observation_table.frame_index, dtype=np.int64),
        observation_frame_indices,
    )
    selected_frame_indices = np.asarray(
        observation_table.frame_index[selection_positions], dtype=np.int64
    )
    mapped_observation_rows = np.asarray(
        observation_table.mapped_process_row[selection_positions], dtype=np.int64
    )
    sim_h = np.full(selection_positions.size, np.nan, dtype=np.float64)
    sim_w = np.full(selection_positions.size, np.nan, dtype=np.float64)
    dx_um = params.grid.uniform_spacing_m(params.geometry) * 1.0e6
    observation_indices_by_process_row: dict[int, list[int]] = {}
    for observation_index, mapped_row in enumerate(mapped_observation_rows):
        observation_indices_by_process_row.setdefault(int(mapped_row), []).append(
            int(observation_index)
        )
    sampled_unique_rows = np.asarray(
        sorted(row for row in observation_indices_by_process_row if row < n_rows),
        dtype=np.int64,
    )
    sampled_frame_count = int(
        sum(
            len(observation_indices_by_process_row[int(row)])
            for row in sampled_unique_rows
        )
    )

    # Patch 16.5.3 observation-level energy accounting. The source field built
    # at row r is applied over interval [r, r+1), so the power carried into the
    # first interval is zero and is updated after each row's source construction.
    previous_source_power_W = 0.0
    cumulative_absorbed_laser_energy_J = 0.0
    cumulative_existing_top_loss_energy_J = 0.0
    cumulative_convection_loss_energy_J = 0.0
    cumulative_radiation_loss_energy_J = 0.0
    cumulative_boiling_loss_energy_J = 0.0
    cumulative_side_loss_energy_J = 0.0
    cumulative_bottom_loss_energy_J = 0.0
    cumulative_total_boundary_loss_energy_J = 0.0
    cumulative_window_exit_energy_J = 0.0
    cumulative_reset_removed_energy_J = 0.0
    maximum_boiling_loss_power_W = 0.0
    previous_interval_powers_W = {
        "top_loss_power_W": 0.0,
        "existing_top_loss_power_W": 0.0,
        "convection_loss_power_W": 0.0,
        "radiation_loss_power_W": 0.0,
        "boiling_loss_power_W": 0.0,
        "side_loss_power_W": 0.0,
        "bottom_loss_power_W": 0.0,
        "total_boundary_loss_power_W": 0.0,
    }

    for row_index in range(n_rows):
        if row_index > 0:
            # Patch 9.2.4: thermal integration remains process-row driven.
            # Future comparison sampling may occur only at camera observations, but
            # every process interval must still be advanced using the process
            # timestamps rather than a camera/comparison cadence.
            interval_s = float(process_time_s[row_index] - process_time_s[row_index - 1])
            remaining_s = interval_s
            interval_energies_J = {
                "top_loss_power_W": 0.0,
                "existing_top_loss_power_W": 0.0,
                "convection_loss_power_W": 0.0,
                "radiation_loss_power_W": 0.0,
                "boiling_loss_power_W": 0.0,
                "side_loss_power_W": 0.0,
                "bottom_loss_power_W": 0.0,
                "total_boundary_loss_power_W": 0.0,
            }
            while remaining_s > 1.0e-15:
                sub_dt_s = min(float(params.time.dt_s), remaining_s)
                sub_params = (
                    params
                    if abs(sub_dt_s - params.time.dt_s) <= 1.0e-15
                    else _params_with_dt(params, sub_dt_s)
                )
                if params.output.use_numba and NUMBA_AVAILABLE:
                    T_new, boundary_powers = thermal_step_numba(
                        T,
                        q_dot,
                        sub_params,
                        temperature_out_K=T_scratch,
                        return_boundary_powers=True,
                    )
                    T, T_scratch = T_new, T
                else:
                    T_new, boundary_powers = thermal_step_numpy(
                        T, q_dot, sub_params, return_boundary_powers=True
                    )
                    T = T_new
                if temperature_trace_callback is not None:
                    temperature_trace_callback(T, float(sub_dt_s))

                cumulative_absorbed_laser_energy_J += previous_source_power_W * sub_dt_s
                for key in interval_energies_J:
                    power = float(boundary_powers[key])
                    if not np.isfinite(power):
                        raise FloatingPointError(f"Nonfinite boundary power {key} at process row {row_index}.")
                    interval_energies_J[key] += power * sub_dt_s
                boiling_power = float(boundary_powers["boiling_loss_power_W"])
                if boiling_power < 0.0:
                    raise FloatingPointError("Patch 16.5.3 boiling term added energy.")
                power_tol = 1.0e-10 * max(
                    1.0,
                    abs(float(boundary_powers["top_loss_power_W"])),
                    abs(float(boundary_powers["total_boundary_loss_power_W"])),
                )
                if not np.isclose(
                    float(boundary_powers["top_loss_power_W"]),
                    float(boundary_powers["existing_top_loss_power_W"]) + boiling_power,
                    rtol=0.0,
                    atol=power_tol,
                ):
                    raise FloatingPointError("Top-boundary power accounting identity failed.")
                if not np.isclose(
                    float(boundary_powers["total_boundary_loss_power_W"]),
                    float(boundary_powers["top_loss_power_W"])
                    + float(boundary_powers["side_loss_power_W"])
                    + float(boundary_powers["bottom_loss_power_W"]),
                    rtol=0.0,
                    atol=power_tol,
                ):
                    raise FloatingPointError("Total-boundary power accounting identity failed.")
                maximum_boiling_loss_power_W = max(maximum_boiling_loss_power_W, boiling_power)
                remaining_s -= sub_dt_s

            if interval_s > 0.0:
                previous_interval_powers_W = {
                    key: float(value / interval_s) for key, value in interval_energies_J.items()
                }
            cumulative_existing_top_loss_energy_J += interval_energies_J["existing_top_loss_power_W"]
            cumulative_convection_loss_energy_J += interval_energies_J["convection_loss_power_W"]
            cumulative_radiation_loss_energy_J += interval_energies_J["radiation_loss_power_W"]
            cumulative_boiling_loss_energy_J += interval_energies_J["boiling_loss_power_W"]
            cumulative_side_loss_energy_J += interval_energies_J["side_loss_power_W"]
            cumulative_bottom_loss_energy_J += interval_energies_J["bottom_loss_power_W"]
            cumulative_total_boundary_loss_energy_J += interval_energies_J["total_boundary_loss_power_W"]

        T, state, moving_record = apply_moving_window_update(
            temperature_K=T,
            state=state,
            params=params,
            controls=controls,
            laser_x_mm=float(x_mm[row_index]),
            laser_y_mm=float(y_mm[row_index]),
            laser_on=bool(laser_on[row_index]),
        )
        cumulative_window_exit_energy_J += float(moving_record.window_exit_energy_J)
        cumulative_reset_removed_energy_J += float(moving_record.reset_removed_energy_J)
        if moving_window_update_callback is not None:
            moving_window_update_callback(
                {
                    "process_row": int(row_index),
                    "laser_on": bool(laser_on[row_index]),
                    "window_reset_flag": bool(moving_record.window_reset_flag),
                    "window_reset_reason": str(moving_record.window_reset_reason),
                    "window_shift_x_cells": int(moving_record.window_shift_x_cells),
                    "window_shift_y_cells": int(moving_record.window_shift_y_cells),
                    "window_exit_energy_J": float(moving_record.window_exit_energy_J),
                    "reset_removed_energy_J": float(moving_record.reset_removed_energy_J),
                    "scan_segment_status": str(moving_record.scan_segment_status),
                }
            )

        if absorbed_power_treatment is None:
            q_dot, current_source = heat_source_for_row(
                params=params,
                source_template=source_template,
                controls=controls,
                spot_size_um=float(params.input.default_spot_size_um),
                laser_on=bool(laser_on[row_index] and ted_calibration_valid[row_index]),
                accumulated_subcell_x_mm=state.accumulated_subcell_x_mm,
                accumulated_subcell_y_mm=state.accumulated_subcell_y_mm,
                effective_absorptivity=float(ted_eta[row_index]),
                field_builder=field_builder,
                row_index=row_index,
                moving_window_state=state,
                moving_window_update=moving_record,
            )
        else:
            assert treatment_modulation is not None and treatment_alpha_base is not None
            q_dot, current_source = heat_source_for_row(
                params=params,
                source_template=source_template,
                controls=controls,
                spot_size_um=float(params.input.default_spot_size_um),
                laser_on=bool(laser_on[row_index]),
                accumulated_subcell_x_mm=state.accumulated_subcell_x_mm,
                accumulated_subcell_y_mm=state.accumulated_subcell_y_mm,
                effective_absorptivity=float(ted_eta[row_index]),
                alpha_base=treatment_alpha_base,
                ted_modulation=float(treatment_modulation[row_index]),
                field_builder=field_builder,
                row_index=row_index,
                moving_window_state=state,
                moving_window_update=moving_record,
            )

        previous_source_power_W = float(current_source.deposited_power_W)

        observation_indices = observation_indices_by_process_row.get(row_index)
        if observation_indices:
            top_surface_K = np.asarray(T[:, :, -1], dtype=np.float64)
            liquidus_K = float(params.material.T_liquidus_K)
            boiling_K = float(params.material.T_boiling_K)
            liquid_mask = top_surface_K >= liquidus_K
            volume_liquid_mask = np.asarray(T >= liquidus_K, dtype=bool)
            volume_boiling_mask = np.asarray(T >= boiling_K, dtype=bool)
            num_cells_above_liquidus = int(np.count_nonzero(volume_liquid_mask))
            num_cells_above_boiling = int(np.count_nonzero(volume_boiling_mask))
            cell_volume_mm3 = (
                float(params.geometry.Lx_mm) / float(params.grid.Nx)
                * float(params.geometry.Ly_mm) / float(params.grid.Ny)
                * float(params.geometry.Lz_mm) / float(params.grid.Nz)
            )
            volume_above_boiling_mm3 = float(num_cells_above_boiling * cell_volume_mm3)
            fraction_melt_cells_above_boiling = (
                float(num_cells_above_boiling / num_cells_above_liquidus)
                if num_cells_above_liquidus > 0
                else 0.0
            )
            surface_peak_flat_index = int(np.argmax(top_surface_K))
            surface_peak_i, surface_peak_j = np.unravel_index(
                surface_peak_flat_index, top_surface_K.shape
            )
            boundary_values_K = np.concatenate(
                (
                    top_surface_K[0, :],
                    top_surface_K[-1, :],
                    top_surface_K[:, 0],
                    top_surface_K[:, -1],
                )
            )
            boundary_sides = tuple(
                side
                for side, contacted in (
                    ("x_min", np.any(liquid_mask[0, :])),
                    ("x_max", np.any(liquid_mask[-1, :])),
                    ("y_min", np.any(liquid_mask[:, 0])),
                    ("y_max", np.any(liquid_mask[:, -1])),
                )
                if bool(contacted)
            )
            if np.any(liquid_mask):
                liquid_ij = np.argwhere(liquid_mask)
                clearance_cells = int(
                    np.min(
                        np.column_stack(
                            (
                                liquid_ij[:, 0],
                                params.grid.Nx - 1 - liquid_ij[:, 0],
                                liquid_ij[:, 1],
                                params.grid.Ny - 1 - liquid_ij[:, 1],
                            )
                        )
                    )
                )
                liquid_extent_x_cells = int(
                    np.max(liquid_ij[:, 0]) - np.min(liquid_ij[:, 0]) + 1
                )
                liquid_extent_y_cells = int(
                    np.max(liquid_ij[:, 1]) - np.min(liquid_ij[:, 1]) + 1
                )
            else:
                clearance_cells = None
                liquid_extent_x_cells = 0
                liquid_extent_y_cells = 0
            classification = "ZERO_FOOTPRINT"
            h_px = 0.0
            w_px = 0.0
            try:
                h_px, w_px = _compute_top_surface_hw_pixels(
                    temperature_K=T,
                    liquidus_temperature_K=liquidus_K,
                    cell_size_um=dx_um,
                    experimental_pixel_size_um=float(
                        comparison.experimental_pixel_size_um
                    ),
                    geometry_method=comparison.hw_geometry_method,
                )
                classification = (
                    "FINITE_MELT"
                    if np.isfinite(h_px)
                    and np.isfinite(w_px)
                    and (h_px > 0.0 or w_px > 0.0)
                    else "ZERO_FOOTPRINT"
                )
            except UnenclosedLiquidusContourError as exc:
                frame_indices = tuple(
                    int(selected_frame_indices[index])
                    for index in observation_indices
                )
                max_boundary_K = float(np.max(boundary_values_K))
                context = (
                    f"layer={comparison.layer_name}; process_row={row_index}; "
                    f"frame_indices={list(frame_indices)}; boundary_sides={list(boundary_sides)}; "
                    f"max_boundary_temperature_K={max_boundary_K:.6g}; "
                    f"liquidus_temperature_K={liquidus_K:.6g}."
                )
                enriched_error = UnenclosedLiquidusContourError(
                    f"{exc} Context: {context}",
                    layer_name=comparison.layer_name,
                    process_row=row_index,
                    frame_indices=frame_indices,
                    boundary_sides=boundary_sides,
                    max_boundary_temperature_K=max_boundary_K,
                    liquidus_temperature_K=liquidus_K,
                )
                if unenclosed_contour_policy == "raise":
                    raise enriched_error from exc
                unenclosed_contour_failure_count += len(observation_indices)
                classification = "UNENCLOSED"
                h_px = float("nan")
                w_px = float("nan")
                print(
                    "WARNING: H/W extraction undefined because the interpolated "
                    "liquidus contour is not enclosed; recording NaN for the "
                    f"affected production observation(s) and continuing. {enriched_error}"
                )
            if observation_diagnostics is not None:
                source_center_x_mm = (
                    0.5 * float(params.geometry.Lx_mm)
                    + float(state.accumulated_subcell_x_mm)
                )
                source_center_y_mm = (
                    0.5 * float(params.geometry.Ly_mm)
                    + float(state.accumulated_subcell_y_mm)
                )
                dx_mm = float(params.geometry.Lx_mm) / float(params.grid.Nx)
                beam_i = int(np.floor(source_center_x_mm / dx_mm))
                beam_j = int(np.floor(source_center_y_mm / dx_mm))
                component_diagnostics = top_surface_liquid_component_diagnostics(
                    liquid_mask, beam_i=beam_i, beam_j=beam_j
                )
                beam_component_mask = beam_connected_liquid_component_mask(
                    liquid_mask, beam_i=beam_i, beam_j=beam_j
                )
                beam_component_hw = interpolated_component_contour_hw_diagnostic(
                    T[:, :, -1],
                    beam_component_mask,
                    liquidus_temperature_K=liquidus_K,
                    cell_size_um=dx_um,
                    experimental_pixel_size_um=float(
                        comparison.experimental_pixel_size_um
                    ),
                )
                component_diagnostics.update({
                    "beam_component_hw_diagnostic_status": beam_component_hw["status"],
                    "beam_component_hw_diagnostic_available": bool(beam_component_hw["available"]),
                    "beam_component_contour_enclosed": beam_component_hw["contour_enclosed"],
                    "beam_component_boundary_sides": list(beam_component_hw["boundary_sides"]),
                    "beam_component_simulated_H_pixels": beam_component_hw["H_pixels"],
                    "beam_component_simulated_W_pixels": beam_component_hw["W_pixels"],
                    "beam_component_simulated_H_over_W": beam_component_hw["H_over_W"],
                    "beam_component_diagnostic_drives_production_hw": False,
                })
                surface_peak_x_mm = (float(surface_peak_i) + 0.5) * (
                    float(params.geometry.Lx_mm) / float(params.grid.Nx)
                )
                surface_peak_y_mm = (float(surface_peak_j) + 0.5) * (
                    float(params.geometry.Ly_mm) / float(params.grid.Ny)
                )
                peak_delta_x_mm = float(surface_peak_x_mm - source_center_x_mm)
                peak_delta_y_mm = float(surface_peak_y_mm - source_center_y_mm)
                # Patch 16.6 adds diagnostic-only full-field validity channels.
                # They do not alter the thermal state or any pre-existing H/W/T
                # observable; they make the no-negative/nonfinite state gate
                # directly auditable at each required observation.
                finite_temperature_mask = np.isfinite(T)
                nonfinite_temperature_cell_count = int(
                    T.size - np.count_nonzero(finite_temperature_mask)
                )
                negative_temperature_cell_count = int(
                    np.count_nonzero(T[finite_temperature_mask] < 0.0)
                )
                minimum_volume_temperature_K = (
                    float(np.min(T[finite_temperature_mask]))
                    if np.any(finite_temperature_mask)
                    else float("nan")
                )
                surface_peak_K = float(np.max(top_surface_K))
                volume_peak_K = float(np.max(T))
                surface_superheat_K = np.maximum(top_surface_K - boiling_K, 0.0)
                max_surface_superheat_K = float(np.max(surface_superheat_K))
                surface_above_boiling_count = int(np.count_nonzero(top_surface_K >= boiling_K))
                surface_above_boiling_fraction = float(surface_above_boiling_count / top_surface_K.size)
                volume_above_boiling_fraction = float(num_cells_above_boiling / T.size)
                stored_energy_J = compute_stored_energy_relative_to_temperature_J(
                    T, reference_temperature_K=bulk_temperature_K, params=params
                )
                energy_balance_residual_J = float(
                    cumulative_absorbed_laser_energy_J
                    - cumulative_total_boundary_loss_energy_J
                    - cumulative_window_exit_energy_J
                    - cumulative_reset_removed_energy_J
                    - stored_energy_J
                )
                energy_balance_scale_J = max(
                    abs(cumulative_absorbed_laser_energy_J), abs(stored_energy_J), 1.0e-12
                )
                energy_balance_relative_error = float(
                    abs(energy_balance_residual_J) / energy_balance_scale_J
                )
                boiling_fraction = (
                    float(cumulative_boiling_loss_energy_J / cumulative_absorbed_laser_energy_J)
                    if cumulative_absorbed_laser_energy_J > 0.0
                    else None
                )
                for observation_index in observation_indices:
                    observation_record = {
                            "frame_index": int(selected_frame_indices[observation_index]),
                            "mapped_process_row": int(row_index),
                            "classification": classification,
                            "boundary_sides": list(boundary_sides),
                            "contour_to_boundary_clearance_cells": clearance_cells,
                            "contour_to_boundary_clearance_mm": (
                                None
                                if clearance_cells is None
                                else float(clearance_cells * dx_um * 1.0e-3)
                            ),
                            "top_surface_peak_temperature_K": surface_peak_K,
                            "volume_peak_temperature_K": volume_peak_K,
                            "T_peak_surface_K": surface_peak_K,
                            "T_peak_volume_K": volume_peak_K,
                            "T_min_volume_K": minimum_volume_temperature_K,
                            "nonfinite_temperature_cell_count": nonfinite_temperature_cell_count,
                            "negative_temperature_cell_count": negative_temperature_cell_count,
                            "T_peak_surface_over_T_liquidus": float(surface_peak_K / liquidus_K),
                            "T_peak_surface_over_T_boiling": float(surface_peak_K / boiling_K),
                            "max_boundary_temperature_K": float(np.max(boundary_values_K)),
                            "liquidus_temperature_K": liquidus_K,
                            "boundary_liquidus_margin_K": float(
                                np.max(boundary_values_K) - liquidus_K
                            ),
                            "window_dimensions_cells": {
                                "Nx": int(params.grid.Nx),
                                "Ny": int(params.grid.Ny),
                                "Nz": int(params.grid.Nz),
                            },
                            "window_dimensions_mm": {
                                "Lx_mm": float(params.geometry.Lx_mm),
                                "Ly_mm": float(params.geometry.Ly_mm),
                                "Lz_mm": float(params.geometry.Lz_mm),
                            },
                            "cell_spacing_um": float(dx_um),
                            "equivalent_liquid_footprint_extent_cells": {
                                "x": int(liquid_extent_x_cells),
                                "y": int(liquid_extent_y_cells),
                                "major": int(max(liquid_extent_x_cells, liquid_extent_y_cells)),
                                "minor": int(min(liquid_extent_x_cells, liquid_extent_y_cells)),
                            },
                            "predicted_H_tail_available": False,
                            "boiling_temperature_K": boiling_K,
                            "represented_liquid_cell_count": int(np.count_nonzero(liquid_mask)),
                            **component_diagnostics,
                            "hw_geometry_extraction_method": str(comparison.hw_geometry_method),
                            "simulation_pixel_scale_um": float(dx_um),
                            "experimental_pixel_scale_um": float(comparison.experimental_pixel_size_um),
                            "simulation_to_experimental_pixel_scale": float(
                                dx_um / float(comparison.experimental_pixel_size_um)
                            ),
                            "selected_frame_index": int(selected_frame_indices[observation_index]),
                            "selected_process_row": int(row_index),
                            "num_cells_above_liquidus": num_cells_above_liquidus,
                            "num_cells_above_boiling": num_cells_above_boiling,
                            "volume_above_boiling_mm3": volume_above_boiling_mm3,
                            "volume_above_boiling": volume_above_boiling_mm3,
                            "fraction_of_melt_cells_above_boiling": fraction_melt_cells_above_boiling,
                            "max_surface_superheat_K": max_surface_superheat_K,
                            "num_surface_cells_above_boiling": surface_above_boiling_count,
                            "fraction_surface_cells_above_boiling": surface_above_boiling_fraction,
                            "fraction_volume_cells_above_boiling": volume_above_boiling_fraction,
                            "boiling_loss_power_previous_interval_W": float(previous_interval_powers_W["boiling_loss_power_W"]),
                            "maximum_boiling_loss_power_W": float(maximum_boiling_loss_power_W),
                            "existing_top_loss_power_previous_interval_W": float(previous_interval_powers_W["existing_top_loss_power_W"]),
                            "convection_loss_power_previous_interval_W": float(previous_interval_powers_W["convection_loss_power_W"]),
                            "radiation_loss_power_previous_interval_W": float(previous_interval_powers_W["radiation_loss_power_W"]),
                            "side_loss_power_previous_interval_W": float(previous_interval_powers_W["side_loss_power_W"]),
                            "bottom_loss_power_previous_interval_W": float(previous_interval_powers_W["bottom_loss_power_W"]),
                            "total_boundary_loss_power_previous_interval_W": float(previous_interval_powers_W["total_boundary_loss_power_W"]),
                            "cumulative_absorbed_laser_energy_J": float(cumulative_absorbed_laser_energy_J),
                            "cumulative_boiling_loss_energy_J": float(cumulative_boiling_loss_energy_J),
                            "boiling_removed_fraction_of_absorbed": boiling_fraction,
                            "cumulative_existing_top_loss_energy_J": float(cumulative_existing_top_loss_energy_J),
                            "cumulative_top_loss_energy_J": float(cumulative_existing_top_loss_energy_J + cumulative_boiling_loss_energy_J),
                            "cumulative_convection_loss_energy_J": float(cumulative_convection_loss_energy_J),
                            "cumulative_radiation_loss_energy_J": float(cumulative_radiation_loss_energy_J),
                            "cumulative_side_loss_energy_J": float(cumulative_side_loss_energy_J),
                            "cumulative_bottom_loss_energy_J": float(cumulative_bottom_loss_energy_J),
                            "cumulative_total_boundary_loss_energy_J": float(cumulative_total_boundary_loss_energy_J),
                            "cumulative_window_exit_energy_J": float(cumulative_window_exit_energy_J),
                            "cumulative_reset_removed_energy_J": float(cumulative_reset_removed_energy_J),
                            "stored_energy_relative_to_bulk_J": float(stored_energy_J),
                            "energy_balance_residual_J": energy_balance_residual_J,
                            "energy_balance_relative_error": energy_balance_relative_error,
                            "source_center_local_x_mm": source_center_x_mm,
                            "source_center_local_y_mm": source_center_y_mm,
                            "peak_surface_local_x_mm": surface_peak_x_mm,
                            "peak_surface_local_y_mm": surface_peak_y_mm,
                            "peak_surface_delta_x_from_laser_mm": peak_delta_x_mm,
                            "peak_surface_delta_y_from_laser_mm": peak_delta_y_mm,
                            "peak_surface_radial_distance_from_laser_mm": float(
                                np.hypot(peak_delta_x_mm, peak_delta_y_mm)
                            ),
                            "peak_temperature_time_relative_to_observation_s": None,
                            "peak_temperature_time_tracking_available": False,
                            "time_above_liquidus_s": None,
                            "estimated_time_above_boiling_s": None,
                            "peak_heating_rate_K_s": None,
                            "peak_cooling_rate_K_s": None,
                            "thermal_history_rate_metrics_available": False,
                            "moving_window_reset_flag": bool(moving_record.window_reset_flag),
                            "moving_window_reset_reason": str(moving_record.window_reset_reason),
                            "moving_window_shift_x_cells": int(moving_record.window_shift_x_cells),
                            "moving_window_shift_y_cells": int(moving_record.window_shift_y_cells),
                        }
                    observation_diagnostics.append(observation_record)
                    if observation_capture_callback is not None:
                        observation_capture_callback(dict(observation_record))
            sim_h[observation_indices] = h_px
            sim_w[observation_indices] = w_px

        progress_every = int(comparison.progress_every_rows)
        if progress_every > 0 and (
            (row_index + 1) % progress_every == 0 or row_index + 1 == n_rows
        ):
            print(
                f"  Processed {row_index + 1:,} / {n_rows:,} "
                f"{comparison.layer_name} rows"
            )

    metadata: dict[str, float | int | str] = {
        "rows_simulated": int(n_rows),
        "camera_observation_frames_total": int(observation_table.n_observations),
        "camera_observation_frames_selected": int(selection_positions.size),
        "camera_observation_frames_sampled": int(sampled_frame_count),
        "camera_observation_unique_process_rows_sampled": int(sampled_unique_rows.size),
        "camera_observation_duplicate_frames_on_sampled_rows": int(
            sampled_frame_count - sampled_unique_rows.size
        ),
        "hw_sampling_cadence": CAMERA_OBSERVATION_SAMPLING_CADENCE,
        "layer_name": comparison.layer_name,
        "sample_frequency_hz": float(
            (process.h5_metadata or {}).get(
                "effective_process_rate_hz", process.h5_sample_frequency_hz
            )
        ),
        "configured_comparison_sample_frequency_hz": float(comparison.sample_frequency_hz),
        "process_integration_time_source": str(
            (process.h5_metadata or {}).get("process_time_source", "process.time_s")
        ),
        "drive_threshold": float(drive_threshold),
        "ted_global_off_baseline": float(process.ted_global_off_baseline),
        "simulation_cell_size_um": float(dx_um),
        "experimental_pixel_size_um": float(comparison.experimental_pixel_size_um),
        "liquidus_temperature_K": float(params.material.T_liquidus_K),
        "hw_geometry_method": str(comparison.hw_geometry_method),
        "hw_extraction_unenclosed_contour_failure_count": int(
            unenclosed_contour_failure_count
        ),
        "hw_extraction_unenclosed_contour_policy": str(unenclosed_contour_policy),
        "bbox_algorithm": _bbox_algorithm_description(
            comparison.hw_geometry_method
        ),
        "liquidus_contour_interpolation": (
            "linear_between_neighboring_top_surface_cell_centers"
            if comparison.hw_geometry_method == "interpolated_liquidus_contour"
            else "not_applicable_cell_footprint_reference"
        ),
        "difference_definition": "simulated - experimental",
        "synchronization_mapping_dataset": str(
            layer_input.synchronization_mapping_dataset or "not_provided"
        ),
        "synchronization_process_time_dataset": str(
            layer_input.synchronization_process_time_dataset or "not_provided"
        ),
        "synchronization_method": str(
            layer_input.synchronization_method or "not_provided"
        ),
        "synchronization_version": str(
            layer_input.synchronization_version or "not_provided"
        ),
    }
    if absorbed_power_treatment is None:
        metadata.update(
            {
                "absorbed_power_architecture": "legacy_calibration_factor_times_absolute_TED_absorptivity",
                "source_enable_policy": "laser_on_and_TED_calibration_valid",
            }
        )
    else:
        assert treatment_modulation is not None and treatment_alpha_base is not None
        powered_modulation = treatment_modulation[np.asarray(laser_on, dtype=bool)]
        metadata.update(
            {
                "absorbed_power_architecture": "P_laser_times_alpha_base_times_m_TED",
                "absorbed_power_treatment_identifier": str(
                    absorbed_power_treatment.identifier
                ),
                "alpha_base": float(treatment_alpha_base),
                "source_enable_policy": "physical_laser_on_only",
                "ted_modulation_powered_min": float(np.min(powered_modulation))
                if powered_modulation.size
                else float("nan"),
                "ted_modulation_powered_max": float(np.max(powered_modulation))
                if powered_modulation.size
                else float("nan"),
                "ted_modulation_powered_mean": float(np.mean(powered_modulation))
                if powered_modulation.size
                else float("nan"),
            }
        )
    return sim_h, sim_w, metadata


def _simulate_layer_melt_pool_hw(
    input_path: Path,
    params: SimulationParameters,
    max_rows: int | None = None,
    observation_frame_indices: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, dict[str, float | int | str]]:
    """Load one HDF5 layer, then run the shared in-memory thermal/HW core."""

    layer_input = load_layer_h5_process_data(
        path=input_path,
        layer_name=params.comparison.layer_name,
        params=params,
        require_camera_sync=True,
    )
    return _simulate_preloaded_layer_melt_pool_hw(
        layer_input=layer_input,
        params=params,
        max_rows=max_rows,
        observation_frame_indices=observation_frame_indices,
    )


def run_in_memory_layer_melt_pool_comparison(
    params: SimulationParameters,
    preloaded: PreloadedLayerMeltPoolComparison,
    max_rows: int | None = None,
    *,
    observation_frame_indices: np.ndarray | None = None,
    workspace: InMemoryCalibrationTrialWorkspace | None = None,
    unenclosed_contour_policy: str = "raise",
    absorbed_power_treatment: AbsorbedPowerTreatment | None = None,
    capture_observation_diagnostics: bool = False,
    execution_interfaces: InMemoryExecutionInterfaces | None = None,
) -> InMemoryMeltPoolComparisonResult:
    """Evaluate frame-rate H/W entirely in memory for Patch 10.3.2.

    No HDF5 output/copy, verification pass, plots, or reproducibility/release
    metadata are produced. The supplied ``preloaded`` object can be reused for
    every source-parameter trial whose input/TED preprocessing definition is
    unchanged. Patch 10.3.3 optionally supplies a reusable trial workspace so
    large thermal/source allocations and one-time FVM compilation are not
    repeated between sequential calibration evaluations.
    """

    params.validate()
    if not params.comparison.enabled:
        raise ValueError("Melt-pool comparison is disabled in parameters.py.")
    _validate_preloaded_layer_melt_pool_comparison(preloaded, params)
    observation_table = preloaded.layer_input.observation_table
    if observation_table is None:
        raise ValueError(
            "Timestamp-based comparison requires a valid camera observation table."
        )

    selection_positions = _selected_observation_positions(
        np.asarray(observation_table.frame_index, dtype=np.int64),
        observation_frame_indices,
    )
    observation_diagnostics: list[dict[str, Any]] | None = (
        [] if capture_observation_diagnostics else None
    )
    sim_h, sim_w, metadata = _simulate_preloaded_layer_melt_pool_hw(
        layer_input=preloaded.layer_input,
        params=params,
        max_rows=max_rows,
        observation_frame_indices=observation_frame_indices,
        workspace=workspace,
        unenclosed_contour_policy=unenclosed_contour_policy,
        absorbed_power_treatment=absorbed_power_treatment,
        observation_diagnostics=observation_diagnostics,
        execution_interfaces=execution_interfaces,
    )
    frame_index = np.asarray(
        observation_table.frame_index[selection_positions], dtype=np.int64
    )
    mapped_process_row = np.asarray(
        observation_table.mapped_process_row[selection_positions], dtype=np.int64
    )
    experimental_h = np.asarray(
        observation_table.experimental_h_pixels[selection_positions],
        dtype=np.float64,
    )
    experimental_w = np.asarray(
        observation_table.experimental_w_pixels[selection_positions],
        dtype=np.float64,
    )
    simulated_h = np.asarray(sim_h, dtype=np.float64)
    simulated_w = np.asarray(sim_w, dtype=np.float64)

    return InMemoryMeltPoolComparisonResult(
        frame_index=_readonly_array(frame_index, dtype=np.int64),
        mapped_process_row=_readonly_array(mapped_process_row, dtype=np.int64),
        experimental_H_pixels=_readonly_array(experimental_h, dtype=np.float64),
        experimental_W_pixels=_readonly_array(experimental_w, dtype=np.float64),
        simulated_H_pixels=_readonly_array(simulated_h, dtype=np.float64),
        simulated_W_pixels=_readonly_array(simulated_w, dtype=np.float64),
        H_difference_pixels=_readonly_array(
            simulated_h - experimental_h, dtype=np.float64
        ),
        W_difference_pixels=_readonly_array(
            simulated_w - experimental_w, dtype=np.float64
        ),
        metadata=dict(metadata),
        observation_diagnostics=tuple(observation_diagnostics or ()),
    )


def _comparison_dataset_creation_kwargs(
    dataset: h5py.Dataset,
    new_shape: tuple[int, ...],
) -> dict[str, Any]:
    """Preserve legal HDF5 creation properties when replacing an enlarged dataset."""
    kwargs: dict[str, Any] = {"dtype": dataset.dtype}
    if dataset.chunks is not None:
        kwargs["chunks"] = tuple(
            min(int(chunk), int(length))
            for chunk, length in zip(dataset.chunks, new_shape)
        )
    if dataset.compression is not None:
        kwargs["compression"] = dataset.compression
        if dataset.compression_opts is not None:
            kwargs["compression_opts"] = dataset.compression_opts
    if dataset.shuffle:
        kwargs["shuffle"] = True
    if dataset.fletcher32:
        kwargs["fletcher32"] = True
    if dataset.scaleoffset is not None:
        kwargs["scaleoffset"] = dataset.scaleoffset
    if dataset.fillvalue is not None:
        kwargs["fillvalue"] = dataset.fillvalue
    return kwargs


def _write_layer_melt_pool_comparison_h5(
    input_path: Path,
    output_path: Path,
    layer_name: str,
    sim_h: np.ndarray,
    sim_w: np.ndarray,
    metadata: dict[str, float | int | str],
    params: SimulationParameters,
    observation_frame_indices: np.ndarray | None = None,
) -> Path:
    """Write canonical frame-rate comparison data plus compatibility channels.

    Patch 9.2.6 makes ``<layer>/comparison`` the canonical comparison output.
    It contains one record per synchronization-valid camera frame. The existing
    process-row appended channels are retained only for backward compatibility;
    they remain NaN away from rows that have at least one camera observation.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()

    with h5py.File(input_path, "r") as src, h5py.File(output_path, "w") as dst:
        for key, value in src.attrs.items():
            dst.attrs[key] = value
        if "part boundaries" in src:
            src.copy("part boundaries", dst)
        src.copy(layer_name, dst)

        group = dst[layer_name]
        old_names_ds = group["names"]
        old_data_ds = group["data"]
        old_names = decode_h5_names(old_names_ds[:])
        old_data = np.asarray(old_data_ds[:])
        n_samples = int(old_data.shape[1])

        if "gige_time" not in group:
            raise KeyError("Comparison output requires gige_time.")
        if "sync/gige_image_to_data_index" not in group:
            raise KeyError(
                "Comparison output requires sync/gige_image_to_data_index."
            )

        gige_time_s = np.asarray(group["gige_time"][:], dtype=np.float64)
        mapping = np.asarray(
            group["sync/gige_image_to_data_index"][:], dtype=np.int64
        )
        if gige_time_s.shape != mapping.shape:
            raise ValueError(
                "gige_time and sync/gige_image_to_data_index must have equal length."
            )

        valid_frame_mask = (mapping >= 0) & (mapping < n_samples)
        available_frame_index = np.flatnonzero(valid_frame_mask).astype(
            np.int64, copy=False
        )
        selection_positions = _selected_observation_positions(
            available_frame_index, observation_frame_indices
        )
        frame_index = available_frame_index[selection_positions]
        mapped_process_row = mapping[frame_index].astype(np.int64, copy=False)
        if sim_h.size != frame_index.size or sim_w.size != frame_index.size:
            raise ValueError(
                "Simulation H/W length must match the valid camera observation count."
            )

        experimental_h_process = old_data[old_names.index("H"), :].astype(
            np.float64, copy=False
        )
        experimental_w_process = old_data[old_names.index("W"), :].astype(
            np.float64, copy=False
        )
        experimental_h = experimental_h_process[mapped_process_row]
        experimental_w = experimental_w_process[mapped_process_row]
        h_difference = np.asarray(sim_h, dtype=np.float64) - experimental_h
        w_difference = np.asarray(sim_w, dtype=np.float64) - experimental_w

        if _COMPARISON_GROUP_NAME in group:
            del group[_COMPARISON_GROUP_NAME]
        comparison_group = group.create_group(_COMPARISON_GROUP_NAME)
        comparison_values = {
            "frame_index": frame_index,
            "gige_time_s": gige_time_s[frame_index],
            "mapped_process_row": mapped_process_row,
            "experimental_H_pixels": experimental_h,
            "experimental_W_pixels": experimental_w,
            "simulated_H_pixels": np.asarray(sim_h, dtype=np.float64),
            "simulated_W_pixels": np.asarray(sim_w, dtype=np.float64),
            "H_difference_pixels": h_difference,
            "W_difference_pixels": w_difference,
        }
        for field_name in _COMPARISON_FRAME_FIELDS:
            dataset = comparison_group.create_dataset(
                field_name, data=comparison_values[field_name]
            )
            if field_name == "gige_time_s":
                dataset.attrs["units"] = "s"
            elif field_name.endswith("_pixels"):
                dataset.attrs["units"] = "pixels"
            else:
                dataset.attrs["units"] = "1"

        comparison_group.attrs["schema"] = "lpbf_melt_pool_hw_frame_comparison"
        comparison_group.attrs["schema_version"] = "9.2.6"
        comparison_group.attrs["difference_definition"] = "simulated - experimental"
        comparison_group.attrs["observation_count"] = int(frame_index.size)
        comparison_group.attrs["source_mapping_dataset"] = (
            "sync/gige_image_to_data_index"
        )
        process_row_observation_mask = np.zeros(n_samples, dtype=bool)
        if mapped_process_row.size:
            process_row_observation_mask[np.unique(mapped_process_row)] = True
        mask_dataset = comparison_group.create_dataset(
            "process_row_observation_mask", data=process_row_observation_mask
        )
        mask_dataset.attrs["units"] = "1"
        mask_dataset.attrs["description"] = (
            "True where at least one valid camera observation maps to the process row"
        )
        for key, value in metadata.items():
            comparison_group.attrs[key] = value

        write_reproducibility_metadata(
            dst,
            build_reproducibility_metadata(
                params,
                comparison_metadata=metadata,
                comparison_frame_count=int(frame_index.size),
            ),
        )

        # Backward-compatible process-row projection retained during the 9.2
        # transition. Multiple frames on one row must share the same simulated
        # thermal state, so their values must be identical before projection.
        sim_h_by_process_row = np.full(n_samples, np.nan, dtype=np.float64)
        sim_w_by_process_row = np.full(n_samples, np.nan, dtype=np.float64)
        for mapped_row in np.unique(mapped_process_row):
            observation_indices = np.flatnonzero(mapped_process_row == mapped_row)
            finite_indices = observation_indices[
                np.isfinite(sim_h[observation_indices])
                & np.isfinite(sim_w[observation_indices])
            ]
            if finite_indices.size == 0:
                continue
            h_values = sim_h[finite_indices]
            w_values = sim_w[finite_indices]
            if not np.all(h_values == h_values[0]) or not np.all(w_values == w_values[0]):
                raise ValueError(
                    "Duplicate camera frames mapped to one process row received "
                    "inconsistent simulated H/W values."
                )
            sim_h_by_process_row[int(mapped_row)] = float(h_values[0])
            sim_w_by_process_row[int(mapped_row)] = float(w_values[0])

        compatibility_h_difference = sim_h_by_process_row - experimental_h_process
        compatibility_w_difference = sim_w_by_process_row - experimental_w_process
        new_data = np.vstack(
            (
                old_data,
                sim_h_by_process_row,
                sim_w_by_process_row,
                compatibility_h_difference,
                compatibility_w_difference,
            )
        )
        new_names = old_names + list(_COMPARISON_APPENDED_NAMES)

        data_attrs = dict(old_data_ds.attrs)
        names_attrs = dict(old_names_ds.attrs)
        data_kwargs = _comparison_dataset_creation_kwargs(old_data_ds, new_data.shape)
        names_dtype = old_names_ds.dtype

        del group["data"]
        del group["names"]
        new_data_ds = group.create_dataset("data", data=new_data, **data_kwargs)
        new_names_ds = group.create_dataset(
            "names",
            shape=(len(new_names),),
            dtype=names_dtype,
        )
        new_names_ds[:] = np.asarray(new_names, dtype=object)

        for key, value in data_attrs.items():
            new_data_ds.attrs[key] = value
        for key, value in names_attrs.items():
            new_names_ds.attrs[key] = value
        for key, value in metadata.items():
            new_data_ds.attrs[f"simulation_{key}"] = value

        new_data_ds.attrs["simulation_H_channel"] = _COMPARISON_APPENDED_NAMES[0]
        new_data_ds.attrs["simulation_W_channel"] = _COMPARISON_APPENDED_NAMES[1]
        new_data_ds.attrs["simulation_H_difference_channel"] = _COMPARISON_APPENDED_NAMES[2]
        new_data_ds.attrs["simulation_W_difference_channel"] = _COMPARISON_APPENDED_NAMES[3]
        new_data_ds.attrs["simulation_comparison_group"] = _COMPARISON_GROUP_NAME
        new_data_ds.attrs["simulation_comparison_schema_version"] = "9.2.6"
        new_data_ds.attrs["simulation_process_row_channels_role"] = (
            "backward_compatibility_projection"
        )

    return output_path


def _verify_layer_melt_pool_comparison_h5(
    output_path: Path,
    source_path: Path | None = None,
    layer_name: str = "layer53",
    rows_expected_finite: int | None = None,
) -> dict[str, object]:
    """Validate canonical frame comparison data and compatibility channels."""
    with h5py.File(output_path, "r") as h5_file:
        root_keys = list(h5_file.keys())
        if layer_name not in root_keys:
            raise AssertionError(f"Output is missing {layer_name!r}: {root_keys}")
        other_layers = [
            key for key in root_keys if key.startswith("layer") and key != layer_name
        ]
        if other_layers:
            raise AssertionError(f"Unexpected layers in comparison output: {other_layers}")

        group = h5_file[layer_name]
        names = decode_h5_names(group["names"][:])
        data = group["data"]
        if data.shape[0] != len(names):
            raise AssertionError("Comparison data channel count does not match names length.")
        if tuple(names[-4:]) != _COMPARISON_APPENDED_NAMES:
            raise AssertionError(f"Unexpected appended channels: {names[-4:]}")

        if _COMPARISON_GROUP_NAME not in group:
            raise AssertionError(
                f"Output is missing canonical {layer_name}/{_COMPARISON_GROUP_NAME} group."
            )
        comparison_group = group[_COMPARISON_GROUP_NAME]
        missing_fields = [
            field for field in _COMPARISON_FRAME_FIELDS if field not in comparison_group
        ]
        if missing_fields:
            raise AssertionError(
                "Canonical comparison group is missing fields: "
                + ", ".join(missing_fields)
            )

        frame_lengths = {
            field: int(comparison_group[field].shape[0])
            for field in _COMPARISON_FRAME_FIELDS
        }
        if len(set(frame_lengths.values())) != 1:
            raise AssertionError(
                f"Canonical comparison fields have inconsistent lengths: {frame_lengths}"
            )
        observation_count = next(iter(frame_lengths.values()), 0)
        if int(comparison_group.attrs.get("observation_count", -1)) != observation_count:
            raise AssertionError("Canonical comparison observation_count metadata is wrong.")

        frame_index = np.asarray(comparison_group["frame_index"][:], dtype=np.int64)
        gige_time_s = np.asarray(comparison_group["gige_time_s"][:], dtype=np.float64)
        mapped_process_row = np.asarray(
            comparison_group["mapped_process_row"][:], dtype=np.int64
        )
        experimental_h_frame = np.asarray(
            comparison_group["experimental_H_pixels"][:], dtype=np.float64
        )
        experimental_w_frame = np.asarray(
            comparison_group["experimental_W_pixels"][:], dtype=np.float64
        )
        simulated_h_frame = np.asarray(
            comparison_group["simulated_H_pixels"][:], dtype=np.float64
        )
        simulated_w_frame = np.asarray(
            comparison_group["simulated_W_pixels"][:], dtype=np.float64
        )
        h_diff_frame = np.asarray(
            comparison_group["H_difference_pixels"][:], dtype=np.float64
        )
        w_diff_frame = np.asarray(
            comparison_group["W_difference_pixels"][:], dtype=np.float64
        )

        if frame_index.size and np.any(np.diff(frame_index) <= 0):
            raise AssertionError("Canonical comparison frame_index must be increasing.")
        if not np.array_equal(
            np.isnan(h_diff_frame), np.isnan(simulated_h_frame - experimental_h_frame)
        ) or not np.allclose(
            h_diff_frame, simulated_h_frame - experimental_h_frame, equal_nan=True
        ):
            raise AssertionError("Canonical H differences are inconsistent.")
        if not np.array_equal(
            np.isnan(w_diff_frame), np.isnan(simulated_w_frame - experimental_w_frame)
        ) or not np.allclose(
            w_diff_frame, simulated_w_frame - experimental_w_frame, equal_nan=True
        ):
            raise AssertionError("Canonical W differences are inconsistent.")

        if "gige_time" not in group or "sync/gige_image_to_data_index" not in group:
            raise AssertionError("Canonical comparison requires copied camera synchronization.")
        source_gige_time = np.asarray(group["gige_time"][:], dtype=np.float64)
        source_mapping = np.asarray(
            group["sync/gige_image_to_data_index"][:], dtype=np.int64
        )
        if not np.array_equal(gige_time_s, source_gige_time[frame_index]):
            raise AssertionError("Canonical camera timestamps do not match source frames.")
        if not np.array_equal(mapped_process_row, source_mapping[frame_index]):
            raise AssertionError("Canonical mapped process rows do not match source mapping.")
        if "process_row_observation_mask" not in comparison_group:
            raise AssertionError("Canonical comparison is missing process-row observation mask.")
        process_row_observation_mask = np.asarray(
            comparison_group["process_row_observation_mask"][:], dtype=bool
        )
        if process_row_observation_mask.shape != (data.shape[1],):
            raise AssertionError("Process-row observation mask has incorrect length.")
        expected_observation_mask = np.zeros(data.shape[1], dtype=bool)
        if mapped_process_row.size:
            expected_observation_mask[np.unique(mapped_process_row)] = True
        if not np.array_equal(process_row_observation_mask, expected_observation_mask):
            raise AssertionError("Process-row observation mask does not match frame mapping.")

        process_experimental_h = np.asarray(data[names.index("H"), :], dtype=np.float64)
        process_experimental_w = np.asarray(data[names.index("W"), :], dtype=np.float64)
        if not np.array_equal(
            experimental_h_frame,
            process_experimental_h[mapped_process_row],
            equal_nan=True,
        ):
            raise AssertionError("Canonical experimental H does not match mapped process rows.")
        if not np.array_equal(
            experimental_w_frame,
            process_experimental_w[mapped_process_row],
            equal_nan=True,
        ):
            raise AssertionError("Canonical experimental W does not match mapped process rows.")

        simulated = np.asarray(data[-4:-2, :], dtype=np.float64)
        sampling_cadence = str(
            data.attrs.get("simulation_hw_sampling_cadence", "process_rows")
        )
        if sampling_cadence == "camera_observation_mapped_process_rows":
            rows_simulated = int(data.attrs["simulation_rows_simulated"])
            mapped = mapped_process_row[
                (mapped_process_row >= 0) & (mapped_process_row < rows_simulated)
            ]
            expected_finite_mask = np.zeros(data.shape[1], dtype=bool)
            if mapped.size:
                expected_finite_mask[np.unique(mapped)] = True
            actual_finite_mask = np.all(np.isfinite(simulated), axis=0)
            if not np.array_equal(actual_finite_mask, expected_finite_mask):
                raise AssertionError(
                    "Compatibility H/W finite-row mask does not match mapped camera rows."
                )
        else:
            finite_rows = (
                data.shape[1] if rows_expected_finite is None else int(rows_expected_finite)
            )
            if finite_rows > 0 and not np.all(np.isfinite(simulated[:, :finite_rows])):
                raise AssertionError(
                    "Simulated H/W contains non-finite values in simulated rows."
                )

        summary = {
            "root_keys": root_keys,
            "layer_name": layer_name,
            "data_shape": tuple(int(v) for v in data.shape),
            "appended_names": tuple(names[-4:]),
            "rows": int(data.shape[1]),
            "comparison_fields": _COMPARISON_FRAME_FIELDS,
            "comparison_observations": int(observation_count),
        }

    if source_path is not None:
        with h5py.File(source_path, "r") as src, h5py.File(output_path, "r") as dst:
            src_group = src[layer_name]
            dst_group = dst[layer_name]
            original_channel_count = int(src_group["data"].shape[0])
            if not np.array_equal(
                np.asarray(src_group["data"][:]),
                np.asarray(dst_group["data"][:original_channel_count, :]),
                equal_nan=True,
            ):
                raise AssertionError("Original layer data channels changed during copy.")
            for key in src_group.keys():
                if key in {"data", "names"}:
                    continue
                if key not in dst_group:
                    raise AssertionError(f"Copied layer is missing {key!r}.")
                src_obj = src_group[key]
                dst_obj = dst_group[key]
                if isinstance(src_obj, h5py.Dataset):
                    src_values = np.asarray(src_obj[:])
                    dst_values = np.asarray(dst_obj[:])
                    if (
                        np.issubdtype(src_values.dtype, np.floating)
                        or np.issubdtype(src_values.dtype, np.complexfloating)
                    ):
                        equal = np.array_equal(src_values, dst_values, equal_nan=True)
                    else:
                        equal = np.array_equal(src_values, dst_values)
                    if not equal:
                        raise AssertionError(f"Copied dataset {key!r} changed.")

    return summary


def run_layer_melt_pool_comparison(
    params: SimulationParameters | None = None,
    max_rows: int | None = None,
    *,
    observation_frame_indices: np.ndarray | None = None,
) -> Path:
    """Run the configured independent-layer H/W comparison and return its HDF5 path."""
    if params is None:
        params = get_params()
    else:
        params.validate()
    if not params.comparison.enabled:
        raise ValueError("Melt-pool comparison is disabled in parameters.py.")

    input_path = resolve_h5_path(params)
    output_path = Path(params.output.output_directory) / params.comparison.output_h5_filename
    print("Running experimental/simulated melt-pool H/W comparison.")
    print(f"  Input:  {input_path}")
    print(f"  Layer:  {params.comparison.layer_name}")
    print(f"  Output: {output_path}")

    sim_h, sim_w, metadata = _simulate_layer_melt_pool_hw(
        input_path=input_path,
        params=params,
        max_rows=max_rows,
        observation_frame_indices=observation_frame_indices,
    )
    _write_layer_melt_pool_comparison_h5(
        input_path=input_path,
        output_path=output_path,
        layer_name=params.comparison.layer_name,
        sim_h=sim_h,
        sim_w=sim_w,
        metadata=metadata,
        params=params,
        observation_frame_indices=observation_frame_indices,
    )
    _verify_layer_melt_pool_comparison_h5(
        output_path=output_path,
        source_path=input_path,
        layer_name=params.comparison.layer_name,
    )
    print("Melt-pool H/W comparison complete.")
    print(f"  HDF5 file: {output_path}")
    return output_path
