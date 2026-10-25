"""Patch 22.4.3.2: narrow-window calibration (ledger A25, A26).

No thermal run: scope, objective, surrogate, guard, held-out refusal and parallel/serial identity are tested on
synthetic inputs. The live gate is the ``smoke`` stage (Stage-A bit identity on one unit).
"""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import numpy as np
import pytest

import lpbf.calibration as w
from lpbf.calibration_contract import validation_member_identities
from lpbf.execution.work_units import SimulationResult
from lpbf.experiments.dataset import DatasetMember
from lpbf.hierarchical_objective import (
    H_METRIC_WEIGHT,
    H_REPEATABILITY_SCALE_PIXELS,
    PATCH_VERSION as PIXEL_OBJECTIVE_VERSION,
    W_METRIC_WEIGHT,
    W_REPEATABILITY_SCALE_PIXELS,
    aggregate_hierarchical_records,
)
from lpbf.infrastructure import canonical_sha256
from lpbf.log_ratio_objective import OBJECTIVE_CONTRACT_VERSION, aggregate_log_ratio_records, log_ratio
from lpbf.scored_frame_rule import scored_frame_indices

REPO = Path(__file__).resolve().parents[1]
RECORD_CSV = REPO / "docs" / "reference" / "LPBF_Process_Parameters.csv"
LN2, LN3, LN20 = math.log(2.0), math.log(3.0), math.log(20.0)


# ---------------------------------------------------------------------- Stage A guard gap (written first)


# ---------------------------------------------------------------------- member and condition scope


def test_roles_follow_the_a8_partition_and_the_ved_window():
    roles = w.derive_member_roles()
    assert roles["calibration"] == tuple(sorted(w.CALIBRATION_MEMBERS))
    assert roles["in_window_held_out"] == tuple(sorted(w.IN_WINDOW_HELD_OUT))
    assert roles["out_of_window_examined"] == tuple(sorted(w.OUT_OF_WINDOW_EXAMINED))
    assert roles["out_of_window_blind"] == tuple(sorted(w.OUT_OF_WINDOW_BLIND))
    assert len(w.CALIBRATION_MEMBERS) == 9 and len(w.EVALUATION_MEMBERS) == 15
    records = w.member_records()
    assert sorted({records[m]["condition_id"] for m in w.CALIBRATION_MEMBERS}) == sorted(w.CALIBRATION_CONDITIONS)
    assert len(w.CALIBRATION_CONDITIONS) == 5
    assert set(w.IN_WINDOW_HELD_OUT) | set(w.OUT_OF_WINDOW_BLIND) == validation_member_identities()
    assert len(set(w.CALIBRATION_MEMBERS) | set(w.EVALUATION_MEMBERS)) == 24
    assert w.DESIGN_UNIT_COUNT == 17 * 9


def test_ved_matches_the_read_only_process_record():
    sets = {"7/30/2026": "20260730", "7/31/2026": "20260731", "9/4/2026": "20260904", "9/10/2026": "20260910"}
    with RECORD_CSV.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    records = w.member_records()
    assert len(rows) == 24
    for row in rows:
        identity = f"{sets[row['Date']]}:part_{int(row['Part Number'])}"
        assert records[identity]["power_W"] == float(row["Power (W)"])
        assert records[identity]["speed_mm_s"] == float(row["Travel Speed (mm/s)"])
        assert abs(records[identity]["ved_J_mm3"] - float(row["Volumetric Power Density (J/mm3)"])) < 0.05
        inside = 65.0 <= float(row["Volumetric Power Density (J/mm3)"]) <= 85.0
        assert inside == (identity in w.CALIBRATION_MEMBERS or identity in w.IN_WINDOW_HELD_OUT)


def test_frozen_design_is_admissible_and_coded_coordinates_round_trip():
    candidates = w.frozen_design_candidates()
    assert len(candidates) == 17
    assert w.coordinate_bounds() == {
        "abs_depth_identifiable_coordinate": (-3.0, 3.0),
        "liquid_conductivity_enhancement_factor": (1.5, 2.5),
        "eta_directional": (0.0, 1.0),
    }
    for candidate in candidates:
        assert candidate["guard_value"] <= w.guard_maximum()
        assert w.from_coded(candidate["coded"]) == pytest.approx(candidate["coordinates"], abs=1e-12)
        assert all(abs(value) <= 1.0 for value in candidate["coded"])
    center = next(c for c in candidates if c["candidate_id"] == "anchor_center")
    assert center["coded"] == [0.0, 0.0, 0.0]


