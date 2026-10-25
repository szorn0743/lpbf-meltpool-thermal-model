from __future__ import annotations

from types import SimpleNamespace
import math

import numpy as np
import pytest

from lpbf.model._accepted_core import comparison as accepted_comparison
from lpbf.model.execution_interfaces import InMemoryExecutionInterfaces
from lpbf.model.laser_component_association import (
    CONTINUOUS_DISTANCE_METRIC,
    POLICY_VERSION as ACTIVE_POLICY_VERSION,
    select_laser_associated_component,
)
from lpbf.model.observation_diagnostics import beam_connected_liquid_component_mask
from lpbf.model.production_hw import (
    PRODUCTION_HW_DEFINITION,
    PRODUCTION_HW_SEMANTICS_VERSION,
    laser_associated_observation_instrumentation,
)


SPACING_MM = 0.016


def _physical_selection(
    mask: np.ndarray,
    *,
    source_x_cells: float,
    source_y_cells: float,
):
    source_x_mm = source_x_cells * SPACING_MM
    source_y_mm = source_y_cells * SPACING_MM
    return select_laser_associated_component(
        mask,
        beam_i=math.floor(source_x_cells),
        beam_j=math.floor(source_y_cells),
        source_center_x_mm=source_x_mm,
        source_center_y_mm=source_y_mm,
        cell_spacing_x_mm=SPACING_MM,
        cell_spacing_y_mm=SPACING_MM,
    )


def _temperature(mask: np.ndarray) -> np.ndarray:
    top = np.full(mask.shape, 1000.0, dtype=np.float64)
    top[mask] = 2000.0
    return top


def _physical_production_diag(
    mask: np.ndarray,
    *,
    source_x_cells: float,
    source_y_cells: float,
) -> dict:
    """Exercise the same heat-source capture seam used by production runs."""

    nx, ny = mask.shape
    params = SimpleNamespace(
        geometry=SimpleNamespace(Lx_mm=nx * SPACING_MM, Ly_mm=ny * SPACING_MM),
        grid=SimpleNamespace(Nx=nx, Ny=ny),
    )

    def fake_heat_source(**_kwargs):
        # Patch 22.3.7: production also needs the realized Gaussian radius.
        return np.zeros((nx, ny, 1), dtype=np.float64), SimpleNamespace(
            deposited_power_W=0.0, gaussian_radius_mm=0.040
        )

    source_x_mm = source_x_cells * SPACING_MM
    source_y_mm = source_y_cells * SPACING_MM
    with laser_associated_observation_instrumentation(
        execution_interfaces=InMemoryExecutionInterfaces(
            heat_source_for_row=fake_heat_source
        )
    ) as interfaces:
        interfaces.heat_source_for_row(
            params=params,
            accumulated_subcell_x_mm=source_x_mm - 0.5 * params.geometry.Lx_mm,
            accumulated_subcell_y_mm=source_y_mm - 0.5 * params.geometry.Ly_mm,
        )
        beam_i = math.floor(source_x_cells)
        beam_j = math.floor(source_y_cells)
        diagnostics = accepted_comparison.top_surface_liquid_component_diagnostics(
            mask, beam_i=beam_i, beam_j=beam_j
        )
        beam_mask = beam_connected_liquid_component_mask(
            mask, beam_i=beam_i, beam_j=beam_j
        )
        accepted_comparison.interpolated_component_contour_hw_diagnostic(
            _temperature(mask),
            beam_mask,
            liquidus_temperature_K=1500.0,
            cell_size_um=SPACING_MM * 1000.0,
            experimental_pixel_size_um=4.0,
        )
    diagnostics["frame_index"] = 0
    diagnostics["mapped_process_row"] = 0
    return diagnostics


