"""Patch 19.7.4 computation-only current-physics execution boundary.

This module owns the expensive numerical simulation path only.  It composes the
accepted Patch 18 directional transport and Patch 19 deposition-depth source
through the exact accepted comparison loop, but it does not calculate a calibration
objective, render human-readable reports, or create manifests/archives.

Numerical diagnostic payloads emitted by the accepted solver are returned as
raw execution telemetry for downstream diagnostic interpretation.  The module
performs no file writes and imports no reporting/provenance packaging code.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Callable

import numpy as np

# The supported adapter and accepted orchestration both use canonical package
# imports; Patch 20.11 installs no root-module aliases or process-global shims.
from lpbf.model import comparison as supported_comparison

from lpbf.model.current_configuration import (
    CURRENT_FIXED_CONFIGURATION,
    CurrentConfigurationError,
    CurrentPhysicsParameters,
    build_current_trial_parameters,
    validate_current_physics_parameters,
)
from lpbf.model.deposition_depth_source import (
    DepositionDepthFieldBuilder,
    DepositionDepthKernelDiagnostics,
    build_centered_heat_source_for_row_with_deposition_depth,
)
from lpbf.model.directional_runtime import (
    DirectionalProcessStepDiagnostics,
    explicit_fvm_step_for_process_row,
)
from lpbf.model.directional_transport import (
    PRODUCTION_DAQ_DT_S,
    directional_explicit_stability_record,
)
from lpbf.model.execution_interfaces import (
    InMemoryExecutionInterfaces,
    MovingWindowUpdateCallback,
    ObservationCaptureCallback,
    TemperatureTraceCallback,
)


class CurrentPhysicsExecutionError(RuntimeError):
    """Raised when the current computation-only execution path fails closed."""


@dataclass(frozen=True)
class CurrentPhysicsProcessCondition:
    """Prepared immutable inputs for one coupon/process condition."""

    base_params: Any
    preloaded: Any


@dataclass(frozen=True)
class CurrentPhysicsExecutionResult:
    """Raw computation result before diagnostic/objective/reporting layers."""

    comparison_result: Any
    physics_parameters: CurrentPhysicsParameters
    execution_usage: dict[str, Any]
    directional_stability: dict[str, Any]


@dataclass
class CurrentPhysicsExecutionUsage:
    source_build_count: int = 0
    powered_source_build_count: int = 0
    maximum_abs_source_power_error_W: float = 0.0
    maximum_abs_source_power_relative_error: float = 0.0
    minimum_finite_depth_normalization: float | None = None
    maximum_finite_depth_normalization: float | None = None
    directional_step_count: int = 0
    directional_tensor_active_step_count: int = 0
    isotropic_fallback_step_count: int = 0
    isotropic_neutral_step_count: int = 0
    directional_gate_accepted_step_count: int = 0
    directional_liquid_available_step_count: int = 0
    directional_active_face_step_count: int = 0
    cumulative_directional_active_x_face_count: int = 0
    cumulative_directional_active_y_face_count: int = 0
    maximum_directional_active_liquid_cell_count: int = 0
    directional_gate_accepted_time_s: float = 0.0
    directional_active_face_time_s: float = 0.0
    isotropic_fallback_time_s: float = 0.0
    moving_window_update_count: int = 0
    moving_window_shift_event_count: int = 0
    moving_window_reset_count: int = 0
    moving_window_reset_reason_counts: dict[str, int] | None = None
    moving_window_total_exit_energy_J: float = 0.0
    moving_window_total_reset_removed_energy_J: float = 0.0
    moving_window_observation_snapshots: list[dict[str, Any]] | None = None
    minimum_depth_power_fraction_sum: float | None = None
    maximum_depth_power_fraction_sum: float | None = None
    minimum_top_cell_power_fraction: float | None = None
    maximum_top_cell_power_fraction: float | None = None

    def __post_init__(self) -> None:
        if self.moving_window_reset_reason_counts is None:
            self.moving_window_reset_reason_counts = {}
        if self.moving_window_observation_snapshots is None:
            self.moving_window_observation_snapshots = []

    def record_source(self, diagnostics: DepositionDepthKernelDiagnostics) -> None:
        self.source_build_count += 1
        if float(diagnostics.accepted_absorbed_power_W) > 0.0:
            self.powered_source_build_count += 1
        self.maximum_abs_source_power_error_W = max(
            self.maximum_abs_source_power_error_W,
            abs(float(diagnostics.source_power_error_W)),
        )
        self.maximum_abs_source_power_relative_error = max(
            self.maximum_abs_source_power_relative_error,
            abs(float(diagnostics.source_power_relative_error)),
        )
        normalization = diagnostics.finite_depth_normalization
        if normalization is not None and math.isfinite(float(normalization)):
            value = float(normalization)
            self.minimum_finite_depth_normalization = (
                value
                if self.minimum_finite_depth_normalization is None
                else min(self.minimum_finite_depth_normalization, value)
            )
            self.maximum_finite_depth_normalization = (
                value
                if self.maximum_finite_depth_normalization is None
                else max(self.maximum_finite_depth_normalization, value)
            )
        depth_sum = float(diagnostics.depth_power_fraction_sum)
        self.minimum_depth_power_fraction_sum = (
            depth_sum
            if self.minimum_depth_power_fraction_sum is None
            else min(self.minimum_depth_power_fraction_sum, depth_sum)
        )
        self.maximum_depth_power_fraction_sum = (
            depth_sum
            if self.maximum_depth_power_fraction_sum is None
            else max(self.maximum_depth_power_fraction_sum, depth_sum)
        )
        top_fraction = float(diagnostics.top_cell_power_fraction)
        self.minimum_top_cell_power_fraction = (
            top_fraction
            if self.minimum_top_cell_power_fraction is None
            else min(self.minimum_top_cell_power_fraction, top_fraction)
        )
        self.maximum_top_cell_power_fraction = (
            top_fraction
            if self.maximum_top_cell_power_fraction is None
            else max(self.maximum_top_cell_power_fraction, top_fraction)
        )

    def record_directional(
        self, diagnostics: DirectionalProcessStepDiagnostics, dt_s: float
    ) -> None:
        self.directional_step_count += 1
        decision = diagnostics.row_decision.transport_decision
        kernel = diagnostics.kernel
        dt = float(dt_s)
        if decision.directional_tensor_active:
            self.directional_tensor_active_step_count += 1
            self.directional_gate_accepted_step_count += 1
            self.directional_gate_accepted_time_s += dt
        elif decision.isotropic_fallback_active:
            self.isotropic_fallback_step_count += 1
            self.isotropic_fallback_time_s += dt
        elif decision.accepted_isotropic_delegation:
            self.isotropic_neutral_step_count += 1
        if int(kernel.liquid_cell_count) > 0:
            self.directional_liquid_available_step_count += 1
        active_x = int(kernel.directional_active_x_face_count)
        active_y = int(kernel.directional_active_y_face_count)
        self.cumulative_directional_active_x_face_count += active_x
        self.cumulative_directional_active_y_face_count += active_y
        self.maximum_directional_active_liquid_cell_count = max(
            self.maximum_directional_active_liquid_cell_count,
            int(kernel.directional_active_liquid_cell_count),
        )
        if active_x + active_y > 0:
            self.directional_active_face_step_count += 1
            self.directional_active_face_time_s += dt

    def record_moving_window_update(self, record: dict[str, Any]) -> None:
        self.moving_window_update_count += 1
        shift_x = int(record["window_shift_x_cells"])
        shift_y = int(record["window_shift_y_cells"])
        if shift_x != 0 or shift_y != 0:
            self.moving_window_shift_event_count += 1
        if bool(record["window_reset_flag"]):
            self.moving_window_reset_count += 1
            reason = str(record.get("window_reset_reason", "")) or "unspecified"
            assert self.moving_window_reset_reason_counts is not None
            self.moving_window_reset_reason_counts[reason] = (
                self.moving_window_reset_reason_counts.get(reason, 0) + 1
            )
        self.moving_window_total_exit_energy_J += float(record["window_exit_energy_J"])
        self.moving_window_total_reset_removed_energy_J += float(
            record["reset_removed_energy_J"]
        )

    def record_observation_snapshot(self, record: dict[str, Any]) -> None:
        """Record moving-window cumulative telemetry at one accepted observation.

        Patch 20.15.2 distinguishes an observation-time cumulative snapshot from
        the full-execution totals accumulated after later process rows.  This is
        passive telemetry only; it cannot alter temperatures, H/W, or moving-window
        state.
        """

        frame = record.get("selected_frame_index", record.get("frame_index"))
        row = record.get("selected_process_row", record.get("mapped_process_row"))
        if frame is None or row is None:
            raise CurrentPhysicsExecutionError(
                "observation diagnostics do not expose selected frame/process-row identity"
            )
        snapshot = {
            "selected_frame_index": int(frame),
            "selected_process_row": int(row),
            "cumulative_window_exit_energy_J": float(self.moving_window_total_exit_energy_J),
            "cumulative_reset_removed_energy_J": float(
                self.moving_window_total_reset_removed_energy_J
            ),
            "cumulative_total_removed_energy_J": float(
                self.moving_window_total_exit_energy_J
                + self.moving_window_total_reset_removed_energy_J
            ),
        }
        assert self.moving_window_observation_snapshots is not None
        self.moving_window_observation_snapshots.append(snapshot)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_build_count": int(self.source_build_count),
            "powered_source_build_count": int(self.powered_source_build_count),
            "maximum_abs_source_power_error_W": float(
                self.maximum_abs_source_power_error_W
            ),
            "maximum_abs_source_power_relative_error": float(
                self.maximum_abs_source_power_relative_error
            ),
            "minimum_finite_depth_normalization": self.minimum_finite_depth_normalization,
            "maximum_finite_depth_normalization": self.maximum_finite_depth_normalization,
            "directional_step_count": int(self.directional_step_count),
            "directional_tensor_active_step_count": int(
                self.directional_tensor_active_step_count
            ),
            "isotropic_fallback_step_count": int(self.isotropic_fallback_step_count),
            "isotropic_neutral_step_count": int(self.isotropic_neutral_step_count),
            "directional_gate_accepted_step_count": int(self.directional_gate_accepted_step_count),
            "directional_liquid_available_step_count": int(self.directional_liquid_available_step_count),
            "directional_active_face_step_count": int(self.directional_active_face_step_count),
            "cumulative_directional_active_x_face_count": int(self.cumulative_directional_active_x_face_count),
            "cumulative_directional_active_y_face_count": int(self.cumulative_directional_active_y_face_count),
            "maximum_directional_active_liquid_cell_count": int(self.maximum_directional_active_liquid_cell_count),
            "directional_gate_accepted_time_s": float(self.directional_gate_accepted_time_s),
            "directional_active_face_time_s": float(self.directional_active_face_time_s),
            "isotropic_fallback_time_s": float(self.isotropic_fallback_time_s),
            "moving_window_update_count": int(self.moving_window_update_count),
            "moving_window_shift_event_count": int(self.moving_window_shift_event_count),
            "moving_window_reset_count": int(self.moving_window_reset_count),
            "moving_window_reset_reason_counts": dict(self.moving_window_reset_reason_counts or {}),
            "moving_window_total_exit_energy_J": float(self.moving_window_total_exit_energy_J),
            "moving_window_total_reset_removed_energy_J": float(self.moving_window_total_reset_removed_energy_J),
            "moving_window_total_removed_energy_J": float(
                self.moving_window_total_exit_energy_J + self.moving_window_total_reset_removed_energy_J
            ),
            "moving_window_observation_snapshot_count": int(
                len(self.moving_window_observation_snapshots or ())
            ),
            "moving_window_observation_snapshots": [
                dict(item) for item in (self.moving_window_observation_snapshots or ())
            ],
            "minimum_depth_power_fraction_sum": self.minimum_depth_power_fraction_sum,
            "maximum_depth_power_fraction_sum": self.maximum_depth_power_fraction_sum,
            "minimum_top_cell_power_fraction": self.minimum_top_cell_power_fraction,
            "maximum_top_cell_power_fraction": self.maximum_top_cell_power_fraction,
        }


def current_physics_trial_parameters(
    base_params: Any,
    physics: CurrentPhysicsParameters,
):
    """Return the centralized validated trial bundle for the frozen model."""
    try:
        return build_current_trial_parameters(base_params, physics)
    except CurrentConfigurationError as exc:
        raise CurrentPhysicsExecutionError(str(exc)) from exc


def current_directional_stability_record(
    params: Any, physics: CurrentPhysicsParameters
) -> dict[str, Any]:
    """Return the accepted conservative worst-orientation stability preflight."""

    material = params.material
    return directional_explicit_stability_record(
        density_kg_m3=float(material.density_kg_m3),
        cp_solid_J_kgK=float(material.cp_solid_J_kgK),
        cp_mushy_effective_J_kgK=float(material.cp_eff_mushy_J_kgK),
        cp_liquid_J_kgK=float(material.cp_liquid_J_kgK),
        k_solid_W_mK=float(material.k_solid_W_mK),
        k_mushy_W_mK=float(material.k_mushy_W_mK),
        physical_liquid_conductivity_W_mK=float(material.k_liquid_W_mK),
        isotropic_enhancement_factor=float(
            physics.liquid_conductivity_enhancement_factor
        ),
        eta=float(physics.eta_directional),
        scan_axis_angle_deg=45.0,
        grid_spacing_m=float(params.grid.uniform_spacing_m(params.geometry)),
        selected_dt_s=float(params.time.dt_s),
        safety_factor=float(params.time.explicit_stability_safety_factor),
    )


# Accepted private name retained for Patch 19.x reproduction callers.
_current_directional_stability_record = current_directional_stability_record


def build_neutral_absorbed_power_treatment(
    process: Any,
    physics: CurrentPhysicsParameters,
):
    modulation = np.ones_like(
        np.asarray(process.laser_on, dtype=bool), dtype=np.float64
    )
    return supported_comparison.AbsorbedPowerTreatment(
        identifier="patch19.7.2_current_physics_global_alpha_neutral_ted",
        alpha_base=float(physics.absorptivity),
        ted_modulation=modulation,
        metadata={
            "schema": "lpbf_patch19_7_2_current_physics",
            "architecture": "P_laser_times_global_alpha_times_neutral_m_TED",
            "m_TED": 1.0,
            "quadratic_boiling_strength": float(
                CURRENT_FIXED_CONFIGURATION["quadratic_boiling_strength"]
            ),
            "parameter_fitting_performed": False,
        },
    )


def build_current_physics_execution_interfaces(
    *,
    params: Any,
    preloaded: Any,
    physics: CurrentPhysicsParameters,
    usage: CurrentPhysicsExecutionUsage,
    source_diagnostic_callback: Callable[[Any, int | None], None] | None = None,
    directional_diagnostic_callback: Callable[[Any, float], None] | None = None,
    temperature_trace_callback: TemperatureTraceCallback | None = None,
    observation_capture_callback: ObservationCaptureCallback | None = None,
    moving_window_update_callback: MovingWindowUpdateCallback | None = None,
) -> InMemoryExecutionInterfaces:
    """Build per-call numerical interfaces without mutating shared module state."""

    process = preloaded.layer_input.process
    x = np.asarray(process.laser_x_mm, dtype=np.float64)
    y = np.asarray(process.laser_y_mm, dtype=np.float64)
    powered = np.asarray(process.laser_on, dtype=bool)
    tracks = np.asarray(process.scan_track_id, dtype=np.int64)
    if x.ndim != 1 or not (x.shape == y.shape == powered.shape == tracks.shape):
        raise CurrentPhysicsExecutionError("invalid row-aligned process kinematics")

    source_builder = DepositionDepthFieldBuilder(
        params,
        deposition_depth_mode=physics.deposition_depth_mode,
        exponential_characteristic_depth_mm=physics.deposition_depth_mm,
    )
    current_source_row: list[int | None] = [None]
    effective_source_scratch = np.empty(
        (params.grid.Nx, params.grid.Ny, params.grid.Nz), dtype=np.float64
    )

    def source_callable(*args: Any, **kwargs: Any):
        if args:
            raise CurrentPhysicsExecutionError(
                "accepted comparison source call unexpectedly used positional arguments"
            )
        if "field_builder" not in kwargs:
            raise CurrentPhysicsExecutionError(
                "accepted comparison source call no longer exposes field_builder"
            )
        row = kwargs.get("row_index")
        current_source_row[0] = None if row is None else int(row)
        redirected = dict(kwargs)
        redirected["field_builder"] = source_builder
        q_dot, source, diagnostics = (
            build_centered_heat_source_for_row_with_deposition_depth(**redirected)
        )
        usage.record_source(diagnostics)
        if source_diagnostic_callback is not None:
            source_diagnostic_callback(diagnostics, current_source_row[0])
        return q_dot, source

    def require_source_row() -> int:
        row = current_source_row[0]
        if row is None:
            raise CurrentPhysicsExecutionError(
                "directional timestep executed before source-row identity was established"
            )
        return int(row)

    def numba_step_callable(
        temperature_K: np.ndarray,
        volumetric_heat_source_W_m3: np.ndarray,
        sub_params: Any,
        *,
        temperature_out_K: np.ndarray | None = None,
        return_boundary_powers: bool = False,
    ):
        step_result, diagnostics = explicit_fvm_step_for_process_row(
            temperature_K,
            volumetric_heat_source_W_m3,
            sub_params,
            eta_directional=float(physics.eta_directional),
            x_machine_mm=x,
            y_machine_mm=y,
            laser_on=powered,
            scan_track_id=tracks,
            row_index=require_source_row(),
            process_dt_s=PRODUCTION_DAQ_DT_S,
            temperature_out_K=temperature_out_K,
            effective_source_scratch_W_m3=effective_source_scratch,
            return_boundary_powers=return_boundary_powers,
        )
        usage.record_directional(diagnostics, float(sub_params.time.dt_s))
        if directional_diagnostic_callback is not None:
            directional_diagnostic_callback(diagnostics, float(sub_params.time.dt_s))
        return step_result

    def numpy_step_callable(
        temperature_K: np.ndarray,
        volumetric_heat_source_W_m3: np.ndarray,
        sub_params: Any,
        *,
        return_boundary_powers: bool = False,
    ):
        step_result, diagnostics = explicit_fvm_step_for_process_row(
            temperature_K,
            volumetric_heat_source_W_m3,
            sub_params,
            eta_directional=float(physics.eta_directional),
            x_machine_mm=x,
            y_machine_mm=y,
            laser_on=powered,
            scan_track_id=tracks,
            row_index=require_source_row(),
            process_dt_s=PRODUCTION_DAQ_DT_S,
            return_boundary_powers=return_boundary_powers,
        )
        usage.record_directional(diagnostics, float(sub_params.time.dt_s))
        if directional_diagnostic_callback is not None:
            directional_diagnostic_callback(diagnostics, float(sub_params.time.dt_s))
        return step_result

    def capture_observation(record: Any) -> None:
        payload = dict(record)
        usage.record_observation_snapshot(payload)
        if observation_capture_callback is not None:
            observation_capture_callback(payload)

    return InMemoryExecutionInterfaces(
        heat_source_for_row=source_callable,
        thermal_step_numba=numba_step_callable,
        thermal_step_numpy=numpy_step_callable,
        temperature_trace_callback=temperature_trace_callback,
        observation_capture_callback=capture_observation,
        moving_window_update_callback=moving_window_update_callback,
    )


def prepare_current_physics_process_condition(
    base_params: Any,
) -> CurrentPhysicsProcessCondition:
    """Preload one process condition for repeated current-physics evaluations."""

    preloaded = supported_comparison.preload_layer_melt_pool_comparison(base_params)
    return CurrentPhysicsProcessCondition(base_params=base_params, preloaded=preloaded)


def execute_current_physics(
    process_condition: CurrentPhysicsProcessCondition,
    physics: CurrentPhysicsParameters,
    **kwargs: Any,
) -> CurrentPhysicsExecutionResult:
    """Run the computation-only four-parameter current model in memory."""

    if not isinstance(process_condition, CurrentPhysicsProcessCondition):
        raise TypeError("process_condition must be a CurrentPhysicsProcessCondition")
    if not isinstance(physics, CurrentPhysicsParameters):
        raise TypeError("physics must be a CurrentPhysicsParameters")
    try:
        validate_current_physics_parameters(
            process_condition.base_params,
            physics,
            allow_legacy_deposition_control=False,
        )
    except CurrentConfigurationError as exc:
        raise CurrentPhysicsExecutionError(str(exc)) from exc
    return _execute_current_physics_simulation(
        process_condition.base_params,
        process_condition.preloaded,
        physics,
        **kwargs,
    )


def _execute_current_physics_simulation(
    base_params: Any,
    preloaded: Any,
    physics: CurrentPhysicsParameters,
    *,
    max_rows: int | None = None,
    observation_frame_indices: np.ndarray | None = None,
    workspace: Any | None = None,
    unenclosed_contour_policy: str = "raise",
    source_diagnostic_callback: Callable[[Any, int | None], None] | None = None,
    directional_diagnostic_callback: Callable[[Any, float], None] | None = None,
    temperature_trace_callback: TemperatureTraceCallback | None = None,
    observation_capture_callback: ObservationCaptureCallback | None = None,
    absorbed_power_treatment: Any | None = None,
) -> CurrentPhysicsExecutionResult:
    """Execute accepted numerical physics without reporting/objective packaging."""

    params = current_physics_trial_parameters(base_params, physics)
    stability = current_directional_stability_record(params, physics)
    if stability["status"] != "PASS":
        raise CurrentPhysicsExecutionError(
            "current directional/liquid-conductivity state fails the accepted "
            "conservative explicit-stability preflight"
        )
    usage = CurrentPhysicsExecutionUsage()

    def record_moving_window_update(record: dict[str, Any]) -> None:
        usage.record_moving_window_update(dict(record))

    interfaces = build_current_physics_execution_interfaces(
        params=params,
        preloaded=preloaded,
        physics=physics,
        usage=usage,
        source_diagnostic_callback=source_diagnostic_callback,
        directional_diagnostic_callback=directional_diagnostic_callback,
        temperature_trace_callback=temperature_trace_callback,
        observation_capture_callback=observation_capture_callback,
        moving_window_update_callback=record_moving_window_update,
    )
    treatment = absorbed_power_treatment
    if treatment is None:
        treatment = build_neutral_absorbed_power_treatment(
            preloaded.layer_input.process, physics
        )
    result = supported_comparison.run_in_memory_layer_melt_pool_comparison(
        params,
        preloaded,
        max_rows=max_rows,
        observation_frame_indices=observation_frame_indices,
        workspace=workspace,
        unenclosed_contour_policy=unenclosed_contour_policy,
        absorbed_power_treatment=treatment,
        capture_observation_diagnostics=True,
        execution_interfaces=interfaces,
    )
    return CurrentPhysicsExecutionResult(
        comparison_result=result,
        physics_parameters=physics,
        execution_usage=usage.to_dict(),
        directional_stability=stability,
    )


__all__ = [
    "CurrentPhysicsExecutionError",
    "CurrentPhysicsExecutionResult",
    "CurrentPhysicsExecutionUsage",
    "CurrentPhysicsParameters",
    "CurrentPhysicsProcessCondition",
    "build_current_physics_execution_interfaces",
    "build_neutral_absorbed_power_treatment",
    "current_directional_stability_record",
    "current_physics_trial_parameters",
    "execute_current_physics",
    "prepare_current_physics_process_condition",
]
