"""Patch 19.0 deposition-depth design primitives.

This module records and exercises the frozen mathematical contract without
wiring a new source into the production solver.  The accepted source remains
the default and is identified explicitly as ``legacy_uniform_top_slab``.

The future active mode is a finite-domain, normalized truncated exponential.
Depth ``s`` is measured inward from the top free-surface face, so ``s = 0`` at
``z = Lz`` and ``s = Lz`` at the bottom face.  For characteristic e-folding
depth ``lambda`` and available material depth ``D`` its continuous density is

    p(s) = exp(-s / lambda) / (lambda * (1 - exp(-D / lambda)))

for ``0 <= s <= D``.  Cell weights are exact integrals over control-volume
faces and are discretely renormalized before use.  Patch 19.0 does not alter
``HeatSourceFieldBuilder``, ``HeatSourceParameters``, or any solver path.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Sequence


LEGACY_DEPOSITION_DEPTH_MODE = "legacy_uniform_top_slab"
EXPONENTIAL_DEPOSITION_DEPTH_MODE = "normalized_truncated_exponential"
DEFAULT_DEPOSITION_DEPTH_MODE = LEGACY_DEPOSITION_DEPTH_MODE
DEPOSITION_DEPTH_PARAMETER_NAME = "exponential_characteristic_depth_mm"
DEPOSITION_DEPTH_PARAMETER_UNITS = "mm"
DEPTH_COORDINATE_DEFINITION = "s_m = Lz_m - z_m; s=0 at top free-surface face"
MATERIAL_INTERFACE_POLICY = (
    "same_material_layer_interfaces_transparent; distinct_material_or_void_unsupported_fail_closed"
)
FINITE_DEPTH_POLICY = "truncate_at_bottom_face_and_renormalize_same_absorbed_power"
LATERAL_PROFILE_POLICY = "reuse_accepted_discrete_gaussian_without_depth_broadening"


class DepositionDepthDesignError(ValueError):
    """Raised when a proposed Patch 19 deposition-depth state is invalid."""


@dataclass(frozen=True)
class DepositionDepthDesignState:
    """Design-level selector for the legacy or future active source path.

    ``legacy_depth_mm`` retains the meaning of the existing ``depth_mm`` field:
    it is a cell-centre cutoff for a uniform top slab.  It is deliberately not
    reused as the exponential e-folding depth.
    """

    mode: str = DEFAULT_DEPOSITION_DEPTH_MODE
    legacy_depth_mm: float = 0.10
    exponential_characteristic_depth_mm: float | None = None

    def validate(self, *, domain_depth_mm: float) -> None:
        _validate_positive_finite("domain_depth_mm", domain_depth_mm)
        _validate_positive_finite("legacy_depth_mm", self.legacy_depth_mm)
        if self.legacy_depth_mm > domain_depth_mm:
            raise DepositionDepthDesignError(
                "legacy_depth_mm must not exceed domain_depth_mm"
            )

        if self.mode == LEGACY_DEPOSITION_DEPTH_MODE:
            if self.exponential_characteristic_depth_mm is not None:
                raise DepositionDepthDesignError(
                    "legacy mode requires exponential_characteristic_depth_mm=None"
                )
            return

        if self.mode != EXPONENTIAL_DEPOSITION_DEPTH_MODE:
            raise DepositionDepthDesignError(
                f"unsupported deposition-depth mode: {self.mode!r}"
            )

        value = self.exponential_characteristic_depth_mm
        if value is None:
            raise DepositionDepthDesignError(
                "exponential mode requires exponential_characteristic_depth_mm"
            )
        _validate_positive_finite(DEPOSITION_DEPTH_PARAMETER_NAME, value)
        if value > domain_depth_mm:
            raise DepositionDepthDesignError(
                "exponential_characteristic_depth_mm must not exceed domain_depth_mm"
            )

    @property
    def delegates_exactly_to_accepted_builder(self) -> bool:
        """Whether Patch 19.1 must call the existing builder unchanged."""
        return self.mode == LEGACY_DEPOSITION_DEPTH_MODE


def _validate_positive_finite(name: str, value: float) -> None:
    if not math.isfinite(value) or value <= 0.0:
        raise DepositionDepthDesignError(f"{name} must be finite and positive")


def truncated_exponential_normalization(
    *, characteristic_depth_m: float, available_depth_m: float
) -> float:
    """Return ``1 - exp(-D/lambda)`` using a cancellation-safe expression."""
    _validate_positive_finite("characteristic_depth_m", characteristic_depth_m)
    _validate_positive_finite("available_depth_m", available_depth_m)
    return -math.expm1(-available_depth_m / characteristic_depth_m)


def normalized_truncated_exponential_cell_fractions(
    *,
    domain_depth_m: float,
    nz: int,
    characteristic_depth_m: float,
) -> tuple[float, ...]:
    """Return bottom-to-top cell power fractions for the frozen active kernel.

    The solver indexes ``z`` from the bottom, so the final returned entry is
    the top cell.  Each raw weight is the analytic integral over one cell's
    shallow/deep depth faces.  A final discrete normalization is mandatory and
    protects total power from floating-point summation and finite-domain
    truncation effects.
    """
    _validate_positive_finite("domain_depth_m", domain_depth_m)
    _validate_positive_finite("characteristic_depth_m", characteristic_depth_m)
    if characteristic_depth_m > domain_depth_m:
        raise DepositionDepthDesignError(
            "characteristic_depth_m must not exceed domain_depth_m"
        )
    if not isinstance(nz, int) or isinstance(nz, bool) or nz <= 0:
        raise DepositionDepthDesignError("nz must be a positive integer")

    dz_m = domain_depth_m / nz
    raw: list[float] = []
    for k in range(nz):
        shallow_face_m = max(0.0, domain_depth_m - (k + 1) * dz_m)
        deep_face_m = max(shallow_face_m, domain_depth_m - k * dz_m)
        cell_thickness_m = deep_face_m - shallow_face_m
        weight = math.exp(-shallow_face_m / characteristic_depth_m) * (
            -math.expm1(-cell_thickness_m / characteristic_depth_m)
        )
        raw.append(weight)

    discrete_normalizer = math.fsum(raw)
    if not math.isfinite(discrete_normalizer) or discrete_normalizer <= 0.0:
        raise DepositionDepthDesignError(
            "truncated-exponential cell weights have no finite positive support"
        )
    fractions = tuple(weight / discrete_normalizer for weight in raw)
    if any(not math.isfinite(value) or value < 0.0 for value in fractions):
        raise DepositionDepthDesignError(
            "truncated-exponential normalization produced invalid fractions"
        )
    return fractions


def legacy_uniform_top_slab_cell_indices(
    *, domain_depth_m: float, nz: int, legacy_depth_m: float
) -> tuple[int, ...]:
    """Reproduce the accepted cell-centre eligibility rule for design audits.

    Patch 19.1 is required to delegate to the production builder in legacy
    mode; this helper documents the current rule and is not a replacement for
    that delegation.
    """
    _validate_positive_finite("domain_depth_m", domain_depth_m)
    _validate_positive_finite("legacy_depth_m", legacy_depth_m)
    if legacy_depth_m > domain_depth_m:
        raise DepositionDepthDesignError(
            "legacy_depth_m must not exceed domain_depth_m"
        )
    if not isinstance(nz, int) or isinstance(nz, bool) or nz <= 0:
        raise DepositionDepthDesignError("nz must be a positive integer")

    dz_m = domain_depth_m / nz
    threshold_m = domain_depth_m - legacy_depth_m
    return tuple(
        k for k in range(nz) if (k + 0.5) * dz_m >= threshold_m
    )


def normalized_discrete_gaussian_fractions(
    *,
    x_centers_m: Sequence[float],
    y_centers_m: Sequence[float],
    center_x_m: float,
    center_y_m: float,
    gaussian_radius_m: float,
) -> tuple[tuple[float, ...], ...]:
    """Reference the unchanged accepted in-plane Gaussian discretization."""
    _validate_positive_finite("gaussian_radius_m", gaussian_radius_m)
    if not x_centers_m or not y_centers_m:
        raise DepositionDepthDesignError("lateral coordinate arrays must be nonempty")
    radius_squared = gaussian_radius_m * gaussian_radius_m
    raw = tuple(
        tuple(
            math.exp(
                -2.0
                * (
                    (float(x_m) - center_x_m) ** 2
                    + (float(y_m) - center_y_m) ** 2
                )
                / radius_squared
            )
            for y_m in y_centers_m
        )
        for x_m in x_centers_m
    )
    normalizer = math.fsum(value for row in raw for value in row)
    if not math.isfinite(normalizer) or normalizer <= 0.0:
        raise DepositionDepthDesignError(
            "discrete Gaussian has no finite positive support"
        )
    return tuple(tuple(value / normalizer for value in row) for row in raw)


def separable_cell_power_fractions(
    *,
    lateral_fractions: Sequence[Sequence[float]],
    depth_fractions: Sequence[float],
) -> tuple[tuple[tuple[float, ...], ...], ...]:
    """Combine unchanged lateral fractions and new depth fractions.

    The result is a dimensionless per-cell power partition.  Patch 19.1 will
    divide each cell's assigned power by its cell volume to obtain ``W/m^3``.
    """
    if not lateral_fractions or not depth_fractions:
        raise DepositionDepthDesignError("lateral and depth fractions must be nonempty")
    depth = tuple(float(value) for value in depth_fractions)
    if any(not math.isfinite(value) or value < 0.0 for value in depth):
        raise DepositionDepthDesignError("depth fractions must be finite and nonnegative")
    rows = tuple(tuple(float(value) for value in row) for row in lateral_fractions)
    if any(not row for row in rows):
        raise DepositionDepthDesignError("lateral rows must be nonempty")
    width = len(rows[0])
    if any(len(row) != width for row in rows):
        raise DepositionDepthDesignError("lateral fractions must be rectangular")
    if any(
        not math.isfinite(value) or value < 0.0
        for row in rows
        for value in row
    ):
        raise DepositionDepthDesignError(
            "lateral fractions must be finite and nonnegative"
        )

    lateral_sum = math.fsum(value for row in rows for value in row)
    depth_sum = math.fsum(depth)
    if not math.isclose(lateral_sum, 1.0, rel_tol=0.0, abs_tol=2.0e-14):
        raise DepositionDepthDesignError("lateral fractions must sum to one")
    if not math.isclose(depth_sum, 1.0, rel_tol=0.0, abs_tol=2.0e-14):
        raise DepositionDepthDesignError("depth fractions must sum to one")

    return tuple(
        tuple(tuple(lateral_value * depth_value for depth_value in depth) for lateral_value in row)
        for row in rows
    )


def analytic_truncated_exponential_mean_depth_m(
    *, characteristic_depth_m: float, available_depth_m: float
) -> float:
    """Return the exact mean inward depth of the frozen continuous kernel."""
    normalization = truncated_exponential_normalization(
        characteristic_depth_m=characteristic_depth_m,
        available_depth_m=available_depth_m,
    )
    tail = math.exp(-available_depth_m / characteristic_depth_m)
    return characteristic_depth_m - available_depth_m * tail / normalization


def cell_center_mean_depth_m(
    *, domain_depth_m: float, fractions_bottom_to_top: Sequence[float]
) -> float:
    """Return the cell-centre approximation to mean inward depth."""
    fractions = tuple(float(value) for value in fractions_bottom_to_top)
    if not fractions:
        raise DepositionDepthDesignError("fractions_bottom_to_top must be nonempty")
    nz = len(fractions)
    dz_m = domain_depth_m / nz
    return math.fsum(
        fraction * (domain_depth_m - (k + 0.5) * dz_m)
        for k, fraction in enumerate(fractions)
    )


__all__ = (
    "DEFAULT_DEPOSITION_DEPTH_MODE",
    "DEPOSITION_DEPTH_PARAMETER_NAME",
    "DEPOSITION_DEPTH_PARAMETER_UNITS",
    "DEPTH_COORDINATE_DEFINITION",
    "DepositionDepthDesignError",
    "DepositionDepthDesignState",
    "EXPONENTIAL_DEPOSITION_DEPTH_MODE",
    "FINITE_DEPTH_POLICY",
    "LATERAL_PROFILE_POLICY",
    "LEGACY_DEPOSITION_DEPTH_MODE",
    "MATERIAL_INTERFACE_POLICY",
    "analytic_truncated_exponential_mean_depth_m",
    "cell_center_mean_depth_m",
    "legacy_uniform_top_slab_cell_indices",
    "normalized_discrete_gaussian_fractions",
    "normalized_truncated_exponential_cell_fractions",
    "separable_cell_power_fractions",
    "truncated_exponential_normalization",
)
