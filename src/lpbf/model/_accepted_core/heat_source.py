"""
Fast cell-centered Gaussian volumetric heat-source construction.

The production moving-window workflow reuses one HeatSourceFieldBuilder so
coordinate arrays, depth masks, and output storage are not allocated for every
input row. The discrete finite-volume integral is normalized to the deposited
laser power.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np

from lpbf.model._accepted_core.parameters import (
    MM_TO_M,
    HeatSourceParameters,
    MovingWindowControls,
    SimulationParameters,
)
from lpbf.model._accepted_core.moving_window import (
    MovingWindowState,
    MovingWindowUpdateResult,
    _validate_accumulated_subcell_displacement_mm,
)


def _make_cell_center_coordinate_arrays(
    params: SimulationParameters,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Create one-dimensional cell-centered coordinate arrays in metres."""
    dx = params.grid.uniform_spacing_m(params.geometry)
    x = (np.arange(params.grid.Nx, dtype=np.float64) + 0.5) * dx
    y = (np.arange(params.grid.Ny, dtype=np.float64) + 0.5) * dx
    z = (np.arange(params.grid.Nz, dtype=np.float64) + 0.5) * dx
    return x, y, z


class HeatSourceFieldBuilder:
    """Reusable separable Gaussian source builder.

    The returned array is an internal reusable buffer when ``copy=False``.
    Callers must consume it before requesting the next source field.
    """

    def __init__(self, params: SimulationParameters) -> None:
        params.validate()
        self.params = params
        self.x, self.y, self.z = _make_cell_center_coordinate_arrays(params)
        self.dx = params.grid.uniform_spacing_m(params.geometry)
        self.cell_volume_m3 = self.dx**3
        shape = (params.grid.Nx, params.grid.Ny, params.grid.Nz)
        self._q_dot = np.zeros(shape, dtype=np.float64)
        self._gx = np.empty(params.grid.Nx, dtype=np.float64)
        self._gy = np.empty(params.grid.Ny, dtype=np.float64)
        self._radial = np.empty((params.grid.Nx, params.grid.Ny), dtype=np.float64)

    @property
    def buffer(self) -> np.ndarray:
        return self._q_dot

    def build(
        self,
        source: HeatSourceParameters | None = None,
        *,
        copy: bool = False,
        validate: bool = True,
    ) -> np.ndarray:
        """Build a normalized source field into reusable storage."""
        if source is None:
            source = self.params.heat_source
        if validate:
            source.validate(self.params)

        q_dot = self._q_dot
        q_dot.fill(0.0)
        deposited_power_W = float(source.deposited_power_W)
        if deposited_power_W == 0.0:
            return q_dot.copy() if copy else q_dot

        radius_squared = source.gaussian_radius_m**2
        x_center = source.center_x_m(self.params)
        y_center = source.center_y_m(self.params)

        np.subtract(self.x, x_center, out=self._gx)
        np.square(self._gx, out=self._gx)
        self._gx *= -2.0 / radius_squared
        np.exp(self._gx, out=self._gx)

        np.subtract(self.y, y_center, out=self._gy)
        np.square(self._gy, out=self._gy)
        self._gy *= -2.0 / radius_squared
        np.exp(self._gy, out=self._gy)

        np.multiply(self._gx[:, None], self._gy[None, :], out=self._radial)

        z_min_deposit = self.params.geometry.Lz_m - source.depth_m
        first_k = int(np.searchsorted(self.z, z_min_deposit, side="left"))
        if first_k >= self.params.grid.Nz:
            dx_mm = self.dx / MM_TO_M
            raise ValueError(
                "Heat-source normalization failed because the deposition depth "
                "does not overlap any cell centers.\n"
                f"  depth_mm = {source.depth_mm:.6e} mm\n"
                f"  dx       = {dx_mm:.6e} mm"
            )

        number_of_depth_cells = self.params.grid.Nz - first_k
        discrete_integral = (
            float(np.sum(self._radial, dtype=np.float64))
            * number_of_depth_cells
            * self.cell_volume_m3
        )
        if discrete_integral <= 0.0 or not np.isfinite(discrete_integral):
            raise ValueError("Heat-source normalization produced a nonpositive integral.")

        scale = deposited_power_W / discrete_integral
        q_dot[:, :, first_k:] = self._radial[:, :, None] * scale
        return q_dot.copy() if copy else q_dot



def _gaussian_radius_mm_from_spot_size_um(
    spot_size_um: float,
    controls: MovingWindowControls,
    fallback_radius_mm: float,
) -> float:
    """Interpret one process-row spot size as the Gaussian radius in millimetres."""
    if not np.isfinite(spot_size_um) or spot_size_um <= 0.0:
        return float(fallback_radius_mm)

    spot_size_mm = float(spot_size_um) * 1.0e-3
    if controls.spot_size_um_is_diameter:
        return 0.5 * spot_size_mm
    return spot_size_mm


