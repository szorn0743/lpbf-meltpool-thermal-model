"""The thesis scoring hierarchy, tested invariant by invariant.

frame -> scan track -> coupon -> exact-condition replicate -> unique condition, every level an unweighted mean.
Residuals are log ratios with a one-pixel floor; the first and last eligible frame of each track are excluded;
undefined predictions are never fabricated; coverage is reported and flagged below 95 %.
"""
from __future__ import annotations

import math

import pytest

from lpbf.hierarchical_objective import COVERAGE_FLOOR, FAILED_CANDIDATE_PENALTY
from lpbf.log_ratio_objective import AGGREGATION_HIERARCHY, PIXEL_FLOOR, aggregate_log_ratio_records, log_ratio
from lpbf.scored_frame_rule import (
    EXCLUDED_TRACK_FIRST,
    EXCLUDED_TRACK_LAST,
    EXCLUDED_TRACK_SINGLE_FRAME,
    NOT_ELIGIBLE,
    apply_scored_frame_rule,
    label_track_positions,
    scored_frame_indices,
)

A, B, C = "20260730:part_1", "20260731:part_1", "20260910:part_1"  # A and B replicate the same condition
COND_AB, COND_C = "P140_V850", "P140_V700"


def _record(member, cid, track, frame, h_exp, w_exp, h_sim=None, w_sim=None, status="PASS", scored=True, eligible=True):
    power, speed = cid[1:].split("_V")
    row = {
        "member_identity": member,
        "acquisition_set_id": member.split(":", 1)[0],
        "power_W": int(power),
        "speed_mm_s": int(speed),
        "exact_condition_id": cid,
        "scan_track_id": str(track),
        "frame_index": frame,
        "experimental_H_pixels": h_exp,
        "experimental_W_pixels": w_exp,
        "observation_eligible": eligible,
        "status": status,
        "scored_frame": scored,
    }
    if h_sim is not None:
        row["simulated_H_pixels"], row["simulated_W_pixels"] = h_sim, w_sim
    return row


def _score(records, members=(A, B, C), conditions=(COND_AB, COND_C)):
    return aggregate_log_ratio_records(records, member_ids=list(members), condition_ids=list(conditions))


def _h_component(records):
    return _score(records)["H_component"]


def _baseline(*, frames_a1=2, tracks_a=1, b_tracks=1, c_ratio=1.0):
    """Coupon A (track 1 with ``frames_a1`` frames at ratio 2 and more tracks at ratio 1), B at ratio 4 on
    ``b_tracks`` tracks, C at ``c_ratio``."""

    records = [_record(A, COND_AB, 1, i, 10.0, 10.0, 20.0, 10.0) for i in range(frames_a1)]
    for track in range(2, tracks_a + 1):
        records.append(_record(A, COND_AB, track, 100 * track, 10.0, 10.0, 10.0, 10.0))
    for track in range(1, b_tracks + 1):
        records.append(_record(B, COND_AB, track, 100 * track, 10.0, 10.0, 40.0, 10.0))
    records.append(_record(C, COND_C, 1, 0, 10.0, 10.0, 10.0 * c_ratio, 10.0))
    return records


def test_hierarchy_is_the_documented_one():
    assert list(AGGREGATION_HIERARCHY) == ["camera_frame", "scan_track", "coupon", "exact_condition_replicate", "unique_calibration_condition"]
    assert _score(_baseline())["aggregation_hierarchy"] == list(AGGREGATION_HIERARCHY)


def test_more_frames_do_not_give_a_track_extra_weight():
    ln2 = math.log(2.0)
    # track 1 of coupon A with 2 frames and with 200 frames, all at ratio 2: the track mean is ln2**2 either way
    two = _score(_baseline(frames_a1=2))
    many = _score(_baseline(frames_a1=200))
    assert two["H_component"] == pytest.approx(many["H_component"], rel=1e-14)
    track = next(row for row in many["track_rows"] if row["member_identity"] == A and row["scan_track_id"] == "1")
    assert track["scored_count"] == 200 and track["H_mean_sq_log"] == pytest.approx(ln2**2, rel=1e-14)


def test_more_tracks_do_not_give_a_coupon_extra_weight():
    ln2, ln4 = math.log(2.0), math.log(4.0)
    # coupon A: one track at ratio 2 plus k tracks at ratio 1 -> coupon mean (ln2**2 + k*0)/(k+1); coupon B at ratio 4
    for k in (0, 1, 9):
        result = _score(_baseline(tracks_a=k + 1))
        coupon_a = next(row for row in result["coupon_rows"] if row["member_identity"] == A)
        assert coupon_a["track_count"] == k + 1
        assert coupon_a["H_mean_sq_log"] == pytest.approx(ln2**2 / (k + 1), rel=1e-14)
        # the condition shared by A and B is the mean of the two coupon values, whatever the track counts
        condition = next(row for row in result["condition_rows"] if row["exact_condition_id"] == COND_AB)
        assert condition["H_mean_sq_log"] == pytest.approx((ln2**2 / (k + 1) + ln4**2) / 2, rel=1e-14)


