"""Patch 18.1 conservative directional-conduction kernel.

This module deliberately leaves the accepted scalar solver untouched.  The
nonzero directional operator is implemented as an *additive correction* to the
accepted scalar conduction update:

    K = k_iso I + D,
    D = eta_directional * k_iso * (t outer t).

The accepted scalar operator therefore remains the baseline everywhere.  The
correction is evaluated only on internal faces whose two adjacent cells are
liquid (T >= T_liquidus).  This fail-closed face rule prevents directional
enhancement from being extended into the solid or mushy region during the
implementation phase.

At eta_directional == 0, or whenever the current orientation is unresolved,
``explicit_fvm_step_directional`` delegates directly to the accepted scalar
``solver.explicit_fvm_step``.  It does not execute the tensor kernel.

Patch 18.1 keeps the frozen scalar core untouched.  A package-owned compiled
directional correction path feeds the accepted scalar Numba timestep through
an effective-source scratch field; neutral and fallback states still delegate
directly to the accepted scalar solver.  Full real-data orchestration remains
a later integration seam.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

try:
    from numba import njit
except ImportError:  # pragma: no cover - accepted scalar solver owns fallback behavior
    njit = None

from lpbf.model._accepted_core import solver as accepted_scalar_solver
from lpbf.model.parameters import SimulationParameters

from lpbf.model.directional_transport import (
    LiquidTransportDecision,
    TRANSPORT_MODE_DIRECTIONAL,
)


class DirectionalTensorKernelError(ValueError):
    """Raised when an active tensor step violates the frozen Patch 18 contract."""


@dataclass(frozen=True)
class DirectionalKernelDiagnostics:
    """Audit record for one directional-kernel evaluation."""

    transport_mode: str
    accepted_scalar_delegation: bool
    directional_tensor_active: bool
    requested_eta_directional: float
    effective_eta_directional: float
    liquid_cell_count: int
    directional_active_liquid_cell_count: int
    isotropic_fallback_liquid_cell_count: int
    directional_active_liquid_fraction: float
    isotropic_fallback_liquid_fraction: float
    directional_active_x_face_count: int
    directional_active_y_face_count: int
    internal_directional_energy_change_J_m3_sum: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "transport_mode": self.transport_mode,
            "accepted_scalar_delegation": self.accepted_scalar_delegation,
            "directional_tensor_active": self.directional_tensor_active,
            "requested_eta_directional": self.requested_eta_directional,
            "effective_eta_directional": self.effective_eta_directional,
            "liquid_cell_count": self.liquid_cell_count,
            "directional_active_liquid_cell_count": (
                self.directional_active_liquid_cell_count
            ),
            "isotropic_fallback_liquid_cell_count": (
                self.isotropic_fallback_liquid_cell_count
            ),
            "directional_active_liquid_fraction": (
                self.directional_active_liquid_fraction
            ),
            "isotropic_fallback_liquid_fraction": (
                self.isotropic_fallback_liquid_fraction
            ),
            "directional_active_x_face_count": self.directional_active_x_face_count,
            "directional_active_y_face_count": self.directional_active_y_face_count,
            "internal_directional_energy_change_J_m3_sum": (
                self.internal_directional_energy_change_J_m3_sum
            ),
        }


def _cell_center_gradient(
    field: np.ndarray,
    *,
    axis: int,
    spacing_m: float,
) -> np.ndarray:
    """Return a second-order interior / first-order edge cell-centered gradient."""
    values = np.asarray(field, dtype=np.float64)
    if values.ndim != 3:
        raise DirectionalTensorKernelError("temperature field must be three-dimensional")
    if axis not in (0, 1):
        raise DirectionalTensorKernelError("directional in-plane gradient axis must be 0 or 1")
    if not np.isfinite(spacing_m) or spacing_m <= 0.0:
        raise DirectionalTensorKernelError("grid spacing must be finite and positive")

    gradient = np.zeros_like(values, dtype=np.float64)
    length = values.shape[axis]
    if length <= 1:
        return gradient

    lower = [slice(None)] * 3
    upper = [slice(None)] * 3
    first = [slice(None)] * 3
    second = [slice(None)] * 3
    last = [slice(None)] * 3
    penultimate = [slice(None)] * 3

    first[axis] = 0
    second[axis] = 1
    last[axis] = -1
    penultimate[axis] = -2
    gradient[tuple(first)] = (
        values[tuple(second)] - values[tuple(first)]
    ) / spacing_m
    gradient[tuple(last)] = (
        values[tuple(last)] - values[tuple(penultimate)]
    ) / spacing_m

    if length > 2:
        center = [slice(None)] * 3
        lower[axis] = slice(0, -2)
        upper[axis] = slice(2, None)
        center[axis] = slice(1, -1)
        gradient[tuple(center)] = (
            values[tuple(upper)] - values[tuple(lower)]
        ) / (2.0 * spacing_m)
    return gradient


def _validate_active_decision_against_parameters(
    decision: LiquidTransportDecision,
    params: SimulationParameters,
) -> tuple[float, float, float]:
    """Return additive in-plane tensor components after contract validation."""
    if decision.accepted_isotropic_delegation:
        raise DirectionalTensorKernelError(
            "delegating transport decisions must not enter the tensor kernel"
        )
    if not decision.directional_tensor_active:
        raise DirectionalTensorKernelError(
            "non-delegating transport decision is not an active directional tensor"
        )
    if decision.transport_mode != TRANSPORT_MODE_DIRECTIONAL:
        raise DirectionalTensorKernelError(
            "active tensor decision has an unexpected transport mode"
        )
    if decision.scan_unit_x is None or decision.scan_unit_y is None:
        raise DirectionalTensorKernelError("active tensor decision requires a scan unit vector")

    norm = float(np.hypot(decision.scan_unit_x, decision.scan_unit_y))
    if not np.isclose(norm, 1.0, rtol=0.0, atol=1.0e-12):
        raise DirectionalTensorKernelError("scan direction must be unit normalized")

    k_iso = float(params.material.k_liquid_effective_W_mK)
    if not np.isclose(
        decision.principal_perpendicular_W_mK,
        k_iso,
        rtol=0.0,
        atol=1.0e-12,
    ):
        raise DirectionalTensorKernelError(
            "transport decision transverse conductivity does not match accepted scalar liquid conductivity"
        )
    if not np.isclose(
        decision.principal_build_normal_W_mK,
        k_iso,
        rtol=0.0,
        atol=1.0e-12,
    ):
        raise DirectionalTensorKernelError(
            "transport decision build-normal conductivity does not match accepted scalar liquid conductivity"
        )

    tensor = np.asarray(decision.liquid_conductivity_tensor_W_mK, dtype=np.float64)
    if tensor.shape != (3, 3) or not np.all(np.isfinite(tensor)):
        raise DirectionalTensorKernelError("active conductivity tensor must be finite 3x3")
    if not np.array_equal(tensor, tensor.T):
        raise DirectionalTensorKernelError("active conductivity tensor must be exactly symmetric")
    if not np.all(np.linalg.eigvalsh(tensor) > 0.0):
        raise DirectionalTensorKernelError("active conductivity tensor must be positive definite")

    # Patch 18 freezes no xz/yz coupling and no change to build-normal liquid k.
    zero_components = (tensor[0, 2], tensor[2, 0], tensor[1, 2], tensor[2, 1])
    if any(abs(float(value)) > 1.0e-12 for value in zero_components):
        raise DirectionalTensorKernelError("Patch 18 tensor may not contain xz or yz coupling")
    if not np.isclose(tensor[2, 2], k_iso, rtol=0.0, atol=1.0e-12):
        raise DirectionalTensorKernelError("Patch 18 tensor may not alter build-normal conductivity")

    d_xx = float(tensor[0, 0] - k_iso)
    d_xy = float(tensor[0, 1])
    d_yy = float(tensor[1, 1] - k_iso)
    if d_xx < -1.0e-12 or d_yy < -1.0e-12:
        raise DirectionalTensorKernelError("directional additive normal components must be nonnegative")
    return d_xx, d_xy, d_yy


def compute_directional_conduction_correction_energy_density_J_m3(
    temperature_K: np.ndarray,
    params: SimulationParameters,
    transport_decision: LiquidTransportDecision,
) -> tuple[np.ndarray, DirectionalKernelDiagnostics]:
    """Return the conservative nonzero-eta conduction correction for one step.

    The returned field is an *energy-density increment* (J/m^3), not a complete
    timestep.  The accepted scalar conduction operator is intentionally absent
    here and must remain the baseline in the caller.

    Directional enhancement is evaluated only on liquid-liquid internal x/y
    faces.  Each face exchange is added to one adjacent cell and subtracted from
    the other, so the correction cannot create net internal energy apart from
    floating-point summation roundoff.
    """
    T = np.asarray(temperature_K, dtype=np.float64)
    if T.ndim != 3:
        raise DirectionalTensorKernelError("temperature field must be three-dimensional")
    if not np.all(np.isfinite(T)):
        raise DirectionalTensorKernelError("temperature field must be finite")

    d_xx, d_xy, d_yy = _validate_active_decision_against_parameters(
        transport_decision, params
    )
    dt = float(params.time.dt_s)
    dx = float(params.grid.uniform_spacing_m(params.geometry))
    if not np.isfinite(dt) or dt <= 0.0:
        raise DirectionalTensorKernelError("timestep must be finite and positive")
    if not np.isfinite(dx) or dx <= 0.0:
        raise DirectionalTensorKernelError("grid spacing must be finite and positive")

    liquid = T >= float(params.material.T_liquidus_K)
    correction = np.zeros_like(T, dtype=np.float64)
    grad_x = _cell_center_gradient(T, axis=0, spacing_m=dx)
    grad_y = _cell_center_gradient(T, axis=1, spacing_m=dx)

    active_x_faces = 0
    if T.shape[0] > 1:
        face_active_x = liquid[:-1, :, :] & liquid[1:, :, :]
        active_x_faces = int(np.count_nonzero(face_active_x))
        normal_gradient_x = (T[1:, :, :] - T[:-1, :, :]) / dx
        tangential_gradient_y = 0.5 * (grad_y[:-1, :, :] + grad_y[1:, :, :])
        directional_flux_x_W_m2 = np.where(
            face_active_x,
            d_xx * normal_gradient_x + d_xy * tangential_gradient_y,
            0.0,
        )
        exchange_x_J_m3 = dt * directional_flux_x_W_m2 / dx
        correction[:-1, :, :] += exchange_x_J_m3
        correction[1:, :, :] -= exchange_x_J_m3

    active_y_faces = 0
    if T.shape[1] > 1:
        face_active_y = liquid[:, :-1, :] & liquid[:, 1:, :]
        active_y_faces = int(np.count_nonzero(face_active_y))
        normal_gradient_y = (T[:, 1:, :] - T[:, :-1, :]) / dx
        tangential_gradient_x = 0.5 * (grad_x[:, :-1, :] + grad_x[:, 1:, :])
        directional_flux_y_W_m2 = np.where(
            face_active_y,
            d_xy * tangential_gradient_x + d_yy * normal_gradient_y,
            0.0,
        )
        exchange_y_J_m3 = dt * directional_flux_y_W_m2 / dx
        correction[:, :-1, :] += exchange_y_J_m3
        correction[:, 1:, :] -= exchange_y_J_m3

    liquid_count = int(np.count_nonzero(liquid))
    active_liquid_cells = np.zeros_like(liquid, dtype=bool)
    if T.shape[0] > 1:
        face_active_x = liquid[:-1, :, :] & liquid[1:, :, :]
        active_liquid_cells[:-1, :, :] |= face_active_x
        active_liquid_cells[1:, :, :] |= face_active_x
    if T.shape[1] > 1:
        face_active_y = liquid[:, :-1, :] & liquid[:, 1:, :]
        active_liquid_cells[:, :-1, :] |= face_active_y
        active_liquid_cells[:, 1:, :] |= face_active_y
    directional_active_cell_count = int(np.count_nonzero(active_liquid_cells))
    directional_fraction = (
        float(directional_active_cell_count / liquid_count) if liquid_count else 0.0
    )
    fallback_fraction = 0.0

    diagnostics = DirectionalKernelDiagnostics(
        transport_mode=transport_decision.transport_mode,
        accepted_scalar_delegation=False,
        directional_tensor_active=True,
        requested_eta_directional=float(transport_decision.requested_eta_directional),
        effective_eta_directional=float(transport_decision.effective_eta_directional),
        liquid_cell_count=liquid_count,
        directional_active_liquid_cell_count=directional_active_cell_count,
        isotropic_fallback_liquid_cell_count=0,
        directional_active_liquid_fraction=directional_fraction,
        isotropic_fallback_liquid_fraction=fallback_fraction,
        directional_active_x_face_count=active_x_faces,
        directional_active_y_face_count=active_y_faces,
        internal_directional_energy_change_J_m3_sum=float(
            np.sum(correction, dtype=np.float64)
        ),
    )
    return correction, diagnostics


def directional_usage_diagnostics_for_delegation(
    temperature_K: np.ndarray,
    params: SimulationParameters,
    transport_decision: LiquidTransportDecision,
) -> DirectionalKernelDiagnostics:
    """Return liquid usage fractions for neutral/fallback scalar delegation."""
    T = np.asarray(temperature_K, dtype=np.float64)
    liquid_count = int(np.count_nonzero(T >= float(params.material.T_liquidus_K)))
    fallback_count = liquid_count if transport_decision.isotropic_fallback_active else 0
    fallback_fraction = 1.0 if fallback_count else 0.0
    return DirectionalKernelDiagnostics(
        transport_mode=transport_decision.transport_mode,
        accepted_scalar_delegation=True,
        directional_tensor_active=False,
        requested_eta_directional=float(transport_decision.requested_eta_directional),
        effective_eta_directional=float(transport_decision.effective_eta_directional),
        liquid_cell_count=liquid_count,
        directional_active_liquid_cell_count=0,
        isotropic_fallback_liquid_cell_count=fallback_count,
        directional_active_liquid_fraction=0.0,
        isotropic_fallback_liquid_fraction=fallback_fraction,
        directional_active_x_face_count=0,
        directional_active_y_face_count=0,
        internal_directional_energy_change_J_m3_sum=0.0,
    )



def _active_directional_usage_diagnostics(
    temperature_K: np.ndarray,
    params: SimulationParameters,
    transport_decision: LiquidTransportDecision,
    *,
    internal_directional_energy_change_J_m3_sum: float,
) -> DirectionalKernelDiagnostics:
    """Build active-transport diagnostics without re-evaluating the tensor flux."""
    T = np.asarray(temperature_K, dtype=np.float64)
    liquid = T >= float(params.material.T_liquidus_K)
    liquid_count = int(np.count_nonzero(liquid))
    active_x_faces = (
        int(np.count_nonzero(liquid[:-1, :, :] & liquid[1:, :, :]))
        if T.shape[0] > 1
        else 0
    )
    active_y_faces = (
        int(np.count_nonzero(liquid[:, :-1, :] & liquid[:, 1:, :]))
        if T.shape[1] > 1
        else 0
    )
    active_liquid_cells = np.zeros_like(liquid, dtype=bool)
    if T.shape[0] > 1:
        face_active_x = liquid[:-1, :, :] & liquid[1:, :, :]
        active_liquid_cells[:-1, :, :] |= face_active_x
        active_liquid_cells[1:, :, :] |= face_active_x
    if T.shape[1] > 1:
        face_active_y = liquid[:, :-1, :] & liquid[:, 1:, :]
        active_liquid_cells[:, :-1, :] |= face_active_y
        active_liquid_cells[:, 1:, :] |= face_active_y
    directional_active_cell_count = int(np.count_nonzero(active_liquid_cells))
    return DirectionalKernelDiagnostics(
        transport_mode=transport_decision.transport_mode,
        accepted_scalar_delegation=False,
        directional_tensor_active=True,
        requested_eta_directional=float(transport_decision.requested_eta_directional),
        effective_eta_directional=float(transport_decision.effective_eta_directional),
        liquid_cell_count=liquid_count,
        directional_active_liquid_cell_count=directional_active_cell_count,
        isotropic_fallback_liquid_cell_count=0,
        directional_active_liquid_fraction=(
            float(directional_active_cell_count / liquid_count) if liquid_count else 0.0
        ),
        isotropic_fallback_liquid_fraction=0.0,
        directional_active_x_face_count=active_x_faces,
        directional_active_y_face_count=active_y_faces,
        internal_directional_energy_change_J_m3_sum=float(
            internal_directional_energy_change_J_m3_sum
        ),
    )


if njit is not None:
    @njit(cache=True)
    def _directional_effective_source_numba_kernel(
        T: np.ndarray,
        q_dot: np.ndarray,
        q_effective: np.ndarray,
        dx: float,
        liquidus_K: float,
        d_xx: float,
        d_xy: float,
        d_yy: float,
    ) -> None:
        """Add the directional divergence to q_dot in W/m^3.

        The face arithmetic mirrors
        ``compute_directional_conduction_correction_energy_density_J_m3`` but
        omits dt, so the result can be passed directly to the accepted scalar
        Numba timestep as an effective volumetric source.  Every internal-face
        exchange is equal and opposite.
        """
        nx, ny, nz = T.shape
        for i in range(nx):
            for j in range(ny):
                for k in range(nz):
                    q_effective[i, j, k] = q_dot[i, j, k]

        if nx > 1:
            for i in range(nx - 1):
                for j in range(ny):
                    for k in range(nz):
                        if T[i, j, k] < liquidus_K or T[i + 1, j, k] < liquidus_K:
                            continue
                        normal_gradient_x = (T[i + 1, j, k] - T[i, j, k]) / dx

                        if ny <= 1:
                            grad_y_left = 0.0
                            grad_y_right = 0.0
                        elif j == 0:
                            grad_y_left = (T[i, 1, k] - T[i, 0, k]) / dx
                            grad_y_right = (T[i + 1, 1, k] - T[i + 1, 0, k]) / dx
                        elif j == ny - 1:
                            grad_y_left = (T[i, ny - 1, k] - T[i, ny - 2, k]) / dx
                            grad_y_right = (T[i + 1, ny - 1, k] - T[i + 1, ny - 2, k]) / dx
                        else:
                            grad_y_left = (T[i, j + 1, k] - T[i, j - 1, k]) / (2.0 * dx)
                            grad_y_right = (T[i + 1, j + 1, k] - T[i + 1, j - 1, k]) / (2.0 * dx)

                        tangential_gradient_y = 0.5 * (grad_y_left + grad_y_right)
                        flux_x = d_xx * normal_gradient_x + d_xy * tangential_gradient_y
                        rate = flux_x / dx
                        q_effective[i, j, k] += rate
                        q_effective[i + 1, j, k] -= rate

        if ny > 1:
            for i in range(nx):
                for j in range(ny - 1):
                    for k in range(nz):
                        if T[i, j, k] < liquidus_K or T[i, j + 1, k] < liquidus_K:
                            continue
                        normal_gradient_y = (T[i, j + 1, k] - T[i, j, k]) / dx

                        if nx <= 1:
                            grad_x_lower = 0.0
                            grad_x_upper = 0.0
                        elif i == 0:
                            grad_x_lower = (T[1, j, k] - T[0, j, k]) / dx
                            grad_x_upper = (T[1, j + 1, k] - T[0, j + 1, k]) / dx
                        elif i == nx - 1:
                            grad_x_lower = (T[nx - 1, j, k] - T[nx - 2, j, k]) / dx
                            grad_x_upper = (T[nx - 1, j + 1, k] - T[nx - 2, j + 1, k]) / dx
                        else:
                            grad_x_lower = (T[i + 1, j, k] - T[i - 1, j, k]) / (2.0 * dx)
                            grad_x_upper = (T[i + 1, j + 1, k] - T[i - 1, j + 1, k]) / (2.0 * dx)

                        tangential_gradient_x = 0.5 * (grad_x_lower + grad_x_upper)
                        flux_y = d_xy * tangential_gradient_x + d_yy * normal_gradient_y
                        rate = flux_y / dx
                        q_effective[i, j, k] += rate
                        q_effective[i, j + 1, k] -= rate
else:  # pragma: no cover
    _directional_effective_source_numba_kernel = None


def explicit_fvm_step_directional_numba(
    temperature_K: np.ndarray,
    volumetric_heat_source_W_m3: np.ndarray,
    params: SimulationParameters,
    *,
    transport_decision: LiquidTransportDecision,
    temperature_out_K: np.ndarray | None = None,
    effective_source_scratch_W_m3: np.ndarray | None = None,
    return_boundary_powers: bool = False,
    return_directional_diagnostics: bool = False,
):
    """Advance one compiled directional timestep through the accepted Numba solver.

    Neutral and fallback decisions delegate *directly* to the accepted scalar
    Numba timestep.  For an active tensor, a compiled Patch 18 face kernel adds
    only ``div(D grad T)`` to a scratch volumetric source, after which the
    accepted scalar Numba timestep owns scalar conduction, source addition,
    external boundaries, boiling loss, and enthalpy inversion.
    """
    if transport_decision.accepted_isotropic_delegation:
        scalar_result = accepted_scalar_solver.explicit_fvm_step_numba(
            temperature_K,
            volumetric_heat_source_W_m3,
            params,
            temperature_out_K=temperature_out_K,
            return_boundary_powers=return_boundary_powers,
        )
        if not return_directional_diagnostics:
            return scalar_result
        diagnostics = directional_usage_diagnostics_for_delegation(
            temperature_K, params, transport_decision
        )
        return scalar_result, diagnostics

    if not accepted_scalar_solver.NUMBA_AVAILABLE or _directional_effective_source_numba_kernel is None:
        return explicit_fvm_step_directional(
            temperature_K,
            volumetric_heat_source_W_m3,
            params,
            transport_decision=transport_decision,
            return_boundary_powers=return_boundary_powers,
            return_directional_diagnostics=return_directional_diagnostics,
        )

    d_xx, d_xy, d_yy = _validate_active_decision_against_parameters(
        transport_decision, params
    )
    T = np.ascontiguousarray(temperature_K, dtype=np.float64)
    q = np.ascontiguousarray(volumetric_heat_source_W_m3, dtype=np.float64)
    if T.shape != q.shape:
        raise DirectionalTensorKernelError(
            "temperature and volumetric heat-source fields must have identical shape"
        )

    if effective_source_scratch_W_m3 is None:
        q_effective = np.empty_like(q)
    else:
        q_effective = effective_source_scratch_W_m3
        if q_effective.shape != q.shape or q_effective.dtype != np.float64:
            raise DirectionalTensorKernelError(
                "effective-source scratch must be float64 with the temperature-field shape"
            )
        if (
            np.shares_memory(q_effective, np.asarray(temperature_K))
            or np.shares_memory(q_effective, np.asarray(volumetric_heat_source_W_m3))
            or (temperature_out_K is not None and np.shares_memory(q_effective, np.asarray(temperature_out_K)))
        ):
            raise DirectionalTensorKernelError(
                "effective-source scratch must not alias temperature, source, or temperature-output storage"
            )
        if not q_effective.flags.c_contiguous:
            raise DirectionalTensorKernelError(
                "effective-source scratch must be C-contiguous"
            )

    dx = float(params.grid.uniform_spacing_m(params.geometry))
    _directional_effective_source_numba_kernel(
        T,
        q,
        q_effective,
        dx,
        float(params.material.T_liquidus_K),
        float(d_xx),
        float(d_xy),
        float(d_yy),
    )

    scalar_result = accepted_scalar_solver.explicit_fvm_step_numba(
        T,
        q_effective,
        params,
        temperature_out_K=temperature_out_K,
        return_boundary_powers=return_boundary_powers,
    )
    if not return_directional_diagnostics:
        return scalar_result

    net_directional_increment = float(
        params.time.dt_s
        * np.sum(q_effective - q, dtype=np.float64)
    )
    diagnostics = _active_directional_usage_diagnostics(
        T,
        params,
        transport_decision,
        internal_directional_energy_change_J_m3_sum=net_directional_increment,
    )
    return scalar_result, diagnostics

def explicit_fvm_step_directional(
    temperature_K: np.ndarray,
    volumetric_heat_source_W_m3: np.ndarray,
    params: SimulationParameters,
    *,
    transport_decision: LiquidTransportDecision,
    return_boundary_powers: bool = False,
    return_directional_diagnostics: bool = False,
):
    """Advance one NumPy timestep with exact scalar delegation when required.

    This is the Patch 18.1 NumPy reference seam.  The compiled counterpart is
    ``explicit_fvm_step_directional_numba``; neither path alters the frozen
    scalar solver core.
    """
    if transport_decision.accepted_isotropic_delegation:
        scalar_result = accepted_scalar_solver.explicit_fvm_step(
            temperature_K,
            volumetric_heat_source_W_m3,
            params,
            return_boundary_powers=return_boundary_powers,
        )
        if not return_directional_diagnostics:
            return scalar_result
        diagnostics = directional_usage_diagnostics_for_delegation(
            temperature_K, params, transport_decision
        )
        return scalar_result, diagnostics

    correction, diagnostics = (
        compute_directional_conduction_correction_energy_density_J_m3(
            temperature_K,
            params,
            transport_decision,
        )
    )

    # Reuse the exact accepted scalar conduction/source/boundary/enthalpy
    # primitives.  Only the conservative directional correction is new.
    dt = float(params.time.dt_s)
    delta_u = accepted_scalar_solver._compute_phase_aware_conduction_energy_density_update(
        temperature_K, params
    )
    delta_u += correction
    delta_u += dt * np.asarray(volumetric_heat_source_W_m3, dtype=np.float64)
    delta_u, boundary_powers = accepted_scalar_solver._apply_boundary_energy_density_fluxes(
        temperature_K, delta_u, params
    )
    T_new = accepted_scalar_solver._apply_enthalpy_energy_density_update(
        temperature_K, delta_u, params
    )

    if params.boundary_conditions.boiling_damper_strength > 0.0:
        if not np.all(np.isfinite(T_new)):
            raise FloatingPointError(
                "Patch 18.1 directional Python step generated nonfinite temperature."
            )
        if np.any(T_new < 0.0):
            raise FloatingPointError(
                "Patch 18.1 directional Python step generated negative enthalpy/temperature state."
            )

    result = (
        (T_new, boundary_powers)
        if return_boundary_powers
        else (T_new, float(boundary_powers["top_loss_power_W"]))
    )
    if return_directional_diagnostics:
        return result, diagnostics
    return result
