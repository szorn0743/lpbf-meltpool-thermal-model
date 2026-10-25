from __future__ import annotations

import csv
import math
from dataclasses import replace
from pathlib import Path

import pytest

from lpbf.calibration_contract import condition_id
from lpbf.data.full_coupon_manifest import load_full_coupon_manifest
from lpbf.execution.campaign_provenance import (
    canonical_coupon_roster,
    deterministic_result_relative_path,
    result_record,
)
from lpbf.experiments.dataset import DatasetMember
from lpbf.hierarchical_objective import FrameSetContract
from lpbf.patch22_4_1_calibration_readiness import build_freeze
from lpbf.patch22_4_2_parallel_coarse_calibration import build_coarse_calibration_manifest
from lpbf.patch22_4_3_parallel_coarse_calibration_execution import (
    PATCH_VERSION,
    REVIEW_STATUS,
    WORK_UNIT_PAYLOAD_SCHEMA,
    PreflightBundle,
    _aggregate_and_write,
    _find_frame_file,
    _frame_records_from_evaluation,
    _json_safe,
    _load_completed_records,
    _portable_frame_rows,
    _validate_process_condition_manifest,
    _validate_payload,
    _trial_gate_failures,
    Patch2243Error,
    PRODUCTION_HW_ASSOCIATION_POLICY_VERSION,
    PRODUCTION_HW_DEFINITION,
    PRODUCTION_HW_SEMANTICS_VERSION,
)
from lpbf.infrastructure import canonical_sha256, write_json


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


def _payload_for_unit(
    unit,
    *,
    frame_observations_sha256: str = "frame-current",
    preflight_sha256: str = "preflight-current",
    frame_set_identity_digest: str = "frame-set-current",
    candidate_coordinates: dict | None = None,
) -> dict:
    row = _base_row(
        unit.member_identity,
        float(unit.nominal_power_W),
        float(unit.nominal_speed_mm_s),
        int(unit.coupon_position),
    )
    row["portable_member_identity"] = unit.portable_member_identity
    row["source_date"] = unit.source_date
    row["spot_diameter_mm"] = float(unit.spot_diameter_mm)
    payload = {
        "schema": WORK_UNIT_PAYLOAD_SCHEMA,
        "schema_version": PATCH_VERSION,
        "status": "PASS",
        "work_unit_id": unit.work_unit_id,
        "candidate_id": unit.parameter_point_id,
        "member_identity": unit.member_identity,
        "candidate_coordinates": dict(
            unit.parameter_values if candidate_coordinates is None else candidate_coordinates
        ),
        "parameter_sha256": unit.parameter_sha256,
        "campaign_manifest_sha256": unit.canonical_manifest_sha256,
        "preflight_sha256": preflight_sha256,
        "frame_observations_sha256": frame_observations_sha256,
        "frame_set_identity_digest": frame_set_identity_digest,
        "portable_member_identity": unit.portable_member_identity,
        "input_sha256": unit.input_sha256,
        "acquisition_set_id": unit.acquisition_set_id,
        "coupon_position": int(unit.coupon_position),
        "condition_id": unit.condition_id,
        "process_condition_id": condition_id(
            unit.nominal_power_W, unit.nominal_speed_mm_s
        ),
        "nominal_power_W": float(unit.nominal_power_W),
        "nominal_speed_mm_s": float(unit.nominal_speed_mm_s),
        "spot_diameter_mm": float(unit.spot_diameter_mm),
        "source_date": unit.source_date,
        "process_condition_provenance": dict(unit.process_condition_provenance),
        "parameter_sweep_id": unit.parameter_sweep_id,
        "production_hw_definition": PRODUCTION_HW_DEFINITION,
        "production_hw_semantics_version": PRODUCTION_HW_SEMANTICS_VERSION,
        "production_hw_association_policy_version": PRODUCTION_HW_ASSOCIATION_POLICY_VERSION,
        "window_cells": 99,
        "frame_record_count": 1,
        "eligible_frame_count": 1,
        "frame_records": [row],
        "gate_failures": [],
        "diagnostics": {
            "atomic_evaluation_status": "PASS",
            "raw_global_Tmax_K": 2500.0,
            "energy_balance_relative_error": 1.0e-14,
            "maximum_abs_source_power_relative_error": 1.0e-14,
        },
        "atomic_evaluation_sha256": "synthetic",
        "atomic_failure_evaluation": None,
        "validation_partition_used": False,
        "parameter_selection_performed": False,
        "parameter_fitting_performed": False,
    }
    payload["payload_sha256"] = canonical_sha256(
        {key: value for key, value in payload.items() if key != "payload_sha256"}
    )
    return payload


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


