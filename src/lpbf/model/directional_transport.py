"""Directional heat-transport design primitives.

Patch 18.0 freezes the mathematical and software contract without activating a
nonzero tensor in the PDE.  The accepted scalar liquid-conductivity closure is
the transverse and build-normal baseline, and a nonnegative directional term
may increase only conductivity along the currently resolved in-plane scan axis.

For accepted scalar liquid conductivity ``k_iso`` and in-plane unit scan vector
``t`` the frozen tensor is ``K = k_iso I + eta_directional k_iso (t outer t)``.
Consequently ``k_parallel = k_iso (1 + eta_directional)`` while transverse and
build-normal conductivity remain ``k_iso``.  ``eta_directional == 0`` and every
unresolved current direction require explicit delegation to the accepted scalar
solver path rather than execution of a mathematically equivalent tensor path.

The closure represents unresolved anisotropic liquid-pool energy transport. It
does not calculate velocity, pressure, free-surface motion, Marangoni flow,
recoil, vapor flow, or keyhole dynamics.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import math
from typing import Any, Sequence

import numpy as np


DIRECTIONAL_ETA_GRID = (0.0, 0.25, 0.50, 0.75, 1.00)
NEUTRAL_DIRECTIONAL_ETA = 0.0
PATCH18_0_MIN_DIRECTIONAL_ETA = 0.0
PATCH18_0_MAX_DIRECTIONAL_ETA = 1.0
DIRECTIONAL_ACTIVATION_DOMAIN = "LIQUID_CELLS_T_GE_T_LIQUIDUS_ONLY"
DIRECTIONAL_DIAGNOSTIC_FIELDS = (
    "local_scan_unit_x",
    "local_scan_unit_y",
    "scan_axis_angle_deg",
    "selected_direction_scale_intervals",
    "fallback_state",
    "unresolved_direction_reason_code",
    "k_parallel_W_mK",
    "k_perpendicular_W_mK",
    "k_build_normal_W_mK",
    "tensor_Kxx_W_mK",
    "tensor_Kxy_W_mK",
    "tensor_Kyy_W_mK",
    "tensor_Kzz_W_mK",
    "directional_active_liquid_fraction",
    "isotropic_fallback_liquid_fraction",
)
SCAN_DIRECTION_WINDOW_INTERVALS = 20
MULTISCALE_SCAN_DIRECTION_INTERVALS = (20, 10, 5, 2)
MINIMUM_SCAN_DISPLACEMENT_MM = 0.005
MAXIMUM_SPLIT_TURN_ANGLE_DEG = 10.0
MINIMUM_CHORD_EFFICIENCY = 0.995
MAXIMUM_CROSS_TRACK_DEVIATION_ABSOLUTE_MM = 0.003
MAXIMUM_CROSS_TRACK_DEVIATION_FRACTION = 0.02
MAXIMUM_ADJACENT_SCALE_AXIS_DISAGREEMENT_DEG = 5.0
PRODUCTION_DAQ_DT_S = 5.0e-6
PRODUCTION_DIRECTIONAL_FALLBACK_POLICY = (
    "CURRENT_INTERVAL_OR_LOCATION_UNRESOLVED_DIRECTION_ISOTROPIC_V1"
)
TRANSPORT_MODE_DIRECTIONAL = "SCAN_ALIGNED_DIRECTIONAL_TENSOR"
TRANSPORT_MODE_ISOTROPIC_NEUTRAL = "ACCEPTED_ISOTROPIC_NEUTRAL_DELEGATION"
TRANSPORT_MODE_ISOTROPIC_FALLBACK = "ACCEPTED_ISOTROPIC_ORIENTATION_FALLBACK"


class DirectionalTransportDesignError(ValueError):
    """Raised when a proposed directional state or scan frame is invalid."""


@dataclass(frozen=True)
class PrincipalLiquidConductivities:
    """Liquid principal conductivities in the local scan frame."""

    parallel_W_mK: float
    perpendicular_W_mK: float
    build_normal_W_mK: float

    @property
    def trace_W_mK(self) -> float:
        return (
            self.parallel_W_mK
            + self.perpendicular_W_mK
            + self.build_normal_W_mK
        )

    @property
    def minimum_W_mK(self) -> float:
        return min(
            self.parallel_W_mK,
            self.perpendicular_W_mK,
            self.build_normal_W_mK,
        )

    @property
    def maximum_W_mK(self) -> float:
        return max(
            self.parallel_W_mK,
            self.perpendicular_W_mK,
            self.build_normal_W_mK,
        )


@dataclass(frozen=True)
class ScanDirectionEstimate:
    """One verified local machine-motion direction and speed estimate."""

    center_row: int
    track_id: int
    start_row: int
    end_row: int
    interval_count: int
    duration_s: float
    displacement_x_mm: float
    displacement_y_mm: float
    speed_mm_s: float
    unit_x: float
    unit_y: float
    directed_angle_deg: float
    undirected_axis_angle_deg: float

    def to_dict(self) -> dict[str, int | float]:
        return {
            "center_row": self.center_row,
            "track_id": self.track_id,
            "start_row": self.start_row,
            "end_row": self.end_row,
            "interval_count": self.interval_count,
            "duration_s": self.duration_s,
            "displacement_x_mm": self.displacement_x_mm,
            "displacement_y_mm": self.displacement_y_mm,
            "speed_mm_s": self.speed_mm_s,
            "unit_x": self.unit_x,
            "unit_y": self.unit_y,
            "directed_angle_deg": self.directed_angle_deg,
            "undirected_axis_angle_deg": self.undirected_axis_angle_deg,
        }


@dataclass(frozen=True)
class ScanStraightnessCandidate:
    """Diagnostics for one candidate displacement-window length."""

    window_intervals: int
    available: bool
    estimate: ScanDirectionEstimate | None
    split_row: int | None
    split_turn_angle_deg: float | None
    chord_efficiency: float | None
    maximum_cross_track_deviation_mm: float | None
    allowed_cross_track_deviation_mm: float | None
    intrinsic_straightness_pass: bool
    adjacent_smaller_window_intervals: int | None
    adjacent_scale_axis_disagreement_deg: float | None
    adjacent_scale_confirmation_pass: bool
    multiscale_straightness_pass: bool
    rejection_reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "window_intervals": self.window_intervals,
            "available": self.available,
            "estimate": None if self.estimate is None else self.estimate.to_dict(),
            "split_row": self.split_row,
            "split_turn_angle_deg": self.split_turn_angle_deg,
            "chord_efficiency": self.chord_efficiency,
            "maximum_cross_track_deviation_mm": (
                self.maximum_cross_track_deviation_mm
            ),
            "allowed_cross_track_deviation_mm": (
                self.allowed_cross_track_deviation_mm
            ),
            "intrinsic_straightness_pass": self.intrinsic_straightness_pass,
            "adjacent_smaller_window_intervals": (
                self.adjacent_smaller_window_intervals
            ),
            "adjacent_scale_axis_disagreement_deg": (
                self.adjacent_scale_axis_disagreement_deg
            ),
            "adjacent_scale_confirmation_pass": (
                self.adjacent_scale_confirmation_pass
            ),
            "multiscale_straightness_pass": self.multiscale_straightness_pass,
            "rejection_reasons": list(self.rejection_reasons),
        }


@dataclass(frozen=True)
class MultiscaleScanDirectionResult:
    """Fail-closed choice of the longest locally straight scan window."""

    center_row: int
    status: str
    selected_estimate: ScanDirectionEstimate | None
    speed_reference_window_intervals: int
    speed_reference_estimate: ScanDirectionEstimate | None
    candidates: tuple[ScanStraightnessCandidate, ...]

    @property
    def straightness_pass(self) -> bool:
        return self.selected_estimate is not None

    @property
    def selected_window_intervals(self) -> int | None:
        if self.selected_estimate is None:
            return None
        return self.selected_estimate.interval_count

    def to_dict(self) -> dict[str, Any]:
        return {
            "center_row": self.center_row,
            "status": self.status,
            "straightness_pass": self.straightness_pass,
            "selected_window_intervals": self.selected_window_intervals,
            "selected_estimate": (
                None
                if self.selected_estimate is None
                else self.selected_estimate.to_dict()
            ),
            "speed_reference_window_intervals": (
                self.speed_reference_window_intervals
            ),
            "speed_reference_estimate": (
                None
                if self.speed_reference_estimate is None
                else self.speed_reference_estimate.to_dict()
            ),
            "candidate_records": [row.to_dict() for row in self.candidates],
        }


@dataclass(frozen=True)
class LiquidTransportDecision:
    """Production transport choice for one interval or spatial location.

    The decision is deliberately stateless: it can use only the current scan
    gate result.  Consequently, an unresolved corner or stationary region
    cannot inherit a previous direction.  ``accepted_isotropic_delegation`` is
    an implementation requirement, not merely a mathematically equivalent
    tensor hint; the future PDE path must call the accepted scalar formulation
    whenever it is true.
    """

    policy_identifier: str
    transport_mode: str
    requested_eta_directional: float
    effective_eta_directional: float
    directional_transport_requested: bool
    directional_tensor_active: bool
    accepted_isotropic_delegation: bool
    isotropic_fallback_active: bool
    orientation_resolved: bool
    orientation_status: str
    unresolved_direction_reason_code: str | None
    selected_window_intervals: int | None
    scan_axis_angle_deg: float | None
    scan_unit_x: float | None
    scan_unit_y: float | None
    principal_parallel_W_mK: float
    principal_perpendicular_W_mK: float
    principal_build_normal_W_mK: float
    liquid_conductivity_tensor_W_mK: tuple[
        tuple[float, float, float],
        tuple[float, float, float],
        tuple[float, float, float],
    ]

    def to_dict(self) -> dict[str, Any]:
        tensor = self.liquid_conductivity_tensor_W_mK
        return {
            "policy_identifier": self.policy_identifier,
            "transport_mode": self.transport_mode,
            "requested_eta_directional": self.requested_eta_directional,
            "effective_eta_directional": self.effective_eta_directional,
            "directional_transport_requested": (
                self.directional_transport_requested
            ),
            "directional_tensor_active": self.directional_tensor_active,
            "accepted_isotropic_delegation": (
                self.accepted_isotropic_delegation
            ),
            "isotropic_fallback_active": self.isotropic_fallback_active,
            "orientation_resolved": self.orientation_resolved,
            "orientation_status": self.orientation_status,
            "unresolved_direction_reason_code": (
                self.unresolved_direction_reason_code
            ),
            "selected_window_intervals": self.selected_window_intervals,
            "scan_axis_angle_deg": self.scan_axis_angle_deg,
            "scan_unit_x": self.scan_unit_x,
            "scan_unit_y": self.scan_unit_y,
            "local_scan_unit_x": self.scan_unit_x,
            "local_scan_unit_y": self.scan_unit_y,
            "selected_direction_scale_intervals": self.selected_window_intervals,
            "fallback_state": self.isotropic_fallback_active,
            "principal_parallel_W_mK": self.principal_parallel_W_mK,
            "principal_perpendicular_W_mK": self.principal_perpendicular_W_mK,
            "principal_build_normal_W_mK": self.principal_build_normal_W_mK,
            "k_parallel_W_mK": self.principal_parallel_W_mK,
            "k_perpendicular_W_mK": self.principal_perpendicular_W_mK,
            "k_build_normal_W_mK": self.principal_build_normal_W_mK,
            "tensor_Kxx_W_mK": tensor[0][0],
            "tensor_Kxy_W_mK": tensor[0][1],
            "tensor_Kyy_W_mK": tensor[1][1],
            "tensor_Kzz_W_mK": tensor[2][2],
            "liquid_conductivity_tensor_W_mK": [list(row) for row in tensor],
            "decision_scope": "current_interval_or_location_only",
            "next_state_policy": "reevaluate_current_scan_gate_do_not_hold_direction",
        }


def _finite_float(name: str, value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise DirectionalTransportDesignError(f"{name} must be numeric") from exc
    if not math.isfinite(result):
        raise DirectionalTransportDesignError(f"{name} must be finite")
    return result


def accepted_isotropic_liquid_conductivity_W_mK(
    *,
    physical_liquid_conductivity_W_mK: float,
    isotropic_enhancement_factor: float,
) -> float:
    """Return the accepted scalar liquid conductivity ``k_iso = C_k k_l``."""
    k_liquid = _finite_float(
        "physical_liquid_conductivity_W_mK",
        physical_liquid_conductivity_W_mK,
    )
    enhancement = _finite_float(
        "isotropic_enhancement_factor", isotropic_enhancement_factor
    )
    if k_liquid <= 0.0:
        raise DirectionalTransportDesignError(
            "physical_liquid_conductivity_W_mK must be positive"
        )
    if enhancement < 1.0:
        raise DirectionalTransportDesignError(
            "isotropic_enhancement_factor must be at least 1"
        )
    return float(k_liquid * enhancement)


def principal_liquid_conductivities(
    *,
    physical_liquid_conductivity_W_mK: float,
    isotropic_enhancement_factor: float,
    eta: float,
) -> PrincipalLiquidConductivities:
    """Return the Patch 18.0 frozen scan-frame principal conductivities.

    Let ``k_iso = C_k k_l`` be the accepted scalar liquid conductivity.  The
    directional term is strictly additive along the resolved scan axis:

    ``k_parallel = k_iso * (1 + eta)``
    ``k_perpendicular = k_iso``
    ``k_z = k_iso``

    Patch 18.0 freezes the conservative implementation/verification range to
    ``0 <= eta <= 1``.  This is not a fitted range or a preferred value.
    """
    k_iso = accepted_isotropic_liquid_conductivity_W_mK(
        physical_liquid_conductivity_W_mK=physical_liquid_conductivity_W_mK,
        isotropic_enhancement_factor=isotropic_enhancement_factor,
    )
    eta_value = _finite_float("eta", eta)
    if not (
        PATCH18_0_MIN_DIRECTIONAL_ETA
        <= eta_value
        <= PATCH18_0_MAX_DIRECTIONAL_ETA
    ):
        raise DirectionalTransportDesignError("eta must be within [0, 1]")

    return PrincipalLiquidConductivities(
        parallel_W_mK=k_iso * (1.0 + eta_value),
        perpendicular_W_mK=k_iso,
        build_normal_W_mK=k_iso,
    )


def rotated_liquid_conductivity_tensor_W_mK(
    *,
    physical_liquid_conductivity_W_mK: float,
    isotropic_enhancement_factor: float,
    eta: float,
    scan_axis_angle_deg: float,
) -> np.ndarray:
    """Return the 3x3 conductivity tensor in fixed local x/y/z coordinates.

    The scan axis lies in the top-surface x/y plane and is undirected.  Local
    x/y remain parallel to X-Machine/Y-Machine; +z is the build-surface normal.
    Tensor rotation therefore follows the measured scan, not the filename,
    coupon orientation, or whichever global axis happens to be dominant.
    """
    principal = principal_liquid_conductivities(
        physical_liquid_conductivity_W_mK=physical_liquid_conductivity_W_mK,
        isotropic_enhancement_factor=isotropic_enhancement_factor,
        eta=eta,
    )
    angle_deg = _finite_float("scan_axis_angle_deg", scan_axis_angle_deg) % 180.0
    if float(eta) == NEUTRAL_DIRECTIONAL_ETA:
        # Preserve an exactly diagonal neutral tensor without trigonometric
        # roundoff.  The future timestep must delegate to the frozen isotropic
        # solver at eta=0 for field-level, not merely mathematical, equivalence.
        return np.diag(
            np.asarray(
                [
                    principal.parallel_W_mK,
                    principal.perpendicular_W_mK,
                    principal.build_normal_W_mK,
                ],
                dtype=np.float64,
            )
        )

    angle_rad = math.radians(angle_deg)
    scan = np.asarray(
        [math.cos(angle_rad), math.sin(angle_rad), 0.0], dtype=np.float64
    )
    k_iso = principal.perpendicular_W_mK
    tensor = k_iso * np.eye(3, dtype=np.float64) + (
        float(eta) * k_iso * np.outer(scan, scan)
    )
    return np.asarray(tensor, dtype=np.float64)


def directional_explicit_stability_record(
    *,
    density_kg_m3: float,
    cp_solid_J_kgK: float,
    cp_mushy_effective_J_kgK: float,
    cp_liquid_J_kgK: float,
    k_solid_W_mK: float,
    k_mushy_W_mK: float,
    physical_liquid_conductivity_W_mK: float,
    isotropic_enhancement_factor: float,
    eta: float,
    scan_axis_angle_deg: float,
    grid_spacing_m: float,
    selected_dt_s: float,
    safety_factor: float,
) -> dict[str, float | bool | str | list[list[float]]]:
    """Return a conservative explicit bound for the proposed rotated stencil.

    For the planned conservative face-flux discretization, a Gershgorin bound
    for the liquid operator is

    ``dt <= rho*cp*dx^2 / (2*(Kxx + Kyy + Kzz + 2*abs(Kxy)))``.

    It reduces exactly to ``rho*cp*dx^2/(6*k)`` in the isotropic state.  The
    minimum of the solid, mushy, and liquid bounds is then multiplied by the
    accepted safety factor.  Passing this design bound is necessary but not
    sufficient to authorize the future tensor kernel.
    """
    rho = _finite_float("density_kg_m3", density_kg_m3)
    cp_solid = _finite_float("cp_solid_J_kgK", cp_solid_J_kgK)
    cp_mushy = _finite_float(
        "cp_mushy_effective_J_kgK", cp_mushy_effective_J_kgK
    )
    cp_liquid = _finite_float("cp_liquid_J_kgK", cp_liquid_J_kgK)
    k_solid = _finite_float("k_solid_W_mK", k_solid_W_mK)
    k_mushy = _finite_float("k_mushy_W_mK", k_mushy_W_mK)
    dx = _finite_float("grid_spacing_m", grid_spacing_m)
    dt = _finite_float("selected_dt_s", selected_dt_s)
    safety = _finite_float("safety_factor", safety_factor)
    positive = (rho, cp_solid, cp_mushy, cp_liquid, k_solid, k_mushy, dx, dt)
    if any(value <= 0.0 for value in positive):
        raise DirectionalTransportDesignError(
            "density, heat capacities, conductivities, spacing, and dt must be positive"
        )
    if not 0.0 < safety <= 1.0:
        raise DirectionalTransportDesignError("safety_factor must be within (0, 1]")

    tensor = rotated_liquid_conductivity_tensor_W_mK(
        physical_liquid_conductivity_W_mK=physical_liquid_conductivity_W_mK,
        isotropic_enhancement_factor=isotropic_enhancement_factor,
        eta=eta,
        scan_axis_angle_deg=scan_axis_angle_deg,
    )
    denominator_liquid = 2.0 * (
        tensor[0, 0]
        + tensor[1, 1]
        + tensor[2, 2]
        + 2.0 * abs(tensor[0, 1])
    )
    raw_solid_s = rho * cp_solid * dx**2 / (6.0 * k_solid)
    raw_mushy_s = rho * cp_mushy * dx**2 / (6.0 * k_mushy)
    raw_liquid_s = rho * cp_liquid * dx**2 / denominator_liquid
    raw_limit_s = min(raw_solid_s, raw_mushy_s, raw_liquid_s)
    safe_limit_s = safety * raw_limit_s
    eigenvalues = np.linalg.eigvalsh(tensor)
    symmetric = bool(np.array_equal(tensor, tensor.T))
    positive_definite = bool(np.all(eigenvalues > 0.0))
    passes = bool(symmetric and positive_definite and dt <= safe_limit_s)
    return {
        "eta": float(eta),
        "scan_axis_angle_deg": float(scan_axis_angle_deg) % 180.0,
        "tensor_W_mK": tensor.tolist(),
        "tensor_trace_W_mK": float(np.trace(tensor)),
        "tensor_eigenvalues_W_mK": [float(value) for value in eigenvalues],
        "tensor_symmetric": symmetric,
        "tensor_positive_definite": positive_definite,
        "solid_raw_limit_s": float(raw_solid_s),
        "mushy_raw_limit_s": float(raw_mushy_s),
        "liquid_raw_limit_s": float(raw_liquid_s),
        "raw_explicit_limit_s": float(raw_limit_s),
        "safe_explicit_limit_s": float(safe_limit_s),
        "selected_dt_s": dt,
        "selected_over_safe_limit": float(dt / safe_limit_s),
        "stability_bound_role": "conservative_design_preflight_not_kernel_validation",
        "status": "PASS" if passes else "FAIL_CLOSED",
    }


def estimate_local_scan_direction(
    x_machine_mm: np.ndarray,
    y_machine_mm: np.ndarray,
    laser_on: np.ndarray,
    *,
    center_row: int,
    scan_track_id: np.ndarray | None = None,
    window_intervals: int = SCAN_DIRECTION_WINDOW_INTERVALS,
    dt_s: float = PRODUCTION_DAQ_DT_S,
) -> ScanDirectionEstimate:
    """Estimate the local scan frame with one centered 20-interval displacement.

    At the 200 kHz production clock, 20 intervals span 100 microseconds.  The
    window is shifted, without changing its length, when the requested row is
    near a track endpoint.  It may never cross a laser-off row or track
    boundary.  Nominal speed is not used to select or validate the window.
    """
    x = np.asarray(x_machine_mm, dtype=np.float64)
    y = np.asarray(y_machine_mm, dtype=np.float64)
    powered = np.asarray(laser_on, dtype=bool)
    if x.ndim != 1 or y.ndim != 1 or powered.ndim != 1:
        raise DirectionalTransportDesignError(
            "x_machine_mm, y_machine_mm, and laser_on must be one-dimensional"
        )
    if not (x.size == y.size == powered.size):
        raise DirectionalTransportDesignError(
            "x_machine_mm, y_machine_mm, and laser_on must have equal length"
        )
    row = int(center_row)
    if row < 0 or row >= x.size:
        raise DirectionalTransportDesignError("center_row is outside the process data")
    if not powered[row]:
        raise DirectionalTransportDesignError("center_row must be laser-on")
    intervals = int(window_intervals)
    if intervals < 1:
        raise DirectionalTransportDesignError("window_intervals must be positive")
    sample_dt_s = _finite_float("dt_s", dt_s)
    if sample_dt_s <= 0.0:
        raise DirectionalTransportDesignError("dt_s must be positive")

    if scan_track_id is None:
        track = np.zeros(powered.shape, dtype=np.int64)
        next_id = 0
        in_track = False
        for index, is_on in enumerate(powered):
            if is_on and not in_track:
                next_id += 1
                in_track = True
            elif not is_on:
                in_track = False
            if is_on:
                track[index] = next_id
    else:
        track = np.asarray(scan_track_id, dtype=np.int64)
        if track.shape != powered.shape:
            raise DirectionalTransportDesignError(
                "scan_track_id must match the process-row shape"
            )
    track_value = int(track[row])
    if track_value <= 0:
        raise DirectionalTransportDesignError(
            "center_row does not have a positive powered scan-track id"
        )
    positions = np.flatnonzero((track == track_value) & powered)
    if positions.size == 0 or not np.all(np.diff(positions) == 1):
        raise DirectionalTransportDesignError(
            "powered scan-track rows must form one contiguous segment"
        )
    track_start = int(positions[0])
    track_end = int(positions[-1])
    if track_end - track_start < intervals:
        raise DirectionalTransportDesignError(
            f"scan track is shorter than the required {intervals}-interval window"
        )

    start = row - intervals // 2
    start = max(track_start, min(start, track_end - intervals))
    end = start + intervals
    if not np.all(powered[start : end + 1]) or not np.all(
        track[start : end + 1] == track_value
    ):
        raise DirectionalTransportDesignError(
            "scan-direction window crossed a laser transition or track boundary"
        )
    endpoints = np.asarray([x[start], y[start], x[end], y[end]])
    if not np.all(np.isfinite(endpoints)):
        raise DirectionalTransportDesignError(
            "scan-direction window endpoints must be finite"
        )
    displacement_x = float(x[end] - x[start])
    displacement_y = float(y[end] - y[start])
    distance_mm = float(math.hypot(displacement_x, displacement_y))
    if distance_mm <= np.finfo(np.float64).eps:
        raise DirectionalTransportDesignError(
            "scan-direction displacement is zero or numerically unresolved"
        )
    duration_s = intervals * sample_dt_s
    directed_angle_deg = math.degrees(
        math.atan2(displacement_y, displacement_x)
    ) % 360.0
    return ScanDirectionEstimate(
        center_row=row,
        track_id=track_value,
        start_row=start,
        end_row=end,
        interval_count=intervals,
        duration_s=duration_s,
        displacement_x_mm=displacement_x,
        displacement_y_mm=displacement_y,
        speed_mm_s=distance_mm / duration_s,
        unit_x=displacement_x / distance_mm,
        unit_y=displacement_y / distance_mm,
        directed_angle_deg=float(directed_angle_deg),
        undirected_axis_angle_deg=float(directed_angle_deg % 180.0),
    )


def _directed_vector_turn_angle_deg(
    first_x: float,
    first_y: float,
    second_x: float,
    second_y: float,
) -> float:
    first_norm = math.hypot(first_x, first_y)
    second_norm = math.hypot(second_x, second_y)
    if first_norm <= np.finfo(np.float64).eps or second_norm <= np.finfo(
        np.float64
    ).eps:
        raise DirectionalTransportDesignError(
            "split-window displacement is zero or numerically unresolved"
        )
    cosine = (first_x * second_x + first_y * second_y) / (
        first_norm * second_norm
    )
    return float(math.degrees(math.acos(max(-1.0, min(1.0, cosine)))))


def _straightness_candidate(
    x_machine_mm: np.ndarray,
    y_machine_mm: np.ndarray,
    laser_on: np.ndarray,
    *,
    center_row: int,
    scan_track_id: np.ndarray | None,
    window_intervals: int,
    dt_s: float,
    minimum_net_displacement_mm: float,
    maximum_split_turn_angle_deg: float,
    minimum_chord_efficiency: float,
    maximum_cross_track_deviation_absolute_mm: float,
    maximum_cross_track_deviation_fraction: float,
) -> ScanStraightnessCandidate:
    try:
        estimate = estimate_local_scan_direction(
            x_machine_mm,
            y_machine_mm,
            laser_on,
            center_row=center_row,
            scan_track_id=scan_track_id,
            window_intervals=window_intervals,
            dt_s=dt_s,
        )
        x = np.asarray(x_machine_mm, dtype=np.float64)
        y = np.asarray(y_machine_mm, dtype=np.float64)
        points = np.column_stack(
            (
                x[estimate.start_row : estimate.end_row + 1],
                y[estimate.start_row : estimate.end_row + 1],
            )
        )
        if not np.all(np.isfinite(points)):
            raise DirectionalTransportDesignError(
                "scan-direction window contains non-finite machine positions"
            )

        split_row = estimate.start_row + estimate.interval_count // 2
        first_x = float(x[split_row] - x[estimate.start_row])
        first_y = float(y[split_row] - y[estimate.start_row])
        second_x = float(x[estimate.end_row] - x[split_row])
        second_y = float(y[estimate.end_row] - y[split_row])
        first_distance = math.hypot(first_x, first_y)
        second_distance = math.hypot(second_x, second_y)
        split_turn_angle_deg = _directed_vector_turn_angle_deg(
            first_x,
            first_y,
            second_x,
            second_y,
        )
        net_distance = math.hypot(
            estimate.displacement_x_mm, estimate.displacement_y_mm
        )
        chord_efficiency = min(
            1.0, net_distance / (first_distance + second_distance)
        )

        relative = points - points[0]
        cross_products = np.abs(
            relative[:, 0] * estimate.displacement_y_mm
            - relative[:, 1] * estimate.displacement_x_mm
        )
        maximum_cross_track_deviation_mm = float(
            np.max(cross_products) / net_distance
        )
        allowed_cross_track_deviation_mm = float(
            maximum_cross_track_deviation_absolute_mm
            + maximum_cross_track_deviation_fraction * net_distance
        )
        reasons: list[str] = []
        if net_distance < minimum_net_displacement_mm:
            reasons.append("net_displacement_below_minimum")
        if split_turn_angle_deg > maximum_split_turn_angle_deg:
            reasons.append("split_turn_angle_exceeds_limit")
        if chord_efficiency < minimum_chord_efficiency:
            reasons.append("chord_efficiency_below_minimum")
        if (
            maximum_cross_track_deviation_mm
            > allowed_cross_track_deviation_mm
        ):
            reasons.append("cross_track_deviation_exceeds_limit")
        intrinsic_pass = not reasons
        return ScanStraightnessCandidate(
            window_intervals=int(window_intervals),
            available=True,
            estimate=estimate,
            split_row=split_row,
            split_turn_angle_deg=split_turn_angle_deg,
            chord_efficiency=float(chord_efficiency),
            maximum_cross_track_deviation_mm=(
                maximum_cross_track_deviation_mm
            ),
            allowed_cross_track_deviation_mm=allowed_cross_track_deviation_mm,
            intrinsic_straightness_pass=intrinsic_pass,
            adjacent_smaller_window_intervals=None,
            adjacent_scale_axis_disagreement_deg=None,
            adjacent_scale_confirmation_pass=False,
            multiscale_straightness_pass=False,
            rejection_reasons=tuple(reasons),
        )
    except DirectionalTransportDesignError as exc:
        return ScanStraightnessCandidate(
            window_intervals=int(window_intervals),
            available=False,
            estimate=None,
            split_row=None,
            split_turn_angle_deg=None,
            chord_efficiency=None,
            maximum_cross_track_deviation_mm=None,
            allowed_cross_track_deviation_mm=None,
            intrinsic_straightness_pass=False,
            adjacent_smaller_window_intervals=None,
            adjacent_scale_axis_disagreement_deg=None,
            adjacent_scale_confirmation_pass=False,
            multiscale_straightness_pass=False,
            rejection_reasons=(f"unavailable:{exc}",),
        )


def estimate_multiscale_scan_direction(
    x_machine_mm: np.ndarray,
    y_machine_mm: np.ndarray,
    laser_on: np.ndarray,
    *,
    center_row: int,
    scan_track_id: np.ndarray | None = None,
    candidate_window_intervals: Sequence[int] = MULTISCALE_SCAN_DIRECTION_INTERVALS,
    speed_reference_window_intervals: int = SCAN_DIRECTION_WINDOW_INTERVALS,
    dt_s: float = PRODUCTION_DAQ_DT_S,
    minimum_net_displacement_mm: float = MINIMUM_SCAN_DISPLACEMENT_MM,
    maximum_split_turn_angle_deg: float = MAXIMUM_SPLIT_TURN_ANGLE_DEG,
    minimum_chord_efficiency: float = MINIMUM_CHORD_EFFICIENCY,
    maximum_cross_track_deviation_absolute_mm: float = (
        MAXIMUM_CROSS_TRACK_DEVIATION_ABSOLUTE_MM
    ),
    maximum_cross_track_deviation_fraction: float = (
        MAXIMUM_CROSS_TRACK_DEVIATION_FRACTION
    ),
    maximum_adjacent_scale_axis_disagreement_deg: float = (
        MAXIMUM_ADJACENT_SCALE_AXIS_DISAGREEMENT_DEG
    ),
) -> MultiscaleScanDirectionResult:
    """Choose the longest straight scan window and reject unresolved corners.

    Each candidate must pass displacement, split-turn, chord-efficiency, and
    cross-track-deviation checks.  Every candidate except the shortest must
    also agree with the immediately smaller scale, which must itself be
    intrinsically straight.  The 20-interval estimate remains a separately
    reported 100-microsecond speed reference even when a shorter orientation
    window is selected.
    """
    windows = tuple(int(value) for value in candidate_window_intervals)
    if not windows or any(value < 2 for value in windows):
        raise DirectionalTransportDesignError(
            "candidate_window_intervals must contain values of at least 2"
        )
    if len(set(windows)) != len(windows) or any(
        left <= right for left, right in zip(windows, windows[1:])
    ):
        raise DirectionalTransportDesignError(
            "candidate_window_intervals must be unique and strictly decreasing"
        )
    reference_intervals = int(speed_reference_window_intervals)
    if reference_intervals not in windows:
        raise DirectionalTransportDesignError(
            "speed_reference_window_intervals must be one candidate window"
        )

    minimum_displacement = _finite_float(
        "minimum_net_displacement_mm", minimum_net_displacement_mm
    )
    maximum_turn = _finite_float(
        "maximum_split_turn_angle_deg", maximum_split_turn_angle_deg
    )
    minimum_efficiency = _finite_float(
        "minimum_chord_efficiency", minimum_chord_efficiency
    )
    maximum_deviation_absolute = _finite_float(
        "maximum_cross_track_deviation_absolute_mm",
        maximum_cross_track_deviation_absolute_mm,
    )
    maximum_deviation_fraction = _finite_float(
        "maximum_cross_track_deviation_fraction",
        maximum_cross_track_deviation_fraction,
    )
    maximum_scale_disagreement = _finite_float(
        "maximum_adjacent_scale_axis_disagreement_deg",
        maximum_adjacent_scale_axis_disagreement_deg,
    )
    if minimum_displacement <= 0.0:
        raise DirectionalTransportDesignError(
            "minimum_net_displacement_mm must be positive"
        )
    if not 0.0 <= maximum_turn < 180.0:
        raise DirectionalTransportDesignError(
            "maximum_split_turn_angle_deg must be within [0, 180)"
        )
    if not 0.0 < minimum_efficiency <= 1.0:
        raise DirectionalTransportDesignError(
            "minimum_chord_efficiency must be within (0, 1]"
        )
    if maximum_deviation_absolute < 0.0 or maximum_deviation_fraction < 0.0:
        raise DirectionalTransportDesignError(
            "cross-track deviation allowances must be nonnegative"
        )
    if not 0.0 <= maximum_scale_disagreement <= 90.0:
        raise DirectionalTransportDesignError(
            "maximum adjacent-scale axis disagreement must be within [0, 90]"
        )

    raw_candidates = [
        _straightness_candidate(
            x_machine_mm,
            y_machine_mm,
            laser_on,
            center_row=center_row,
            scan_track_id=scan_track_id,
            window_intervals=window,
            dt_s=dt_s,
            minimum_net_displacement_mm=minimum_displacement,
            maximum_split_turn_angle_deg=maximum_turn,
            minimum_chord_efficiency=minimum_efficiency,
            maximum_cross_track_deviation_absolute_mm=(
                maximum_deviation_absolute
            ),
            maximum_cross_track_deviation_fraction=maximum_deviation_fraction,
        )
        for window in windows
    ]
    candidates: list[ScanStraightnessCandidate] = []
    for index, candidate in enumerate(raw_candidates):
        reasons = list(candidate.rejection_reasons)
        smaller = raw_candidates[index + 1] if index + 1 < len(raw_candidates) else None
        if smaller is None:
            scale_confirmation_pass = True
            smaller_intervals = None
            scale_disagreement = None
        else:
            smaller_intervals = smaller.window_intervals
            if (
                candidate.estimate is None
                or smaller.estimate is None
                or not smaller.intrinsic_straightness_pass
            ):
                scale_confirmation_pass = False
                scale_disagreement = None
                reasons.append("adjacent_smaller_scale_not_straight")
            else:
                scale_disagreement = acute_axis_misalignment_deg(
                    candidate.estimate.undirected_axis_angle_deg,
                    smaller.estimate.undirected_axis_angle_deg,
                )
                scale_confirmation_pass = bool(
                    scale_disagreement <= maximum_scale_disagreement
                )
                if not scale_confirmation_pass:
                    reasons.append("adjacent_scale_axis_disagreement_exceeds_limit")
        multiscale_pass = bool(
            candidate.intrinsic_straightness_pass and scale_confirmation_pass
        )
        candidates.append(
            replace(
                candidate,
                adjacent_smaller_window_intervals=smaller_intervals,
                adjacent_scale_axis_disagreement_deg=scale_disagreement,
                adjacent_scale_confirmation_pass=scale_confirmation_pass,
                multiscale_straightness_pass=multiscale_pass,
                rejection_reasons=tuple(dict.fromkeys(reasons)),
            )
        )

    selected = next(
        (
            row.estimate
            for row in candidates
            if row.multiscale_straightness_pass and row.estimate is not None
        ),
        None,
    )
    try:
        # Keep the established endpoint-displacement velocity diagnostic
        # independent of the straightness tests.  A curved or stopped path may
        # be invalid for tensor orientation while its fixed-window reference
        # remains useful evidence of why the row was rejected.
        speed_reference = estimate_local_scan_direction(
            x_machine_mm,
            y_machine_mm,
            laser_on,
            center_row=center_row,
            scan_track_id=scan_track_id,
            window_intervals=reference_intervals,
            dt_s=dt_s,
        )
    except DirectionalTransportDesignError:
        speed_reference = None
    return MultiscaleScanDirectionResult(
        center_row=int(center_row),
        status=(
            "PASS_MULTISCALE_SCAN_STRAIGHTNESS"
            if selected is not None
            else "FAIL_CLOSED_NO_STRAIGHT_SCAN_SCALE"
        ),
        selected_estimate=selected,
        speed_reference_window_intervals=reference_intervals,
        speed_reference_estimate=speed_reference,
        candidates=tuple(candidates),
    )


def unresolved_scan_direction_reason_code(
    result: MultiscaleScanDirectionResult | None,
) -> str | None:
    """Classify why the current scan frame cannot orient a tensor.

    This classification affects diagnostics only.  Every unresolved class has
    the same production action: use the accepted isotropic liquid-conductivity
    formulation for the current interval or location and reevaluate the gate
    at the next state.
    """
    if result is not None and result.selected_estimate is not None:
        return None
    if result is None:
        return "ORIENTATION_RESULT_UNAVAILABLE"

    reasons = tuple(
        reason
        for candidate in result.candidates
        for reason in candidate.rejection_reasons
    )
    corner_markers = (
        "split_turn_angle_exceeds_limit",
        "chord_efficiency_below_minimum",
        "cross_track_deviation_exceeds_limit",
        "adjacent_scale_axis_disagreement_exceeds_limit",
    )
    if any(marker in reason for reason in reasons for marker in corner_markers):
        return "CORNER_OR_NONSTRAIGHT_PATH"
    stationary_markers = (
        "net_displacement_below_minimum",
        "displacement is zero or numerically unresolved",
        "split-window displacement is zero or numerically unresolved",
    )
    if any(marker in reason for reason in reasons for marker in stationary_markers):
        return "STATIONARY_OR_NEAR_STATIONARY_PATH"
    if any("scan track is shorter" in reason for reason in reasons):
        return "INSUFFICIENT_TRAJECTORY_LENGTH"
    return "OTHER_KINEMATIC_DEGENERACY"


def _tensor_as_tuple(
    tensor: np.ndarray,
) -> tuple[
    tuple[float, float, float],
    tuple[float, float, float],
    tuple[float, float, float],
]:
    array = np.asarray(tensor, dtype=np.float64)
    if array.shape != (3, 3):
        raise DirectionalTransportDesignError(
            "liquid conductivity tensor must have shape (3, 3)"
        )
    return tuple(tuple(float(value) for value in row) for row in array)  # type: ignore[return-value]


def resolve_liquid_transport_decision(
    *,
    physical_liquid_conductivity_W_mK: float,
    isotropic_enhancement_factor: float,
    eta_directional: float,
    scan_direction_result: MultiscaleScanDirectionResult | None,
) -> LiquidTransportDecision:
    """Choose scan-aligned transport or deterministic accepted-isotropic use.

    ``eta_directional == 0`` always requires exact delegation to the accepted
    isotropic scalar solver, whether or not a scan direction is available.
    For nonzero eta, a tensor is active only when the current multiscale gate
    supplies a trustworthy direction.  Any unresolved current state falls
    back to the same accepted isotropic liquid conductivity.  No Cartesian
    direction is invented, no diagonal is inferred across a corner, and no
    previous orientation is accepted as an input to this stateless policy.
    """
    eta_value = _finite_float("eta_directional", eta_directional)
    principal = principal_liquid_conductivities(
        physical_liquid_conductivity_W_mK=(
            physical_liquid_conductivity_W_mK
        ),
        isotropic_enhancement_factor=isotropic_enhancement_factor,
        eta=eta_value,
    )
    isotropic_k = accepted_isotropic_liquid_conductivity_W_mK(
        physical_liquid_conductivity_W_mK=physical_liquid_conductivity_W_mK,
        isotropic_enhancement_factor=isotropic_enhancement_factor,
    )
    isotropic_tensor = _tensor_as_tuple(
        np.diag(np.asarray([isotropic_k, isotropic_k, isotropic_k]))
    )
    orientation_resolved = bool(
        scan_direction_result is not None
        and scan_direction_result.selected_estimate is not None
    )
    orientation_status = (
        "NO_ORIENTATION_RESULT"
        if scan_direction_result is None
        else str(scan_direction_result.status)
    )
    reason_code = unresolved_scan_direction_reason_code(scan_direction_result)

    if eta_value == NEUTRAL_DIRECTIONAL_ETA:
        return LiquidTransportDecision(
            policy_identifier=PRODUCTION_DIRECTIONAL_FALLBACK_POLICY,
            transport_mode=TRANSPORT_MODE_ISOTROPIC_NEUTRAL,
            requested_eta_directional=eta_value,
            effective_eta_directional=NEUTRAL_DIRECTIONAL_ETA,
            directional_transport_requested=False,
            directional_tensor_active=False,
            accepted_isotropic_delegation=True,
            isotropic_fallback_active=False,
            orientation_resolved=orientation_resolved,
            orientation_status=orientation_status,
            unresolved_direction_reason_code=reason_code,
            selected_window_intervals=(
                None
                if scan_direction_result is None
                else scan_direction_result.selected_window_intervals
            ),
            scan_axis_angle_deg=(
                None
                if not orientation_resolved
                else float(
                    scan_direction_result.selected_estimate.undirected_axis_angle_deg
                )
            ),
            scan_unit_x=(
                None
                if not orientation_resolved
                else float(scan_direction_result.selected_estimate.unit_x)
            ),
            scan_unit_y=(
                None
                if not orientation_resolved
                else float(scan_direction_result.selected_estimate.unit_y)
            ),
            principal_parallel_W_mK=isotropic_k,
            principal_perpendicular_W_mK=isotropic_k,
            principal_build_normal_W_mK=isotropic_k,
            liquid_conductivity_tensor_W_mK=isotropic_tensor,
        )

    if not orientation_resolved:
        return LiquidTransportDecision(
            policy_identifier=PRODUCTION_DIRECTIONAL_FALLBACK_POLICY,
            transport_mode=TRANSPORT_MODE_ISOTROPIC_FALLBACK,
            requested_eta_directional=eta_value,
            effective_eta_directional=NEUTRAL_DIRECTIONAL_ETA,
            directional_transport_requested=True,
            directional_tensor_active=False,
            accepted_isotropic_delegation=True,
            isotropic_fallback_active=True,
            orientation_resolved=False,
            orientation_status=orientation_status,
            unresolved_direction_reason_code=reason_code,
            selected_window_intervals=None,
            scan_axis_angle_deg=None,
            scan_unit_x=None,
            scan_unit_y=None,
            principal_parallel_W_mK=isotropic_k,
            principal_perpendicular_W_mK=isotropic_k,
            principal_build_normal_W_mK=isotropic_k,
            liquid_conductivity_tensor_W_mK=isotropic_tensor,
        )

    assert scan_direction_result is not None
    assert scan_direction_result.selected_estimate is not None
    angle_deg = float(
        scan_direction_result.selected_estimate.undirected_axis_angle_deg
    )
    tensor = rotated_liquid_conductivity_tensor_W_mK(
        physical_liquid_conductivity_W_mK=(
            physical_liquid_conductivity_W_mK
        ),
        isotropic_enhancement_factor=isotropic_enhancement_factor,
        eta=eta_value,
        scan_axis_angle_deg=angle_deg,
    )
    if principal.minimum_W_mK <= 0.0:
        raise DirectionalTransportDesignError(
            "directional principal conductivity must remain positive"
        )
    return LiquidTransportDecision(
        policy_identifier=PRODUCTION_DIRECTIONAL_FALLBACK_POLICY,
        transport_mode=TRANSPORT_MODE_DIRECTIONAL,
        requested_eta_directional=eta_value,
        effective_eta_directional=eta_value,
        directional_transport_requested=True,
        directional_tensor_active=True,
        accepted_isotropic_delegation=False,
        isotropic_fallback_active=False,
        orientation_resolved=True,
        orientation_status=orientation_status,
        unresolved_direction_reason_code=None,
        selected_window_intervals=(
            scan_direction_result.selected_window_intervals
        ),
        scan_axis_angle_deg=angle_deg,
        scan_unit_x=float(scan_direction_result.selected_estimate.unit_x),
        scan_unit_y=float(scan_direction_result.selected_estimate.unit_y),
        principal_parallel_W_mK=principal.parallel_W_mK,
        principal_perpendicular_W_mK=principal.perpendicular_W_mK,
        principal_build_normal_W_mK=principal.build_normal_W_mK,
        liquid_conductivity_tensor_W_mK=_tensor_as_tuple(tensor),
    )


def acute_axis_misalignment_deg(angle_a_deg: float, angle_b_deg: float) -> float:
    """Return the acute separation of two undirected axes in degrees."""
    first = _finite_float("angle_a_deg", angle_a_deg) % 180.0
    second = _finite_float("angle_b_deg", angle_b_deg) % 180.0
    separation = abs(first - second)
    return float(min(separation, 180.0 - separation))


__all__ = (
    "DIRECTIONAL_ACTIVATION_DOMAIN",
    "DIRECTIONAL_DIAGNOSTIC_FIELDS",
    "DIRECTIONAL_ETA_GRID",
    "DirectionalTransportDesignError",
    "LiquidTransportDecision",
    "MAXIMUM_ADJACENT_SCALE_AXIS_DISAGREEMENT_DEG",
    "MAXIMUM_CROSS_TRACK_DEVIATION_ABSOLUTE_MM",
    "MAXIMUM_CROSS_TRACK_DEVIATION_FRACTION",
    "MAXIMUM_SPLIT_TURN_ANGLE_DEG",
    "MINIMUM_CHORD_EFFICIENCY",
    "MINIMUM_SCAN_DISPLACEMENT_MM",
    "MULTISCALE_SCAN_DIRECTION_INTERVALS",
    "MultiscaleScanDirectionResult",
    "NEUTRAL_DIRECTIONAL_ETA",
    "PATCH18_0_MAX_DIRECTIONAL_ETA",
    "PATCH18_0_MIN_DIRECTIONAL_ETA",
    "PRODUCTION_DAQ_DT_S",
    "PRODUCTION_DIRECTIONAL_FALLBACK_POLICY",
    "PrincipalLiquidConductivities",
    "SCAN_DIRECTION_WINDOW_INTERVALS",
    "ScanDirectionEstimate",
    "ScanStraightnessCandidate",
    "TRANSPORT_MODE_DIRECTIONAL",
    "TRANSPORT_MODE_ISOTROPIC_FALLBACK",
    "TRANSPORT_MODE_ISOTROPIC_NEUTRAL",
    "accepted_isotropic_liquid_conductivity_W_mK",
    "acute_axis_misalignment_deg",
    "directional_explicit_stability_record",
    "estimate_local_scan_direction",
    "estimate_multiscale_scan_direction",
    "principal_liquid_conductivities",
    "resolve_liquid_transport_decision",
    "rotated_liquid_conductivity_tensor_W_mK",
    "unresolved_scan_direction_reason_code",
)