# ---------------------------------------------------------------------- objective 22.4.3.2


def _record(member, cid, track, frame, h_exp, w_exp, h_sim=None, w_sim=None, status="PASS", scored=True):
    power, speed = cid[1:].split("_V")
    row = {
        "member_identity": member,
        "portable_member_identity": member,
        "acquisition_set_id": member.split(":", 1)[0],
        "part_number": member.rsplit("_", 1)[-1],
        "power_W": int(power),
        "speed_mm_s": int(speed),
        "exact_condition_id": cid,
        "scan_track_id": str(track),
        "frame_index": frame,
        "experimental_H_pixels": h_exp,
        "experimental_W_pixels": w_exp,
        "observation_eligible": True,
        "observation_status": "ELIGIBLE_FINITE_HW",
        "status": status,
        "scored_frame": scored,
    }
    if h_sim is not None:
        row["simulated_H_pixels"] = h_sim
        row["simulated_W_pixels"] = w_sim
    return row


A, B, C = "20260730:part_1", "20260731:part_1", "20260910:part_1"


def _hand_records():
    return [
        _record(A, "P140_V850", 1, 0, 9.0, 8.0, status="EXCLUDED", scored=False),
        _record(A, "P140_V850", 1, 1, 10.0, 8.0, 20.0, 8.0),
        _record(A, "P140_V850", 1, 2, 10.0, 8.0, 10.0, 4.0),
        _record(A, "P140_V850", 2, 3, 10.0, 8.0, 30.0, 8.0),
        _record(A, "P140_V850", 2, 4, 10.0, 8.0, status="UNDEFINED"),
        _record(B, "P140_V850", 1, 1, 20.0, 8.0, 10.0, 16.0),
        _record(C, "P140_V700", 1, 1, 20.0, 0.5, 0.0, 0.0),
    ]


def test_log_ratio_objective_matches_a_hand_computation():
    result = aggregate_log_ratio_records(_hand_records(), member_ids=[A, B, C], condition_ids=["P140_V850", "P140_V700"])
    coupon_a_h = ((LN2**2 + 0.0) / 2 + LN3**2) / 2
    coupon_a_w = ((0.0 + LN2**2) / 2 + 0.0) / 2
    cond_850_h, cond_850_w = (coupon_a_h + LN2**2) / 2, (coupon_a_w + LN2**2) / 2
    cond_700_h, cond_700_w = LN20**2, 0.0
    h_component, w_component = (cond_850_h + cond_700_h) / 2, (cond_850_w + cond_700_w) / 2
    assert result["status"] == "PASS"
    assert result["schema_version"] == OBJECTIVE_CONTRACT_VERSION == "22.4.3.2"
    assert result["H_component"] == pytest.approx(h_component, rel=1e-14)
    assert result["W_component"] == pytest.approx(w_component, rel=1e-14)
    assert result["objective_value"] == pytest.approx(0.5 * h_component + 0.5 * w_component, rel=1e-14)
    assert result["e_H"] == pytest.approx(math.sqrt(h_component), rel=1e-14)
    counts = result["counts"]
    assert counts["scored_frame_count"] == 5 and counts["undefined_frame_count"] == 1 and counts["excluded_by_rule_count"] == 1
    assert counts["coverage_by_coupon"][A] == pytest.approx(0.75)
    assert result["coverage_flag"] is True and result["low_coverage_coupons"] == [A]
    # the zero prediction (D1) is floored at one pixel; the sub-pixel camera width is floored too
    assert counts["floored_frame_count"] == 1 and counts["zero_prediction_frame_count"] == 1
    assert counts["floored_by_quantity"] == {"simulated_H": 1, "simulated_W": 1, "experimental_H": 0, "experimental_W": 1}
    coupon_c = next(row for row in result["coupon_rows"] if row["member_identity"] == C)
    assert coupon_c["median_r_H"] == pytest.approx(-LN20) and coupon_c["median_r_W"] == 0.0
    weighted = aggregate_log_ratio_records(_hand_records(), member_ids=[A, B, C], condition_ids=["P140_V850", "P140_V700"], weights=(1.0, 0.0))
    assert weighted["objective_value"] == pytest.approx(h_component, rel=1e-14)


