"""Patch 22.3.7: beam-share association, no-melt scored as zero, scored-frame rule, frame-level scoring."""
from __future__ import annotations

import json
import math
import pickle
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

import lpbf.patch22_3_7_stage_a as stage_a_module
from lpbf.execution.campaign_provenance import PRODUCTION_SEMANTICS_ID
from lpbf.execution.work_units import SimulationResult
from lpbf.experiments.current_framework import (
    CalibrationExecutionScope,
    CurrentExperimentFrameworkError,
    _calibration_observation_records,
)
from lpbf.experiments.dataset import DatasetMember
from lpbf.hierarchical_objective import (
    COVERAGE_FLOOR,
    FAILED_CANDIDATE_PENALTY,
    FAILED_CANDIDATE_STATUS,
    PATCH_VERSION as OBJECTIVE_PATCH_VERSION,
    aggregate_hierarchical_records,
    run_design_only_verification,
    validate_hierarchical_objective_contract,
)
from lpbf.model._accepted_core import comparison as accepted_comparison
from lpbf.model.execution_interfaces import InMemoryExecutionInterfaces
from lpbf.model.laser_component_association import (
    BEAM_SHARE_FLOOR,
    BEAM_SHARE_SELECTION_MODE,
    CONTINUOUS_DISTANCE_METRIC,
    CONTINUOUS_DISTANCE_POLICY_VERSION,
    NO_LASER_ASSOCIATED_MELT_STATUS,
    POLICY_VERSION,
    select_laser_associated_component,
    select_laser_associated_component_by_beam_share,
    surface_beam_profile,
)
from lpbf.model.observation_diagnostics import beam_connected_liquid_component_mask
from lpbf.model.production_hw import (
    PRODUCTION_HW_DEFINITION,
    PRODUCTION_HW_SEMANTICS_VERSION,
    LaserAssociatedHWEvaluationError,
    apply_laser_associated_production_hw,
    laser_associated_observation_instrumentation,
)
from lpbf.patch22_3_7_stage_a import (
    STAGE_A_STATUS_PASS,
    StageAError,
    build_stage_a_jobs,
    compare_with_census_prediction,
    run_stage_a,
)
from lpbf.patch22_4_1_calibration_readiness import build_freeze
from lpbf.patch22_4_3_parallel_coarse_calibration_execution import (
    UNDEFINED_OBSERVATION_POLICY,
    _frame_records_from_evaluation,
    _trial_gate_failures,
)
from lpbf.scored_frame_rule import (
    SCORED_FRAME_RULE_ID,
    SCORED_FRAME_RULE_VERSION,
    apply_scored_frame_rule,
    scored_frame_indices,
)

SPACING = 0.016
RADIUS = 0.040
LIQUIDUS = 1673.15


def _geometry(source_x_cells: float, source_y_cells: float) -> dict:
    return {
        "beam_i": math.floor(source_x_cells),
        "beam_j": math.floor(source_y_cells),
        "source_center_x_mm": source_x_cells * SPACING,
        "source_center_y_mm": source_y_cells * SPACING,
        "cell_spacing_x_mm": SPACING,
        "cell_spacing_y_mm": SPACING,
        "gaussian_radius_mm": RADIUS,
    }


# ------------------------------------------------------------------ F2 selector


def test_versions_and_constants_are_bumped_and_the_old_selector_is_frozen():
    assert POLICY_VERSION == "22.3.7"
    assert CONTINUOUS_DISTANCE_POLICY_VERSION == "22.3.5"
    assert PRODUCTION_HW_SEMANTICS_VERSION == "22.3.7"
    assert PRODUCTION_HW_DEFINITION == "laser_associated_component_interpolated_liquidus_contour"
    assert PRODUCTION_SEMANTICS_ID == "patch22_3_7_laser_associated_component_beam_power_share_hw"
    assert BEAM_SHARE_FLOOR == 0.02
    assert BEAM_SHARE_SELECTION_MODE == "largest_beam_share"
    assert OBJECTIVE_PATCH_VERSION == "22.3.7" and COVERAGE_FLOOR == 0.95
    assert SCORED_FRAME_RULE_VERSION == "22.3.7"
    assert UNDEFINED_OBSERVATION_POLICY == "record_undefined"
    mask = np.zeros((9, 9), dtype=bool)
    mask[4, 4] = True
    old, _ = select_laser_associated_component(mask, beam_i=4, beam_j=4)
    assert old["policy_version"] == "22.3.5"


def test_beam_share_selects_the_pool_under_the_beam_over_a_remnant_one_hatch_over():
    mask = np.zeros((99, 99), dtype=bool)
    mask[47:52, 47:51] = True  # pool containing the beam cell (49, 49)
    mask[44:56, 54:57] = True  # previous-line remnant, five cells over
    selection, selected = select_laser_associated_component_by_beam_share(mask, **_geometry(49.5, 49.5))
    assert selection["status"] == "SELECTED" and selection["selection_mode"] == BEAM_SHARE_SELECTION_MODE
    assert selection["policy_version"] == "22.3.7" and selection["contains_beam_cell"] is True
    assert selection["beam_share"] > 0.3 and selection["beam_share_floor"] == BEAM_SHARE_FLOOR
    assert selection["component_count"] == 2 and selection["tie_count"] == 1
    assert selection["min_distance_cells"] == 0.0 and selection["distance_metric"] == CONTINUOUS_DISTANCE_METRIC
    assert selected is not None and selected[49, 49] and not selected[50, 55]


