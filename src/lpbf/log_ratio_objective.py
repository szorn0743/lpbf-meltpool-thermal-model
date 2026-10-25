"""Objective contract 22.4.3.2: log-ratio H/W residuals through the A10 hierarchy (ledger A26).

Per scored frame, in camera pixels::

    r_H = ln(max(H_sim, 1) / max(H_exp, 1)),   r_W = ln(max(W_sim, 1) / max(W_exp, 1))
    f   = w_H * r_H**2 + w_W * r_W**2           (w_H = w_W = 0.5)

The one-pixel floor keeps ``NO_LASER_ASSOCIATED_MELT`` (D1, H = W = 0) finite and heavily
penalized; floored frames are counted.  The frame -> scan track -> coupon -> exact-condition
replicate -> unique condition hierarchy, the frame classes, coverage, the coverage flag and the
infrastructure penalty are those of objective contract 22.3.7 (A10, A23) and reuse its code; only
the residual form differs.  The 22.3.7 pixel objective in ``hierarchical_objective`` is untouched.

Because f is linear in r_H**2 and r_W**2 and every level is an unweighted mean, the objective
equals ``w_H * H_component + w_W * W_component``, where each component is the hierarchical mean
of the squared log residual.  The H-only and W-only sensitivities are therefore the components
themselves, and the hierarchical log-RMS errors are ``e_Q = sqrt(Q_component)``.
"""
from __future__ import annotations

import math
from statistics import median
from typing import Any, Iterable, Mapping, Sequence

from lpbf.hierarchical_objective import (
    COVERAGE_FLOOR,
    FAILED_CANDIDATE_PENALTY,
    PASS_STATUS,
    HierarchicalObjectiveError,
    _candidate_values,
    _coverage_by_coupon,
    _failure_rows,
    _normalise_input_row,
    _penalty_result,
    _validate_requested_partition,
    frame_identity_digest,
)

OBJECTIVE_CONTRACT_VERSION = "22.4.3.2"
SCHEMA = "lpbf_patch22_4_3_2_log_ratio_objective"
PIXEL_FLOOR = 1.0
H_WEIGHT = 0.5
W_WEIGHT = 0.5
AGGREGATION_HIERARCHY = (
    "camera_frame",
    "scan_track",
    "coupon",
    "exact_condition_replicate",
    "unique_calibration_condition",
)


def log_ratio(simulated: float, experimental: float) -> float:
    """ln(max(sim, 1) / max(exp, 1)) for nonnegative pixel values."""

    return math.log(max(float(simulated), PIXEL_FLOOR) / max(float(experimental), PIXEL_FLOOR))


def _mean(values: Sequence[float]) -> float:
    if not values:
        raise HierarchicalObjectiveError("cannot average an empty hierarchy level")
    return math.fsum(values) / len(values)


def _level_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    """Unweighted mean of the child level's squared and signed log residuals."""

    h_sq = _mean([float(row["H_mean_sq_log"]) for row in rows])
    w_sq = _mean([float(row["W_mean_sq_log"]) for row in rows])
    return {
        "H_mean_sq_log": h_sq,
        "W_mean_sq_log": w_sq,
        "H_mean_log": _mean([float(row["H_mean_log"]) for row in rows]),
        "W_mean_log": _mean([float(row["W_mean_log"]) for row in rows]),
        "e_H": math.sqrt(h_sq),
        "e_W": math.sqrt(w_sq),
    }


