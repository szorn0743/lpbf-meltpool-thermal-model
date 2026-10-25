from lpbf.patch22_4_2_parallel_coarse_calibration import (
    EXPECTED_CANDIDATES,
    EXPECTED_CALIBRATION_MEMBERS,
    EXPECTED_WORK_UNITS,
    STATUS,
    build_authorization_record,
    build_coarse_calibration_manifest,
)
from lpbf.patch22_4_1_calibration_readiness import build_freeze


def test_manifest_is_17_by_16_calibration_only():
    manifest = build_coarse_calibration_manifest()
    freeze = build_freeze()
    cal = set(freeze["campaign"]["calibration_members"])
    val = set(freeze["campaign"]["validation_members"])
    assert len(manifest.work_units) == EXPECTED_WORK_UNITS == 272
    assert len({u.parameter_point_id for u in manifest.work_units}) == EXPECTED_CANDIDATES == 17
    assert {u.member_identity for u in manifest.work_units} == cal
    assert not ({u.member_identity for u in manifest.work_units} & val)


def test_each_candidate_has_all_16_calibration_members():
    manifest = build_coarse_calibration_manifest()
    for candidate in {u.parameter_point_id for u in manifest.work_units}:
        members = {u.member_identity for u in manifest.work_units if u.parameter_point_id == candidate}
        assert len(members) == EXPECTED_CALIBRATION_MEMBERS == 16


def test_authorization_contract_passes_without_spawn_execution():
    record = build_authorization_record(workers=4, execute_spawn_test=False)
    assert record["status"] == STATUS
    assert record["all_acceptance_gates_pass"]
    assert record["authorization"]["coarse_calibration_search_authorized_after_acceptance"]
    assert not record["authorization"]["regional_refinement_authorized"]
    assert not record["authorization"]["held_out_validation_authorized"]
    assert not record["authorization"]["thermal_search_performed"]


def test_immutability_and_window_are_frozen():
    record = build_authorization_record(workers=4, execute_spawn_test=False)
    assert record["campaign"]["production_window_cells"] == 99
    assert record["campaign"]["workers"] == 4
    assert record["immutability"] == {
        "accepted_numerical_core_modified": False,
        "production_hw_definition_changed": False,
        "objective_contract_changed": False,
        "calibration_partition_changed": False,
    }