def test_beam_share_selects_a_trailing_pool_the_one_cell_rule_rejected():
    mask = np.zeros((99, 99), dtype=bool)
    mask[42:48, 47:52] = True  # nearest cell center 1.5 cells behind the source along x
    geometry = _geometry(49.5, 49.5)
    old, _ = select_laser_associated_component(mask, **{k: v for k, v in geometry.items() if k != "gaussian_radius_mm"})
    assert old["status"] == "FAIL_CLOSED_DISTANCE_EXCEEDED"
    new, selected = select_laser_associated_component_by_beam_share(mask, **geometry)
    assert new["status"] == "SELECTED" and new["contains_beam_cell"] is False
    assert new["beam_share"] >= BEAM_SHARE_FLOOR
    assert new["min_distance_cells"] == pytest.approx(2.0)
    assert np.array_equal(selected, mask)


def test_beam_share_reports_no_laser_associated_melt_when_only_a_far_remnant_is_liquid():
    mask = np.zeros((99, 99), dtype=bool)
    mask[44:56, 54:57] = True
    selection, selected = select_laser_associated_component_by_beam_share(mask, **_geometry(49.5, 49.5))
    assert selection["status"] == NO_LASER_ASSOCIATED_MELT_STATUS
    assert selection["selection_mode"] == "no_beam_power_on_liquid"
    assert selection["selected_label"] is None and selected is None
    assert selection["beam_share"] < BEAM_SHARE_FLOOR and selection["beam_share"] > 0.0
    assert selection["min_distance_cells"] == pytest.approx(5.0)


def test_beam_share_zero_footprint_and_tied_shares():
    empty = np.zeros((20, 20), dtype=bool)
    zero, selected = select_laser_associated_component_by_beam_share(empty, **_geometry(10.0, 10.0))
    assert zero["status"] == "ZERO_FOOTPRINT" and selected is None and zero["component_count"] == 0
    mirror = np.zeros((20, 20), dtype=bool)
    mirror[7:9, 8:12] = True   # two pools symmetric about the source at (10, 10) cells
    mirror[11:13, 8:12] = True
    tied, selected = select_laser_associated_component_by_beam_share(mirror, **_geometry(10.0, 10.0))
    assert tied["status"] == "FAIL_CLOSED_TIED_SHARE" and tied["tie_count"] == 2 and selected is None


@pytest.mark.parametrize(
    "override, message",
    [
        ({"gaussian_radius_mm": 0.0}, "radius"),
        ({"cell_spacing_y_mm": 0.017}, "uniform"),
        ({"source_center_x_mm": float("nan")}, "finite"),
        ({"beam_share_floor": 1.0}, "floor"),
    ],
)
def test_beam_share_selector_validates_its_inputs(override, message):
    mask = np.zeros((9, 9), dtype=bool)
    mask[4, 4] = True
    with pytest.raises(ValueError, match=message):
        select_laser_associated_component_by_beam_share(mask, **{**_geometry(4.5, 4.5), **override})


def test_surface_beam_profile_lives_with_the_policy_and_is_normalized():
    profile = surface_beam_profile(99, 99, spacing_mm=SPACING, center_x_mm=0.805, center_y_mm=0.792, gaussian_radius_mm=RADIUS)
    assert profile.sum() == pytest.approx(1.0, abs=1e-12)
    assert np.unravel_index(int(np.argmax(profile)), profile.shape) == (50, 49)


def test_frame_13768_recorded_geometry_is_selected_by_beam_share():
    mask = np.zeros((99, 99), dtype=bool)
    mask[49, 49] = True
    selection, selected = select_laser_associated_component_by_beam_share(
        mask,
        beam_i=50,
        beam_j=50,
        source_center_x_mm=0.8015615993051555,
        source_center_y_mm=0.8017107251828961,
        cell_spacing_x_mm=0.016,
        cell_spacing_y_mm=0.016,
        gaussian_radius_mm=RADIUS,
    )
    assert selection["status"] == "SELECTED" and selection["beam_share"] > BEAM_SHARE_FLOOR
    assert selection["min_distance_mm"] == pytest.approx(0.013627999297405347)
    assert selection["min_distance_cells"] == pytest.approx(0.8517499560878342)
    assert np.array_equal(selected, mask)


# ------------------------------------------------------------- production wrapper