def build_centered_heat_source_for_row(
    params: SimulationParameters,
    source_template: HeatSourceParameters,
    controls: MovingWindowControls,
    spot_size_um: float,
    laser_on: bool,
    accumulated_subcell_x_mm: float = 0.0,
    accumulated_subcell_y_mm: float = 0.0,
    effective_absorptivity: float = 0.0,
    alpha_base: float | None = None,
    ted_modulation: float | None = None,
    field_builder: HeatSourceFieldBuilder | None = None,
    row_index: int | None = None,
    moving_window_state: MovingWindowState | None = None,
    moving_window_update: MovingWindowUpdateResult | None = None,
) -> tuple[np.ndarray, HeatSourceParameters]:
    """
    Build a Gaussian q_dot for one data row.

    Integer-cell laser motion is handled by shifting the temperature field.
    The remaining subcell laser motion is represented by offsetting the heat
    source inside the local computational window. In HDF5 mode the physical
    source power comes from HeatSourceParameters.incident_power_W.

    Legacy production behavior is retained when ``alpha_base`` and
    ``ted_modulation`` are both omitted: the row-specific absorptivity is
    ``calibration_factor * effective_absorptivity``.

    Patch 14.2 diagnostic behavior is enabled only when both are supplied:
    ``absorptivity = alpha_base * ted_modulation``.  In that mode the frozen
    ``calibration_factor`` is *not* multiplied again; Patch 14.2 treats the
    accepted calibration-factor value as the baseline absorbed-energy scale
    under the explicit alpha_base name.
    """
    revised_architecture = alpha_base is not None or ted_modulation is not None
    if revised_architecture and (alpha_base is None or ted_modulation is None):
        raise ValueError(
            "alpha_base and ted_modulation must be supplied together for the "
            "Patch 14.2 absorbed-power architecture."
        )

    if laser_on:
        incident_power_W = max(0.0, float(source_template.incident_power_W))
        if revised_architecture:
            assert alpha_base is not None and ted_modulation is not None
            alpha = float(alpha_base)
            modulation = float(ted_modulation)
            if not np.isfinite(alpha) or not (0.0 <= alpha <= 1.0):
                raise ValueError("alpha_base must be finite and within [0, 1].")
            if not np.isfinite(modulation) or modulation < 0.0:
                raise ValueError("ted_modulation must be finite and nonnegative.")
            absorptivity = float(np.clip(alpha * modulation, 0.0, 1.0))
        else:
            eta_ted = (
                float(np.clip(effective_absorptivity, 0.0, 1.0))
                if np.isfinite(effective_absorptivity)
                else 0.0
            )
            calibration_factor = float(
                np.clip(source_template.calibration_factor, 0.0, 1.0)
            )
            absorptivity = float(np.clip(calibration_factor * eta_ted, 0.0, 1.0))
    else:
        incident_power_W = 0.0
        absorptivity = 0.0

    gaussian_radius_mm = _gaussian_radius_mm_from_spot_size_um(
        spot_size_um=spot_size_um,
        controls=controls,
        fallback_radius_mm=source_template.gaussian_radius_mm,
    )

    dx_mm = params.grid.uniform_spacing_m(params.geometry) / MM_TO_M
    dy_mm = dx_mm
    try:
        _validate_accumulated_subcell_displacement_mm(
            accumulated_subcell_x_mm=accumulated_subcell_x_mm,
            accumulated_subcell_y_mm=accumulated_subcell_y_mm,
            dx_mm=dx_mm,
            dy_mm=dy_mm,
        )
    except ValueError as exc:
        # Patch 9.3.4: enrich the low-level residual failure with the source and
        # moving-window context available at this production boundary.  The
        # requested center is calculated only for diagnostics after validation
        # has already failed; no source field is constructed.
        requested_center_x_mm = (
            0.5 * params.geometry.Lx_mm + float(accumulated_subcell_x_mm)
        )
        requested_center_y_mm = (
            0.5 * params.geometry.Ly_mm + float(accumulated_subcell_y_mm)
        )

        shift_x_cells = None
        shift_y_cells = None
        scan_segment_status = None
        reset_occurred = None
        reset_reason = None
        if moving_window_state is not None:
            shift_x_cells = int(moving_window_state.shift_x_cells)
            shift_y_cells = int(moving_window_state.shift_y_cells)
            scan_segment_status = str(moving_window_state.current_scan_segment_status)
            reset_occurred = bool(moving_window_state.reset_occurred)
        if moving_window_update is not None:
            shift_x_cells = int(moving_window_update.window_shift_x_cells)
            shift_y_cells = int(moving_window_update.window_shift_y_cells)
            scan_segment_status = str(moving_window_update.scan_segment_status)
            reset_occurred = bool(moving_window_update.window_reset_flag)
            reset_reason = str(moving_window_update.window_reset_reason)

        def _diagnostic_value(value: object | None) -> str:
            return "unavailable" if value is None else str(value)

        raise ValueError(
            f"{exc} "
            f"row_index={_diagnostic_value(row_index)}; "
            f"requested_center_x_mm={requested_center_x_mm:.17g}; "
            f"requested_center_y_mm={requested_center_y_mm:.17g}; "
            f"domain_x_bounds_mm=[0, {params.geometry.Lx_mm:.17g}]; "
            f"domain_y_bounds_mm=[0, {params.geometry.Ly_mm:.17g}]; "
            f"latest_shift_x_cells={_diagnostic_value(shift_x_cells)}; "
            f"latest_shift_y_cells={_diagnostic_value(shift_y_cells)}; "
            f"scan_segment_status={_diagnostic_value(scan_segment_status)}; "
            f"reset_occurred={_diagnostic_value(reset_occurred)}; "
            f"reset_reason={_diagnostic_value(reset_reason)}."
        ) from exc

    center_x_mm = 0.5 * params.geometry.Lx_mm + float(accumulated_subcell_x_mm)
    center_y_mm = 0.5 * params.geometry.Ly_mm + float(accumulated_subcell_y_mm)

    source = replace(
        source_template,
        incident_power_W=incident_power_W,
        absorptivity=absorptivity,
        gaussian_radius_mm=gaussian_radius_mm,
        center_x_mm=center_x_mm,
        center_y_mm=center_y_mm,
    )
    q_dot = (
        field_builder.build(source, copy=False, validate=False)
        if field_builder is not None
        else HeatSourceFieldBuilder(params).build(source, copy=True)
    )
    return q_dot, source


if __name__ == "__main__":
    print(
        "heat_source.py is a library module. Run run_simulation.py for the "
        "HDF5 analytics workflow."
    )