def test_payload_validation_rejects_validation_partition_use():
    manifest = build_coarse_calibration_manifest()
    unit = manifest.work_units[0]
    payload = _payload_for_unit(unit)
    payload["validation_partition_used"] = True
    payload["payload_sha256"] = canonical_sha256(
        {key: value for key, value in payload.items() if key != "payload_sha256"}
    )
    with pytest.raises(Exception):
        _validate_payload(payload, unit)


def test_payload_validation_rejects_candidate_coordinate_mismatch_even_with_correct_id():
    manifest = build_coarse_calibration_manifest()
    unit = manifest.work_units[0]
    payload = _payload_for_unit(unit)
    altered = dict(payload["candidate_coordinates"])
    first_name = sorted(altered)[0]
    altered[first_name] = float(altered[first_name]) + 1.0e-9
    payload["candidate_coordinates"] = altered
    payload["payload_sha256"] = canonical_sha256(
        {key: value for key, value in payload.items() if key != "payload_sha256"}
    )
    with pytest.raises(Patch2243Error, match="candidate coordinates"):
        _validate_payload(payload, unit)


def test_resume_rejects_checkpoint_bound_to_old_characterization_hash(tmp_path: Path):
    manifest = build_coarse_calibration_manifest()
    unit = manifest.work_units[0]
    payload = _payload_for_unit(unit, frame_observations_sha256="old-frame-hash")
    record_path = tmp_path / deterministic_result_relative_path(unit)
    record_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(record_path, result_record(unit, payload))

    with pytest.raises(Patch2243Error, match="characterization provenance"):
        _load_completed_records(
            manifest=manifest,
            result_root=tmp_path,
            resume=True,
            expected_preflight_sha256="preflight-current",
            expected_frame_observations_sha256={
                unit.member_identity: "new-frame-hash"
            },
            expected_frame_set_identity_digest="frame-set-current",
        )


def test_full_24_coupon_process_condition_manifest_gate_rejects_swapped_power():
    manifest = load_full_coupon_manifest()
    members = []
    for ordinal, member in enumerate(manifest.enabled_members, start=1):
        members.append(
            DatasetMember(
                set_id=ordinal,
                dataset_member_id=member.key.part_number,
                coupon_position=member.key.part_number,
                path=Path(member.expected_filename),
                sha256=str(member.sha256),
                power_W=float(member.nominal_power_W),
                nominal_speed_mm_s=float(member.nominal_speed_mm_s),
                spot_diameter_mm=float(member.spot_diameter_mm),
                campaign_id=member.key.campaign_id,
                acquisition_set_id=member.key.acquisition_set_id,
                layer_name=member.key.layer_name,
                expected_filename=member.expected_filename,
                source_date=str(member.process_condition_provenance["source_date"]),
                process_condition_provenance=dict(member.process_condition_provenance),
            )
        )
    assert len(_validate_process_condition_manifest(members)) == 24
    altered = list(members)
    altered[0] = replace(altered[0], power_W=999.0)
    with pytest.raises(Patch2243Error, match="process-condition mismatch"):
        _validate_process_condition_manifest(altered)


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