def _production_diag(mask: np.ndarray, *, source_x_cells: float, source_y_cells: float, radius: float | None = RADIUS) -> dict:
    nx, ny = mask.shape
    params = SimpleNamespace(
        geometry=SimpleNamespace(Lx_mm=nx * SPACING, Ly_mm=ny * SPACING),
        grid=SimpleNamespace(Nx=nx, Ny=ny),
    )
    source = SimpleNamespace(deposited_power_W=0.0) if radius is None else SimpleNamespace(deposited_power_W=0.0, gaussian_radius_mm=radius)

    def fake_heat_source(**_kwargs):
        return np.zeros((nx, ny, 1), dtype=np.float64), source

    top = np.full(mask.shape, 1000.0)
    top[mask] = 2000.0
    beam_i, beam_j = math.floor(source_x_cells), math.floor(source_y_cells)
    with laser_associated_observation_instrumentation(
        execution_interfaces=InMemoryExecutionInterfaces(heat_source_for_row=fake_heat_source)
    ) as interfaces:
        interfaces.heat_source_for_row(
            params=params,
            accumulated_subcell_x_mm=source_x_cells * SPACING - 0.5 * params.geometry.Lx_mm,
            accumulated_subcell_y_mm=source_y_cells * SPACING - 0.5 * params.geometry.Ly_mm,
        )
        diagnostics = accepted_comparison.top_surface_liquid_component_diagnostics(mask, beam_i=beam_i, beam_j=beam_j)
        accepted_comparison.interpolated_component_contour_hw_diagnostic(
            top,
            beam_connected_liquid_component_mask(mask, beam_i=beam_i, beam_j=beam_j),
            liquidus_temperature_K=1500.0,
            cell_size_um=SPACING * 1000.0,
            experimental_pixel_size_um=8.0,
        )
    diagnostics["frame_index"] = 0
    diagnostics["mapped_process_row"] = 0
    return diagnostics


@dataclass(frozen=True)
class _FakeResult:
    frame_index: Any
    mapped_process_row: Any
    experimental_H_pixels: Any
    experimental_W_pixels: Any
    simulated_H_pixels: Any
    simulated_W_pixels: Any
    H_difference_pixels: Any
    W_difference_pixels: Any
    metadata: dict
    observation_diagnostics: tuple


def _fake_result(diagnostics: list[dict]) -> _FakeResult:
    count = len(diagnostics)
    aligned = tuple({**item, "frame_index": index, "mapped_process_row": index} for index, item in enumerate(diagnostics))
    return _FakeResult(
        frame_index=np.arange(count),
        mapped_process_row=np.arange(count),
        experimental_H_pixels=np.full(count, 9.0),
        experimental_W_pixels=np.full(count, 7.0),
        simulated_H_pixels=np.full(count, 1.0),
        simulated_W_pixels=np.full(count, 1.0),
        H_difference_pixels=np.full(count, -8.0),
        W_difference_pixels=np.full(count, -6.0),
        metadata={},
        observation_diagnostics=aligned,
    )


def test_production_reports_22_3_7_and_scores_no_melt_as_zero_without_touching_undefined():
    pool = np.zeros((40, 40), dtype=bool)
    pool[18:23, 18:22] = True
    under = _production_diag(pool, source_x_cells=20.5, source_y_cells=20.5)
    assert under["production_hw_association_status"] == "SELECTED"
    assert under["production_hw_association_mode"] == BEAM_SHARE_SELECTION_MODE
    assert under["production_hw_association_policy_version"] == "22.3.7"
    assert under["production_hw_semantics_version"] == "22.3.7"
    assert under["production_hw_association_beam_share"] > 0.3 and under["production_hw_association_beam_share_floor"] == 0.02
    assert under["production_hw_association_contains_beam_cell"] is True
    assert under["production_hw_simulated_H_pixels"] > 0.0 and under["production_hw_component_contour_enclosed"] is True

    remnant = np.zeros((40, 40), dtype=bool)
    remnant[10:30, 30:33] = True  # ten cells away from the source
    far = _production_diag(remnant, source_x_cells=20.5, source_y_cells=20.5)
    assert far["production_hw_association_status"] == NO_LASER_ASSOCIATED_MELT_STATUS
    assert far["production_hw_association_fail_closed"] is False
    assert far["production_hw_component_status"] == NO_LASER_ASSOCIATED_MELT_STATUS
    assert far["production_hw_simulated_H_pixels"] == 0.0 and far["production_hw_simulated_W_pixels"] == 0.0

    edge = np.zeros((40, 40), dtype=bool)
    edge[0:3, 18:22] = True  # the selected pool touches the window boundary
    unenclosed = _production_diag(edge, source_x_cells=1.5, source_y_cells=20.0)
    assert unenclosed["production_hw_association_status"] == "SELECTED"
    assert "UNENCLOSED" in unenclosed["production_hw_component_status"]

    result = apply_laser_associated_production_hw(_fake_result([under, far, unenclosed]), invalid_policy="record_nan", expose_diagnostics=True)
    h = np.asarray(result.simulated_H_pixels)
    w = np.asarray(result.simulated_W_pixels)
    assert h[0] > 0.0 and w[0] > 0.0
    assert (h[1], w[1]) == (0.0, 0.0) and result.observation_diagnostics[1]["classification"] == NO_LASER_ASSOCIATED_MELT_STATUS
    assert math.isnan(h[2]) and math.isnan(w[2]) and result.observation_diagnostics[2]["classification"] == "UNENCLOSED"
    metadata = result.metadata
    assert metadata["production_hw_semantics_version"] == "22.3.7" and metadata["production_hw_association_policy_version"] == "22.3.7"
    assert metadata["production_hw_association_beam_share_floor"] == 0.02
    assert metadata["production_hw_no_laser_associated_melt_count"] == 1
    assert metadata["production_hw_selected_count"] == 1 and metadata["production_hw_association_failure_count"] == 1
    assert "max_fallback_distance_cells" not in json.dumps(metadata)
    with pytest.raises(LaserAssociatedHWEvaluationError):
        apply_laser_associated_production_hw(_fake_result([unenclosed]), invalid_policy="raise", expose_diagnostics=False)


