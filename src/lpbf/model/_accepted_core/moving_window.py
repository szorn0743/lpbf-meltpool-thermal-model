"""
HDF5-driven moving-window driver for the explicit finite-volume heat solver.

This module wraps the solver step instead of replacing it. The local Cartesian
grid remains fixed in orientation, the Gaussian heat source remains centered in
local x-y coordinates except for subcell offsets, and measured laser positions
move the local computational window through global space.

Process-data ingestion is owned by ``input_data.py`` and simulation orchestration
is owned by ``simulation.py``. This module owns moving-window state, field shifts,
subcell displacement, reset behavior, and moving-window energy accounting.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
import numpy as np

from lpbf.model._accepted_core.parameters import (
    MM_TO_M,
    MovingWindowControls,
    SimulationParameters,
)
from lpbf.model._accepted_core.solver import compute_stored_energy_relative_to_temperature_J


# Residual moving-window displacement should remain within one grid cell after
# integer-cell shifts.  Use the same dimensionless floating-point margin as
# the near-integer accumulator guard so the invariant is stable at exact cell
# boundaries without materially widening the allowed residual range.
_RESIDUAL_DISPLACEMENT_CELL_TOL = 1.0e-9


def _residual_displacement_tolerance_mm(grid_spacing_mm: float) -> float:
    """Return the floating-point margin for the one-cell residual invariant."""
    if not math.isfinite(grid_spacing_mm) or grid_spacing_mm <= 0.0:
        raise ValueError("grid_spacing_mm must be finite and positive.")
    return _RESIDUAL_DISPLACEMENT_CELL_TOL * grid_spacing_mm


def _residual_displacement_limit_mm(grid_spacing_mm: float) -> float:
    """Maximum allowed residual magnitude: one grid cell plus FP margin."""
    return grid_spacing_mm + _residual_displacement_tolerance_mm(grid_spacing_mm)


def _validate_accumulated_subcell_displacement_mm(
    accumulated_subcell_x_mm: float,
    accumulated_subcell_y_mm: float,
    dx_mm: float,
    dy_mm: float,
) -> None:
    """Validate the Patch 9.3 residual-displacement invariant."""
    x_limit_mm = _residual_displacement_limit_mm(dx_mm)
    y_limit_mm = _residual_displacement_limit_mm(dy_mm)

    x_mm = float(accumulated_subcell_x_mm)
    y_mm = float(accumulated_subcell_y_mm)
    if (
        not math.isfinite(x_mm)
        or not math.isfinite(y_mm)
        or abs(x_mm) > x_limit_mm
        or abs(y_mm) > y_limit_mm
    ):
        raise ValueError(
            "Moving-window residual displacement invariant violated: "
            f"accumulated_subcell_x_mm={x_mm:.17g}, "
            f"accumulated_subcell_y_mm={y_mm:.17g}, "
            f"dx_mm={float(dx_mm):.17g}, dy_mm={float(dy_mm):.17g}, "
            f"x_limit_mm={x_limit_mm:.17g}, y_limit_mm={y_limit_mm:.17g}."
        )


# -------------------------------------------------------------------------
# Moving-window state and operations
# -------------------------------------------------------------------------


@dataclass
class MovingWindowState:
    previous_laser_x_mm: float | None = None
    previous_laser_y_mm: float | None = None
    previous_powered_laser_x_mm: float | None = None
    previous_powered_laser_y_mm: float | None = None
    accumulated_subcell_x_mm: float = 0.0
    accumulated_subcell_y_mm: float = 0.0
    bulk_temperature_K: float = np.nan
    laser_on: bool = False
    current_scan_segment_status: str = "not_started"
    reset_occurred: bool = False
    shift_x_cells: int = 0
    shift_y_cells: int = 0


@dataclass(frozen=True)
class MovingWindowUpdateResult:
    """Fixed-schema result from one moving-window update."""

    window_reset_flag: bool
    window_reset_reason: str
    window_shift_x_cells: int
    window_shift_y_cells: int
    window_exit_energy_J: float
    reset_removed_energy_J: float
    scan_segment_status: str


def _sensible_energy_relative_to_bulk_J(
    T: np.ndarray,
    bulk_temperature_K: float,
    params: SimulationParameters,
) -> float:
    """
    Return stored material enthalpy relative to the local bulk temperature.

    The calculation is phase-aware and includes apparent latent enthalpy across
    the solidus-liquidus interval.
    """
    return compute_stored_energy_relative_to_temperature_J(
        temperature_K=T,
        reference_temperature_K=bulk_temperature_K,
        params=params,
    )


def _shifted_out_energy_J(
    T_old: np.ndarray,
    shift_x_cells: int,
    shift_y_cells: int,
    bulk_temperature_K: float,
    params: SimulationParameters,
) -> float:
    """Return sensible energy, relative to bulk, carried out of the local window."""
    Nx, Ny, _ = T_old.shape

    if abs(shift_x_cells) >= Nx or abs(shift_y_cells) >= Ny:
        return _sensible_energy_relative_to_bulk_J(T_old, bulk_temperature_K, params)

    keep = np.zeros((Nx, Ny), dtype=bool)

    if shift_x_cells >= 0:
        src_x = slice(0, Nx - shift_x_cells)
    else:
        src_x = slice(-shift_x_cells, Nx)

    if shift_y_cells >= 0:
        src_y = slice(0, Ny - shift_y_cells)
    else:
        src_y = slice(-shift_y_cells, Ny)

    keep[src_x, src_y] = True
    exit_mask = ~keep

    if not np.any(exit_mask):
        return 0.0

    return compute_stored_energy_relative_to_temperature_J(
        temperature_K=T_old[exit_mask, :],
        reference_temperature_K=bulk_temperature_K,
        params=params,
    )


def _shift_temperature_field_no_wrap(
    T: np.ndarray,
    shift_x_cells: int,
    shift_y_cells: int,
    fill_temperature_K: float,
) -> np.ndarray:
    """
    Shift the 3D local temperature field by integer cells without wrapping.

    Positive shift_x_cells moves existing values toward larger local x indices.
    Negative shift_x_cells moves existing values toward smaller local x indices.
    Newly exposed cells are filled with fill_temperature_K.
    """
    if shift_x_cells == 0 and shift_y_cells == 0:
        return T

    Nx, Ny, _ = T.shape
    T_new = np.full_like(T, fill_temperature_K)

    if abs(shift_x_cells) >= Nx or abs(shift_y_cells) >= Ny:
        return T_new

    if shift_x_cells >= 0:
        src_x = slice(0, Nx - shift_x_cells)
        dst_x = slice(shift_x_cells, Nx)
    else:
        src_x = slice(-shift_x_cells, Nx)
        dst_x = slice(0, Nx + shift_x_cells)

    if shift_y_cells >= 0:
        src_y = slice(0, Ny - shift_y_cells)
        dst_y = slice(shift_y_cells, Ny)
    else:
        src_y = slice(-shift_y_cells, Ny)
        dst_y = slice(0, Ny + shift_y_cells)

    T_new[dst_x, dst_y, :] = T[src_x, src_y, :]
    return T_new


def _integer_cells_from_accumulator(accumulated_mm: float, dx_mm: float) -> int:
    """
    Convert accumulated subcell motion into an integer number of cells.

    The intended behavior is truncation toward zero, but floating-point
    roundoff can turn an exact one-cell displacement into 0.999999999999999
    and incorrectly return 0. The near-integer guard prevents that.
    """
    ratio = accumulated_mm / dx_mm
    nearest = round(ratio)

    if math.isclose(
        ratio,
        nearest,
        rel_tol=0.0,
        abs_tol=_RESIDUAL_DISPLACEMENT_CELL_TOL,
    ):
        return int(nearest)

    return int(math.trunc(ratio))


def apply_moving_window_update(
    temperature_K: np.ndarray,
    state: MovingWindowState,
    params: SimulationParameters,
    controls: MovingWindowControls,
    laser_x_mm: float,
    laser_y_mm: float,
    laser_on: bool,
) -> tuple[np.ndarray, MovingWindowState, MovingWindowUpdateResult]:
    """
    Apply the moving-window reset/shift/remain decision before the FVM heat step.
    """
    dx_mm = params.grid.uniform_spacing_m(params.geometry) / MM_TO_M

    reset = False
    reset_reason = ""
    shift_x_cells = 0
    shift_y_cells = 0
    window_exit_energy_J = 0.0
    reset_removed_energy_J = 0.0
    status = "laser_off"

    previous_row_was_on = bool(state.laser_on)

    if not laser_on:
        status = "laser_off"
        state.previous_laser_x_mm = laser_x_mm
        state.previous_laser_y_mm = laser_y_mm
        state.laser_on = False
        state.current_scan_segment_status = status
        state.reset_occurred = False
        state.shift_x_cells = 0
        state.shift_y_cells = 0
        return temperature_K, state, MovingWindowUpdateResult(
            window_reset_flag=False,
            window_reset_reason=reset_reason,
            window_shift_x_cells=0,
            window_shift_y_cells=0,
            window_exit_energy_J=0.0,
            reset_removed_energy_J=0.0,
            scan_segment_status=status,
        )

    if state.previous_powered_laser_x_mm is None or state.previous_powered_laser_y_mm is None:
        status = "first_powered_point"
        state.accumulated_subcell_x_mm = 0.0
        state.accumulated_subcell_y_mm = 0.0
    else:
        dx_laser_mm = laser_x_mm - state.previous_powered_laser_x_mm
        dy_laser_mm = laser_y_mm - state.previous_powered_laser_y_mm
        travel_distance_mm = math.hypot(dx_laser_mm, dy_laser_mm)

        # Patch 9.4.2: classify spatial discontinuity independently from
        # laser-power state. A large machine-coordinate jump is a geometric
        # condition and must not be hidden by the fact that the previous row
        # happened to be laser-off.
        spatial_discontinuity = (
            travel_distance_mm > controls.reset_distance_threshold_mm
        )

        if spatial_discontinuity:
            # Patch 9.4.3 policy: this local moving-window model has no global
            # thermal-history field from which to initialize a physically
            # remote region. Carrying the existing local field would therefore
            # transplant heat to unrelated material. The explicit supported
            # action is to reset the remote local window to bulk temperature.
            if controls.large_jump_policy != "reset_to_bulk":
                raise ValueError(
                    "Unsupported moving-window large-jump policy: "
                    f"{controls.large_jump_policy!r}. Only 'reset_to_bulk' is implemented."
                )
            reset = True
            reset_reason = "large_jump"
            status = "reset_large_jump"
        elif (
            controls.reset_on_new_powered_scan_after_off
            and not previous_row_was_on
        ):
            # Legacy opt-in retained from Patch 9.4.1. With the production
            # default False, laser-off alone is not a reset condition.
            reset = True
            reset_reason = "new_powered_scan_after_laser_off"
            status = "reset_after_laser_off"
        else:
            status = "powered_continuous"
            state.accumulated_subcell_x_mm += dx_laser_mm
            state.accumulated_subcell_y_mm += dy_laser_mm

            laser_x_cells = _integer_cells_from_accumulator(
                state.accumulated_subcell_x_mm,
                dx_mm,
            )
            laser_y_cells = _integer_cells_from_accumulator(
                state.accumulated_subcell_y_mm,
                dx_mm,
            )

            if laser_x_cells != 0 or laser_y_cells != 0:
                # Temperature field shifts opposite the laser motion.
                shift_x_cells = -laser_x_cells
                shift_y_cells = -laser_y_cells

                window_exit_energy_J = _shifted_out_energy_J(
                    temperature_K,
                    shift_x_cells=shift_x_cells,
                    shift_y_cells=shift_y_cells,
                    bulk_temperature_K=state.bulk_temperature_K,
                    params=params,
                )

                temperature_K = _shift_temperature_field_no_wrap(
                    temperature_K,
                    shift_x_cells=shift_x_cells,
                    shift_y_cells=shift_y_cells,
                    fill_temperature_K=state.bulk_temperature_K,
                )

                state.accumulated_subcell_x_mm -= laser_x_cells * dx_mm
                state.accumulated_subcell_y_mm -= laser_y_cells * dx_mm

                # Patch 9.3.1 invariant definition: after integer-cell shifts,
                # each accumulated subcell residual is expected to remain within
                # one grid spacing plus _residual_displacement_tolerance_mm().

    if reset:
        energy_before_reset_J = _sensible_energy_relative_to_bulk_J(
            temperature_K,
            bulk_temperature_K=state.bulk_temperature_K,
            params=params,
        )
        temperature_K = np.full_like(temperature_K, state.bulk_temperature_K)
        energy_after_reset_J = _sensible_energy_relative_to_bulk_J(
            temperature_K,
            bulk_temperature_K=state.bulk_temperature_K,
            params=params,
        )
        reset_removed_energy_J = energy_before_reset_J - energy_after_reset_J
        state.accumulated_subcell_x_mm = 0.0
        state.accumulated_subcell_y_mm = 0.0

    state.previous_laser_x_mm = laser_x_mm
    state.previous_laser_y_mm = laser_y_mm
    state.previous_powered_laser_x_mm = laser_x_mm
    state.previous_powered_laser_y_mm = laser_y_mm
    state.laser_on = True
    state.current_scan_segment_status = status
    state.reset_occurred = reset
    state.shift_x_cells = int(shift_x_cells)
    state.shift_y_cells = int(shift_y_cells)

    return temperature_K, state, MovingWindowUpdateResult(
        window_reset_flag=bool(reset),
        window_reset_reason=reset_reason,
        window_shift_x_cells=int(shift_x_cells),
        window_shift_y_cells=int(shift_y_cells),
        window_exit_energy_J=float(window_exit_energy_J),
        reset_removed_energy_J=float(reset_removed_energy_J),
        scan_segment_status=status,
    )
