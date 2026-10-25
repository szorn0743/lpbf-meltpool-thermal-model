"""Behavior-preserving XY computational-window resizing for the current LPBF model."""
from __future__ import annotations

from dataclasses import replace
import math
from typing import Any

from lpbf.model.parameters import Geometry, Grid
from lpbf.runtime.parameters import THERMAL_DT_S


SUPPORTED_ODD_WINDOW_CELLS = (39, 59, 79, 99, 117)
FROZEN_SPACING_UM = 16.0


class WindowGeometryError(RuntimeError):
    """Raised when a requested window violates frozen grid invariants."""


def resize_xy_window(base: Any, cells: int):
    """Resize X/Y cell count while retaining 16 um spacing, Z grid, and thermal dt."""
    if cells not in SUPPORTED_ODD_WINDOW_CELLS or cells % 2 != 1:
        raise ValueError(f"Unsupported odd window cell count: {cells}")
    spacing_m = float(base.grid.uniform_spacing_m(base.geometry))
    spacing_mm = spacing_m * 1.0e3
    out = replace(
        base,
        geometry=Geometry(
            Lx_mm=cells * spacing_mm,
            Ly_mm=cells * spacing_mm,
            Lz_mm=base.geometry.Lz_mm,
        ),
        grid=Grid(Nx=cells, Ny=cells, Nz=base.grid.Nz),
    )
    out.validate()
    actual_um = float(out.grid.uniform_spacing_m(out.geometry) * 1.0e6)
    if not math.isclose(actual_um, FROZEN_SPACING_UM, rel_tol=0.0, abs_tol=1.0e-9):
        raise WindowGeometryError(f"{cells}x{cells} changed frozen spacing: {actual_um} um")
    if not math.isclose(
        float(out.time.dt_s), THERMAL_DT_S, rel_tol=0.0, abs_tol=1.0e-15
    ):
        raise WindowGeometryError(f"{cells}x{cells} changed frozen thermal dt")
    return out