def test_log_ratio_floor_and_penalty_rules():
    assert log_ratio(0.0, 20.0) == pytest.approx(-LN20)
    assert log_ratio(0.4, 0.2) == 0.0
    assert log_ratio(5.0, 0.0) == pytest.approx(math.log(5.0))
    failed = _hand_records()
    failed[1] = {**failed[1], "status": "FAIL", "failure": {"code": "X"}}
    result = aggregate_log_ratio_records(failed, member_ids=[A, B, C], condition_ids=["P140_V850", "P140_V700"])
    assert result["status"] == "FAILED_CANDIDATE_PENALTY" and result["objective_value"] == 1e12 and result["e_H"] is None
    with pytest.raises(Exception, match="non-calibration"):
        aggregate_log_ratio_records(_hand_records(), member_ids=[A, B], condition_ids=["P140_V850", "P140_V700"])


def test_pixel_objective_22_3_7_is_unchanged():
    assert PIXEL_OBJECTIVE_VERSION == "22.3.7"
    assert (H_REPEATABILITY_SCALE_PIXELS, W_REPEATABILITY_SCALE_PIXELS, H_METRIC_WEIGHT, W_METRIC_WEIGHT) == (0.90, 0.65, 0.50, 0.50)
    result = aggregate_hierarchical_records(_hand_records(), calibration_member_ids=[A, B, C], calibration_condition_ids=["P140_V850", "P140_V700"])
    track_a1_h = (10.0**2 + 0.0) / 2 / 0.81
    track_a1_w = (0.0 + 4.0**2) / 2 / 0.4225
    coupon_a_h, coupon_a_w = (track_a1_h + 20.0**2 / 0.81) / 2, (track_a1_w + 0.0) / 2
    cond_850_h, cond_850_w = (coupon_a_h + 10.0**2 / 0.81) / 2, (coupon_a_w + 8.0**2 / 0.4225) / 2
    cond_700_h, cond_700_w = 20.0**2 / 0.81, 0.5**2 / 0.4225
    expected = 0.5 * (cond_850_h + cond_700_h) / 2 + 0.5 * (cond_850_w + cond_700_w) / 2
    assert result["objective_value"] == pytest.approx(expected, rel=1e-12)
    assert result["objective_value"] == 193.8773833004602  # bit-level pin of the 22.3.7 path


# ---------------------------------------------------------------------- surrogate and confirmation


def _design_coded():
    return {c["candidate_id"]: c["coded"] for c in w.frozen_design_candidates()}


def _box(x):
    return bool(np.all(np.abs(np.asarray(x)) <= 1.0))


def test_quadratic_fit_recovers_a_known_surrogate():
    design = _design_coded()
    beta = np.array([1.0, 0.2, -0.1, 0.3, 0.5, 0.7, 0.4, 0.1, -0.05, 0.02])
    points = np.array([design[cid] for cid in sorted(design)])
    fit = w.fit_quadratic(points, w.quadratic_features(points) @ beta)
    assert np.allclose(fit["coefficients"], beta, atol=1e-10)
    assert fit["r_squared"] == pytest.approx(1.0) and fit["loo_rmse"] < 1e-9
    hessian = w.surrogate_hessian(beta)
    assert np.allclose(hessian, hessian.T) and hessian[0, 0] == 1.0 and hessian[0, 1] == 0.1
    x = np.array([0.3, -0.2, 0.5])
    numeric = [(w.surrogate_value(beta, x + e) - w.surrogate_value(beta, x - e)) / 2e-6 for e in np.eye(3) * 1e-6]
    assert np.allclose(w.surrogate_gradient(beta, x), numeric, atol=1e-6)
    with pytest.raises(w.WindowCalibrationError, match="not identified"):
        w.fit_quadratic(points[:9], np.zeros(9))


def test_constrained_minimizer_finds_the_guard_boundary_minimum():
    def admissible(x):
        return _box(x) and float(x[1] + x[2]) <= 0.5

    target = np.array([0.0, 1.0, 1.0])
    design = _design_coded()
    j = {cid: float(1.0 + np.sum((np.array(x) - target) ** 2)) for cid, x in design.items()}
    proposal = w.propose_confirmation(design, j, admissible)
    assert np.allclose(proposal["minimum"]["x"], [0.0, 0.25, 0.25], atol=2e-3)
    assert proposal["flat_valley"] is False
    assert [p["candidate_id"] for p in proposal["confirmation_candidates"]] == ["confirm_c1"]