def _frame_summary(frames: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Pooled descriptive statistics of scored frames (never objective weights)."""

    return {
        "median_r_H": float(median([row["r_H"] for row in frames])),
        "median_r_W": float(median([row["r_W"] for row in frames])),
        "median_H_ratio": float(median([math.exp(row["r_H"]) for row in frames])),
        "median_W_ratio": float(median([math.exp(row["r_W"]) for row in frames])),
        "floored_frame_count": sum(1 for row in frames if row["floored"]),
        "zero_prediction_frame_count": sum(1 for row in frames if row["H_sim"] == 0.0 and row["W_sim"] == 0.0),
    }


def _penalty(rows: Sequence[Mapping[str, Any]], *, candidate_id: str | None, reason: str, failure_rows: Sequence[Mapping[str, Any]], penalty: float, weights: tuple[float, float]) -> dict[str, Any]:
    result = _penalty_result(rows, candidate_id=candidate_id, reason=reason, failure_rows=failure_rows, penalty=penalty)
    result.update(
        {
            "schema": SCHEMA,
            "schema_version": OBJECTIVE_CONTRACT_VERSION,
            "weights": {"H": weights[0], "W": weights[1]},
            "pixel_floor": PIXEL_FLOOR,
            "H_component": None,
            "W_component": None,
            "e_H": None,
            "e_W": None,
        }
    )
    return result


def aggregate_log_ratio_records(
    records: Sequence[Mapping[str, Any]],
    *,
    member_ids: Iterable[str],
    condition_ids: Iterable[str],
    require_complete: bool = True,
    candidate_id: str | None = None,
    weights: tuple[float, float] = (H_WEIGHT, W_WEIGHT),
    failed_penalty: float = FAILED_CANDIDATE_PENALTY,
) -> dict[str, Any]:
    """Aggregate one candidate's frame records under objective contract 22.4.3.2.

    ``records`` are campaign-style frame records (``PASS`` / ``UNDEFINED`` / ``EXCLUDED`` /
    ``FAIL``) as produced by the 22.3.7 unit path.  Members and conditions outside the
    requested sets are refused; which members may be requested is the caller's guard.
    """

    if not records:
        raise HierarchicalObjectiveError("log-ratio objective requires frame records")
    w_h, w_w = (float(value) for value in weights)
    if not (math.isfinite(w_h) and math.isfinite(w_w)) or w_h < 0.0 or w_w < 0.0 or w_h + w_w <= 0.0:
        raise HierarchicalObjectiveError("weights must be finite, nonnegative and not both zero")
    rows = [_normalise_input_row(raw) for raw in records]
    keys = [(row["member_identity"], row["scan_track_id"], row["frame_index"]) for row in rows]
    if len(set(keys)) != len(keys):
        raise HierarchicalObjectiveError("duplicate member/track/frame identity")
    members = frozenset(str(value) for value in member_ids)
    conditions = frozenset(str(value) for value in condition_ids)
    _validate_requested_partition(rows, calibration_member_ids=members, calibration_condition_ids=conditions, require_complete=require_complete)
    track_conditions: dict[tuple[str, str], str] = {}
    for row in rows:
        previous = track_conditions.setdefault((row["member_identity"], row["scan_track_id"]), row["exact_condition_id"])
        if previous != row["exact_condition_id"]:
            raise HierarchicalObjectiveError(f"scan track {(row['member_identity'], row['scan_track_id'])} spans multiple exact conditions")

    failures = _failure_rows(rows)
    if failures:
        return _penalty(rows, candidate_id=candidate_id, reason="candidate member/frame evaluation reported failure", failure_rows=failures, penalty=failed_penalty, weights=(w_h, w_w))
    coverage = _coverage_by_coupon(rows)
    empty = sorted(member for member, item in coverage.items() if item["denominator"] > 0 and item["scored"] == 0)
    if empty:
        return _penalty(
            rows,
            candidate_id=candidate_id,
            reason=f"coupon has no scored frames: {empty}",
            failure_rows=[{"member_identity": member, "status": "NO_SCORED_FRAMES"} for member in empty],
            penalty=failed_penalty,
            weights=(w_h, w_w),
        )

    frames: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda item: (item["member_identity"], item["scan_track_id"], item["frame_index"])):
        if row["frame_class"] != "SCORED":
            continue
        try:
            h_sim, w_sim = _candidate_values(row["raw"])
        except (KeyError, HierarchicalObjectiveError) as exc:
            invalid.append({"member_identity": row["member_identity"], "scan_track_id": row["scan_track_id"], "frame_index": row["frame_index"], "status": "INVALID_CANDIDATE_H_W", "failure": str(exc)})
            continue
        h_exp, w_exp = float(row["experimental_H_pixels"]), float(row["experimental_W_pixels"])
        floors = {
            "simulated_H": h_sim < PIXEL_FLOOR,
            "simulated_W": w_sim < PIXEL_FLOOR,
            "experimental_H": h_exp < PIXEL_FLOOR,
            "experimental_W": w_exp < PIXEL_FLOOR,
        }
        frames.append(
            {
                "member_identity": row["member_identity"],
                "acquisition_set_id": row["acquisition_set_id"],
                "exact_condition_id": row["exact_condition_id"],
                "scan_track_id": row["scan_track_id"],
                "frame_index": row["frame_index"],
                "H_sim": h_sim,
                "W_sim": w_sim,
                "r_H": log_ratio(h_sim, h_exp),
                "r_W": log_ratio(w_sim, w_exp),
                "floors": floors,
                "floored": any(floors.values()),
            }
        )
    if invalid:
        return _penalty(rows, candidate_id=candidate_id, reason="candidate produced missing, nonfinite, or negative simulated H/W", failure_rows=invalid, penalty=failed_penalty, weights=(w_h, w_w))
    if not frames:
        raise HierarchicalObjectiveError("no scored frames remain")

    by_track: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for frame in frames:
        by_track.setdefault((frame["member_identity"], frame["scan_track_id"]), []).append(frame)
    track_rows: list[dict[str, Any]] = []
    for (member, track), group in sorted(by_track.items()):
        h_sq = _mean([frame["r_H"] ** 2 for frame in group])
        w_sq = _mean([frame["r_W"] ** 2 for frame in group])
        track_rows.append(
            {
                "member_identity": member,
                "scan_track_id": track,
                "exact_condition_id": group[0]["exact_condition_id"],
                "scored_count": len(group),
                "H_mean_sq_log": h_sq,
                "W_mean_sq_log": w_sq,
                "H_mean_log": _mean([frame["r_H"] for frame in group]),
                "W_mean_log": _mean([frame["r_W"] for frame in group]),
                "track_scalar_objective": w_h * h_sq + w_w * w_sq,
            }
        )

    frames_by_member: dict[str, list[dict[str, Any]]] = {}
    for frame in frames:
        frames_by_member.setdefault(frame["member_identity"], []).append(frame)
    tracks_by_member: dict[str, list[dict[str, Any]]] = {}
    for row in track_rows:
        tracks_by_member.setdefault(row["member_identity"], []).append(row)
    coupon_rows: list[dict[str, Any]] = []
    for member, group in sorted(tracks_by_member.items()):
        metrics = _level_metrics(group)
        coupon_rows.append(
            {
                "member_identity": member,
                "acquisition_set_id": frames_by_member[member][0]["acquisition_set_id"],
                "exact_condition_id": group[0]["exact_condition_id"],
                "track_count": len(group),
                "coverage": coverage[member]["coverage"],
                "scored_frame_count": coverage[member]["scored"],
                "undefined_frame_count": coverage[member]["undefined"],
                "excluded_by_rule_count": coverage[member]["excluded_by_rule"],
                **metrics,
                **_frame_summary(frames_by_member[member]),
                "coupon_scalar_objective": w_h * metrics["H_mean_sq_log"] + w_w * metrics["W_mean_sq_log"],
            }
        )

    coupons_by_condition: dict[str, list[dict[str, Any]]] = {}
    for row in coupon_rows:
        coupons_by_condition.setdefault(row["exact_condition_id"], []).append(row)
    if require_complete and set(coupons_by_condition) != conditions:
        raise HierarchicalObjectiveError(f"conditions lack scored coupons: {sorted(conditions - set(coupons_by_condition))}")
    frames_by_condition: dict[str, list[dict[str, Any]]] = {}
    for frame in frames:
        frames_by_condition.setdefault(frame["exact_condition_id"], []).append(frame)
    condition_rows: list[dict[str, Any]] = []
    for cid, group in sorted(coupons_by_condition.items()):
        metrics = _level_metrics(group)
        condition_rows.append(
            {
                "exact_condition_id": cid,
                "member_identities": [row["member_identity"] for row in group],
                "replicate_coupon_count": len(group),
                **metrics,
                **_frame_summary(frames_by_condition[cid]),
                "condition_objective_contribution": w_h * metrics["H_mean_sq_log"] + w_w * metrics["W_mean_sq_log"],
            }
        )

    h_component = _mean([row["H_mean_sq_log"] for row in condition_rows])
    w_component = _mean([row["W_mean_sq_log"] for row in condition_rows])
    low_coverage = sorted(member for member, item in coverage.items() if item["coverage"] is not None and item["coverage"] < COVERAGE_FLOOR)
    denominator = sum(item["denominator"] for item in coverage.values())
    floor_counts = {name: sum(1 for frame in frames if frame["floors"][name]) for name in ("simulated_H", "simulated_W", "experimental_H", "experimental_W")}
    return {
        "schema": SCHEMA,
        "schema_version": OBJECTIVE_CONTRACT_VERSION,
        "status": PASS_STATUS,
        "candidate_id": candidate_id,
        "objective_value": float(w_h * h_component + w_w * w_component),
        "penalty_applied": False,
        "weights": {"H": w_h, "W": w_w},
        "pixel_floor": PIXEL_FLOOR,
        "H_component": float(h_component),
        "W_component": float(w_component),
        "e_H": math.sqrt(h_component),
        "e_W": math.sqrt(w_component),
        "coverage_flag": bool(low_coverage),
        "low_coverage_coupons": low_coverage,
        "fabricated_residuals_used": False,
        "frame_identity_digest": frame_identity_digest(rows),
        "aggregation_hierarchy": list(AGGREGATION_HIERARCHY),
        "counts": {
            "frame_record_count": len(rows),
            "scored_frame_count": len(frames),
            "undefined_frame_count": sum(1 for row in rows if row["frame_class"] == "UNDEFINED"),
            "excluded_by_rule_count": sum(1 for row in rows if row["frame_class"] == "EXCLUDED_BY_RULE"),
            "ineligible_frame_count": sum(1 for row in rows if row["frame_class"] == "INELIGIBLE"),
            "coverage_denominator": denominator,
            "coverage": (len(frames) / denominator) if denominator else None,
            "coverage_floor": COVERAGE_FLOOR,
            "coverage_by_coupon": {member: item["coverage"] for member, item in sorted(coverage.items())},
            "floored_frame_count": sum(1 for frame in frames if frame["floored"]),
            "floored_by_quantity": floor_counts,
            "zero_prediction_frame_count": sum(1 for frame in frames if frame["H_sim"] == 0.0 and frame["W_sim"] == 0.0),
            "track_count": len(track_rows),
            "coupon_count": len(coupon_rows),
            "condition_count": len(condition_rows),
        },
        "track_rows": track_rows,
        "coupon_rows": coupon_rows,
        "condition_rows": condition_rows,
    }


__all__ = [
    "H_WEIGHT",
    "OBJECTIVE_CONTRACT_VERSION",
    "PIXEL_FLOOR",
    "W_WEIGHT",
    "aggregate_log_ratio_records",
    "log_ratio",
]
