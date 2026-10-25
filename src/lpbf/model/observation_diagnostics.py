"""Passive observation diagnostics for LPBF melt-pool geometry.

These helpers characterize already-computed top-surface liquidus fields.  They
never alter the production temperature field, production H/W extraction, or
calibration objective.  Patch 22.1 adds a beam-connected-component diagnostic
so window adequacy can be separated from contamination by disconnected liquid
remnants.
"""
from __future__ import annotations

from typing import Any

import numpy as np


def _label_liquid_components(liquid_mask: np.ndarray) -> tuple[np.ndarray, list[int]]:
    mask = np.asarray(liquid_mask, dtype=bool)
    if mask.ndim != 2:
        raise ValueError("liquid_mask must be two-dimensional")
    nx, ny = mask.shape
    labels = np.zeros((nx, ny), dtype=np.int32)
    sizes: list[int] = []
    label = 0
    for i in range(nx):
        for j in range(ny):
            if not mask[i, j] or labels[i, j] != 0:
                continue
            label += 1
            stack = [(i, j)]
            labels[i, j] = label
            size = 0
            while stack:
                ci, cj = stack.pop()
                size += 1
                for ni, nj in (
                    (ci - 1, cj),
                    (ci + 1, cj),
                    (ci, cj - 1),
                    (ci, cj + 1),
                ):
                    if (
                        0 <= ni < nx
                        and 0 <= nj < ny
                        and mask[ni, nj]
                        and labels[ni, nj] == 0
                    ):
                        labels[ni, nj] = label
                        stack.append((ni, nj))
            sizes.append(size)
    return labels, sizes


def beam_connected_liquid_component_mask(
    liquid_mask: np.ndarray,
    *,
    beam_i: int,
    beam_j: int,
) -> np.ndarray:
    """Return only the 4-neighbor liquid component containing the laser center.

    If the laser-center cell is not liquid, an all-false mask is returned.  No
    nearest-component or largest-component substitution is made.
    """

    mask = np.asarray(liquid_mask, dtype=bool)
    labels, _ = _label_liquid_components(mask)
    nx, ny = mask.shape
    if not nx or not ny:
        return np.zeros_like(mask, dtype=bool)
    bi = min(max(int(beam_i), 0), nx - 1)
    bj = min(max(int(beam_j), 0), ny - 1)
    beam_label = int(labels[bi, bj])
    if beam_label <= 0:
        return np.zeros_like(mask, dtype=bool)
    return labels == beam_label


def top_surface_liquid_component_diagnostics(
    liquid_mask: np.ndarray,
    *,
    beam_i: int,
    beam_j: int,
) -> dict[str, int | bool | float | None]:
    """Return 4-neighbor liquidus component diagnostics for one top surface."""

    mask = np.asarray(liquid_mask, dtype=bool)
    labels, sizes = _label_liquid_components(mask)
    nx, ny = mask.shape
    largest = max(sizes, default=0)
    bi = min(max(int(beam_i), 0), max(nx - 1, 0))
    bj = min(max(int(beam_j), 0), max(ny - 1, 0))
    beam_label = int(labels[bi, bj]) if nx and ny else 0
    beam_size = sizes[beam_label - 1] if beam_label > 0 else 0
    represented = int(np.count_nonzero(mask))
    boundary_contact = bool(
        nx
        and ny
        and (
            np.any(mask[0, :])
            or np.any(mask[-1, :])
            or np.any(mask[:, 0])
            or np.any(mask[:, -1])
        )
    )
    beam_mask = labels == beam_label if beam_label > 0 else np.zeros_like(mask, dtype=bool)
    beam_boundary_contact = bool(
        nx
        and ny
        and beam_label > 0
        and (
            np.any(beam_mask[0, :])
            or np.any(beam_mask[-1, :])
            or np.any(beam_mask[:, 0])
            or np.any(beam_mask[:, -1])
        )
    )
    beam_clearance = None
    if beam_label > 0:
        beam_ij = np.argwhere(beam_mask)
        beam_clearance = int(
            np.min(
                np.column_stack(
                    (
                        beam_ij[:, 0],
                        nx - 1 - beam_ij[:, 0],
                        beam_ij[:, 1],
                        ny - 1 - beam_ij[:, 1],
                    )
                )
            )
        )
    return {
        "liquidus_component_count": int(len(sizes)),
        "largest_liquidus_component_cell_count": int(largest),
        "beam_connected_liquidus_component_cell_count": int(beam_size),
        "beam_center_cell_is_liquid": bool(beam_label > 0),
        "liquidus_contour_boundary_contact": boundary_contact,
        "beam_connected_liquidus_component_boundary_contact": beam_boundary_contact,
        "beam_connected_liquidus_component_clearance_cells": beam_clearance,
        "beam_connected_liquidus_component_is_largest": bool(
            beam_label > 0 and beam_size == largest
        ),
        "remote_liquid_cell_count": int(max(represented - beam_size, 0)),
        "beam_connected_liquid_cell_fraction": (
            None if represented == 0 else float(beam_size / represented)
        ),
    }