def test_continuous_inside_and_orthogonal_boundary_distance():
    mask = np.zeros((9, 9), dtype=bool)
    mask[4, 4] = True
    inside, selected = _physical_selection(
        mask, source_x_cells=4.7, source_y_cells=4.7
    )
    assert inside["status"] == "SELECTED"
    assert inside["selection_mode"] == "strict_center"
    assert inside["distance_metric"] == CONTINUOUS_DISTANCE_METRIC
    assert np.array_equal(selected, mask)

    orthogonal = np.zeros((9, 9), dtype=bool)
    orthogonal[4, 5] = True
    boundary, selected = _physical_selection(
        orthogonal, source_x_cells=4.5, source_y_cells=4.5
    )
    assert boundary["status"] == "SELECTED"
    assert boundary["selection_mode"] == "unique_nearest_fallback"
    assert boundary["min_distance_cells"] == pytest.approx(1.0)
    assert boundary["min_distance_mm"] == pytest.approx(SPACING_MM)
    assert np.array_equal(selected, orthogonal)


def test_diagonal_below_physical_tolerance_is_selected_but_old_grid_rule_rejects():
    mask = np.zeros((9, 9), dtype=bool)
    mask[5, 5] = True
    continuous, selected = _physical_selection(
        mask, source_x_cells=4.9, source_y_cells=4.9
    )
    legacy, legacy_selected = select_laser_associated_component(
        mask, beam_i=4, beam_j=4
    )
    assert continuous["status"] == "SELECTED"
    assert continuous["selection_mode"] == "unique_nearest_fallback"
    assert continuous["min_distance_cells"] == pytest.approx(math.sqrt(0.72))
    assert np.array_equal(selected, mask)
    assert legacy["status"] == "FAIL_CLOSED_DISTANCE_EXCEEDED"
    assert legacy["min_distance_cells"] == pytest.approx(math.sqrt(2.0))
    assert legacy_selected is None


def test_slightly_outside_physical_tolerance_fails_closed():
    mask = np.zeros((9, 9), dtype=bool)
    mask[4, 5] = True
    diagnostics, selected = _physical_selection(
        mask, source_x_cells=4.5, source_y_cells=4.499
    )
    assert diagnostics["status"] == "FAIL_CLOSED_DISTANCE_EXCEEDED"
    assert diagnostics["min_distance_cells"] > 1.0
    assert selected is None


def test_near_component_wins_over_remote_component_without_remote_contamination():
    near = np.zeros((11, 11), dtype=bool)
    near[4, 5:7] = True
    remote = near.copy()
    remote[1, 1:3] = True
    diagnostics, selected = _physical_selection(
        remote, source_x_cells=4.9, source_y_cells=4.9
    )
    assert diagnostics["status"] == "SELECTED"
    assert selected is not None
    assert selected[4, 5] and selected[4, 6]
    assert not selected[1, 1]
    assert not selected[1, 2]


def test_tied_and_remote_components_fail_closed():
    tied = np.zeros((9, 9), dtype=bool)
    tied[4, 3] = True
    tied[4, 5] = True
    diagnostics, selected = _physical_selection(
        tied, source_x_cells=4.5, source_y_cells=4.5
    )
    assert diagnostics["status"] == "FAIL_CLOSED_TIED_NEAREST"
    assert selected is None

    remote = np.zeros((9, 9), dtype=bool)
    remote[4, 7] = True
    diagnostics, selected = _physical_selection(
        remote, source_x_cells=4.5, source_y_cells=4.5
    )
    assert diagnostics["status"] == "FAIL_CLOSED_DISTANCE_EXCEEDED"
    assert diagnostics["min_distance_cells"] == pytest.approx(3.0)
    assert selected is None


def test_selected_boundary_component_remains_fail_closed_as_unenclosed_contour():
    mask = np.zeros((9, 9), dtype=bool)
    mask[0, 4:6] = True
    diagnostics = _physical_production_diag(
        mask, source_x_cells=1.5, source_y_cells=4.5
    )
    assert diagnostics["production_hw_association_status"] == "SELECTED"
    assert diagnostics["production_hw_association_distance_metric"] == CONTINUOUS_DISTANCE_METRIC
    assert diagnostics["production_hw_component_available"] is False
    assert "UNENCLOSED" in diagnostics["production_hw_component_status"]


