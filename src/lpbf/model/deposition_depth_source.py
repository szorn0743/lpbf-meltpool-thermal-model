"""Patch 19.1 production deposition-depth heat-source kernel.

The accepted Patch 16/17 heat source remains the exact default path.  This
module adds one package-owned opt-in source redistribution mode implementing
the frozen Patch 19.0 normalized truncated exponential through depth.

No root scientific implementation is modified.  In legacy mode the builder
calls :class:`heat_source.HeatSourceFieldBuilder` directly.  In exponential
mode it reuses the accepted cell-centred x/y coordinates and Gaussian formula,
then combines the normalized lateral weights with analytic control-volume
integrals of the frozen depth kernel.  Only the spatial distribution changes;
the accepted absorbed power remains ``incident_power_W * absorptivity``.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

import numpy as np

from lpbf.model._accepted_core.heat_source import (
    HeatSourceFieldBuilder as AcceptedHeatSourceFieldBuilder,
    build_centered_heat_source_for_row as _accepted_build_centered_heat_source_for_row,
)
from lpbf.model.deposition_depth import (
    DEFAULT_DEPOSITION_DEPTH_MODE,
    EXPONENTIAL_DEPOSITION_DEPTH_MODE,
    LEGACY_DEPOSITION_DEPTH_MODE,
    MATERIAL_INTERFACE_POLICY,
    DepositionDepthDesignError,
    DepositionDepthDesignState,
    normalized_truncated_exponential_cell_fractions,
    truncated_exponential_normalization,
)
from lpbf.model.parameters import (
    HeatSourceParameters,
    MovingWindowControls,
    SimulationParameters,
)
from lpbf.model._accepted_core.moving_window import MovingWindowState, MovingWindowUpdateResult


_MM_TO_M = 1.0e-3
SUPPORTED_MATERIAL_GEOMETRY = "flat_fully_material_filled_rectangular_domain"


class DepositionDepthKernelError(ValueError):
    """Raised when Patch 19.1 cannot apply the frozen source contract safely."""


@dataclass(frozen=True)
class DepositionDepthKernelDiagnostics:
    """Auditable diagnostics required by the Patch 19.0 frozen design."""

    deposition_depth_mode: str
    legacy_builder_delegated: bool
    exponential_characteristic_depth_mm: float | None
    represented_material_depth_mm: float
    finite_depth_normalization: float | None
    top_cell_power_fraction: float
    depth_power_fraction_sum: float
    integrated_source_power_W: float
    accepted_absorbed_power_W: float
    source_power_error_W: float
    source_power_relative_error: float
    material_interface_policy: str = MATERIAL_INTERFACE_POLICY
    material_geometry: str = SUPPORTED_MATERIAL_GEOMETRY

    def to_dict(self) -> dict[str, Any]:
        return {
            "deposition_depth_mode": self.deposition_depth_mode,
            "legacy_builder_delegated": bool(self.legacy_builder_delegated),
            "exponential_characteristic_depth_mm": self.exponential_characteristic_depth_mm,
            "represented_material_depth_mm": float(self.represented_material_depth_mm),
            "finite_depth_normalization": self.finite_depth_normalization,
            "top_cell_power_fraction": float(self.top_cell_power_fraction),
            "depth_power_fraction_sum": float(self.depth_power_fraction_sum),
            "integrated_source_power_W": float(self.integrated_source_power_W),
            "accepted_absorbed_power_W": float(self.accepted_absorbed_power_W),
            "source_power_error_W": float(self.source_power_error_W),
            "source_power_relative_error": float(self.source_power_relative_error),
            "material_interface_policy": self.material_interface_policy,
            "material_geometry": self.material_geometry,
        }


class DepositionDepthFieldBuilder:
    """Reusable Patch 19.1 heat-source builder with exact legacy delegation.

    Parameters
    ----------
    params:
        Accepted simulation parameter bundle.  Grid, beam, power, and timestep
        semantics are not redefined here.
    deposition_depth_mode:
        ``legacy_uniform_top_slab`` (default) or
        ``normalized_truncated_exponential``.
    exponential_characteristic_depth_mm:
        Required only for the exponential mode.  It is the e-folding depth
        measured inward from the top free-surface face and must satisfy
        ``0 < lambda <= Lz``.
    material_geometry:
        Patch 19.1 supports only the current flat, fully material-filled
        rectangular domain.  Any other requested geometry fails closed.
    """

    def __init__(
        self,
        params: SimulationParameters,
        *,
        deposition_depth_mode: str = DEFAULT_DEPOSITION_DEPTH_MODE,
        exponential_characteristic_depth_mm: float | None = None,
        material_geometry: str = SUPPORTED_MATERIAL_GEOMETRY,
    ) -> None:
        params.validate()
        if material_geometry != SUPPORTED_MATERIAL_GEOMETRY:
            raise DepositionDepthKernelError(
                "Patch 19.1 supports only a flat, fully material-filled rectangular "
                "domain; distinct material, void, gas, or nonflat free-surface "
                "geometry must fail closed."
            )

        self.params = params
        self.deposition_depth_mode = str(deposition_depth_mode)
        self.exponential_characteristic_depth_mm = (
            None
            if exponential_characteristic_depth_mm is None
            else float(exponential_characteristic_depth_mm)
        )
        self.material_geometry = material_geometry

        self._accepted_builder = AcceptedHeatSourceFieldBuilder(params)
        self.x = self._accepted_builder.x
        self.y = self._accepted_builder.y
        self.z = self._accepted_builder.z
        self.dx = self._accepted_builder.dx
        self.cell_volume_m3 = self._accepted_builder.cell_volume_m3

        shape = (params.grid.Nx, params.grid.Ny, params.grid.Nz)
        self._q_dot = np.zeros(shape, dtype=np.float64)
        self._gx = np.empty(params.grid.Nx, dtype=np.float64)
        self._gy = np.empty(params.grid.Ny, dtype=np.float64)
        self._radial = np.empty((params.grid.Nx, params.grid.Ny), dtype=np.float64)
        self._depth_fractions = np.empty(params.grid.Nz, dtype=np.float64)
        self._last_diagnostics: DepositionDepthKernelDiagnostics | None = None

        self._validate_mode_contract(params.heat_source)
        if self.deposition_depth_mode == EXPONENTIAL_DEPOSITION_DEPTH_MODE:
            assert self.exponential_characteristic_depth_mm is not None
            fractions = normalized_truncated_exponential_cell_fractions(
                domain_depth_m=float(params.geometry.Lz_m),
                nz=int(params.grid.Nz),
                characteristic_depth_m=(
                    self.exponential_characteristic_depth_mm * _MM_TO_M
                ),
            )
            self._depth_fractions[:] = np.asarray(fractions, dtype=np.float64)

    @property
    def buffer(self) -> np.ndarray:
        """Return the reusable output buffer for the selected mode."""
        if self.deposition_depth_mode == LEGACY_DEPOSITION_DEPTH_MODE:
            return self._accepted_builder.buffer
        return self._q_dot

    @property
    def last_diagnostics(self) -> DepositionDepthKernelDiagnostics | None:
        """Diagnostics for the most recent successful ``build`` call."""
        return self._last_diagnostics

    def _validate_mode_contract(self, source: HeatSourceParameters) -> None:
        state = DepositionDepthDesignState(
            mode=self.deposition_depth_mode,
            legacy_depth_mm=float(source.depth_mm),
            exponential_characteristic_depth_mm=(
                self.exponential_characteristic_depth_mm
            ),
        )
        try:
            state.validate(domain_depth_mm=float(self.params.geometry.Lz_mm))
        except DepositionDepthDesignError as exc:
            raise DepositionDepthKernelError(str(exc)) from exc

    def _set_diagnostics(
        self,
        *,
        source: HeatSourceParameters,
        field: np.ndarray,
        legacy_builder_delegated: bool,
        finite_depth_normalization: float | None,
        top_cell_power_fraction: float,
        depth_power_fraction_sum: float,
    ) -> None:
        accepted_power = float(source.deposited_power_W)
        integrated_power = float(
            np.sum(field, dtype=np.float64) * self.cell_volume_m3
        )
        error = integrated_power - accepted_power
        relative_error = (
            0.0 if accepted_power == 0.0 else error / abs(accepted_power)
        )
        self._last_diagnostics = DepositionDepthKernelDiagnostics(
            deposition_depth_mode=self.deposition_depth_mode,
            legacy_builder_delegated=legacy_builder_delegated,
            exponential_characteristic_depth_mm=(
                self.exponential_characteristic_depth_mm
            ),
            represented_material_depth_mm=float(self.params.geometry.Lz_mm),
            finite_depth_normalization=finite_depth_normalization,
            top_cell_power_fraction=float(top_cell_power_fraction),
            depth_power_fraction_sum=float(depth_power_fraction_sum),
            integrated_source_power_W=integrated_power,
            accepted_absorbed_power_W=accepted_power,
            source_power_error_W=error,
            source_power_relative_error=relative_error,
            material_geometry=self.material_geometry,
        )

    def _legacy_depth_diagnostics(
        self, source: HeatSourceParameters
    ) -> tuple[float, float]:
        z_min_deposit = self.params.geometry.Lz_m - source.depth_m
        first_k = int(np.searchsorted(self.z, z_min_deposit, side="left"))
        count = self.params.grid.Nz - first_k
        if count <= 0:
            return 0.0, 0.0
        return 1.0 / float(count), 1.0

    def build(
        self,
        source: HeatSourceParameters | None = None,
        *,
        copy: bool = False,
        validate: bool = True,
    ) -> np.ndarray:
        """Build the selected source into reusable storage.

        Legacy mode directly invokes the accepted builder.  Exponential mode
        changes only the separable depth weights; the accepted Gaussian,
        absorbed power, cell volume, center, and row-specific source state are
        retained exactly.
        """
        if source is None:
            source = self.params.heat_source
        if validate:
            source.validate(self.params)
        self._validate_mode_contract(source)

        if self.deposition_depth_mode == LEGACY_DEPOSITION_DEPTH_MODE:
            field = self._accepted_builder.build(
                source,
                copy=copy,
                validate=False,
            )
            top_fraction, depth_sum = self._legacy_depth_diagnostics(source)
            self._set_diagnostics(
                source=source,
                field=field,
                legacy_builder_delegated=True,
                finite_depth_normalization=None,
                top_cell_power_fraction=top_fraction,
                depth_power_fraction_sum=depth_sum,
            )
            return field

        if self.deposition_depth_mode != EXPONENTIAL_DEPOSITION_DEPTH_MODE:
            # Defensive guard if mutable state is corrupted after construction.
            raise DepositionDepthKernelError(
                f"unsupported deposition-depth mode: {self.deposition_depth_mode!r}"
            )

        q_dot = self._q_dot
        q_dot.fill(0.0)
        accepted_power_W = float(source.deposited_power_W)
        assert self.exponential_characteristic_depth_mm is not None
        characteristic_depth_m = (
            self.exponential_characteristic_depth_mm * _MM_TO_M
        )
        finite_normalizer = truncated_exponential_normalization(
            characteristic_depth_m=characteristic_depth_m,
            available_depth_m=float(self.params.geometry.Lz_m),
        )
        depth_sum = float(math.fsum(float(v) for v in self._depth_fractions))
        top_fraction = float(self._depth_fractions[-1])

        if accepted_power_W == 0.0:
            self._set_diagnostics(
                source=source,
                field=q_dot,
                legacy_builder_delegated=False,
                finite_depth_normalization=finite_normalizer,
                top_cell_power_fraction=top_fraction,
                depth_power_fraction_sum=depth_sum,
            )
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
        lateral_sum = float(np.sum(self._radial, dtype=np.float64))
        if not np.isfinite(lateral_sum) or lateral_sum <= 0.0:
            raise DepositionDepthKernelError(
                "accepted lateral Gaussian has no finite positive discrete support"
            )

        # q_ijk = P_abs * (G_ij/sum(G)) * b_k / V_cell.
        # A single scale avoids an intermediate lateral-fraction allocation.
        scale = accepted_power_W / (lateral_sum * self.cell_volume_m3)
        q_dot[:] = (
            self._radial[:, :, None]
            * self._depth_fractions[None, None, :]
            * scale
        )

        # Enforce the frozen discrete finite-volume power identity against the
        # actual floating-point field, not only the factorized normalizers.
        integrated_power_W = float(
            np.sum(q_dot, dtype=np.float64) * self.cell_volume_m3
        )
        if not np.isfinite(integrated_power_W) or integrated_power_W <= 0.0:
            raise DepositionDepthKernelError(
                "deposition-depth source normalization produced nonpositive power"
            )
        q_dot *= accepted_power_W / integrated_power_W

        self._set_diagnostics(
            source=source,
            field=q_dot,
            legacy_builder_delegated=False,
            finite_depth_normalization=finite_normalizer,
            top_cell_power_fraction=top_fraction,
            depth_power_fraction_sum=depth_sum,
        )
        return q_dot.copy() if copy else q_dot


def build_centered_heat_source_for_row_with_deposition_depth(
    params: SimulationParameters,
    source_template: HeatSourceParameters,
    controls: MovingWindowControls,
    spot_size_um: float,
    laser_on: bool,
    *,
    field_builder: DepositionDepthFieldBuilder,
    accumulated_subcell_x_mm: float = 0.0,
    accumulated_subcell_y_mm: float = 0.0,
    effective_absorptivity: float = 0.0,
    alpha_base: float | None = None,
    ted_modulation: float | None = None,
    row_index: int | None = None,
    moving_window_state: MovingWindowState | None = None,
    moving_window_update: MovingWindowUpdateResult | None = None,
) -> tuple[np.ndarray, HeatSourceParameters, DepositionDepthKernelDiagnostics]:
    """Use the accepted row-state logic with the Patch 19.1 field builder.

    Power/absorptivity, spot-size interpretation, moving-window subcell center,
    and source-template replacement are all delegated to the accepted helper.
    Only the final field construction is dispatched through ``field_builder``.
    """
    if not isinstance(field_builder, DepositionDepthFieldBuilder):
        raise TypeError("field_builder must be a DepositionDepthFieldBuilder")

    q_dot, source = _accepted_build_centered_heat_source_for_row(
        params=params,
        source_template=source_template,
        controls=controls,
        spot_size_um=spot_size_um,
        laser_on=laser_on,
        accumulated_subcell_x_mm=accumulated_subcell_x_mm,
        accumulated_subcell_y_mm=accumulated_subcell_y_mm,
        effective_absorptivity=effective_absorptivity,
        alpha_base=alpha_base,
        ted_modulation=ted_modulation,
        field_builder=field_builder,
        row_index=row_index,
        moving_window_state=moving_window_state,
        moving_window_update=moving_window_update,
    )
    diagnostics = field_builder.last_diagnostics
    if diagnostics is None:
        raise RuntimeError("deposition-depth field builder returned no diagnostics")
    return q_dot, source, diagnostics


__all__ = (
    "DepositionDepthFieldBuilder",
    "DepositionDepthKernelDiagnostics",
    "DepositionDepthKernelError",
    "SUPPORTED_MATERIAL_GEOMETRY",
    "build_centered_heat_source_for_row_with_deposition_depth",
)