def test_production_fails_closed_when_the_source_radius_is_unavailable():
    pool = np.zeros((40, 40), dtype=bool)
    pool[18:23, 18:22] = True
    diagnostics = _production_diag(pool, source_x_cells=20.5, source_y_cells=20.5, radius=None)
    assert diagnostics["production_hw_association_status"] == "FAIL_CLOSED_SOURCE_GEOMETRY_UNAVAILABLE"
    assert diagnostics["production_hw_association_fail_closed"] is True
    result = apply_laser_associated_production_hw(_fake_result([diagnostics]), invalid_policy="record_nan", expose_diagnostics=False)
    assert math.isnan(np.asarray(result.simulated_H_pixels)[0])


# -------------------------------------------------------------- F1 scored frames


def _rows(member: str, tracks: dict[str, list[int]], ineligible: set[int] = frozenset()) -> list[dict]:
    rows = []
    for track, frames in tracks.items():
        for frame in frames:
            rows.append(
                {
                    "member_identity": member,
                    "portable_member_identity": member,
                    "acquisition_set_id": member.split(":")[0],
                    "part_number": 1,
                    "power_W": 140.0,
                    "speed_mm_s": 850.0,
                    "exact_condition_id": "P140_V850",
                    "scan_track_id": track,
                    "frame_index": frame,
                    "experimental_H_pixels": 9.0 if frame not in ineligible else None,
                    "experimental_W_pixels": 7.0 if frame not in ineligible else None,
                    "observation_eligible": frame not in ineligible,
                    "observation_status": "ELIGIBLE_FINITE_HW" if frame not in ineligible else "INVALID_NONFINITE_HW",
                    "source_observation_status": "positive" if frame not in ineligible else "nonfinite",
                    "status": "PASS",
                    "failure": None,
                }
            )
    return rows


def test_scored_frame_rule_marks_track_edges_and_single_frame_tracks():
    rows = _rows("20260730:part_1", {"1": [10, 11, 12, 13], "2": [20], "3": [30, 31]}, ineligible={12})
    labelled = apply_scored_frame_rule(rows)
    assert [row["frame_index"] for row in labelled] == [10, 11, 12, 13, 20, 30, 31]
    by_frame = {row["frame_index"]: row for row in labelled}
    assert by_frame[10]["scored_frame"] is False and by_frame[10]["exclusion_reason"] == "EXCLUDED_TRACK_FIRST"
    assert by_frame[11]["scored_frame"] is True and by_frame[11]["exclusion_reason"] is None
    assert by_frame[12]["scored_frame"] is False and by_frame[12]["exclusion_reason"] == "NOT_ELIGIBLE"
    assert by_frame[13]["scored_frame"] is False and by_frame[13]["exclusion_reason"] == "EXCLUDED_TRACK_LAST"
    assert by_frame[20]["exclusion_reason"] == "EXCLUDED_TRACK_SINGLE_FRAME"
    assert by_frame[30]["exclusion_reason"] == "EXCLUDED_TRACK_FIRST" and by_frame[31]["exclusion_reason"] == "EXCLUDED_TRACK_LAST"
    assert all(row["scored_frame_rule_version"] == SCORED_FRAME_RULE_VERSION for row in labelled)
    assert SCORED_FRAME_RULE_ID == "exclude_first_and_last_eligible_frame_of_each_scan_track"
    assert scored_frame_indices(labelled) == (11,)
    assert rows[0].get("scored_frame") is None  # input rows are not mutated


# ----------------------------------------------------------- evaluator policy


def test_scope_accepts_the_record_undefined_policy_and_defaults_to_reject():
    scope = CalibrationExecutionScope(scope_id="x", observation_frame_indices=(1, 2))
    assert scope.undefined_observation_policy == "reject" and scope.to_dict()["undefined_observation_policy"] == "reject"
    recorded = CalibrationExecutionScope(scope_id="x", undefined_observation_policy="record_undefined")
    assert recorded.to_dict()["undefined_observation_policy"] == "record_undefined"
    with pytest.raises(CurrentExperimentFrameworkError, match="undefined_observation_policy"):
        CalibrationExecutionScope(scope_id="x", undefined_observation_policy="bogus")