def test_frame_13768_recorded_geometry_selects_the_peak_cell_for_continuous_reason():
    mask = np.zeros((99, 99), dtype=bool)
    mask[49, 49] = True
    source_x_mm = 0.8015615993051555
    source_y_mm = 0.8017107251828961
    diagnostics, selected = select_laser_associated_component(
        mask,
        beam_i=50,
        beam_j=50,
        source_center_x_mm=source_x_mm,
        source_center_y_mm=source_y_mm,
        cell_spacing_x_mm=0.016,
        cell_spacing_y_mm=0.016,
    )
    legacy, _ = select_laser_associated_component(mask, beam_i=50, beam_j=50)
    assert diagnostics["status"] == "SELECTED"
    assert diagnostics["selection_mode"] == "unique_nearest_fallback"
    assert diagnostics["distance_metric"] == CONTINUOUS_DISTANCE_METRIC
    assert diagnostics["min_distance_mm"] == pytest.approx(0.013627999297405347)
    assert diagnostics["min_distance_cells"] == pytest.approx(0.8517499560878342)
    assert np.array_equal(selected, mask)
    assert legacy["status"] == "FAIL_CLOSED_DISTANCE_EXCEEDED"
    assert legacy["min_distance_cells"] == pytest.approx(math.sqrt(2.0))


def test_patch235_metadata_and_remote_hw_invariance():
    base = np.zeros((11, 11), dtype=bool)
    base[5, 5:7] = True
    remote = base.copy()
    remote[1, 1:4] = True
    base_diag = _physical_production_diag(
        base, source_x_cells=4.9, source_y_cells=5.5
    )
    remote_diag = _physical_production_diag(
        remote, source_x_cells=4.9, source_y_cells=5.5
    )
    # Patch 22.3.7: production selects by beam-power share; the distance telemetry keeps its metric.
    assert base_diag["production_hw_definition"] == PRODUCTION_HW_DEFINITION
    assert base_diag["production_hw_semantics_version"] == PRODUCTION_HW_SEMANTICS_VERSION
    assert base_diag["production_hw_association_policy_version"] == ACTIVE_POLICY_VERSION
    assert base_diag["production_hw_association_distance_metric"] == CONTINUOUS_DISTANCE_METRIC
    assert base_diag["production_hw_association_source_geometry_available"] is True
    assert base_diag["production_hw_association_mode"] == "largest_beam_share"
    assert base_diag["production_hw_simulated_H_pixels"] == pytest.approx(
        remote_diag["production_hw_simulated_H_pixels"]
    )
    assert base_diag["production_hw_simulated_W_pixels"] == pytest.approx(
        remote_diag["production_hw_simulated_W_pixels"]
    )


def test_frame_13768_geometry_produces_finite_selected_component_hw_in_replay_fixture():
    mask = np.zeros((99, 99), dtype=bool)
    mask[48:50, 48:50] = True
    source_x_mm = 0.8015615993051555
    source_y_mm = 0.8017107251828961
    diagnostics = _physical_production_diag(
        mask,
        source_x_cells=source_x_mm / SPACING_MM,
        source_y_cells=source_y_mm / SPACING_MM,
    )
    assert diagnostics["production_hw_association_status"] == "SELECTED"
    assert diagnostics["production_hw_association_mode"] == "largest_beam_share"
    assert diagnostics["production_hw_association_min_distance_mm"] == pytest.approx(
        0.013627999297405347
    )
    assert diagnostics["production_hw_component_available"] is True
    assert diagnostics["production_hw_component_contour_enclosed"] is True
    assert diagnostics["production_hw_simulated_H_pixels"] > 0.0
    assert diagnostics["production_hw_simulated_W_pixels"] > 0.0
