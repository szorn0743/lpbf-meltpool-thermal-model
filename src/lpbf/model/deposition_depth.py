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
    "normalized_truncated_exponential_cell_fractions",
    "truncated_exponential_normalization",
)