def test_observation_records_carry_scored_and_undefined_statuses():
    diagnostics = [
        {"classification": "FINITE_MELT"},
        {"classification": "NO_LASER_ASSOCIATED_MELT"},
        {"classification": "UNENCLOSED", "production_hw_invalid_reason": "UNENCLOSED_BEAM_COMPONENT"},
    ]
    result = SimpleNamespace(
        frame_index=np.array([5, 6, 7]),
        mapped_process_row=np.array([50, 60, 70]),
        experimental_H_pixels=np.array([9.0, 9.0, 9.0]),
        experimental_W_pixels=np.array([7.0, 7.0, 7.0]),
        simulated_H_pixels=np.array([10.0, 0.0, float("nan")]),
        simulated_W_pixels=np.array([6.0, 0.0, float("nan")]),
        observation_diagnostics=tuple(diagnostics),
    )
    with pytest.raises(CurrentExperimentFrameworkError, match="nonfinite"):
        _calibration_observation_records(result)
    records = _calibration_observation_records(result, allow_nonfinite_primary=True)
    assert [row["observation_status"] for row in records] == ["SCORED", "SCORED", "UNDEFINED_UNENCLOSED_BEAM_COMPONENT"]
    assert [row["melt_classification"] for row in records] == ["FINITE_MELT", "NO_LASER_ASSOCIATED_MELT", "UNENCLOSED"]
    assert records[2]["undefined_reason"] == "UNENCLOSED_BEAM_COMPONENT" and records[0]["undefined_reason"] is None


# ------------------------------------------------------ 22.4.3 records and gate


def _evaluation(observations: list[dict]) -> dict:
    return {
        "status": "PASS",
        "stage": "complete",
        "observations": observations,
        "temperature_trace": {"thermal_substep_count": 10, "raw_global_Tmax_K": 2500.0},
        "execution_telemetry": {
            "directional_step_count": 10,
            "temperature_clipping_used": False,
            "every_substep_temperature_trace_complete": True,
            "production_hw_semantics_version": PRODUCTION_HW_SEMANTICS_VERSION,
            "production_hw_definition": PRODUCTION_HW_DEFINITION,
            "production_hw_association_policy_version": POLICY_VERSION,
            "maximum_abs_source_power_relative_error": 1.0e-14,
        },
        "energy_accounting": {"energy_balance_relative_error": 1.0e-14},
        "high_temperature_diagnostics": {},
        "failure": None,
        "temperature_clipping_permitted": False,
    }


def _observation(frame: int, h, w, status: str = "SCORED") -> dict:
    return {"frame_index": frame, "experimental_H_pixels": 9.0, "experimental_W_pixels": 7.0, "simulated_H_pixels": h, "simulated_W_pixels": w, "observation_status": status}


def test_frame_records_keep_undefined_and_excluded_frames_without_failing_the_unit():
    base = apply_scored_frame_rule(_rows("20260730:part_1", {"1": [10, 11, 12, 13]}))
    observations = [_observation(11, 10.0, 6.0), _observation(12, float("nan"), float("nan"), "UNDEFINED_UNENCLOSED_BEAM_COMPONENT")]
    rows, failures = _frame_records_from_evaluation(_evaluation(observations), base_rows=base, undefined_observation_policy="record_undefined")
    assert failures == []
    by_frame = {row["frame_index"]: row for row in rows}
    assert by_frame[10]["status"] == "EXCLUDED" and by_frame[10]["exclusion_reason"] == "EXCLUDED_TRACK_FIRST" and "simulated_H_pixels" not in by_frame[10]
    assert by_frame[11]["status"] == "PASS" and by_frame[11]["simulated_H_pixels"] == 10.0
    assert by_frame[12]["status"] == "UNDEFINED" and by_frame[12]["undefined_reason"] == "UNENCLOSED_BEAM_COMPONENT"
    assert by_frame[12].get("simulated_H_pixels") is None
    assert by_frame[13]["status"] == "EXCLUDED"
    # the historical reject policy still refuses a nonfinite observation
    assert "nonfinite_primary_observation" in _trial_gate_failures(_evaluation(observations), 2)
    # a scored frame that never came back is still an infrastructure failure for the whole unit
    rows, failures = _frame_records_from_evaluation(_evaluation(observations[:1]), base_rows=base, undefined_observation_policy="record_undefined")
    assert failures and all(row["status"] == "FAIL" for row in rows)