def test_minimizer_near_a_design_point_is_not_run_and_a_flat_valley_adds_c2_c3():
    design = _design_coded()
    near = {cid: float(1.0 + 3.0 * np.sum((np.array(x) - [0.01, 0.0, 0.0]) ** 2)) for cid, x in design.items()}
    proposal = w.propose_confirmation(design, near, _box)
    c1 = proposal["proposals"][0]
    assert c1["nearest_point"] == "anchor_center" and c1["run"] is False
    assert proposal["confirmation_candidates"] == []
    flat = {cid: float(1.0 + 0.05 * x[0] ** 2 + 2.0 * (x[1] + 0.2) ** 2 + 2.0 * (x[2] - 0.1) ** 2) for cid, x in design.items()}
    proposal = w.propose_confirmation(design, flat, _box)
    assert proposal["flat_valley"] is True
    roles = {p["candidate_id"]: p for p in proposal["proposals"]}
    assert np.allclose(roles["confirm_c2"]["x"], [1.0, -0.2, 0.1], atol=2e-3) and roles["confirm_c2"]["clipped_by"] == "box"
    assert np.allclose(roles["confirm_c3"]["x"], [-1.0, -0.2, 0.1], atol=2e-3)
    assert len(proposal["confirmation_candidates"]) == 3
    level = {cid: float(1.0 + 0.4 * x[0] ** 2 + 5.0 * x[1] ** 2 + 5.0 * x[2] ** 2) for cid, x in design.items()}
    walk = {p["candidate_id"]: p for p in w.propose_confirmation(design, level, _box)["proposals"]}
    assert walk["confirm_c2"]["clipped_by"] == "level"
    assert w.surrogate_value(w.propose_confirmation(design, level, _box)["fit"]["coefficients"], np.array(walk["confirm_c2"]["x"])) == pytest.approx(1.1, abs=1e-9)


def test_flat_valley_walk_projects_a_level_point_that_eigenvector_noise_puts_just_outside_a_box_face():
    # Patch 22.4.3.2 confirm: c1 sat on t = -1 and v_min carried a -6e-6 t component, so the ray clip gave s = 0
    beta = np.array([1.0, 0.0, 0.0, 0.0, 0.0, 2.0, 0.4, 0.0, 0.0, 0.0])
    x_star = np.array([-1.0, 0.0, 0.0])
    walk = w._walk(beta, _box, x_star, np.array([-1e-6, 0.0, 1.0]), 1.1)
    assert walk["clipped_by"] == "level_projected"
    assert np.allclose(walk["x"], [-1.0, 0.0, 0.5], atol=1e-6) and walk["predicted_J"] == pytest.approx(1.1, abs=1e-9)
    guarded = w._walk(beta, lambda x: _box(x) and float(x[2]) <= 0.3, x_star, np.array([-1e-6, 0.0, 1.0]), 1.1)
    assert guarded["clipped_by"] == "guard" and np.allclose(guarded["x"], [-1.0, 0.0, 0.3], atol=1e-6)
    outward = w._walk(beta, _box, x_star, np.array([-0.2, 0.0, 1.0]), 1.1)
    assert outward["clipped_by"] == "box" and outward["s"] == 0.0 and np.allclose(outward["x"], x_star)


def test_guard_rejects_inadmissible_candidates():
    with pytest.raises(w.WindowCalibrationError, match="not admissible"):
        w.candidate_record("x", {"abs_depth_identifiable_coordinate": 0.0, "liquid_conductivity_enhancement_factor": 2.5, "eta_directional": 1.0}, "confirmation")
    with pytest.raises(w.WindowCalibrationError, match="outside"):
        w.candidate_record("y", {"abs_depth_identifiable_coordinate": 3.5, "liquid_conductivity_enhancement_factor": 2.0, "eta_directional": 0.5}, "confirmation")
    assert w.coded_admissible([0.0, 1.0, 1.0]) is False
    assert w.coded_admissible([0.0, 0.0, 0.0]) is True
    assert w.coded_admissible([1.2, 0.0, 0.0]) is False


# ---------------------------------------------------------------------- selection and readings


def _score(j, boiling=0.0, status="PASS"):
    return {"status": status, "J": j, "fraction_peak_above_boiling": boiling, "coverage_flag": False}


def _cand(coded, guard=0.5):
    return {"coded": list(coded), "guard_value": guard}


