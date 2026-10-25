"""Patch 18.1 stateless production-row directional transport resolution.

This module does not execute experimental characterization.  It provides the
package-owned bridge from row-aligned process kinematics to the frozen
multiscale direction gate and then to the frozen Patch 18 liquid-transport
decision.  Each row is resolved independently so an old direction can never be
held through a corner, laser-off state, or stationary interval.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from lpbf.model.parameters import SimulationParameters
from lpbf.model.directional_solver import (
    DirectionalKernelDiagnostics,
    explicit_fvm_step_directional,
    explicit_fvm_step_directional_numba,
)
from lpbf.model.directional_transport import (
    PRODUCTION_DAQ_DT_S,
    LiquidTransportDecision,
    MultiscaleScanDirectionResult,
    estimate_multiscale_scan_direction,
    resolve_liquid_transport_decision,
)


class DirectionalRuntimeResolutionError(ValueError):
    """Raised when row-aligned kinematic inputs cannot be resolved safely."""


@dataclass(frozen=True)
class DirectionalProcessRowDecision:
    """One current-row kinematic gate plus its transport decision."""

    row_index: int
    laser_on: bool
    scan_track_id: int
    scan_direction_result: MultiscaleScanDirectionResult | None
    transport_decision: LiquidTransportDecision

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "row_index": int(self.row_index),
            "laser_on": bool(self.laser_on),
            "scan_track_id": int(self.scan_track_id),
            "scan_direction_gate": (
                None
                if self.scan_direction_result is None
                else self.scan_direction_result.to_dict()
            ),
        }
        payload.update(self.transport_decision.to_dict())
        return payload


def resolve_directional_transport_for_process_row(
    *,
    params: SimulationParameters,
    eta_directional: float,
    x_machine_mm: np.ndarray,
    y_machine_mm: np.ndarray,
    laser_on: np.ndarray,
    scan_track_id: np.ndarray,
    row_index: int,
    process_dt_s: float = PRODUCTION_DAQ_DT_S,
) -> DirectionalProcessRowDecision:
    """Resolve the tensor/fallback decision for exactly one process row.

    The function is intentionally stateless.  It receives no previous scan
    direction and returns no state to be carried forward.  A production runner
    must call it again at each subsequent row.
    """
    x = np.asarray(x_machine_mm, dtype=np.float64)
    y = np.asarray(y_machine_mm, dtype=np.float64)
    powered = np.asarray(laser_on, dtype=bool)
    track = np.asarray(scan_track_id, dtype=np.int64)
    if x.ndim != 1 or y.ndim != 1 or powered.ndim != 1 or track.ndim != 1:
        raise DirectionalRuntimeResolutionError(
            "directional runtime kinematic arrays must be one-dimensional"
        )
    if not (x.size == y.size == powered.size == track.size):
        raise DirectionalRuntimeResolutionError(
            "directional runtime kinematic arrays must have equal length"
        )
    row = int(row_index)
    if row < 0 or row >= x.size:
        raise DirectionalRuntimeResolutionError("row_index is outside the kinematic arrays")
    if not np.isfinite(process_dt_s) or float(process_dt_s) <= 0.0:
        raise DirectionalRuntimeResolutionError("process_dt_s must be finite and positive")

    gate: MultiscaleScanDirectionResult | None
    if not bool(powered[row]) or int(track[row]) <= 0:
        gate = None
    else:
        gate = estimate_multiscale_scan_direction(
            x,
            y,
            powered,
            center_row=row,
            scan_track_id=track,
            dt_s=float(process_dt_s),
        )

    decision = resolve_liquid_transport_decision(
        physical_liquid_conductivity_W_mK=float(params.material.k_liquid_W_mK),
        isotropic_enhancement_factor=float(
            params.material.liquid_conductivity_enhancement_factor
        ),
        eta_directional=float(eta_directional),
        scan_direction_result=gate,
    )
    return DirectionalProcessRowDecision(
        row_index=row,
        laser_on=bool(powered[row]),
        scan_track_id=int(track[row]),
        scan_direction_result=gate,
        transport_decision=decision,
    )


@dataclass(frozen=True)
class DirectionalProcessStepDiagnostics:
    """Combined current-row kinematic and PDE usage diagnostics."""

    row_decision: DirectionalProcessRowDecision
    kernel: DirectionalKernelDiagnostics

    def to_dict(self) -> dict[str, Any]:
        payload = self.row_decision.to_dict()
        payload.update({f"kernel_{key}": value for key, value in self.kernel.to_dict().items()})
        return payload


def explicit_fvm_step_for_process_row(
    temperature_K: np.ndarray,
    volumetric_heat_source_W_m3: np.ndarray,
    params: SimulationParameters,
    *,
    eta_directional: float,
    x_machine_mm: np.ndarray,
    y_machine_mm: np.ndarray,
    laser_on: np.ndarray,
    scan_track_id: np.ndarray,
    row_index: int,
    process_dt_s: float = PRODUCTION_DAQ_DT_S,
    temperature_out_K: np.ndarray | None = None,
    effective_source_scratch_W_m3: np.ndarray | None = None,
    return_boundary_powers: bool = False,
):
    """Resolve current-row direction and execute exactly one thermal timestep.

    This is the Patch 18.1 production integration seam.  It deliberately owns
    no persistent orientation state: every call reruns the frozen kinematic
    gate for ``row_index``.  The accepted scalar solver remains the exact
    delegated path for neutral and fallback states.
    """
    row_decision = resolve_directional_transport_for_process_row(
        params=params,
        eta_directional=eta_directional,
        x_machine_mm=x_machine_mm,
        y_machine_mm=y_machine_mm,
        laser_on=laser_on,
        scan_track_id=scan_track_id,
        row_index=row_index,
        process_dt_s=process_dt_s,
    )

    use_numba = bool(params.output.use_numba)
    if use_numba:
        step_result, kernel_diagnostics = explicit_fvm_step_directional_numba(
            temperature_K,
            volumetric_heat_source_W_m3,
            params,
            transport_decision=row_decision.transport_decision,
            temperature_out_K=temperature_out_K,
            effective_source_scratch_W_m3=effective_source_scratch_W_m3,
            return_boundary_powers=return_boundary_powers,
            return_directional_diagnostics=True,
        )
    else:
        step_result, kernel_diagnostics = explicit_fvm_step_directional(
            temperature_K,
            volumetric_heat_source_W_m3,
            params,
            transport_decision=row_decision.transport_decision,
            return_boundary_powers=return_boundary_powers,
            return_directional_diagnostics=True,
        )
    return step_result, DirectionalProcessStepDiagnostics(
        row_decision=row_decision,
        kernel=kernel_diagnostics,
    )


__all__ = [
    "DirectionalProcessRowDecision",
    "DirectionalRuntimeResolutionError",
    "DirectionalProcessStepDiagnostics",
    "explicit_fvm_step_for_process_row",
    "resolve_directional_transport_for_process_row",
]
