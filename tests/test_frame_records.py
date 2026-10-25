from __future__ import annotations

import math
from pathlib import Path

import pytest

from lpbf.calibration_contract import condition_id
from lpbf.experiments.dataset import DatasetMember
from lpbf.frame_records import (
    FrameRecordError as Patch2243Error,
    PRODUCTION_HW_ASSOCIATION_POLICY_VERSION,
    PRODUCTION_HW_DEFINITION,
    PRODUCTION_HW_SEMANTICS_VERSION,
    _frame_records_from_evaluation,
    _json_safe,
    _portable_frame_rows,
    _trial_gate_failures,
)


def _base_row(member_id: str, power: float, speed: float, part: int) -> dict:
    return {
        "member_identity": member_id,
        "portable_member_identity": member_id,
        "acquisition_set_id": member_id.split(":", 1)[0],
        "part_number": part,
        "power_W": power,
        "speed_mm_s": speed,
        "exact_condition_id": condition_id(power, speed),
        "scan_track_id": "track_0",
        "frame_index": 0,
        "experimental_H_pixels": 10.0,
        "experimental_W_pixels": 5.0,
        "observation_eligible": True,
        "observation_status": "ELIGIBLE_FINITE_HW",
        "source_observation_status": "positive",
        "status": "PASS",
        "failure": None,
    }


def _pass_evaluation() -> dict:
    return {
        "status": "PASS",
        "stage": "complete",
        "observations": [
            {
                "frame_index": 0,
                "experimental_H_pixels": 10.0,
                "experimental_W_pixels": 5.0,
                "simulated_H_pixels": 10.1,
                "simulated_W_pixels": 5.2,
            }
        ],
        "temperature_trace": {"thermal_substep_count": 10, "raw_global_Tmax_K": 2500.0},
        "execution_telemetry": {
            "directional_step_count": 10,
            "temperature_clipping_used": False,
            "every_substep_temperature_trace_complete": True,
            "production_hw_semantics_version": PRODUCTION_HW_SEMANTICS_VERSION,
            "production_hw_definition": PRODUCTION_HW_DEFINITION,
            "production_hw_association_policy_version": PRODUCTION_HW_ASSOCIATION_POLICY_VERSION,
            "maximum_abs_source_power_relative_error": 1.0e-14,
        },
        "energy_accounting": {"energy_balance_relative_error": 1.0e-14},
        "high_temperature_diagnostics": {},
        "failure": None,
        "temperature_clipping_permitted": False,
    }


def test_json_safe_replaces_nonfinite_values_without_changing_finite_values():
    safe = _json_safe({"a": math.nan, "b": math.inf, "c": -math.inf, "d": 1.25})
    assert safe == {"a": None, "b": None, "c": None, "d": 1.25}


def test_frame_record_conversion_passes_finite_atomic_evaluation():
    base = [_base_row("toy:part_1", 140.0, 850.0, 1)]
    rows, failures = _frame_records_from_evaluation(_pass_evaluation(), base_rows=base)
    assert failures == []
    assert rows[0]["status"] == "PASS"
    assert rows[0]["simulated_H_pixels"] == pytest.approx(10.1)
    assert rows[0]["simulated_W_pixels"] == pytest.approx(5.2)


def test_frame_record_conversion_fails_candidate_closed_on_atomic_failure():
    evaluation = _pass_evaluation()
    evaluation["status"] = "FAILURE"
    evaluation["stage"] = "observation_validation"
    evaluation["failure"] = {"code": "PRIMARY_OBSERVATION_REJECTED"}
    base = [_base_row("toy:part_1", 140.0, 850.0, 1)]
    rows, failures = _frame_records_from_evaluation(evaluation, base_rows=base)
    assert "atomic_evaluator_not_complete_pass" in failures
    assert rows[0]["status"] == "FAIL"
    assert rows[0]["failure"]["code"] == "PATCH_22_4_3_TRIAL_GATE_FAILURE"


def test_trial_gate_rejects_missing_production_hw_telemetry():
    evaluation = _pass_evaluation()
    evaluation["execution_telemetry"].pop("production_hw_semantics_version")
    failures = _trial_gate_failures(evaluation, expected_frame_count=1)
    assert "production_hw_semantics_version_drift" in failures


def test_portable_frame_rows_reject_wrong_coupon_identity(tmp_path: Path):
    member = DatasetMember(
        set_id=1,
        dataset_member_id=1,
        coupon_position=1,
        path=tmp_path / "part_1_20260730.h5",
        sha256="a" * 64,
        power_W=140.0,
        nominal_speed_mm_s=850.0,
        spot_diameter_mm=0.08,
        campaign_id="lpbf_2026_full_coupon_campaign",
        acquisition_set_id="20260730",
        layer_name="layer53",
        expected_filename="part_1_20260730.h5",
        source_date="2026-09-21",
        process_condition_provenance={"source_date": "2026-09-21"},
    )
    path = tmp_path / "frame_observations.csv"
    path.write_text(
        "acquisition_set_id,part_number,portable_member_identity,frame_index,"
        "mapping_status,laser_on,scan_track_id,H_pixels,W_pixels,hw_status,"
        "eligible_melt_pool_observation\n"
        "20260730,1,wrong-identity,0,valid_mapped,true,track_0,10,5,positive,true\n",
        encoding="utf-8",
    )
    with pytest.raises(Patch2243Error, match="portable_member_identity mismatch"):
        _portable_frame_rows(path, member)