def test_selection_by_measured_j_with_ties_near_best_edge_and_e_set():
    candidates = {"a": _cand([0.0, 0.0, 0.0]), "b": _cand([0.1, 0.0, 0.0]), "c": _cand([0.5, 0.0, 0.0]), "d": _cand([-0.5, 0.0, 0.0]), "e": _cand([0.0, 0.0, 0.0])}
    scores = {"a": _score(1.0, 0.2), "b": _score(1.0, 0.1), "c": _score(1.05), "d": _score(1.09), "e": _score(1e12, status="FAILED_CANDIDATE_PENALTY")}
    selection = w.select_candidate(scores, candidates)
    assert selection["selected"] == "b"  # exact tie: lower peak-above-boiling fraction wins
    assert selection["near_best"] == ["b", "a", "c", "d"]
    assert selection["unrankable"] == ["e"]
    assert selection["e_set"] == ["b", "c", "d"]  # "a" is within 0.2 coded units of "b"
    assert selection["reading_C"] == w.READING_C_INTERIOR
    edge = w.select_candidate({"a": _score(1.0)}, {"a": _cand([0.0, 0.95, 0.0])})
    assert edge["reading_C"] == w.READING_C_EDGE and edge["edge"]["coordinates_at_edge"] == ["liquid_conductivity_enhancement_factor"]
    guard_edge = w.select_candidate({"a": _score(1.0)}, {"a": _cand([0.0, 0.0, 0.0], guard=0.93)})
    assert guard_edge["reading_C"] == w.READING_C_EDGE and guard_edge["edge"]["guard_at_edge"] is True