def test_stage_a_annotation_keeps_experimental_observation_status_so_the_objective_accepts_the_records():
    # Regression: the Stage A worker once overwrote the row's experimental-side observation_status with the
    # evaluator's SCORED / None, and the hierarchical objective rejected every candidate ("invalid observation_status").
    base = apply_scored_frame_rule(_rows("toy:part_1", {"1": [10, 11, 12, 13, 14, 15]}))
    evaluation = _evaluation([_observation(frame, 10.0, 6.0) for frame in (11, 12, 13, 14)])
    records, failures = _frame_records_from_evaluation(evaluation, base_rows=base, undefined_observation_policy="record_undefined")
    assert failures == []
    stage_a_module._annotate_frame_records(records, evaluation)
    assert {row["observation_status"] for row in records} == {"ELIGIBLE_FINITE_HW"}  # including the rule-excluded edge frames
    assert {row["frame_index"]: row["evaluator_observation_status"] for row in records} == {10: None, 11: "SCORED", 12: "SCORED", 13: "SCORED", 14: "SCORED", 15: None}
    objective = _aggregate(records)
    assert objective["status"] == "PASS"
    assert objective["counts"]["scored_frame_count"] == 4 and objective["counts"]["excluded_by_rule_count"] == 2


# ------------------------------------------------------------ F3 objective


def _scored_records(undefined: set[int] = frozenset(), excluded_extra: set[int] = frozenset(), fail: set[int] = frozenset()) -> list[dict]:
    rows = apply_scored_frame_rule(_rows("toy:part_1", {"1": list(range(10, 22)), "2": list(range(30, 42))}))
    for row in rows:
        frame = row["frame_index"]
        if frame in excluded_extra:
            row["scored_frame"] = False
            row["exclusion_reason"] = "EXCLUDED_TRACK_FIRST"
        if row["scored_frame"]:
            row["status"] = "PASS"
            row["simulated_H_pixels"] = 9.5
            row["simulated_W_pixels"] = 7.2
        else:
            row["status"] = "EXCLUDED"
        if frame in undefined:
            row["status"] = "UNDEFINED"
            row["undefined_reason"] = "FAIL_CLOSED_TIED_SHARE"
            row.pop("simulated_H_pixels", None)
            row.pop("simulated_W_pixels", None)
        if frame in fail:
            row["status"] = "FAIL"
            row["failure"] = {"code": "PATCH_22_4_3_MISSING_SIMULATED_FRAME_RECORD"}
    return rows


def _aggregate(records):
    return aggregate_hierarchical_records(records, calibration_member_ids={"toy:part_1"}, calibration_condition_ids={"P140_V850"}, require_complete=False, candidate_id="c")


def test_objective_scores_only_scored_frames_and_reports_coverage():
    clean = _aggregate(_scored_records())
    assert clean["status"] == "PASS" and clean["coverage_flag"] is False and clean["low_coverage_coupons"] == []
    counts = clean["counts"]
    assert counts["eligible_frame_count"] == 24 and counts["excluded_by_rule_count"] == 4
    assert counts["scored_frame_count"] == 20 and counts["undefined_frame_count"] == 0
    assert counts["coverage"] == 1.0 and counts["coverage_floor"] == COVERAGE_FLOOR and counts["coverage_by_coupon"] == {"toy:part_1": 1.0}
    assert clean["objective_value"] == pytest.approx(0.5 * (0.5 / 0.9) ** 2 + 0.5 * (0.2 / 0.65) ** 2)
    excluded_rows = [row for row in clean["frame_rows"] if row["frame_class"] == "EXCLUDED_BY_RULE"]
    assert len(excluded_rows) == 4 and all(row["objective_inclusion"] is False and row["simulated_H_pixels"] is None for row in excluded_rows)

    one_undefined = _aggregate(_scored_records(undefined={11}))
    assert one_undefined["objective_value"] == pytest.approx(clean["objective_value"])  # undefined frames never enter residuals
    assert one_undefined["counts"]["undefined_frame_count"] == 1 and one_undefined["counts"]["coverage"] == pytest.approx(19 / 20)
    assert one_undefined["coverage_flag"] is False
    undefined_row = next(row for row in one_undefined["frame_rows"] if row["frame_index"] == 11)
    assert undefined_row["frame_class"] == "UNDEFINED" and undefined_row["undefined_reason"] == "FAIL_CLOSED_TIED_SHARE"

    two_undefined = _aggregate(_scored_records(undefined={11, 12}))
    assert two_undefined["status"] == "PASS" and two_undefined["coverage_flag"] is True
    assert two_undefined["low_coverage_coupons"] == ["toy:part_1"] and two_undefined["counts"]["coverage"] == pytest.approx(18 / 20)
    assert two_undefined["objective_value"] == pytest.approx(clean["objective_value"])


def test_objective_penalizes_only_infrastructure_failures_and_empty_coupons():
    failed = _aggregate(_scored_records(fail={15}))
    assert failed["status"] == FAILED_CANDIDATE_STATUS and failed["objective_value"] == FAILED_CANDIDATE_PENALTY
    assert failed["failed_member_records"][0]["frame_index"] == 15
    empty = _aggregate(_scored_records(undefined=set(range(11, 21)) | set(range(31, 41))))
    assert empty["status"] == FAILED_CANDIDATE_STATUS and "no scored frames" in empty["failure_reason"]