def test_replicate_coupons_do_not_give_a_condition_extra_weight():
    ln2 = math.log(2.0)
    # the condition shared by A and B counts once at the top level, like the single-coupon condition of C
    records = [_record(A, COND_AB, 1, 0, 10.0, 10.0, 20.0, 10.0), _record(B, COND_AB, 1, 0, 10.0, 10.0, 20.0, 10.0), _record(C, COND_C, 1, 0, 10.0, 10.0, 10.0, 10.0)]
    result = _score(records)
    assert result["counts"]["coupon_count"] == 3 and result["counts"]["condition_count"] == 2
    assert result["H_component"] == pytest.approx((ln2**2 + 0.0) / 2, rel=1e-14)
    # a fourth replicate of the same condition changes nothing at the top level
    records.append(_record("20260730:part_3", COND_AB, 1, 0, 10.0, 10.0, 20.0, 10.0))
    assert aggregate_log_ratio_records(records, member_ids=[A, B, C, "20260730:part_3"], condition_ids=[COND_AB, COND_C])["H_component"] == pytest.approx(ln2**2 / 2, rel=1e-14)


def test_log_ratio_residuals_are_as_documented():
    records = [_record(A, COND_AB, 1, 0, 10.0, 8.0, 25.0, 4.0), _record(B, COND_AB, 1, 0, 10.0, 8.0, 10.0, 8.0), _record(C, COND_C, 1, 0, 10.0, 8.0, 10.0, 8.0)]
    result = _score(records)
    frame_h, frame_w = math.log(25.0 / 10.0), math.log(4.0 / 8.0)
    coupon_a = next(row for row in result["coupon_rows"] if row["member_identity"] == A)
    assert coupon_a["H_mean_log"] == pytest.approx(frame_h) and coupon_a["W_mean_log"] == pytest.approx(frame_w)
    # f = 0.5 r_H^2 + 0.5 r_W^2, and the hierarchical means are linear in r^2
    h_component, w_component = (frame_h**2 / 2 + 0.0) / 2, (frame_w**2 / 2 + 0.0) / 2
    assert result["objective_value"] == pytest.approx(0.5 * h_component + 0.5 * w_component, rel=1e-14)
    assert result["e_H"] == pytest.approx(math.sqrt(h_component)) and result["e_W"] == pytest.approx(math.sqrt(w_component))
    assert result["weights"] == {"H": 0.5, "W": 0.5}


def test_one_pixel_floor_keeps_zero_and_subpixel_values_finite():
    assert PIXEL_FLOOR == 1.0
    assert log_ratio(0.0, 20.0) == pytest.approx(-math.log(20.0))  # a NO_LASER_ASSOCIATED_MELT prediction (H = W = 0)
    assert log_ratio(0.4, 0.2) == 0.0  # both below the floor: no residual
    assert log_ratio(5.0, 0.0) == pytest.approx(math.log(5.0))
    assert math.isfinite(log_ratio(0.0, 0.0))
    records = [_record(A, COND_AB, 1, 0, 20.0, 0.5, 0.0, 0.0), _record(B, COND_AB, 1, 0, 10.0, 10.0, 10.0, 10.0), _record(C, COND_C, 1, 0, 10.0, 10.0, 10.0, 10.0)]
    result = _score(records)
    counts = result["counts"]
    assert counts["zero_prediction_frame_count"] == 1 and counts["floored_frame_count"] == 1
    assert counts["floored_by_quantity"] == {"simulated_H": 1, "simulated_W": 1, "experimental_H": 0, "experimental_W": 1}
    assert result["H_component"] == pytest.approx(((math.log(20.0) ** 2 + 0.0) / 2 + 0.0) / 2, rel=1e-14)  # condition AB, then the two conditions
    assert result["status"] == "PASS" and result["penalty_applied"] is False


def test_track_edge_frames_are_excluded_and_never_enter_the_score():
    rows = [{"frame_index": f, "scan_track_id": "7", "observation_eligible": True} for f in (120, 125, 131)]
    rows += [{"frame_index": 140, "scan_track_id": "8", "observation_eligible": True}]
    rows += [{"frame_index": 118, "scan_track_id": "7", "observation_eligible": False}]
    labelled = {row["frame_index"]: row for row in apply_scored_frame_rule(rows)}
    assert labelled[120]["exclusion_reason"] == EXCLUDED_TRACK_FIRST and labelled[131]["exclusion_reason"] == EXCLUDED_TRACK_LAST
    assert labelled[125]["scored_frame"] is True and labelled[125]["exclusion_reason"] is None
    assert labelled[140]["exclusion_reason"] == EXCLUDED_TRACK_SINGLE_FRAME
    assert labelled[118]["exclusion_reason"] == NOT_ELIGIBLE
    assert scored_frame_indices(labelled.values()) == (125,)
    # an excluded frame carries a wild simulated value and still does not change the objective
    records = _baseline()
    excluded = _record(A, COND_AB, 1, 999, 10.0, 10.0, 1.0e6, 1.0e6, status="EXCLUDED", scored=False)
    with_excluded = _score(records + [excluded])
    assert with_excluded["H_component"] == pytest.approx(_h_component(records), rel=1e-14)
    assert with_excluded["counts"]["excluded_by_rule_count"] == 1
    # excluded frames leave the coverage denominator: coverage stays 1.0
    assert with_excluded["counts"]["coverage_by_coupon"][A] == 1.0