def test_full_272_record_aggregation_ranks_candidates_without_final_selection(tmp_path: Path):
    manifest = build_coarse_calibration_manifest()
    freeze = build_freeze()
    calibration = set(freeze["campaign"]["calibration_members"])
    roster = {row["member_identity"]: row for row in canonical_coupon_roster()}
    base_rows = []
    for member_id in sorted(calibration):
        meta = roster[member_id]
        base_rows.append(
            _base_row(
                member_id,
                float(meta["nominal_power_W"]),
                float(meta["nominal_speed_mm_s"]),
                int(meta["coupon_position"]),
            )
        )
    frame_contract = FrameSetContract.from_records(base_rows)
    preflight = {
        "schema": "lpbf_patch22_4_3_real_coarse_calibration_preflight",
        "schema_version": PATCH_VERSION,
        "status": "PASS_PATCH_22_4_3_REAL_COARSE_CALIBRATION_PREFLIGHT",
        "preflight_sha256": "synthetic-preflight",
        "process_condition_manifest_sha256": "synthetic-process-condition-manifest",
    }
    bundle = PreflightBundle(
        manifest=manifest,
        jobs=(),
        frame_set_contract=frame_contract,
        base_rows=tuple(base_rows),
        preflight_record=preflight,
    )
    base_by_member = {row["member_identity"]: row for row in base_rows}
    candidate_ids = []
    for unit in manifest.work_units:
        if unit.parameter_point_id not in candidate_ids:
            candidate_ids.append(unit.parameter_point_id)
    residual_by_candidate = {cid: 0.01 * i for i, cid in enumerate(candidate_ids)}
    records = []
    for unit in manifest.work_units:
        base = dict(base_by_member[unit.member_identity])
        residual = residual_by_candidate[unit.parameter_point_id]
        row = dict(base)
        row["simulated_H_pixels"] = row["experimental_H_pixels"] + residual
        row["simulated_W_pixels"] = row["experimental_W_pixels"] + 2.0 * residual
        payload = _payload_for_unit(unit)
        payload["frame_records"] = [row]
        payload["diagnostics"] = {
            "atomic_evaluation_status": "PASS",
            "raw_global_Tmax_K": 2500.0,
            "energy_balance_relative_error": 1.0e-14,
            "maximum_abs_source_power_relative_error": 1.0e-14,
        }
        payload["payload_sha256"] = canonical_sha256(
            {key: value for key, value in payload.items() if key != "payload_sha256"}
        )
        records.append(result_record(unit, payload))

    write_json(tmp_path / "PATCH_22_4_3_REAL_COARSE_CALIBRATION_PREFLIGHT.json", preflight)
    write_json(
        tmp_path / "PATCH_22_4_3_REAL_COARSE_CALIBRATION_EXECUTION_MANIFEST.json",
        {"schema": "synthetic"},
    )
    status = _aggregate_and_write(
        output=tmp_path,
        bundle=bundle,
        records=list(reversed(records)),
        workers=4,
        reused_result_count=0,
    )
    assert status["status"] == REVIEW_STATUS
    assert status["successful_candidate_count"] == 17
    assert status["failed_candidate_count"] == 0
    assert status["coarse_incumbent_candidate_id"] == candidate_ids[0]
    assert status["coarse_incumbent_is_final_parameter_selection"] is False
    assert status["regional_refinement_authorized"] is False
    assert status["held_out_validation_authorized"] is False
    assert status["parameter_fitting_performed"] is False
    assert (tmp_path / "patch22_4_3_coarse_calibration_review_bundle.zip").is_file()
    trial_rows = list(
        csv.DictReader(
            (tmp_path / "PATCH_22_4_3_TRIAL_SUMMARIES.csv").open(
                "r", encoding="utf-8", newline=""
            )
        )
    )
    assert len(trial_rows) == 272
    units_by_id = {unit.work_unit_id: unit for unit in manifest.work_units}
    for row in trial_rows:
        unit = units_by_id[row["work_unit_id"]]
        assert row["member_identity"] == unit.member_identity
        assert row["acquisition_set_id"] == unit.acquisition_set_id
        assert row["coupon_position"] == str(unit.coupon_position)
        assert row["source_date"] == unit.source_date
        assert row["nominal_power_W"] == str(float(unit.nominal_power_W))
        assert row["nominal_speed_mm_s"] == str(float(unit.nominal_speed_mm_s))
        assert row["candidate_id"] == unit.parameter_point_id