def test_objective_contract_and_design_verification_include_coverage():
    contract = validate_hierarchical_objective_contract()
    assert contract["status"] == "PASS" and contract["coverage_floor"] == COVERAGE_FLOOR
    verification = run_design_only_verification()
    assert verification["checks"]["undefined_frames_excluded_with_coverage"] is True
    assert verification["checks"]["failed_candidates_fail_closed_without_fabricated_residuals"] is True


def test_readiness_freeze_pins_22_3_7_and_frame_level_policies():
    freeze = build_freeze()
    contract = freeze["observation_contract"]
    assert contract["production_hw_semantics_version"] == "22.3.7" and contract["production_hw_association_policy_version"] == "22.3.7"
    assert contract["undefined_observation_policy"] == "record_undefined"
    assert contract["scored_frame_rule"]["version"] == SCORED_FRAME_RULE_VERSION
    assert contract["no_laser_associated_melt_policy"].startswith("scored as H=0,W=0")
    assert contract["candidate_failure_policy"].startswith("frame-level")
    assert freeze["objective_contract"]["coverage_floor"] == COVERAGE_FLOOR
    assert freeze["acceptance_gates"]["production_hw_is_laser_associated_22_3_7"] is True
    assert "production_hw_is_laser_associated_22_3_5" not in freeze["acceptance_gates"]
    assert freeze["all_acceptance_gates_pass"] is True


# ------------------------------------------------------------- Stage A runner


def _member(position: int) -> DatasetMember:
    return DatasetMember(set_id=1, dataset_member_id=position, coupon_position=position, path=Path(f"part_{position}_20260730.h5").resolve(), sha256=f"{position:064d}", power_W=140.0, nominal_speed_mm_s=850.0, spot_diameter_mm=0.08, acquisition_set_id="20260730")


MEMBERS = {"20260730:part_1": _member(1), "20260730:part_3": _member(3)}


def _member_rows():
    return {
        "20260730:part_1": _rows("20260730:part_1", {"1": [10, 11, 12, 13], "2": [20, 21, 22]}),
        "20260730:part_3": _rows("20260730:part_3", {"1": [30, 31, 32]}),
    }


def test_stage_a_jobs_carry_labelled_rows_and_only_request_scored_frames(tmp_path):
    jobs = build_stage_a_jobs([("anchor_t_min", "20260730:part_1"), ("anchor_center", "20260730:part_1")], MEMBERS, _member_rows(), characterization_directory=tmp_path)
    assert [job.experiment_context_dict["candidate_id"] for job in jobs] == ["anchor_center", "anchor_t_min"]
    rows = json.loads(jobs[0].experiment_context_dict["frame_rows_json"])
    assert [row["frame_index"] for row in rows if row["scored_frame"]] == [11, 12, 21]
    assert jobs[0].frame_index == 11 and pickle.loads(pickle.dumps(jobs[0])) == jobs[0]
    with pytest.raises(StageAError, match="frozen coarse design"):
        build_stage_a_jobs([("nope", "20260730:part_1")], MEMBERS, _member_rows(), characterization_directory=tmp_path)


def _fake_stage_a_unit(job):
    context = job.experiment_context_dict
    rows = json.loads(context["frame_rows_json"])
    records = []
    for row in rows:
        record = dict(row)
        if row["scored_frame"]:
            record["status"] = "PASS"
            record["simulated_H_pixels"] = 10.0 + row["frame_index"] % 3
            record["simulated_W_pixels"] = 6.0
            record["production_status"] = "SELECTED"
            record["production_selected_label"] = 1
        else:
            record["status"] = "EXCLUDED"
            record["production_status"] = None
        records.append(record)
    return {
        "candidate_id": context["candidate_id"],
        "member_identity": job.member_identity,
        "frame_records": records,
        "gate_failures": [],
        "evaluation_status": "PASS",
        "evaluation_stage": "complete",
        "evaluation_failure": None,
        "requested_frame_count": sum(1 for row in rows if row["scored_frame"]),
        "returned_frame_count": sum(1 for row in rows if row["scored_frame"]),
        "thermal_execution_performed": True,
    }