def test_readings_v_and_x():
    assert w.reading_v({"H": 1.0, "W": 1.0}, {"H": 1.2, "W": 1.3})["reading"] == w.READING_V_PARTIAL
    assert w.reading_v({"H": 1.0, "W": 1.0}, {"H": 1.25, "W": 0.5})["reading"] == w.READING_V_PASS
    assert w.reading_v({"H": 1.0, "W": 1.0}, {"H": 2.0, "W": 2.0})["reading"] == w.READING_V_FAIL
    assert w.reading_v({"H": 1.0, "W": None}, {"H": 1.0, "W": 1.0})["reading"] == w.READING_UNDEFINED
    assert w.spearman_rho([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert w.spearman_rho([1, 2, 3, 4], [1, 1, 2, 2]) == pytest.approx(0.8944271909999159)
    veds = [41.7, 48.6, 53.6, 55.6, 58.3, 62.5, 95.2, 97.2, 107.1, 125.0]
    coupons = [{"member_identity": f"m{i}", "ved_J_mm3": v, "median_r_W": (v - 80.0) / 100.0, "median_r_H": 1.0 + v / 100.0} for i, v in enumerate(veds)]
    assert w.reading_x(coupons)["reading"] == w.READING_X_CONFIRMED
    flipped = [{**c, "median_r_H": -c["median_r_H"]} for c in coupons]
    assert w.reading_x(flipped)["reading"] == w.READING_X_PARTIAL
    wrong_sign = [{**c, "median_r_W": c["median_r_W"] + 1.0, "median_r_H": -c["median_r_H"]} for c in coupons]
    assert w.reading_x(wrong_sign)["reading"] == w.READING_X_CONTRADICTED
    assert w.reading_x([{**coupons[0], "median_r_W": None}])["reading"] == w.READING_UNDEFINED


# ---------------------------------------------------------------------- held-out refusal and the freeze


@pytest.mark.parametrize("stage", ["smoke", "calibrate", "confirm"])
def test_held_out_and_out_of_window_members_are_refused_outside_evaluate(stage):
    for member in w.IN_WINDOW_HELD_OUT + w.OUT_OF_WINDOW_BLIND:
        with pytest.raises(w.WindowCalibrationError, match="held-out"):
            w.require_stage_members(stage, [w.CALIBRATION_MEMBERS[0], member])
    for member in w.OUT_OF_WINDOW_EXAMINED:
        with pytest.raises(w.WindowCalibrationError, match="not an in-window calibration member"):
            w.require_stage_members(stage, [member])
    assert w.require_stage_members(stage, w.CALIBRATION_MEMBERS) == tuple(sorted(w.CALIBRATION_MEMBERS))


def test_evaluate_requires_a_verified_freeze(tmp_path):
    with pytest.raises(w.WindowCalibrationError, match="verified, committed selection freeze"):
        w.require_stage_members("evaluate", w.IN_WINDOW_HELD_OUT)
    assert w.require_stage_members("evaluate", w.IN_WINDOW_HELD_OUT, freeze_verified=True) == tuple(sorted(w.IN_WINDOW_HELD_OUT))
    outside = tmp_path / "selection_freeze.json"
    outside.write_text("{}", encoding="utf-8")
    sha = w.sha256_file(outside)
    with pytest.raises(w.WindowCalibrationError, match="inside the repository"):
        w.verify_committed_freeze(outside, sha)
    with pytest.raises(w.WindowCalibrationError, match="differs from the one given"):
        w.verify_committed_freeze(outside, "0" * 64)
    tracked = REPO / "src" / "lpbf" / "data" / "accepted_core_hashes.json"
    with pytest.raises(w.WindowCalibrationError, match="not a Patch 22.4.3.2 selection freeze"):
        w.verify_committed_freeze(tracked, w.sha256_file(tracked))
    # a self-consistent freeze inside the repository that is not the release's recorded one is refused
    body = w._json_safe({"schema": "lpbf_patch22_4_3_2_selection_freeze", "J_min": 0.5, "held_out_members_read_before_freeze": []})
    other = REPO / "results" / "calibration" / "_not_the_release_freeze.json"
    other.write_text(json.dumps({**body, "content_sha256": canonical_sha256(body)}), encoding="utf-8")
    try:
        with pytest.raises(w.WindowCalibrationError, match="not the release's recorded selection freeze"):
            w.verify_committed_freeze(other, w.sha256_file(other))
    finally:
        other.unlink()
    # the release's own freeze verifies without git; the HEAD comparison is an optional aid (True in a clean clone, None in a ZIP)
    recorded = REPO / "results" / "calibration" / "selection_freeze.json"
    verified = w.verify_committed_freeze(recorded, w.sha256_file(recorded))
    assert verified["selected"]["candidate_id"] == "confirm_c1"
    assert verified["freeze_committed_at_head"] in (True, False, None)  # False only while the file is uncommitted in a working clone
    with pytest.raises(w.WindowCalibrationError, match="inside the repository"):
        w.run_evaluate(
            data_directory=tmp_path / "missing",
            characterization_directory=tmp_path / "missing",
            output_directory=tmp_path / "out",
            freeze_file=outside,
            freeze_sha256=sha,
            workers=1,
        )
    assert not (tmp_path / "out").exists()


def test_freeze_content_hash_round_trip():
    body = w._json_safe({"schema": "lpbf_patch22_4_3_2_selection_freeze", "J_min": 0.5, "surrogate": {"loo_rmse": float("nan")}, "held_out_members_read_before_freeze": []})
    freeze = {**body, "content_sha256": canonical_sha256(body)}
    assert w.verify_freeze_content(json.loads(json.dumps(freeze)))["J_min"] == 0.5
    with pytest.raises(w.WindowCalibrationError, match="does not verify"):
        w.verify_freeze_content({**freeze, "J_min": 0.4})
    leaked = {**body, "held_out_members_read_before_freeze": ["20260730:part_2"]}
    with pytest.raises(w.WindowCalibrationError, match="held-out reads"):
        w.verify_freeze_content({**leaked, "content_sha256": canonical_sha256(leaked)})


def test_member_resolution_checks_names_and_refuses_unknown_members(tmp_path):
    with pytest.raises(w.WindowCalibrationError, match="not in the canonical manifest"):
        w.resolve_members(tmp_path, ["20260730:part_9"])
    with pytest.raises(w.WindowCalibrationError, match="membership mismatch"):
        w.resolve_members(tmp_path, ["20260730:part_1"])


# ---------------------------------------------------------------------- parallel equals serial, resume


def _member(identity: str) -> DatasetMember:
    set_id, part = identity.split(":part_")
    return DatasetMember(
        set_id=w.SET_ORDINALS[set_id],
        dataset_member_id=int(part),
        coupon_position=int(part),
        path=Path(f"{set_id}_{part}.h5"),
        sha256=f"{int(part):064d}",
        power_W=140.0,
        nominal_speed_mm_s=850.0,
        spot_diameter_mm=0.08,
        acquisition_set_id=set_id,
    )


def _rows(n: int):
    return [{"frame_index": 10 + i, "scored_frame": 0 < i < n - 1, "scan_track_id": "1"} for i in range(n)]


def _fake_unit_job(job):
    ctx = job.experiment_context_dict
    rows = json.loads(ctx["frame_rows_json"])
    scored = scored_frame_indices(rows)
    coordinates = job.candidate_coordinates_dict
    eta = coordinates["eta_directional"]
    return {
        "work_unit_id": job.work_unit_id,
        "candidate_id": ctx["candidate_id"],
        "member_identity": job.member_identity,
        "member_sha256": json.loads(ctx["dataset_member_json"])["sha256"],
        "frame_rows_sha256": canonical_sha256(rows),
        "candidate_coordinates": coordinates,
        "requested_frame_count": len(scored),
        "returned_frame_count": len(scored),
        "captured_frame_count": len(scored),
        "gate_failures": [],
        "capture_gate_failures": [],
        "frame_records": [{**row, "status": "PASS" if row["scored_frame"] else "EXCLUDED", "simulated_H_pixels": 10.0 + eta} for row in rows],
        "peak_surface_temperature_K_by_frame": {str(f): 3000.0 + f + eta for f in scored},
        "capture": {"frame_index": np.array(scored, dtype=np.int64), "top_surface_temperature_K": np.full((len(scored), 3, 3), eta)} if ctx["capture_fields"] else None,
    }


def _reverse_pool(jobs, worker, *, workers, on_result=None):
    results = []
    for job in reversed(tuple(jobs)):
        result = SimulationResult(job=job, payload=worker(job))
        if on_result is not None:
            on_result(result)
        results.append(result)
    return tuple(results)


def _jobs():
    members = {m: _member(m) for m in ("20260730:part_1", "20260731:part_1")}
    rows = {"20260730:part_1": _rows(5), "20260731:part_1": _rows(7)}
    candidates = {c["candidate_id"]: c for c in w.frozen_design_candidates() if c["candidate_id"] in ("anchor_center", "halton_04")}
    units = [(c, m) for c in candidates for m in members]
    jobs = w.build_unit_jobs("calibrate", units, candidates, members, rows, characterization_directory=".", capture_fields=[("halton_04", "20260731:part_1")])
    return jobs, members


def test_unit_jobs_are_sorted_and_spawn_safe():
    import pickle

    jobs, _ = _jobs()
    assert [job.case_index for job in jobs] == [0, 1, 2, 3]
    assert [job.work_unit_id for job in jobs] == [
        "22.4.3.2:anchor_center@20260730:part_1",
        "22.4.3.2:anchor_center@20260731:part_1",
        "22.4.3.2:halton_04@20260730:part_1",
        "22.4.3.2:halton_04@20260731:part_1",
    ]
    assert pickle.loads(pickle.dumps(jobs)) == jobs
    assert [job.experiment_context_dict["capture_fields"] for job in jobs] == [False, False, False, True]


def test_parallel_unit_files_equal_serial_and_resume_reuses_them(tmp_path, monkeypatch):
    monkeypatch.setattr(w, "_window_unit_job", _fake_unit_job)
    monkeypatch.setattr(w, "execute_parallel_jobs", _reverse_pool)
    jobs, members = _jobs()
    serial = w.run_units(tmp_path / "serial", jobs, members, workers=1)
    parallel = w.run_units(tmp_path / "parallel", jobs, members, workers=4)
    assert serial["start_method"] == "serial" and parallel["start_method"] == "spawn"
    files = sorted(p.relative_to(tmp_path / "serial") for p in (tmp_path / "serial").rglob("*") if p.is_file())
    assert [str(p).replace("\\", "/") for p in files] == [
        "fields/halton_04__20260731_part_1.npz",
        "units/anchor_center__20260730_part_1.json",
        "units/anchor_center__20260731_part_1.json",
        "units/halton_04__20260730_part_1.json",
        "units/halton_04__20260731_part_1.json",
    ]
    for path in files:
        assert (tmp_path / "serial" / path).read_bytes() == (tmp_path / "parallel" / path).read_bytes()
    again = w.run_units(tmp_path / "serial", jobs, members, workers=4)
    assert again["units_run"] == 0 and again["units_reused"] == 4
    (tmp_path / "serial" / "fields" / "halton_04__20260731_part_1.npz").write_bytes(b"corrupt")
    partial = w.run_units(tmp_path / "serial", jobs, members, workers=1)
    assert partial["units_run"] == 1 and partial["units_reused"] == 3
