"""Compatibility implementation for current-experiment execution mechanics.

The supported current API is exposed from :mod:`lpbf.execution.api`. This
module retains the accepted names for historical experiment modules while
owning the remaining shared execution mechanics: stability preflight,
temperature tracing, energy accounting, observation extraction, calibration
trial evaluation, checkpoint identity, and result packaging.

Dataset/member resolution now lives in ``experiments.dataset`` and policy
realization/identity now lives in ``experiments.policy``. Those boundaries are
imported and re-exported here for compatibility.

Scientific experiment design, observation selection, acceptance criteria, and
analysis remain with their owning experiment modules. This module performs no
parameter fitting and selects no calibration policy beyond consuming an
explicit :class:`~lpbf.model.parameter_policy.ParameterPolicy` supplied by the
caller.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from lpbf.data.full_coupon_manifest import load_full_coupon_manifest
from lpbf.geometry import SUPPORTED_ODD_WINDOW_CELLS, resize_xy_window
from lpbf.infrastructure import canonical_sha256, sha256_file
from lpbf.model import current_execution
from lpbf.model import comparison as supported_comparison
from lpbf.model.laser_component_association import POLICY_VERSION as PRODUCTION_HW_ASSOCIATION_POLICY_VERSION
from lpbf.model.current_configuration import (
    CURRENT_CALIBRATABLE_PARAMETER_NAMES,
    CURRENT_FIXED_CONFIGURATION,
    CurrentPhysicsParameters,
    validate_current_physics_parameters,
)
from lpbf.model.temperature_diagnostics import canonicalize_high_temperature_diagnostics
from lpbf.model.parameter_policy import ParameterPolicy
from lpbf.model.production_hw import PRODUCTION_HW_DEFINITION, PRODUCTION_HW_SEMANTICS_VERSION
from lpbf.provenance.artifacts import ArtifactBundleSpec, package_artifacts
from lpbf.runtime.parameters import exact_fixed_time_params
from lpbf.provenance.schema_registry import (
    schema_envelope,
    validate_readable_schema,
)

from .dataset import DatasetMember, resolve_full_coupon_members, resolve_legacy_six_members
from .errors import CurrentExperimentFrameworkError
from .policy import (
    PolicyRealization,
    normalize_policy_realization_record_for_read,
    normalized_policy_definition,
    realize_policy_for_trial,
    realized_parameter_vector,
)


FRAMEWORK_SCHEMA_VERSION = "20.12.0"
DEFAULT_ENERGY_RELATIVE_ERROR_LIMIT = 1.0e-9
FROZEN_BOILING_AUDIT_TMAX_K = 7000.0
FROZEN_BOUNDARY_EXPLICIT_FRACTION_LIMIT = 0.90
FROZEN_QUADRATIC_RAMP_DERIVATIVE_MULTIPLIER = 2.01
NOMINAL_HIGH_TEMPERATURE_LIMIT_K = 3133.15
SCREENING_HIGH_TEMPERATURE_CEILING_K = 3233.15
LEGACY_PATCH_22_2_PRODUCTION_WINDOW_CELLS = 79
PRODUCTION_CALIBRATION_WINDOW_CELLS = 99
LEGACY_79_CELL_REPLAY_PATCHES = frozenset({"20.15", "20.16", "21.0", "21.1", "21.2", "21.3", "21.5"})
# Compatibility alias retained for accepted callers. As of Patch 22.3.1 the
# frozen/current production calibration window is 99 cells.
FROZEN_CALIBRATION_WINDOW_CELLS = PRODUCTION_CALIBRATION_WINDOW_CELLS
CALIBRATION_TRIAL_EVALUATION_SCHEMA = "lpbf_calibration_trial_evaluation"
CALIBRATION_TRIAL_EVALUATION_SCHEMA_VERSION = "20.10.0"


def checkpoint_contract_identity(
    *,
    schema: str,
    schema_version: str,
    expected_trial_identities: Sequence[str],
) -> str:
    """Hash the complete ordered deterministic restart contract."""

    if not schema or not schema_version:
        raise CurrentExperimentFrameworkError("checkpoint schema/version must be non-empty")
    identities = tuple(str(value) for value in expected_trial_identities)
    if not identities or any(not value for value in identities):
        raise CurrentExperimentFrameworkError("expected trial identities must be non-empty")
    if len(set(identities)) != len(identities):
        raise CurrentExperimentFrameworkError("expected trial identities must be unique")
    return canonical_sha256(
        {
            **schema_envelope("experiment_checkpoint_contract"),
            "experiment_schema": str(schema),
            "experiment_schema_version": str(schema_version),
            "expected_trial_identities": list(identities),
        }
    )


def boiling_boundary_stability_record(
    params: Any,
    strength: float,
    *,
    numerical_audit_temperature_max_K: float = FROZEN_BOILING_AUDIT_TMAX_K,
    boundary_explicit_fraction_limit: float = FROZEN_BOUNDARY_EXPLICIT_FRACTION_LIMIT,
    quadratic_ramp_derivative_multiplier: float = FROZEN_QUADRATIC_RAMP_DERIVATIVE_MULTIPLIER,
) -> dict[str, Any]:
    """Return the frozen explicit boiling-boundary stability audit."""

    strength = float(strength)
    transition_width_K = float(params.boundary_conditions.boiling_transition_width_K)
    maximum_conductance_W_m2K = float(
        params.boundary_conditions.boiling_max_conductance_W_m2K
    )
    reference_superheat_K = float(params.boundary_conditions.boiling_reference_superheat_K)
    t_boiling_K = float(params.material.T_boiling_K)
    dx = float(params.grid.uniform_spacing_m(params.geometry))
    rho = float(params.material.density_kg_m3)
    cp = float(params.material.cp_liquid_J_kgK)
    dt = float(params.time.dt_s)
    ramp_derivative_h = (
        strength
        * maximum_conductance_W_m2K
        * (transition_width_K / reference_superheat_K)
        * float(quadratic_ramp_derivative_multiplier)
    )
    delta_t = max(float(numerical_audit_temperature_max_K) - t_boiling_K, 0.0)
    tail_derivative_h = (
        2.0 * strength * maximum_conductance_W_m2K * delta_t / reference_superheat_K
    )
    max_h = 10.0 + max(ramp_derivative_h, tail_derivative_h)
    fraction = dt * max_h / (rho * cp * dx)
    passed = (
        math.isfinite(fraction)
        and 0.0 <= fraction < float(boundary_explicit_fraction_limit)
    )
    return {
        "strength": strength,
        "numerical_audit_temperature_max_K": float(numerical_audit_temperature_max_K),
        "boundary_explicit_loss_fraction": float(fraction),
        "boundary_explicit_fraction_limit": float(boundary_explicit_fraction_limit),
        "status": "PASS" if passed else "FAIL",
    }


def current_numerical_stability_preflight(
    params: Any,
    physics: CurrentPhysicsParameters,
    *,
    boiling_strength: float | None = None,
) -> dict[str, Any]:
    """Run every frozen explicit-stability gate required before thermal execution."""

    strength = (
        float(CURRENT_FIXED_CONFIGURATION["quadratic_boiling_strength"])
        if boiling_strength is None
        else float(boiling_strength)
    )
    directional = current_execution.current_directional_stability_record(params, physics)
    boiling = boiling_boundary_stability_record(params, strength)
    passed = directional.get("status") == "PASS" and boiling.get("status") == "PASS"
    failures: list[str] = []
    if directional.get("status") != "PASS":
        failures.append("directional_explicit_stability_preflight")
    if boiling.get("status") != "PASS":
        failures.append("boiling_boundary_stability_preflight")
    return {
        **schema_envelope("numerical_stability_preflight"),
        "status": "PASS" if passed else "FAIL",
        "failure_components": failures,
        "directional": directional,
        "boiling_boundary": boiling,
    }


@dataclass(frozen=True)
class EnergyAccountingRecord:
    cumulative_boiling_loss_energy_J: float
    cumulative_absorbed_laser_energy_J: float
    energy_balance_relative_error: float

    def to_dict(self) -> dict[str, float]:
        return {
            "cumulative_boiling_loss_energy_J": self.cumulative_boiling_loss_energy_J,
            "cumulative_absorbed_laser_energy_J": self.cumulative_absorbed_laser_energy_J,
            "energy_balance_relative_error": self.energy_balance_relative_error,
        }


def classify_current_peak_temperature(
    Tmax_K: float,
    *,
    nominal_limit_K: float = NOMINAL_HIGH_TEMPERATURE_LIMIT_K,
    screening_ceiling_K: float = SCREENING_HIGH_TEMPERATURE_CEILING_K,
) -> str:
    """Classify finite raw peak temperature using the accepted current thresholds."""

    value = float(Tmax_K)
    if not math.isfinite(value):
        raise CurrentExperimentFrameworkError("cannot classify a nonfinite Tmax")
    if value <= float(nominal_limit_K):
        return "PREFERRED"
    if value <= float(screening_ceiling_K):
        return "REVIEW_REQUIRED"
    return "SCREENING_FAIL"


def require_energy_accounting(
    diagnostics: Mapping[str, Any],
    *,
    relative_error_limit: float = DEFAULT_ENERGY_RELATIVE_ERROR_LIMIT,
) -> EnergyAccountingRecord:
    """Validate and normalize the shared experiment energy-accounting contract."""

    try:
        boiling = float(diagnostics["cumulative_boiling_loss_energy_J"])
        absorbed = float(diagnostics["cumulative_absorbed_laser_energy_J"])
        relative = abs(float(diagnostics["energy_balance_relative_error"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise CurrentExperimentFrameworkError(
            "incomplete or nonnumeric energy-accounting diagnostics"
        ) from exc
    if not all(math.isfinite(value) for value in (boiling, absorbed, relative)):
        raise CurrentExperimentFrameworkError("energy-accounting diagnostics must be finite")
    if relative > float(relative_error_limit):
        raise CurrentExperimentFrameworkError(
            f"energy-balance relative error {relative} exceeds limit {relative_error_limit}"
        )
    return EnergyAccountingRecord(
        cumulative_boiling_loss_energy_J=boiling,
        cumulative_absorbed_laser_energy_J=absorbed,
        energy_balance_relative_error=relative,
    )


class TemperatureTraceAccumulator:
    """Every-substep high-temperature telemetry shared by current experiments."""

    def __init__(
        self,
        *,
        cell_volume_mm3: float,
        nominal_limit_K: float = NOMINAL_HIGH_TEMPERATURE_LIMIT_K,
        screening_ceiling_K: float = SCREENING_HIGH_TEMPERATURE_CEILING_K,
    ) -> None:
        if cell_volume_mm3 <= 0.0 or not math.isfinite(cell_volume_mm3):
            raise ValueError("cell_volume_mm3 must be finite and positive")
        self.cell_volume_mm3 = float(cell_volume_mm3)
        self.nominal_limit_K = float(nominal_limit_K)
        self.screening_ceiling_K = float(screening_ceiling_K)
        self.step_count = 0
        self.total_integrated_time_s = 0.0
        self.raw_global_Tmax_K = -math.inf
        self.raw_global_surface_Tmax_K = -math.inf
        self.maximum_cells_above_nominal_limit = 0
        self.maximum_surface_cells_above_nominal_limit = 0
        self.maximum_cells_above_screening_ceiling = 0
        self.any_cell_above_nominal_duration_s = 0.0
        self.any_surface_cell_above_nominal_duration_s = 0.0
        self.any_cell_above_screening_ceiling_duration_s = 0.0
        self.volume_time_above_nominal_mm3_s = 0.0
        self.volume_time_above_screening_ceiling_mm3_s = 0.0
        self._current_nominal_episode_s = 0.0
        self.maximum_consecutive_any_cell_above_nominal_duration_s = 0.0
        self.first_nominal_exceedance_elapsed_s: float | None = None
        self.last_nominal_exceedance_elapsed_s: float | None = None
        self.first_ceiling_exceedance_elapsed_s: float | None = None
        self.last_ceiling_exceedance_elapsed_s: float | None = None
        self._peak_snapshot: dict[str, Any] | None = None

    def record(self, temperature_K: np.ndarray, dt_s: float) -> None:
        values = np.asarray(temperature_K, dtype=np.float64)
        dt = float(dt_s)
        if values.ndim != 3 or values.size == 0:
            raise CurrentExperimentFrameworkError(
                "temperature trace requires a nonempty 3D field"
            )
        if not np.all(np.isfinite(values)):
            raise CurrentExperimentFrameworkError(
                "nonfinite temperature encountered in substep trace"
            )
        if dt <= 0.0 or not math.isfinite(dt):
            raise CurrentExperimentFrameworkError(
                "temperature trace requires positive finite dt"
            )

        self.step_count += 1
        self.total_integrated_time_s += dt
        volume_peak = float(np.max(values))
        surface = values[:, :, -1]
        surface_peak = float(np.max(surface))
        nominal_mask = values >= self.nominal_limit_K
        ceiling_mask = values > self.screening_ceiling_K
        nominal_count = int(np.count_nonzero(nominal_mask))
        ceiling_count = int(np.count_nonzero(ceiling_mask))
        surface_nominal_count = int(np.count_nonzero(surface >= self.nominal_limit_K))

        self.raw_global_surface_Tmax_K = max(self.raw_global_surface_Tmax_K, surface_peak)
        self.maximum_cells_above_nominal_limit = max(
            self.maximum_cells_above_nominal_limit, nominal_count
        )
        self.maximum_surface_cells_above_nominal_limit = max(
            self.maximum_surface_cells_above_nominal_limit, surface_nominal_count
        )
        self.maximum_cells_above_screening_ceiling = max(
            self.maximum_cells_above_screening_ceiling, ceiling_count
        )

        if nominal_count > 0:
            self.any_cell_above_nominal_duration_s += dt
            self.volume_time_above_nominal_mm3_s += nominal_count * self.cell_volume_mm3 * dt
            self._current_nominal_episode_s += dt
            self.maximum_consecutive_any_cell_above_nominal_duration_s = max(
                self.maximum_consecutive_any_cell_above_nominal_duration_s,
                self._current_nominal_episode_s,
            )
            if self.first_nominal_exceedance_elapsed_s is None:
                self.first_nominal_exceedance_elapsed_s = self.total_integrated_time_s
            self.last_nominal_exceedance_elapsed_s = self.total_integrated_time_s
        else:
            self._current_nominal_episode_s = 0.0

        if surface_nominal_count > 0:
            self.any_surface_cell_above_nominal_duration_s += dt

        if ceiling_count > 0:
            self.any_cell_above_screening_ceiling_duration_s += dt
            self.volume_time_above_screening_ceiling_mm3_s += (
                ceiling_count * self.cell_volume_mm3 * dt
            )
            if self.first_ceiling_exceedance_elapsed_s is None:
                self.first_ceiling_exceedance_elapsed_s = self.total_integrated_time_s
            self.last_ceiling_exceedance_elapsed_s = self.total_integrated_time_s

        if volume_peak > self.raw_global_Tmax_K:
            self.raw_global_Tmax_K = volume_peak
            peak_flat_index = int(np.argmax(values))
            peak_index = tuple(int(v) for v in np.unravel_index(peak_flat_index, values.shape))
            peak_z_index = int(peak_index[2])
            peak_layers_below_top = int(values.shape[2] - 1 - peak_z_index)
            self._peak_snapshot = {
                "elapsed_s": self.total_integrated_time_s,
                "Tmax_K": volume_peak,
                "surface_Tmax_K": surface_peak,
                "peak_index_xyz": list(peak_index),
                "peak_z_index": peak_z_index,
                "peak_layers_below_top": peak_layers_below_top,
                "cells_above_nominal_limit": nominal_count,
                "volume_above_nominal_limit_mm3": nominal_count * self.cell_volume_mm3,
                "surface_cells_above_nominal_limit": surface_nominal_count,
                "cells_above_screening_ceiling": ceiling_count,
                "volume_above_screening_ceiling_mm3": ceiling_count * self.cell_volume_mm3,
                "T_p99_9_K": float(np.percentile(values, 99.9)),
                "T_p99_K": float(np.percentile(values, 99.0)),
            }

    def to_dict(self) -> dict[str, Any]:
        if self.step_count <= 0 or not math.isfinite(self.raw_global_Tmax_K):
            raise CurrentExperimentFrameworkError(
                "temperature trace captured no thermal substeps"
            )
        peak = dict(self._peak_snapshot or {})
        return {
            "thermal_substep_count": int(self.step_count),
            "total_integrated_thermal_time_s": float(self.total_integrated_time_s),
            "raw_global_Tmax_K": float(self.raw_global_Tmax_K),
            "raw_global_surface_Tmax_K": float(self.raw_global_surface_Tmax_K),
            "maximum_cells_above_nominal_limit": int(self.maximum_cells_above_nominal_limit),
            "maximum_volume_above_nominal_limit_mm3": float(
                self.maximum_cells_above_nominal_limit * self.cell_volume_mm3
            ),
            "maximum_surface_cells_above_nominal_limit": int(
                self.maximum_surface_cells_above_nominal_limit
            ),
            "maximum_cells_above_screening_ceiling": int(
                self.maximum_cells_above_screening_ceiling
            ),
            "maximum_volume_above_screening_ceiling_mm3": float(
                self.maximum_cells_above_screening_ceiling * self.cell_volume_mm3
            ),
            "any_cell_above_nominal_duration_s": float(
                self.any_cell_above_nominal_duration_s
            ),
            "any_surface_cell_above_nominal_duration_s": float(
                self.any_surface_cell_above_nominal_duration_s
            ),
            "maximum_consecutive_any_cell_above_nominal_duration_s": float(
                self.maximum_consecutive_any_cell_above_nominal_duration_s
            ),
            "volume_time_above_nominal_mm3_s": float(
                self.volume_time_above_nominal_mm3_s
            ),
            "any_cell_above_screening_ceiling_duration_s": float(
                self.any_cell_above_screening_ceiling_duration_s
            ),
            "volume_time_above_screening_ceiling_mm3_s": float(
                self.volume_time_above_screening_ceiling_mm3_s
            ),
            "first_nominal_exceedance_elapsed_s": self.first_nominal_exceedance_elapsed_s,
            "last_nominal_exceedance_elapsed_s": self.last_nominal_exceedance_elapsed_s,
            "first_ceiling_exceedance_elapsed_s": self.first_ceiling_exceedance_elapsed_s,
            "last_ceiling_exceedance_elapsed_s": self.last_ceiling_exceedance_elapsed_s,
            "peak_snapshot": peak,
            "duration_interpretation": (
                "Eulerian represented-domain persistence; not Lagrangian material-point residence time"
            ),
            "material_point_residence_time_available": False,
        }


def cell_volume_mm3(params: Any) -> float:
    """Return the uniform grid-cell volume in mm^3."""

    return float(
        (params.geometry.Lx_mm / params.grid.Nx)
        * (params.geometry.Ly_mm / params.grid.Ny)
        * (params.geometry.Lz_mm / params.grid.Nz)
    )


def build_temperature_instrumented_runner(
    *,
    params: Any,
    preloaded: Any,
    physics: CurrentPhysicsParameters,
    usage: current_execution.CurrentPhysicsExecutionUsage,
    tracer: TemperatureTraceAccumulator,
):
    """Build a per-call traced runner using explicit numerical interfaces.

    Patch 20.11 keeps passive temperature tracing outside the numerical kernel:
    the accepted comparison loop receives an immutable interface bundle for this
    run rather than cloning functions or changing module globals.
    """

    def trace_temperature(temperature: Any, dt_s: float) -> None:
        tracer.record(np.asarray(temperature, dtype=np.float64), float(dt_s))

    def record_moving_window_update(record: Mapping[str, Any]) -> None:
        usage.record_moving_window_update(dict(record))

    interfaces = current_execution.build_current_physics_execution_interfaces(
        params=params,
        preloaded=preloaded,
        physics=physics,
        usage=usage,
        temperature_trace_callback=trace_temperature,
        moving_window_update_callback=record_moving_window_update,
    )

    def run(
        run_params: Any,
        run_preloaded: Any,
        **comparison_kwargs: Any,
    ) -> Any:
        if run_params is not params or run_preloaded is not preloaded:
            raise CurrentExperimentFrameworkError(
                "instrumented runner is bound to exactly one prepared process condition"
            )
        return supported_comparison.run_in_memory_layer_melt_pool_comparison(
            run_params,
            run_preloaded,
            execution_interfaces=interfaces,
            **comparison_kwargs,
        )

    return run



@dataclass(frozen=True)
class InstrumentedTrialResult:
    """Result of one passive-temperature-traced current-physics execution."""

    comparison_result: Any
    temperature_trace: Mapping[str, Any]
    execution_usage: Mapping[str, Any]
    absorbed_power_treatment: Any


def execute_temperature_traced_trial(
    *,
    params: Any,
    preloaded: Any,
    physics: CurrentPhysicsParameters,
    observation_frame_indices: np.ndarray | None,
    treatment_identifier: str | None = None,
    treatment_metadata: Mapping[str, Any] | None = None,
    unenclosed_contour_policy: str = "record_nan",
) -> InstrumentedTrialResult:
    """Execute one accepted trial with passive tracing and explicit metadata.

    This is a lower-level regression/experiment building block after Patch
    20.10. Calibration-facing callers must use :func:`evaluate_calibration_trial`,
    which atomically owns dataset identity, policy realization, both numerical
    preflights, solver entry, tracing, and failure semantics.
    """

    usage = current_execution.CurrentPhysicsExecutionUsage()
    tracer = TemperatureTraceAccumulator(cell_volume_mm3=cell_volume_mm3(params))
    runner = build_temperature_instrumented_runner(
        params=params,
        preloaded=preloaded,
        physics=physics,
        usage=usage,
        tracer=tracer,
    )
    treatment = current_execution.build_neutral_absorbed_power_treatment(
        preloaded.layer_input.process, physics
    )
    if treatment_identifier is not None or treatment_metadata:
        treatment = replace(
            treatment,
            identifier=(
                treatment.identifier
                if treatment_identifier is None
                else str(treatment_identifier)
            ),
            metadata={
                **(treatment.metadata or {}),
                **dict(treatment_metadata or {}),
            },
        )
    result = runner(
        params,
        preloaded,
        observation_frame_indices=(
            None
            if observation_frame_indices is None
            else np.asarray(observation_frame_indices, dtype=np.int64)
        ),
        unenclosed_contour_policy=str(unenclosed_contour_policy),
        absorbed_power_treatment=treatment,
        capture_observation_diagnostics=True,
    )
    return InstrumentedTrialResult(
        comparison_result=result,
        temperature_trace=tracer.to_dict(),
        execution_usage=usage.to_dict(),
        absorbed_power_treatment=treatment,
    )


UNDEFINED_OBSERVATION_POLICIES = frozenset({"reject", "record_undefined"})


@dataclass(frozen=True)
class CalibrationExecutionScope:
    """Explicit, deterministic execution scope for one calibration-facing trial.

    Patch 20.10 does not choose calibration observations, weights, bounds, or an
    optimizer.  A caller may either request every synchronization-valid camera
    observation (``observation_frame_indices=None``) or supply an explicit,
    strictly increasing subset for a governed experiment.  As of Patch 22.3.1,
    the accepted production XY window is 99 cells. Historical 79-cell replay and
    the Patch 22.1 diagnostic window study remain explicitly gated exceptions.
    """

    scope_id: str
    observation_frame_indices: tuple[int, ...] | None = None
    trial_context: Mapping[str, Any] = field(default_factory=dict)
    unenclosed_contour_policy: str = "record_nan"
    window_cells: int = FROZEN_CALIBRATION_WINDOW_CELLS
    # Patch 22.3.7: "record_undefined" lets a trial complete with undefined frames
    # (each observation then carries observation_status SCORED / UNDEFINED_<reason>).
    undefined_observation_policy: str = "reject"

    def __post_init__(self) -> None:
        scope = str(self.scope_id).strip()
        if not scope:
            raise CurrentExperimentFrameworkError("calibration execution scope_id must be non-empty")
        if self.unenclosed_contour_policy not in {"raise", "record_nan"}:
            raise CurrentExperimentFrameworkError(
                "unenclosed_contour_policy must be 'raise' or 'record_nan'"
            )
        if self.undefined_observation_policy not in UNDEFINED_OBSERVATION_POLICIES:
            raise CurrentExperimentFrameworkError(
                "undefined_observation_policy must be 'reject' or 'record_undefined'"
            )
        window_cells = int(self.window_cells)
        if window_cells not in SUPPORTED_ODD_WINDOW_CELLS:
            raise CurrentExperimentFrameworkError(
                f"unsupported diagnostic window size: {window_cells}"
            )
        if window_cells != PRODUCTION_CALIBRATION_WINDOW_CELLS:
            patch22_1_diagnostic = (
                self.trial_context.get("patch") == "22.1_window_sensitivity"
                and self.trial_context.get("diagnostic_only") is True
            )
            legacy_replay = (
                window_cells == LEGACY_PATCH_22_2_PRODUCTION_WINDOW_CELLS
                and self.trial_context.get("legacy_79_cell_contract_replay") is True
                and str(self.trial_context.get("patch", "")) in LEGACY_79_CELL_REPLAY_PATCHES
            )
            if not (patch22_1_diagnostic or legacy_replay):
                raise CurrentExperimentFrameworkError(
                    "non-production window is authorized only for Patch 22.1 "
                    "diagnostic window sensitivity or explicit legacy 79-cell contract replay"
                )
        frames = self.observation_frame_indices
        if frames is not None:
            normalized = tuple(int(value) for value in frames)
            if not normalized:
                raise CurrentExperimentFrameworkError(
                    "observation_frame_indices must be non-empty when supplied"
                )
            if any(value < 0 for value in normalized) or any(
                b <= a for a, b in zip(normalized, normalized[1:])
            ):
                raise CurrentExperimentFrameworkError(
                    "observation_frame_indices must be strictly increasing nonnegative integers"
                )
            object.__setattr__(self, "observation_frame_indices", normalized)
        object.__setattr__(self, "scope_id", scope)
        object.__setattr__(self, "trial_context", dict(self.trial_context))
        object.__setattr__(self, "window_cells", window_cells)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scope_id": self.scope_id,
            "observation_frame_indices": (
                None
                if self.observation_frame_indices is None
                else list(self.observation_frame_indices)
            ),
            "trial_context": dict(self.trial_context),
            "unenclosed_contour_policy": self.unenclosed_contour_policy,
            "window_cells": int(self.window_cells),
            "undefined_observation_policy": self.undefined_observation_policy,
            "calibration_choices_selected": False,
        }


@dataclass(frozen=True)
class CalibrationTrialEvaluation:
    """Versioned atomic result for one Patch 20.10 calibration-facing trial."""

    status: str
    stage: str
    dataset_member: Mapping[str, Any]
    execution_scope: Mapping[str, Any]
    policy_realization: Mapping[str, Any] | None
    numerical_preflight: Mapping[str, Any] | None
    observations: tuple[Mapping[str, Any], ...]
    temperature_trace: Mapping[str, Any] | None
    high_temperature_diagnostics: Mapping[str, Any] | None
    energy_accounting: Mapping[str, Any] | None
    execution_telemetry: Mapping[str, Any] | None
    failure: Mapping[str, Any] | None
    trial_identity: str | None
    manifest_identity: str | None

    @property
    def succeeded(self) -> bool:
        return self.status == "PASS"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": CALIBRATION_TRIAL_EVALUATION_SCHEMA,
            "schema_version": CALIBRATION_TRIAL_EVALUATION_SCHEMA_VERSION,
            "status": self.status,
            "stage": self.stage,
            "manifest_identity": self.manifest_identity,
            "trial_identity": self.trial_identity,
            "dataset_member": dict(self.dataset_member),
            "execution_scope": dict(self.execution_scope),
            "policy_realization": (
                None if self.policy_realization is None else dict(self.policy_realization)
            ),
            "numerical_preflight": (
                None if self.numerical_preflight is None else dict(self.numerical_preflight)
            ),
            "observations": [dict(record) for record in self.observations],
            "temperature_trace": (
                None if self.temperature_trace is None else dict(self.temperature_trace)
            ),
            "high_temperature_diagnostics": (
                None
                if self.high_temperature_diagnostics is None
                else dict(self.high_temperature_diagnostics)
            ),
            "energy_accounting": (
                None if self.energy_accounting is None else dict(self.energy_accounting)
            ),
            "execution_telemetry": (
                None if self.execution_telemetry is None else dict(self.execution_telemetry)
            ),
            "failure": None if self.failure is None else dict(self.failure),
            "fixed_model_quantities": {
                "quadratic_boiling_strength": {
                    "value": float(CURRENT_FIXED_CONFIGURATION["quadratic_boiling_strength"]),
                    "units": "dimensionless",
                    "role": "fixed_regulator",
                    "policy_coefficient": False,
                }
            },
            "calibration_bounds_selected": False,
            "objective_weights_selected": False,
            "optimizer_selected": False,
            "parameter_fitting_performed": False,
            "temperature_clipping_permitted": False,
        }


def _dataset_member_record(member: DatasetMember) -> dict[str, Any]:
    return {
        "portable_identity": member.portable_identity,
        "portable_identity_text": member.portable_identity_text,
        "campaign_id": str(member.campaign_id),
        "acquisition_set_id": str(member.acquisition_set_id),
        "coupon_position": int(member.coupon_position),
        "layer_name": str(member.layer_name),
        "input_filename": member.path.name,
        "runtime_path": str(member.path),
        "power_W": float(member.power_W),
        "nominal_speed_mm_s": float(member.nominal_speed_mm_s),
        "spot_diameter_mm": float(member.spot_diameter_mm),
        "source_date": member.source_date,
        "process_condition_provenance": dict(member.process_condition_provenance),
    }


def _failure_record(
    *,
    stage: str,
    code: str,
    message: str,
    exception_type: str | None,
    solver_entered: bool,
    simulated_outputs_emitted: bool,
) -> dict[str, Any]:
    return {
        "stage": str(stage),
        "code": str(code),
        "message": str(message),
        "exception_type": exception_type,
        "solver_entered": bool(solver_entered),
        "simulated_outputs_emitted": bool(simulated_outputs_emitted),
        "fabricated_outputs_emitted": False,
    }


def _failed_calibration_evaluation(
    *,
    member: DatasetMember,
    scope: CalibrationExecutionScope,
    stage: str,
    code: str,
    message: str,
    exception: BaseException | None = None,
    status: str = "FAILURE",
    policy_realization: PolicyRealization | None = None,
    numerical_preflight: Mapping[str, Any] | None = None,
    observations: Sequence[Mapping[str, Any]] = (),
    temperature_trace: Mapping[str, Any] | None = None,
    high_temperature_diagnostics: Mapping[str, Any] | None = None,
    energy_accounting: Mapping[str, Any] | None = None,
    execution_telemetry: Mapping[str, Any] | None = None,
    manifest_identity: str | None = None,
    solver_entered: bool = False,
    simulated_outputs_emitted: bool = False,
) -> CalibrationTrialEvaluation:
    return CalibrationTrialEvaluation(
        status=status,
        stage=stage,
        dataset_member=_dataset_member_record(member),
        execution_scope=scope.to_dict(),
        policy_realization=(
            None if policy_realization is None else policy_realization.provenance_dict()
        ),
        numerical_preflight=(
            None if numerical_preflight is None else dict(numerical_preflight)
        ),
        observations=tuple(dict(record) for record in observations),
        temperature_trace=(None if temperature_trace is None else dict(temperature_trace)),
        high_temperature_diagnostics=(
            None
            if high_temperature_diagnostics is None
            else dict(high_temperature_diagnostics)
        ),
        energy_accounting=(None if energy_accounting is None else dict(energy_accounting)),
        execution_telemetry=(
            None if execution_telemetry is None else dict(execution_telemetry)
        ),
        failure=_failure_record(
            stage=stage,
            code=code,
            message=message,
            exception_type=None if exception is None else type(exception).__name__,
            solver_entered=solver_entered,
            simulated_outputs_emitted=simulated_outputs_emitted,
        ),
        trial_identity=(
            None if policy_realization is None else policy_realization.trial_identity
        ),
        manifest_identity=manifest_identity,
    )


def _validate_calibration_dataset_member(member: DatasetMember) -> str:
    """Verify canonical manifest membership and exact runtime file identity."""

    if not isinstance(member, DatasetMember):
        raise TypeError("dataset_member must be DatasetMember")
    manifest = load_full_coupon_manifest().require_hash_complete()
    try:
        canonical = manifest.member(
            member.acquisition_set_id,
            member.coupon_position,
            layer_name=member.layer_name,
        )
    except KeyError as exc:
        raise CurrentExperimentFrameworkError(
            "dataset member is not present in the canonical full-coupon manifest"
        ) from exc
    expected_pairs = (
        ("campaign_id", member.campaign_id, canonical.key.campaign_id),
        ("expected_filename", member.expected_filename, canonical.expected_filename),
        ("sha256", member.sha256, canonical.sha256),
        ("power_W", float(member.power_W), float(canonical.nominal_power_W)),
        (
            "nominal_speed_mm_s",
            float(member.nominal_speed_mm_s),
            float(canonical.nominal_speed_mm_s),
        ),
        (
            "spot_diameter_mm",
            float(member.spot_diameter_mm),
            float(canonical.spot_diameter_mm),
        ),
    )
    for field_name, actual, expected in expected_pairs:
        if actual != expected:
            raise CurrentExperimentFrameworkError(
                f"dataset member {field_name} disagrees with canonical manifest"
            )
    path = Path(member.path)
    if not path.is_file():
        raise CurrentExperimentFrameworkError(f"dataset member file does not exist: {path}")
    if path.name != canonical.expected_filename:
        raise CurrentExperimentFrameworkError(
            "runtime dataset filename disagrees with canonical manifest"
        )
    actual_sha256 = sha256_file(path)
    if actual_sha256 != canonical.sha256 or actual_sha256 != member.sha256:
        raise CurrentExperimentFrameworkError(
            "runtime dataset SHA-256 disagrees with canonical manifest identity"
        )
    return manifest.canonical_identity


def _construct_calibration_runtime(
    member: DatasetMember,
    *,
    window_cells: int = FROZEN_CALIBRATION_WINDOW_CELLS,
) -> tuple[Any, Any]:
    """Construct the accepted fixed-time runtime at an explicit XY window."""

    base = resize_xy_window(
        exact_fixed_time_params(member.path, member.condition),
        int(window_cells),
    )
    prepared = current_execution.prepare_current_physics_process_condition(base)
    return base, prepared


def _calibration_observation_records(
    comparison_result: Any,
    *,
    allow_nonfinite_primary: bool = False,
) -> tuple[dict[str, Any], ...]:
    """Normalize H/W arrays and aligned observation diagnostics.

    With ``allow_nonfinite_primary`` the complete observation rows emitted by
    the solver are preserved when the contour extractor records an undefined
    H/W result.  Every row carries ``observation_status``: ``SCORED`` for a
    finite primary observation, ``UNDEFINED_<reason>`` otherwise.  Under the
    Patch 22.3.7 ``record_undefined`` scope policy such rows are returned in a
    completed evaluation and excluded from residuals downstream; under the
    historical ``reject`` policy the caller still returns a failed evaluation.
    """

    arrays = {
        "frame_index": np.asarray(comparison_result.frame_index, dtype=np.int64),
        "mapped_process_row": np.asarray(comparison_result.mapped_process_row, dtype=np.int64),
        "experimental_H_pixels": np.asarray(comparison_result.experimental_H_pixels, dtype=np.float64),
        "experimental_W_pixels": np.asarray(comparison_result.experimental_W_pixels, dtype=np.float64),
        "simulated_H_pixels": np.asarray(comparison_result.simulated_H_pixels, dtype=np.float64),
        "simulated_W_pixels": np.asarray(comparison_result.simulated_W_pixels, dtype=np.float64),
    }
    counts = {values.size for values in arrays.values()}
    if len(counts) != 1:
        raise CurrentExperimentFrameworkError("calibration H/W arrays are not row-aligned")
    count = next(iter(counts), 0)
    diagnostics = tuple(dict(item) for item in comparison_result.observation_diagnostics)
    if count <= 0 or len(diagnostics) != count:
        raise CurrentExperimentFrameworkError(
            "calibration execution returned incomplete observation diagnostics"
        )

    records: list[dict[str, Any]] = []
    for index in range(count):
        exp_h = float(arrays["experimental_H_pixels"][index])
        exp_w = float(arrays["experimental_W_pixels"][index])
        sim_h = float(arrays["simulated_H_pixels"][index])
        sim_w = float(arrays["simulated_W_pixels"][index])
        primary_finite = all(math.isfinite(value) for value in (exp_h, exp_w, sim_h, sim_w))
        if not primary_finite and not allow_nonfinite_primary:
            raise CurrentExperimentFrameworkError(
                "calibration H/W extraction produced a nonfinite primary observation"
            )
        if primary_finite and (sim_h < 0.0 or sim_w < 0.0):
            raise CurrentExperimentFrameworkError(
                "calibration H/W extraction produced a negative melt dimension"
            )
        if primary_finite and (sim_h == 0.0) != (sim_w == 0.0):
            raise CurrentExperimentFrameworkError(
                "calibration H/W extraction produced an invalid partial-zero footprint"
            )
        diagnostic_classification = str(
            diagnostics[index].get("classification", "UNCLASSIFIED")
        )
        if not primary_finite:
            classification = diagnostic_classification
        elif sim_h == 0.0:
            # Patch 22.3.7: keep the "no laser-associated melt" prediction distinct
            # from a window-wide zero footprint; both are scored as zero.
            classification = (
                "NO_LASER_ASSOCIATED_MELT"
                if diagnostic_classification == "NO_LASER_ASSOCIATED_MELT"
                else "ZERO_FOOTPRINT"
            )
        else:
            classification = "FINITE_MELT"
        undefined_reason = (
            None
            if primary_finite
            else str(
                diagnostics[index].get("production_hw_invalid_reason")
                or diagnostic_classification
                or "NONFINITE"
            )
        )
        records.append(
            {
                "frame_index": int(arrays["frame_index"][index]),
                "mapped_process_row": int(arrays["mapped_process_row"][index]),
                "observation_status": "SCORED" if primary_finite else f"UNDEFINED_{undefined_reason}",
                "undefined_reason": undefined_reason,
                "experimental_H_pixels": exp_h,
                "experimental_W_pixels": exp_w,
                "simulated_H_pixels": sim_h,
                "simulated_W_pixels": sim_w,
                "H_error_pixels": float(sim_h - exp_h),
                "W_error_pixels": float(sim_w - exp_w),
                "simulated_H_over_W": (
                    None
                    if not math.isfinite(sim_h)
                    or not math.isfinite(sim_w)
                    or sim_w == 0.0
                    else float(sim_h / sim_w)
                ),
                "melt_classification": classification,
                "observation_diagnostics": diagnostics[index],
            }
        )
    return tuple(records)


def patch20_13_static_diagnostic_telemetry(
    params: Any, physics: CurrentPhysicsParameters
) -> dict[str, Any]:
    """Return non-driving source/grid diagnostic facts for Patch 20.13."""

    try:
        grid_spacing_mm = float(params.grid.uniform_spacing_m(params.geometry) * 1.0e3)
        realized_spot_diameter_mm = float(params.input.default_spot_size_um) * 1.0e-3
    except AttributeError:
        # Lightweight unit-test doubles may omit full runtime geometry/input.
        grid_spacing_mm = None
        realized_spot_diameter_mm = None
    deposition_depth_mm = float(physics.deposition_depth_mm)
    source_depth_resolution_ratio = (
        None
        if grid_spacing_mm is None
        else float(deposition_depth_mm / grid_spacing_mm)
    )
    return {
        "diagnostic_contract_version": "20.13.0",
        "realized_spot_diameter_mm": realized_spot_diameter_mm,
        "grid_spacing_mm": grid_spacing_mm,
        "source_depth_resolution_ratio": source_depth_resolution_ratio,
        "source_depth_resolution_definition": "deposition_depth_mm/grid_spacing_mm",
        "source_power_closure_checked_every_source_build": True,
        "directional_activation_semantics": (
            "gate acceptance is distinct from liquid availability and actual liquid-liquid face activation"
        ),
        "moving_window_telemetry_scope": "all simulated process rows",
        "moving_window_observation_snapshot_scope": "cumulative through each selected process row",
        "moving_window_diagnostic_scope_correction": "20.15.2",
        "observation_component_diagnostics_drive_hw": True,
        "production_hw_definition": PRODUCTION_HW_DEFINITION,
        "production_hw_semantics_version": PRODUCTION_HW_SEMANTICS_VERSION,
        "production_hw_association_policy_version": PRODUCTION_HW_ASSOCIATION_POLICY_VERSION,
    }


def evaluate_calibration_trial(
    dataset_member: DatasetMember,
    parameter_policy: ParameterPolicy,
    execution_scope: CalibrationExecutionScope,
) -> CalibrationTrialEvaluation:
    """Atomically evaluate one calibration-facing trial under the frozen model.

    This is the sole Patch 20.10 public calibration-evaluation transaction.  It
    validates exact dataset identity, constructs the frozen runtime, realizes
    the supplied policy, validates the realized physical state, executes both
    required numerical preflights before solver entry, runs the accepted thermal
    model with every-substep passive temperature tracing, validates H/W and
    energy-accounting outputs, and returns one standardized versioned record.

    It does not select calibration bounds, objective weights, partitions,
    predictors, fitted values, or an optimizer.
    """

    if not isinstance(dataset_member, DatasetMember):
        raise TypeError("dataset_member must be DatasetMember")
    if not isinstance(execution_scope, CalibrationExecutionScope):
        raise TypeError("execution_scope must be CalibrationExecutionScope")
    if not isinstance(parameter_policy, ParameterPolicy):
        raise TypeError("parameter_policy does not satisfy the ParameterPolicy protocol")

    member = dataset_member
    scope = execution_scope
    manifest_identity: str | None = None
    realization: PolicyRealization | None = None
    preflight: Mapping[str, Any] | None = None

    try:
        manifest_identity = _validate_calibration_dataset_member(member)
    except Exception as exc:
        return _failed_calibration_evaluation(
            member=member,
            scope=scope,
            stage="dataset_validation",
            code="DATASET_IDENTITY_REJECTED",
            message=str(exc),
            exception=exc,
        )

    try:
        base, prepared = _construct_calibration_runtime(
            member, window_cells=int(scope.window_cells)
        )
    except Exception as exc:
        return _failed_calibration_evaluation(
            member=member,
            scope=scope,
            stage="process_condition_construction",
            code="PROCESS_CONDITION_CONSTRUCTION_FAILED",
            message=str(exc),
            exception=exc,
            manifest_identity=manifest_identity,
        )

    try:
        realization = realize_policy_for_trial(
            policy=parameter_policy,
            process_condition=member.process_condition,
            input_sha256=member.sha256,
            execution_scope=scope.scope_id,
            trial_context={
                **dict(scope.trial_context),
                "observation_frame_indices": (
                    None
                    if scope.observation_frame_indices is None
                    else list(scope.observation_frame_indices)
                ),
                "window_cells": int(scope.window_cells),
                "unenclosed_contour_policy": scope.unenclosed_contour_policy,
            },
        )
    except Exception as exc:
        return _failed_calibration_evaluation(
            member=member,
            scope=scope,
            stage="policy_realization",
            code="POLICY_REALIZATION_FAILED",
            message=str(exc),
            exception=exc,
            manifest_identity=manifest_identity,
        )

    physics = realization.realized_parameters
    try:
        validate_current_physics_parameters(
            base, physics, allow_legacy_deposition_control=False
        )
        params = current_execution.current_physics_trial_parameters(base, physics)
        fixed_strength = float(CURRENT_FIXED_CONFIGURATION["quadratic_boiling_strength"])
        if not math.isclose(
            float(params.boundary_conditions.boiling_damper_strength),
            fixed_strength,
            rel_tol=0.0,
            abs_tol=1.0e-15,
        ):
            raise CurrentExperimentFrameworkError(
                "runtime trial construction did not preserve the fixed boiling regulator"
            )
    except Exception as exc:
        return _failed_calibration_evaluation(
            member=member,
            scope=scope,
            stage="physical_parameter_validation",
            code="REALIZED_PARAMETER_STATE_REJECTED",
            message=str(exc),
            exception=exc,
            policy_realization=realization,
            manifest_identity=manifest_identity,
        )

    try:
        preflight = current_numerical_stability_preflight(
            params,
            physics,
            boiling_strength=float(CURRENT_FIXED_CONFIGURATION["quadratic_boiling_strength"]),
        )
    except Exception as exc:
        return _failed_calibration_evaluation(
            member=member,
            scope=scope,
            stage="numerical_preflight",
            code="NUMERICAL_PREFLIGHT_ERROR",
            message=str(exc),
            exception=exc,
            policy_realization=realization,
            manifest_identity=manifest_identity,
        )
    if preflight.get("status") != "PASS":
        failures = tuple(str(value) for value in preflight.get("failure_components", ()))
        return _failed_calibration_evaluation(
            member=member,
            scope=scope,
            stage="numerical_preflight",
            code="NUMERICAL_PREFLIGHT_REJECTED",
            message=(
                "frozen numerical preflight rejected trial: "
                + (", ".join(failures) if failures else "unspecified component")
            ),
            status="PREFLIGHT_REJECTED",
            policy_realization=realization,
            numerical_preflight=preflight,
            manifest_identity=manifest_identity,
            solver_entered=False,
            simulated_outputs_emitted=False,
        )

    requested_frames = (
        None
        if scope.observation_frame_indices is None
        else np.asarray(scope.observation_frame_indices, dtype=np.int64)
    )
    try:
        trial = execute_temperature_traced_trial(
            params=params,
            preloaded=prepared.preloaded,
            physics=physics,
            observation_frame_indices=requested_frames,
            treatment_identifier="patch20.13_atomic_calibration_evaluator",
            treatment_metadata={
                "patch": "20.13",
                "evaluation_schema": CALIBRATION_TRIAL_EVALUATION_SCHEMA,
                "evaluation_schema_version": CALIBRATION_TRIAL_EVALUATION_SCHEMA_VERSION,
                "parameter_policy_identity": realization.policy_identity,
                "trial_identity": realization.trial_identity,
                "quadratic_boiling_strength": float(
                    CURRENT_FIXED_CONFIGURATION["quadratic_boiling_strength"]
                ),
                "boiling_strength_role": "fixed_regulator_not_calibration_parameter",
                "parameter_fitting_performed": False,
                "model_parameter_optimization_performed": False,
                "calibration_bounds_selected": False,
                "objective_weights_selected": False,
                "temperature_clipping_permitted": False,
            },
            unenclosed_contour_policy=scope.unenclosed_contour_policy,
        )
    except Exception as exc:
        return _failed_calibration_evaluation(
            member=member,
            scope=scope,
            stage="thermal_execution",
            code="THERMAL_EXECUTION_FAILED",
            message=str(exc),
            exception=exc,
            policy_realization=realization,
            numerical_preflight=preflight,
            manifest_identity=manifest_identity,
            solver_entered=True,
            simulated_outputs_emitted=False,
        )

    trace = dict(trial.temperature_trace)
    telemetry = dict(trial.execution_usage)
    record_undefined = scope.undefined_observation_policy == "record_undefined"
    try:
        observations = _calibration_observation_records(
            trial.comparison_result, allow_nonfinite_primary=record_undefined
        )
    except Exception as exc:
        # Preserve the solver-emitted diagnostic rows before returning the
        # atomic failure.  This second normalization is intentionally
        # diagnostic-only and cannot enter the objective because this branch
        # returns FAILURE.
        diagnostic_observations: tuple[Mapping[str, Any], ...] = ()
        try:
            diagnostic_observations = _calibration_observation_records(
                trial.comparison_result,
                allow_nonfinite_primary=True,
            )
        except Exception:
            # Retain the original failure as the root cause if the comparison
            # payload itself is malformed rather than merely nonfinite.
            diagnostic_observations = ()
        return _failed_calibration_evaluation(
            member=member,
            scope=scope,
            stage="observation_validation",
            code="PRIMARY_OBSERVATION_REJECTED",
            message=str(exc),
            exception=exc,
            policy_realization=realization,
            numerical_preflight=preflight,
            temperature_trace=trace,
            execution_telemetry=telemetry,
            observations=diagnostic_observations,
            manifest_identity=manifest_identity,
            solver_entered=True,
            simulated_outputs_emitted=True,
        )

    try:
        thermal_substeps = int(trace["thermal_substep_count"])
        directional_steps = int(telemetry["directional_step_count"])
        if thermal_substeps <= 0 or thermal_substeps != directional_steps:
            raise CurrentExperimentFrameworkError(
                "every-substep trace count does not reconcile with thermal-step telemetry"
            )
        final_diag = dict(observations[-1]["observation_diagnostics"])
        energy = require_energy_accounting(final_diag)
        high_t = canonicalize_high_temperature_diagnostics(trace, final_diag)
        if "moving_window_update_count" in telemetry:
            comparison_rows = int(trial.comparison_result.metadata["rows_simulated"])
            if int(telemetry["moving_window_update_count"]) != comparison_rows:
                raise CurrentExperimentFrameworkError(
                    "moving-window telemetry does not cover every simulated process row"
                )

            snapshots = tuple(
                dict(item) for item in telemetry.get("moving_window_observation_snapshots", ())
            )
            if len(snapshots) != len(observations):
                raise CurrentExperimentFrameworkError(
                    "moving-window observation-scope telemetry is not aligned with requested observations"
                )
            if int(telemetry.get("moving_window_observation_snapshot_count", len(snapshots))) != len(snapshots):
                raise CurrentExperimentFrameworkError(
                    "moving-window observation snapshot count is inconsistent"
                )

            for observation, snapshot in zip(observations, snapshots, strict=True):
                diag = dict(observation["observation_diagnostics"])
                if int(snapshot["selected_frame_index"]) != int(observation["frame_index"]):
                    raise CurrentExperimentFrameworkError(
                        "moving-window observation snapshot frame identity mismatch"
                    )
                if int(snapshot["selected_process_row"]) != int(observation["mapped_process_row"]):
                    raise CurrentExperimentFrameworkError(
                        "moving-window observation snapshot process-row identity mismatch"
                    )
                for snapshot_key, observation_key in (
                    ("cumulative_window_exit_energy_J", "cumulative_window_exit_energy_J"),
                    ("cumulative_reset_removed_energy_J", "cumulative_reset_removed_energy_J"),
                ):
                    snapshot_value = float(snapshot[snapshot_key])
                    observation_value = float(diag[observation_key])
                    tolerance = max(1.0e-12, 1.0e-12 * abs(observation_value))
                    if not math.isclose(
                        snapshot_value, observation_value, rel_tol=0.0, abs_tol=tolerance
                    ):
                        raise CurrentExperimentFrameworkError(
                            "moving-window observation-scope telemetry mismatch for "
                            f"{observation_key}"
                        )

            total_exit = float(telemetry["moving_window_total_exit_energy_J"])
            total_reset = float(telemetry["moving_window_total_reset_removed_energy_J"])
            total_removed = float(telemetry["moving_window_total_removed_energy_J"])
            total_tolerance = max(1.0e-12, 1.0e-12 * abs(total_removed))
            if not math.isclose(
                total_removed, total_exit + total_reset, rel_tol=0.0, abs_tol=total_tolerance
            ):
                raise CurrentExperimentFrameworkError(
                    "moving-window full-execution removed-energy identity mismatch"
                )

            final_observation_is_end_of_execution = bool(
                snapshots and int(snapshots[-1]["selected_process_row"]) == comparison_rows - 1
            )
            if final_observation_is_end_of_execution:
                for telemetry_key, snapshot_key in (
                    ("moving_window_total_exit_energy_J", "cumulative_window_exit_energy_J"),
                    ("moving_window_total_reset_removed_energy_J", "cumulative_reset_removed_energy_J"),
                ):
                    telemetry_value = float(telemetry[telemetry_key])
                    snapshot_value = float(snapshots[-1][snapshot_key])
                    tolerance = max(1.0e-12, 1.0e-12 * abs(snapshot_value))
                    if not math.isclose(
                        telemetry_value, snapshot_value, rel_tol=0.0, abs_tol=tolerance
                    ):
                        raise CurrentExperimentFrameworkError(
                            "moving-window end-of-execution telemetry mismatch for "
                            f"{telemetry_key}"
                        )

            telemetry["moving_window_observation_scope_reconciled"] = True
            telemetry["moving_window_full_execution_scope_reconciled"] = True
            telemetry["moving_window_final_observation_is_end_of_execution"] = (
                final_observation_is_end_of_execution
            )
            telemetry["moving_window_full_vs_final_observation_equality_required"] = (
                final_observation_is_end_of_execution
            )
    except Exception as exc:
        return _failed_calibration_evaluation(
            member=member,
            scope=scope,
            stage="diagnostic_validation",
            code="MANDATORY_DIAGNOSTICS_REJECTED",
            message=str(exc),
            exception=exc,
            policy_realization=realization,
            numerical_preflight=preflight,
            observations=diagnostic_observations,
            temperature_trace=trace,
            execution_telemetry=telemetry,
            manifest_identity=manifest_identity,
            solver_entered=True,
            simulated_outputs_emitted=True,
        )

    energy_record = energy.to_dict()
    telemetry.update(patch20_13_static_diagnostic_telemetry(params, physics))
    telemetry.update(
        {
            "undefined_observation_policy": scope.undefined_observation_policy,
            "undefined_observation_count": sum(
                1
                for observation in observations
                if str(observation.get("observation_status", "")).startswith("UNDEFINED_")
            ),
            "every_substep_temperature_trace_complete": True,
            "temperature_trace_step_count": int(trace["thermal_substep_count"]),
            "raw_temperature_exceeds_frozen_7000K_audit_envelope": bool(
                float(trace["raw_global_Tmax_K"]) > FROZEN_BOILING_AUDIT_TMAX_K
            ),
            "temperature_7000K_state_is_diagnostic_only": True,
            "temperature_clipping_used": False,
        }
    )
    return CalibrationTrialEvaluation(
        status="PASS",
        stage="complete",
        dataset_member=_dataset_member_record(member),
        execution_scope=scope.to_dict(),
        policy_realization=realization.provenance_dict(),
        numerical_preflight=dict(preflight),
        observations=tuple(observations),
        temperature_trace=trace,
        high_temperature_diagnostics=high_t,
        energy_accounting=energy_record,
        execution_telemetry=telemetry,
        failure=None,
        trial_identity=realization.trial_identity,
        manifest_identity=manifest_identity,
    )

def package_experiment_results(
    output_directory: str | Path,
    *,
    zip_filename: str,
    generated_names: Sequence[str],
    authority_paths: Sequence[str | Path] = (),
    manifest_filename: str,
    compresslevel: int = 9,
) -> Path:
    """Create the standard deterministic manifest + ZIP result bundle."""

    spec = ArtifactBundleSpec(
        zip_filename=str(zip_filename),
        generated_names=tuple(str(name) for name in generated_names),
        authority_paths=tuple(Path(path) for path in authority_paths),
        manifest_filename=str(manifest_filename),
        compresslevel=int(compresslevel),
    )
    return package_artifacts(Path(output_directory), spec)


__all__ = [
    "CALIBRATION_TRIAL_EVALUATION_SCHEMA",
    "CALIBRATION_TRIAL_EVALUATION_SCHEMA_VERSION",
    "CalibrationExecutionScope",
    "CalibrationTrialEvaluation",
    "FROZEN_CALIBRATION_WINDOW_CELLS",
    "LEGACY_PATCH_22_2_PRODUCTION_WINDOW_CELLS",
    "LEGACY_79_CELL_REPLAY_PATCHES",
    "PRODUCTION_CALIBRATION_WINDOW_CELLS",
    "DEFAULT_ENERGY_RELATIVE_ERROR_LIMIT",
    "DatasetMember",
    "EnergyAccountingRecord",
    "InstrumentedTrialResult",
    "NOMINAL_HIGH_TEMPERATURE_LIMIT_K",
    "SCREENING_HIGH_TEMPERATURE_CEILING_K",
    "FRAMEWORK_SCHEMA_VERSION",
    "PolicyRealization",
    "TemperatureTraceAccumulator",
    "boiling_boundary_stability_record",
    "build_temperature_instrumented_runner",
    "cell_volume_mm3",
    "classify_current_peak_temperature",
    "checkpoint_contract_identity",
    "current_numerical_stability_preflight",
    "evaluate_calibration_trial",
    "execute_temperature_traced_trial",
    "normalized_policy_definition",
    "normalize_policy_realization_record_for_read",
    "package_experiment_results",
    "realize_policy_for_trial",
    "realized_parameter_vector",
    "require_energy_accounting",
    "resolve_legacy_six_members",
]
