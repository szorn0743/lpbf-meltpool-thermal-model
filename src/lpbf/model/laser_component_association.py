"""Production laser-to-liquid-component association policy.

Patch 22.3.7 (active, policy version ``22.3.7``): the laser-associated
component is the 4-neighbor liquid component that receives the largest share of
the beam's surface-deposited power, provided that share is at least
``BEAM_SHARE_FLOOR``.  The share uses the model's own separable Gaussian
(``exp(-2 r^2 / R^2)`` with the realized source radius) evaluated at cell
centers and unit-normalized over the window, so it has no grid-direction or
cell-center round-off dependence.  When no component receives the floor share,
the model's prediction is ``NO_LASER_ASSOCIATED_MELT`` (scored as a zero
footprint downstream; owner decision D1).  Tied shares fail closed.

Patch 22.3.5 (frozen, policy version ``22.3.5``): ``select_laser_associated_component``
keeps the continuous-distance one-cell rule for historical replays and tests.
Neither policy alters or recomputes the thermal field.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

from lpbf.model.observation_diagnostics import _label_liquid_components

POLICY_VERSION = "22.3.7"
CONTINUOUS_DISTANCE_POLICY_VERSION = "22.3.5"
MAX_FALLBACK_DISTANCE_CELLS = 1.0
CONTINUOUS_DISTANCE_METRIC = "continuous_physical_cell_center_euclidean"
LEGACY_COMPATIBILITY_DISTANCE_METRIC = "cell_center_index_compatibility"

# Owner decision D3 (2026-10-14): 2 % of the beam's surface-deposited power.  The
# Patch 22.3.6 census measured identical outcomes for any floor from 0.5 % to 10 %.
BEAM_SHARE_FLOOR = 0.02
BEAM_SHARE_TIE_REL_TOL = 1.0e-6
BEAM_SHARE_SELECTION_MODE = "largest_beam_share"
NO_BEAM_POWER_SELECTION_MODE = "no_beam_power_on_liquid"
NO_LASER_ASSOCIATED_MELT_STATUS = "NO_LASER_ASSOCIATED_MELT"
TIED_SHARE_STATUS = "FAIL_CLOSED_TIED_SHARE"


class LaserComponentAssociationError(RuntimeError):
    """Raised when a production association request cannot be resolved safely."""


def surface_beam_profile(
    nx: int,
    ny: int,
    *,
    spacing_mm: float,
    center_x_mm: float,
    center_y_mm: float,
    gaussian_radius_mm: float,
) -> np.ndarray:
    """Surface deposition weights of the model's Gaussian beam over the window cells.

    Same separable ``exp(-2 r^2 / R^2)`` form evaluated at cell centers as the
    accepted heat-source builder, normalized to unit sum over the window.
    """

    spacing = float(spacing_mm)
    radius = float(gaussian_radius_mm)
    if not (math.isfinite(spacing) and spacing > 0.0):
        raise ValueError("spacing_mm must be positive and finite")
    if not (math.isfinite(radius) and radius > 0.0):
        raise ValueError("gaussian_radius_mm must be positive and finite")
    x = (np.arange(int(nx), dtype=np.float64) + 0.5) * spacing
    y = (np.arange(int(ny), dtype=np.float64) + 0.5) * spacing
    radius_squared = radius * radius
    gx = np.exp(-2.0 * (x - float(center_x_mm)) ** 2 / radius_squared)
    gy = np.exp(-2.0 * (y - float(center_y_mm)) ** 2 / radius_squared)
    profile = gx[:, None] * gy[None, :]
    total = float(profile.sum())
    if not math.isfinite(total) or total <= 0.0:
        raise ValueError("beam profile has no weight inside the window")
    return profile / total


def select_laser_associated_component_by_beam_share(
    liquid_mask: np.ndarray,
    *,
    beam_i: int,
    beam_j: int,
    source_center_x_mm: float,
    source_center_y_mm: float,
    cell_spacing_x_mm: float,
    cell_spacing_y_mm: float,
    gaussian_radius_mm: float,
    beam_share_floor: float = BEAM_SHARE_FLOOR,
    tie_rel_tol: float = BEAM_SHARE_TIE_REL_TOL,
) -> tuple[dict[str, Any], np.ndarray | None]:
    """Return the component receiving the largest share of beam power (Patch 22.3.7).

    Policy:
      * no liquid anywhere in the window: ``ZERO_FOOTPRINT``;
      * largest share below ``beam_share_floor``: ``NO_LASER_ASSOCIATED_MELT`` (a
        prediction of no laser-associated pool; scored as zero downstream);
      * two components within ``tie_rel_tol`` of the largest share:
        ``FAIL_CLOSED_TIED_SHARE``;
      * otherwise ``SELECTED`` with mode ``largest_beam_share``.

    ``min_distance_cells`` reports the selected (or best) component's minimum
    cell-center distance from the source as telemetry; it does not drive the
    selection.  Physical geometry is mandatory: there is no index-only mode.
    """

    mask = np.asarray(liquid_mask, dtype=bool)
    if mask.ndim != 2:
        raise ValueError("liquid_mask must be two-dimensional")
    values = (source_center_x_mm, source_center_y_mm, cell_spacing_x_mm, cell_spacing_y_mm, gaussian_radius_mm)
    try:
        source_x, source_y, spacing_x, spacing_y, radius = (float(value) for value in values)
    except (TypeError, ValueError) as exc:
        raise ValueError("physical association coordinates, spacings and radius must be finite") from exc
    if not all(math.isfinite(value) for value in (source_x, source_y, spacing_x, spacing_y, radius)):
        raise ValueError("physical association coordinates, spacings and radius must be finite")
    if spacing_x <= 0.0 or spacing_y <= 0.0:
        raise ValueError("physical association spacings must be positive")
    if not math.isclose(spacing_x, spacing_y, rel_tol=1.0e-12, abs_tol=1.0e-15):
        raise ValueError("beam-share association requires a uniform surface-cell spacing")
    if radius <= 0.0:
        raise ValueError("gaussian_radius_mm must be positive")
    floor = float(beam_share_floor)
    if not math.isfinite(floor) or not (0.0 <= floor < 1.0):
        raise ValueError("beam_share_floor must lie in [0, 1)")
    spacing_mm = 0.5 * (spacing_x + spacing_y)

    labels, sizes = _label_liquid_components(mask)
    nx, ny = mask.shape
    bi = min(max(int(beam_i), 0), nx - 1)
    bj = min(max(int(beam_j), 0), ny - 1)
    base: dict[str, Any] = {
        "policy_version": POLICY_VERSION,
        "distance_metric": CONTINUOUS_DISTANCE_METRIC,
        "beam_share_floor": floor,
        "gaussian_radius_mm": radius,
        "component_count": int(len(sizes)),
        "beam_share_on_liquid_total": 0.0,
        "max_fallback_distance_cells": None,
    }
    if not sizes:
        return (
            {
                **base,
                "status": "ZERO_FOOTPRINT",
                "selected_label": None,
                "selection_mode": "zero_footprint",
                "beam_share": None,
                "contains_beam_cell": False,
                "min_distance_cells": None,
                "min_distance_mm": None,
                "tie_count": 0,
            },
            None,
        )

    profile = surface_beam_profile(
        nx, ny, spacing_mm=spacing_mm, center_x_mm=source_x, center_y_mm=source_y, gaussian_radius_mm=radius
    )
    beam_label = int(labels[bi, bj])
    candidates: list[tuple[float, int, float, bool]] = []
    for label in range(1, len(sizes) + 1):
        component = labels == label
        ij = np.argwhere(component)
        centers_x = (ij[:, 0].astype(np.float64) + 0.5) * spacing_x
        centers_y = (ij[:, 1].astype(np.float64) + 0.5) * spacing_y
        contains = label == beam_label
        distance_cells = 0.0 if contains else float(np.min(np.hypot(centers_x - source_x, centers_y - source_y)) / spacing_mm)
        candidates.append((float(profile[component].sum()), label, distance_cells, contains))
    base["beam_share_on_liquid_total"] = float(sum(item[0] for item in candidates))

    best_share, best_label, best_distance, best_contains = max(candidates, key=lambda item: (item[0], -item[1]))
    tied = [item for item in candidates if math.isclose(item[0], best_share, rel_tol=tie_rel_tol, abs_tol=1.0e-15)]
    telemetry = {
        "beam_share": best_share,
        "min_distance_cells": best_distance,
        "min_distance_mm": best_distance * spacing_mm,
        "tie_count": len(tied),
    }
    if best_share < floor:
        return (
            {
                **base,
                **telemetry,
                "status": NO_LASER_ASSOCIATED_MELT_STATUS,
                "selected_label": None,
                "selection_mode": NO_BEAM_POWER_SELECTION_MODE,
                "contains_beam_cell": False,
            },
            None,
        )
    if len(tied) != 1:
        return (
            {
                **base,
                **telemetry,
                "status": TIED_SHARE_STATUS,
                "selected_label": None,
                "selection_mode": "fail_closed",
                "contains_beam_cell": False,
            },
            None,
        )
    return (
        {
            **base,
            **telemetry,
            "status": "SELECTED",
            "selected_label": int(best_label),
            "selection_mode": BEAM_SHARE_SELECTION_MODE,
            "selected_cell_count": int(sizes[best_label - 1]),
            "contains_beam_cell": bool(best_contains),
        },
        labels == best_label,
    )


def select_laser_associated_component(
    liquid_mask: np.ndarray,
    *,
    beam_i: int,
    beam_j: int,
    max_fallback_distance_cells: float = MAX_FALLBACK_DISTANCE_CELLS,
    source_center_x_mm: float | None = None,
    source_center_y_mm: float | None = None,
    cell_spacing_x_mm: float | None = None,
    cell_spacing_y_mm: float | None = None,
) -> tuple[dict[str, Any], np.ndarray | None]:
    """Frozen Patch 22.3.5 selector (policy version ``22.3.5``); not used by production since 22.3.7.

    Policy:
      * zero liquid footprint remains zero footprint;
      * if the beam-containing cell is liquid, select that 4-neighbor component;
      * otherwise select a *unique* nearest component only when its minimum
        physical distance to a liquid-cell center is no greater than one cell
        spacing;
      * tied nearest components and distances greater than one cell fail closed.

    Cell centers are at ``(index + 0.5) * spacing``.  When physical arguments
    are omitted, the selector uses cell-center index coordinates as a
    compatibility mode for direct historical unit callers.
    """

    mask = np.asarray(liquid_mask, dtype=bool)
    if mask.ndim != 2:
        raise ValueError("liquid_mask must be two-dimensional")
    limit = float(max_fallback_distance_cells)
    if not math.isfinite(limit) or limit < 0.0:
        raise ValueError("max_fallback_distance_cells must be finite and nonnegative")

    physical_arguments = (
        source_center_x_mm,
        source_center_y_mm,
        cell_spacing_x_mm,
        cell_spacing_y_mm,
    )
    physical_mode = any(value is not None for value in physical_arguments)
    if physical_mode and not all(value is not None for value in physical_arguments):
        raise ValueError(
            "source center and both physical cell spacings must be supplied together"
        )
    if physical_mode:
        source_x = float(source_center_x_mm)
        source_y = float(source_center_y_mm)
        spacing_x = float(cell_spacing_x_mm)
        spacing_y = float(cell_spacing_y_mm)
        if not all(math.isfinite(value) for value in (source_x, source_y, spacing_x, spacing_y)):
            raise ValueError("physical association coordinates and spacings must be finite")
        if spacing_x <= 0.0 or spacing_y <= 0.0:
            raise ValueError("physical association spacings must be positive")
        if not math.isclose(spacing_x, spacing_y, rel_tol=1.0e-12, abs_tol=1.0e-15):
            raise ValueError(
                "continuous physical association requires a uniform surface-cell spacing"
            )
        spacing_mm = 0.5 * (spacing_x + spacing_y)
        distance_metric = CONTINUOUS_DISTANCE_METRIC
    else:
        # Direct callers of the pre-22.3.5 selector did not have physical source
        # coordinates.  Keep those calls deterministic and behavior-compatible.
        source_x = float(beam_i) + 0.5
        source_y = float(beam_j) + 0.5
        spacing_mm = 1.0
        distance_metric = LEGACY_COMPATIBILITY_DISTANCE_METRIC

    labels, sizes = _label_liquid_components(mask)
    if not sizes:
        return (
            {
                "status": "ZERO_FOOTPRINT",
                "selected_label": None,
                "selection_mode": "zero_footprint",
                "min_distance_cells": None,
                "tie_count": 0,
                "max_fallback_distance_cells": limit,
                "policy_version": CONTINUOUS_DISTANCE_POLICY_VERSION,
                "distance_metric": distance_metric,
                "min_distance_mm": None,
                "fallback_radius_mm": float(limit * spacing_mm),
            },
            None,
        )

    nx, ny = mask.shape
    bi = min(max(int(beam_i), 0), nx - 1)
    bj = min(max(int(beam_j), 0), ny - 1)
    center_label = int(labels[bi, bj])
    if center_label > 0:
        return (
            {
                "status": "SELECTED",
                "selected_label": center_label,
                "selection_mode": "strict_center",
                "min_distance_cells": 0.0,
                "tie_count": 1,
                "selected_cell_count": int(sizes[center_label - 1]),
                "max_fallback_distance_cells": limit,
                "policy_version": CONTINUOUS_DISTANCE_POLICY_VERSION,
                "distance_metric": distance_metric,
                "min_distance_mm": 0.0,
                "fallback_radius_mm": float(limit * spacing_mm),
            },
            labels == center_label,
        )

    candidates: list[tuple[float, int]] = []
    for label in range(1, len(sizes) + 1):
        ij = np.argwhere(labels == label)
        if physical_mode:
            cell_center_x = (ij[:, 0].astype(np.float64) + 0.5) * float(cell_spacing_x_mm)
            cell_center_y = (ij[:, 1].astype(np.float64) + 0.5) * float(cell_spacing_y_mm)
            distances_mm = np.hypot(cell_center_x - source_x, cell_center_y - source_y)
            component_distance_mm = float(np.min(distances_mm))
            component_distance_cells = component_distance_mm / spacing_mm
        else:
            distance_sq = (ij[:, 0] - bi) ** 2 + (ij[:, 1] - bj) ** 2
            component_distance_cells = math.sqrt(float(np.min(distance_sq)))
            component_distance_mm = component_distance_cells
        candidates.append((component_distance_cells, label))

    minimum_distance = min(item[0] for item in candidates)
    tie_tolerance = max(1.0e-15, 1.0e-12 * abs(minimum_distance))
    nearest = [
        label
        for candidate_distance, label in candidates
        if math.isclose(
            candidate_distance,
            minimum_distance,
            rel_tol=1.0e-12,
            abs_tol=tie_tolerance,
        )
    ]
    minimum_distance_mm = float(minimum_distance * spacing_mm)
    if len(nearest) != 1:
        return (
            {
                "status": "FAIL_CLOSED_TIED_NEAREST",
                "selected_label": None,
                "selection_mode": "fail_closed",
                "min_distance_cells": minimum_distance,
                "tie_count": len(nearest),
                "max_fallback_distance_cells": limit,
                "policy_version": CONTINUOUS_DISTANCE_POLICY_VERSION,
                "distance_metric": distance_metric,
                "min_distance_mm": minimum_distance_mm,
                "fallback_radius_mm": float(limit * spacing_mm),
            },
            None,
        )
    if minimum_distance > limit:
        return (
            {
                "status": "FAIL_CLOSED_DISTANCE_EXCEEDED",
                "selected_label": None,
                "selection_mode": "fail_closed",
                "min_distance_cells": minimum_distance,
                "tie_count": 1,
                "max_fallback_distance_cells": limit,
                "policy_version": CONTINUOUS_DISTANCE_POLICY_VERSION,
                "distance_metric": distance_metric,
                "min_distance_mm": minimum_distance_mm,
                "fallback_radius_mm": float(limit * spacing_mm),
            },
            None,
        )

    label = int(nearest[0])
    return (
        {
            "status": "SELECTED",
            "selected_label": label,
            "selection_mode": "unique_nearest_fallback",
            "min_distance_cells": minimum_distance,
            "tie_count": 1,
            "selected_cell_count": int(sizes[label - 1]),
            "max_fallback_distance_cells": limit,
            "policy_version": CONTINUOUS_DISTANCE_POLICY_VERSION,
            "distance_metric": distance_metric,
            "min_distance_mm": minimum_distance_mm,
            "fallback_radius_mm": float(limit * spacing_mm),
        },
        labels == label,
    )


__all__ = [
    "BEAM_SHARE_FLOOR",
    "BEAM_SHARE_SELECTION_MODE",
    "BEAM_SHARE_TIE_REL_TOL",
    "CONTINUOUS_DISTANCE_METRIC",
    "CONTINUOUS_DISTANCE_POLICY_VERSION",
    "LEGACY_COMPATIBILITY_DISTANCE_METRIC",
    "LaserComponentAssociationError",
    "MAX_FALLBACK_DISTANCE_CELLS",
    "NO_BEAM_POWER_SELECTION_MODE",
    "NO_LASER_ASSOCIATED_MELT_STATUS",
    "POLICY_VERSION",
    "TIED_SHARE_STATUS",
    "select_laser_associated_component",
    "select_laser_associated_component_by_beam_share",
    "surface_beam_profile",
]