def test_track_positions_label_first_last_single_and_interior_frames():
    def rows(frames):
        return [{"member_identity": A, "scan_track_id": track, "frame_index": frame, "experimental_H_pixels": 9.0, "experimental_W_pixels": 8.0, "observation_eligible": True} for track, indices in frames.items() for frame in indices]

    frame_rows = rows({"7": [120, 131, 125], "8": [140], "9": [150, 160]})
    frame_rows.append({**frame_rows[0], "frame_index": 118, "observation_eligible": False})
    positions = label_track_positions(frame_rows)
    assert 118 not in positions
    assert positions[120] == {"scan_track_id": "7", "position": 0, "track_frame_count": 3, "is_first": True, "is_last": False, "edge_class": "first"}
    assert positions[125]["edge_class"] == "interior" and positions[131]["edge_class"] == "last"
    assert positions[140] == {"scan_track_id": "8", "position": 0, "track_frame_count": 1, "is_first": True, "is_last": True, "edge_class": "single"}
    assert positions[150]["is_first"] and positions[160]["is_last"]


def test_undefined_predictions_are_excluded_with_coverage_and_never_fabricated():
    records = _baseline(frames_a1=3)
    undefined = _record(A, COND_AB, 1, 50, 10.0, 10.0, status="UNDEFINED")
    result = _score(records + [undefined])
    assert result["status"] == "PASS"
    assert result["counts"]["undefined_frame_count"] == 1
    assert result["H_component"] == pytest.approx(_h_component(records), rel=1e-14)  # the undefined frame added no residual
    assert result["counts"]["coverage_by_coupon"][A] == pytest.approx(3 / 4)
    assert result["coverage_flag"] is True and result["low_coverage_coupons"] == [A]
    # an undefined frame that carries simulated values is still not scored
    sneaky = {**undefined, "simulated_H_pixels": 1.0e6, "simulated_W_pixels": 1.0e6}
    assert _score(records + [sneaky])["H_component"] == pytest.approx(_h_component(records), rel=1e-14)


def test_coverage_is_scored_over_eligible_minus_excluded():
    records = [
        _record(A, COND_AB, 1, 0, 10.0, 10.0, status="EXCLUDED", scored=False),  # rule-excluded: not in the denominator
        _record(A, COND_AB, 1, 1, 10.0, 10.0, 10.0, 10.0),
        _record(A, COND_AB, 1, 2, 10.0, 10.0, status="UNDEFINED"),  # in the denominator, not scored
        _record(A, COND_AB, 1, 3, 10.0, 10.0, 10.0, 10.0),
        _record(A, COND_AB, 1, 4, 10.0, 10.0, status="EXCLUDED", scored=False),
        _record(A, COND_AB, 2, 10, 10.0, 10.0, eligible=False, scored=False),  # ineligible: outside coverage entirely
        _record(B, COND_AB, 1, 0, 10.0, 10.0, 10.0, 10.0),
        _record(C, COND_C, 1, 0, 10.0, 10.0, 10.0, 10.0),
    ]
    result = _score(records)
    counts = result["counts"]
    assert counts["scored_frame_count"] == 4 and counts["undefined_frame_count"] == 1
    assert counts["excluded_by_rule_count"] == 2 and counts["ineligible_frame_count"] == 1
    assert counts["coverage_by_coupon"][A] == pytest.approx(2 / 3)
    assert counts["coverage_denominator"] == 5 and counts["coverage"] == pytest.approx(4 / 5)
    assert counts["coverage_floor"] == COVERAGE_FLOOR == 0.95
    assert result["low_coverage_coupons"] == [A]
    coupon_a = next(row for row in result["coupon_rows"] if row["member_identity"] == A)
    assert (coupon_a["scored_frame_count"], coupon_a["undefined_frame_count"], coupon_a["excluded_by_rule_count"]) == (2, 1, 2)


def test_infrastructure_failure_and_empty_coupon_take_the_penalty_but_undefined_does_not():
    records = _baseline()
    failed = [{**records[0], "status": "FAIL", "failure": {"code": "X"}}] + records[1:]
    result = _score(failed)
    assert result["penalty_applied"] is True and result["objective_value"] == FAILED_CANDIDATE_PENALTY == 1e12
    # a coupon whose every eligible frame is undefined has no scored frames: penalty, not a fabricated zero
    empty = [_record(A, COND_AB, 1, 0, 10.0, 10.0, status="UNDEFINED"), _record(B, COND_AB, 1, 0, 10.0, 10.0, 10.0, 10.0), _record(C, COND_C, 1, 0, 10.0, 10.0, 10.0, 10.0)]
    result = _score(empty)
    assert result["penalty_applied"] is True and "no scored frames" in result["failure_reason"]
