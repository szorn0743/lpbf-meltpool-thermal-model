from __future__ import annotations

import json
from pathlib import Path

import pytest

from lpbf.execution.campaign_provenance import (
    CampaignExecutionManifest,
    CampaignProvenanceError,
    CampaignStageSpec,
    ParameterPointSpec,
    authorize_stage_dispatch,
    build_campaign_execution_manifest,
    canonical_coupon_roster,
    deterministic_result_relative_path,
    order_result_records_by_manifest,
    reconcile_result_records,
    result_record,
    validate_result_record,
    write_result_once,
)
from lpbf.execution.work_units import SimulationJob
from lpbf.infrastructure import canonical_sha256, read_json

ROOT = Path(__file__).resolve().parents[1]
CONFIG_HASH = canonical_sha256(read_json(ROOT / "src/lpbf/data/frozen_configuration.json"))


def _contexts():
    rows = canonical_coupon_roster()
    result = {}
    for row in rows:
        result.setdefault(row["acquisition_set_id"], {"role": row["set_role"], "protocol": row["acquisition_set_id"]})
    return result


def _stage(stage_id="s1", ordinal=1, points=None):
    return CampaignStageSpec(
        stage_id,
        ordinal,
        f"exp_{stage_id}",
        "sweep",
        tuple(points or [ParameterPointSpec("P0001", {"x": 1.0})]),
        _contexts(),
    )


def _manifest(stages=None):
    return build_campaign_execution_manifest(tuple(stages or [_stage()]), model_configuration_sha256=CONFIG_HASH)


def test_canonical_roster_is_exact_four_by_six():
    rows = canonical_coupon_roster()
    assert len(rows) == 24
    assert [r["set_ordinal"] for r in rows[::6]] == [1, 2, 3, 4]
    for ordinal in range(1, 5):
        group = [r for r in rows if r["set_ordinal"] == ordinal]
        assert [r["coupon_position"] for r in group] == [1, 2, 3, 4, 5, 6]
        assert len({r["input_sha256"] for r in group}) == 6


def test_work_unit_ids_and_paths_are_unique_across_parameter_points():
    points = [ParameterPointSpec(f"P{i:04d}", {"x": float(i)}) for i in range(1, 4)]
    manifest = _manifest([_stage(points=points)])
    assert len(manifest.work_units) == 72
    ids = [u.work_unit_id for u in manifest.work_units]
    paths = [deterministic_result_relative_path(u) for u in manifest.work_units]
    assert len(ids) == len(set(ids))
    assert len(paths) == len(set(paths))


def test_set_specific_context_changes_identity():
    contexts = _contexts()
    stage = _stage()
    baseline = build_campaign_execution_manifest((stage,), model_configuration_sha256=CONFIG_HASH)
    changed = dict(contexts)
    changed["20260730"] = {**changed["20260730"], "protocol": "changed"}
    changed_stage = CampaignStageSpec("s1", 1, "exp_s1", "sweep", stage.parameter_points, changed)
    altered = build_campaign_execution_manifest((changed_stage,), model_configuration_sha256=CONFIG_HASH)
    a = {u.member_identity: u.work_unit_id for u in baseline.work_units}
    b = {u.member_identity: u.work_unit_id for u in altered.work_units}
    assert a["20260730:part_1"] != b["20260730:part_1"]
    assert a["20260731:part_1"] == b["20260731:part_1"]


def test_stage_transition_fails_closed_until_prior_stage_complete():
    manifest = _manifest([_stage("tests", 1), _stage("experiments", 2), _stage("sweep_stage", 3)])
    with pytest.raises(CampaignProvenanceError):
        authorize_stage_dispatch(manifest, "experiments", ())
    stage1 = authorize_stage_dispatch(manifest, "tests", ())
    stage2 = authorize_stage_dispatch(manifest, "experiments", [u.work_unit_id for u in stage1])
    with pytest.raises(CampaignProvenanceError):
        authorize_stage_dispatch(manifest, "sweep_stage", [u.work_unit_id for u in stage1])
    completed = [u.work_unit_id for u in stage1 + stage2]
    assert len(authorize_stage_dispatch(manifest, "sweep_stage", completed)) == 24


def test_result_reconciliation_is_order_independent_and_manifest_order_restored():
    manifest = _manifest()
    records = [result_record(u, {"value": u.sequence_index}) for u in manifest.work_units]
    reversed_records = list(reversed(records))
    assert reconcile_result_records(manifest, reversed_records)["pass"]
    ordered = order_result_records_by_manifest(manifest, reversed_records)
    assert [r["work_unit_id"] for r in ordered] == [u.work_unit_id for u in manifest.work_units]


def test_duplicate_missing_unexpected_and_identity_drift_fail_closed():
    manifest = _manifest()
    records = [result_record(u, {"value": u.sequence_index}) for u in manifest.work_units]
    duplicate = reconcile_result_records(manifest, records + [records[0]])
    assert not duplicate["pass"] and duplicate["duplicate_work_unit_ids"]
    missing = reconcile_result_records(manifest, records[1:])
    assert not missing["pass"] and missing["missing_work_unit_ids"]
    bogus = dict(records[0])
    bogus["work_unit_id"] = "bogus"
    unexpected = reconcile_result_records(manifest, records + [bogus])
    assert not unexpected["pass"] and unexpected["unexpected_work_unit_ids"]
    drift = json.loads(json.dumps(records))
    drift[0]["identity"]["coupon_position"] = 99
    invalid = reconcile_result_records(manifest, drift)
    assert not invalid["pass"] and invalid["invalid_work_unit_ids"]


def test_result_writer_is_idempotent_and_rejects_different_payload(tmp_path):
    manifest = _manifest()
    unit = manifest.work_units[0]
    first = result_record(unit, {"value": 1})
    path1 = write_result_once(tmp_path, unit, first)
    path2 = write_result_once(tmp_path, unit, first)
    assert path1 == path2
    second = result_record(unit, {"value": 2})
    with pytest.raises(CampaignProvenanceError):
        write_result_once(tmp_path, unit, second)


def test_simulation_job_legacy_identity_includes_coordinates():
    a = SimulationJob(0, "20260730:part_1", 0, 99, {"x": 1.0})
    b = SimulationJob(0, "20260730:part_1", 0, 99, {"x": 2.0})
    assert a.identity_key != b.identity_key


def test_simulation_job_work_unit_identity_overrides_legacy_fields():
    a = SimulationJob(0, "20260730:part_1", 0, 99, {"x": 1.0}, work_unit_id="WU-A")
    b = SimulationJob(999, "20260910:part_6", 10, 117, {"x": 9.0}, work_unit_id="WU-A")
    assert a.identity_key == b.identity_key == ("work_unit", "WU-A")


def test_context_must_exactly_cover_selected_sets():
    contexts = _contexts()
    contexts.pop("20260910")
    with pytest.raises(CampaignProvenanceError):
        CampaignStageSpec("s1", 1, "exp", "sweep", (ParameterPointSpec("P1", {}),), contexts)


def test_work_unit_job_binding_cannot_substitute_parameter_point_identity():
    from lpbf.execution.campaign_provenance import simulation_job_for_work_unit
    unit = _manifest().work_units[0]
    job = simulation_job_for_work_unit(unit, frame_index=7, window_cells=99)
    assert job.work_unit_id == unit.work_unit_id
    assert job.member_identity == unit.member_identity
    assert job.candidate_coordinates_dict == dict(unit.parameter_values)
    assert job.identity_provenance_dict["input_sha256"] == unit.input_sha256