def interpolated_component_contour_hw_diagnostic(
    top_surface_temperature_K: np.ndarray,
    component_mask: np.ndarray,
    *,
    liquidus_temperature_K: float,
    cell_size_um: float,
    experimental_pixel_size_um: float,
) -> dict[str, Any]:
    """Measure one explicitly supplied liquid component without changing production H/W.

    The contour uses the same center-to-center linear interpolation and
    ``cv2.minAreaRect`` convention as the production interpolated-liquidus H/W
    algorithm, but crossing points are collected only for the supplied component.
    A component touching the represented boundary remains undefined.
    """

    try:
        import cv2
    except ImportError as exc:  # pragma: no cover - local dependency
        raise ImportError(
            "The melt-pool comparison workflow requires OpenCV. "
            "Install it with 'pip install opencv-python'."
        ) from exc

    top = np.asarray(top_surface_temperature_K, dtype=np.float64)
    component = np.asarray(component_mask, dtype=bool)
    if top.ndim != 2 or component.ndim != 2 or top.shape != component.shape:
        raise ValueError("top-surface temperature and component mask must be matching 2-D arrays")
    if not np.all(np.isfinite(top)):
        raise ValueError("top-surface temperature field must be finite")
    if not np.any(component):
        return {
            "status": "NO_BEAM_CONNECTED_MELT",
            "available": False,
            "contour_enclosed": None,
            "H_pixels": None,
            "W_pixels": None,
            "H_over_W": None,
            "boundary_sides": [],
        }

    boundary_sides = [
        side
        for side, contacted in (
            ("x_min", np.any(component[0, :])),
            ("x_max", np.any(component[-1, :])),
            ("y_min", np.any(component[:, 0])),
            ("y_max", np.any(component[:, -1])),
        )
        if bool(contacted)
    ]
    if boundary_sides:
        return {
            "status": "UNENCLOSED_BEAM_COMPONENT",
            "available": False,
            "contour_enclosed": False,
            "H_pixels": None,
            "W_pixels": None,
            "H_over_W": None,
            "boundary_sides": boundary_sides,
        }

    level = float(liquidus_temperature_K)
    pixel_scale = float(cell_size_um) / float(experimental_pixel_size_um)
    nx, ny = top.shape
    x_centers = (np.arange(nx, dtype=np.float64) + 0.5) * pixel_scale
    y_centers = (np.arange(ny, dtype=np.float64) + 0.5) * pixel_scale
    points: list[tuple[float, float]] = []

    for i in range(nx - 1):
        for j in range(ny):
            if bool(component[i, j]) == bool(component[i + 1, j]):
                continue
            t0 = float(top[i, j])
            t1 = float(top[i + 1, j])
            if (t0 >= level) == (t1 >= level):
                raise ValueError(
                    "component boundary crossed an edge that does not cross T_liquidus"
                )
            fraction = (level - t0) / (t1 - t0)
            x_px = x_centers[i] + fraction * (x_centers[i + 1] - x_centers[i])
            points.append((float(x_px), float(y_centers[j])))

    for i in range(nx):
        for j in range(ny - 1):
            if bool(component[i, j]) == bool(component[i, j + 1]):
                continue
            t0 = float(top[i, j])
            t1 = float(top[i, j + 1])
            if (t0 >= level) == (t1 >= level):
                raise ValueError(
                    "component boundary crossed an edge that does not cross T_liquidus"
                )
            fraction = (level - t0) / (t1 - t0)
            y_px = y_centers[j] + fraction * (y_centers[j + 1] - y_centers[j])
            points.append((float(x_centers[i]), float(y_px)))

    if not points:
        return {
            "status": "DEGENERATE_BEAM_COMPONENT",
            "available": False,
            "contour_enclosed": True,
            "H_pixels": None,
            "W_pixels": None,
            "H_over_W": None,
            "boundary_sides": [],
        }

    rect = cv2.minAreaRect(np.asarray(points, dtype=np.float32))
    side_a, side_b = rect[1]
    H = float(max(side_a, side_b))
    W = float(min(side_a, side_b))
    return {
        "status": "FINITE_BEAM_COMPONENT",
        "available": True,
        "contour_enclosed": True,
        "H_pixels": H,
        "W_pixels": W,
        "H_over_W": None if W == 0.0 else float(H / W),
        "boundary_sides": [],
    }


__all__ = [
    "beam_connected_liquid_component_mask",
    "interpolated_component_contour_hw_diagnostic",
    "top_surface_liquid_component_diagnostics",
]