def test_stage_a_parallel_equals_serial_and_reports_per_candidate_coverage(tmp_path, monkeypatch):
    monkeypatch.setattr(stage_a_module, "_member_map", lambda data_directory: dict(MEMBERS))
    monkeypatch.setattr(stage_a_module, "_find_frame_file", lambda root, member: Path(root) / f"{member.coupon_position}.csv")
    monkeypatch.setattr(stage_a_module, "_portable_frame_rows", lambda path, member: list(_member_rows()[f"20260730:part_{member.coupon_position}"]))
    monkeypatch.setattr(stage_a_module, "_stage_a_unit_job", _fake_stage_a_unit)

    def fake_pool(jobs, worker, *, workers, on_result=None):
        results = []
        for job in reversed(tuple(jobs)):
            result = SimulationResult(job=job, payload=worker(job))
            if on_result is not None:
                on_result(result)
            results.append(result)
        return tuple(results)

    monkeypatch.setattr(stage_a_module, "execute_parallel_jobs", fake_pool)
    common = dict(data_directory=tmp_path, characterization_directory=tmp_path, candidates=("anchor_center", "anchor_t_min"))
    serial = run_stage_a(output_directory=tmp_path / "serial", workers=1, **common)
    parallel = run_stage_a(output_directory=tmp_path / "parallel", workers=4, **common)
    assert serial["status"] == parallel["status"] == STAGE_A_STATUS_PASS
    assert serial["candidates"] == parallel["candidates"]
    candidate = serial["candidates"]["anchor_t_min"]
    assert candidate["objective_status"] == "PASS" and candidate["coverage_flag"] is False
    assert candidate["coverage_by_coupon"] == {"20260730:part_1": 1.0, "20260730:part_3": 1.0}
    assert candidate["scored_frame_count"] == 4 and candidate["excluded_frame_count"] == 6 and candidate["undefined_frame_count"] == 0
    assert math.isfinite(candidate["objective_value_partial_two_members"])
    assert serial["production_hw_semantics_version"] == "22.3.7" and serial["full_campaign_dispatched"] is False
    assert (tmp_path / "parallel" / "PATCH_22_3_7_STAGE_A_FRAMES.csv").read_bytes() == (tmp_path / "serial" / "PATCH_22_3_7_STAGE_A_FRAMES.csv").read_bytes()
    written = [json.loads((tmp_path / folder / "PATCH_22_3_7_STAGE_A_REPORT.json").read_text(encoding="utf-8")) for folder in ("serial", "parallel")]
    for report in written:
        report.pop("stage_a_execution")  # the only field that may differ between the two runs
    assert written[0] == written[1]
    assert serial["stage_a_execution"]["start_method"] == "serial" and parallel["stage_a_execution"]["workers"] == 4


def test_census_prediction_join_verifies_production_against_offline_rule(tmp_path):
    census_dir = tmp_path / "census"
    (census_dir / "units").mkdir(parents=True)
    components = [
        {"label": 1, "beam_share": 0.30, "contains_beam_cell": False, "touches_boundary": False, "contour_status": "FINITE_BEAM_COMPONENT", "H_pixels": 10.0, "W_pixels": 6.0, "min_contour_distance_cells": 0.4, "min_cell_center_distance_cells": 1.1},
        {"label": 2, "beam_share": 0.001, "contains_beam_cell": False, "touches_boundary": False, "contour_status": "FINITE_BEAM_COMPONENT", "H_pixels": 12.0, "W_pixels": 7.0, "min_contour_distance_cells": 4.0, "min_cell_center_distance_cells": 4.5},
    ]
    frames = [
        {"frame_index": 11, "census_components": components, "production_status": "FAIL_CLOSED_DISTANCE_EXCEEDED"},
        {"frame_index": 12, "census_components": [components[1]], "production_status": "FAIL_CLOSED_DISTANCE_EXCEEDED"},
        {"frame_index": 21, "census_components": [], "production_status": "ZERO_FOOTPRINT"},
    ]
    (census_dir / "units" / "anchor_center__20260730_part_1.json").write_text(json.dumps({"candidate_id": "anchor_center", "member_identity": "20260730:part_1", "frames": frames}), encoding="utf-8")
    (census_dir / "PATCH_22_3_6_ASSOCIATION_CENSUS_REPORT.json").write_text(json.dumps({"units": [{"candidate_id": "anchor_center", "member_identity": "20260730:part_1", "unit_file": "anchor_center__20260730_part_1.json"}]}), encoding="utf-8")
    stage_a_records = [
        {"frame_index": 11, "status": "PASS", "simulated_H_pixels": 10.0, "simulated_W_pixels": 6.0, "production_status": "SELECTED", "production_selected_label": 1},
        {"frame_index": 12, "status": "PASS", "simulated_H_pixels": 0.0, "simulated_W_pixels": 0.0, "production_status": NO_LASER_ASSOCIATED_MELT_STATUS, "production_selected_label": None},
        {"frame_index": 21, "status": "PASS", "simulated_H_pixels": 0.0, "simulated_W_pixels": 0.0, "production_status": "ZERO_FOOTPRINT", "production_selected_label": None},
    ]
    comparison = compare_with_census_prediction(census_dir, {("anchor_center", "20260730:part_1"): stage_a_records})
    assert comparison["frames_compared"] == 3 and comparison["status_matches"] == 3 and comparison["hw_matches"] == 1
    assert comparison["mismatches"] == [] and comparison["verdict"] == "PASS"
    stage_a_records[0]["simulated_H_pixels"] = 10.5
    comparison = compare_with_census_prediction(census_dir, {("anchor_center", "20260730:part_1"): stage_a_records})
    assert comparison["verdict"] == "FAIL" and comparison["mismatches"][0]["frame_index"] == 11
