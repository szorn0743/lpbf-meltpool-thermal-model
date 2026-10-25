"""Patch 21.4 all-observation hierarchical H/W objective.

This module is deliberately independent of the thermal solver and HDF5
readers.  It consumes a deterministic portable frame table together with the
H/W values produced by one already-evaluated candidate.  The frame table is
then reduced through the frozen experimental hierarchy::

    frame -> scan track -> coupon -> exact condition replicate -> condition

Only the final condition-balanced scalar is an objective.  Frame, track, and
coupon error summaries are retained for audit and scientific reporting, but
raw frame counts and hierarchy cardinalities never become objective weights.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Iterable, Mapping, Sequence

from lpbf.calibration_contract import (
    COEFFICIENT_ORDER,
    calibration_member_identities,
    condition_id,
    load_patch21_0_contract,
    validation_member_identities,
)
from lpbf.infrastructure import canonical_sha256


# Patch 22.3.7 objective contract: frame-level statuses with coverage (ledger A20/A23).
PATCH_VERSION = "22.3.7"
SCHEMA = "lpbf_patch21_4_hierarchical_all_observation_objective"
FRAME_IDENTITY_SCHEMA = "member_identity/scan_track_id/frame_index"
H_REPEATABILITY_SCALE_PIXELS = 0.90
W_REPEATABILITY_SCALE_PIXELS = 0.65
H_METRIC_WEIGHT = 0.50
W_METRIC_WEIGHT = 0.50
PIXEL_SIZE_UM = 8.0
FAILED_CANDIDATE_PENALTY = 1.0e12
PASS_STATUS = "PASS"
FAILED_CANDIDATE_STATUS = "FAILED_CANDIDATE_PENALTY"
UNDEFINED_FRAME_STATUS = "UNDEFINED"
EXCLUDED_FRAME_STATUS = "EXCLUDED"
# Owner decision D3 (2026-10-14): a coupon whose scored fraction of eligible,
# non-excluded frames falls below this flags the candidate (it is still ranked,
# with the flag visible).  Only infrastructure failures take the penalty.
COVERAGE_FLOOR = 0.95
_NON_FAILURE_STATUSES = frozenset({PASS_STATUS, UNDEFINED_FRAME_STATUS, EXCLUDED_FRAME_STATUS})

_ELIGIBLE_FINITE = "ELIGIBLE_FINITE_HW"
_ELIGIBLE_ZERO = "ELIGIBLE_ZERO_FOOTPRINT"
_INVALID_STATUSES = frozenset(
    {
        "INVALID_NONFINITE_HW",
        "INVALID_NEGATIVE_HW",
        "INELIGIBLE_NONFINITE_HW",
        "INELIGIBLE_INVALID_HW",
        "EXCLUDED_NONFINITE_HW",
    }
)


class HierarchicalObjectiveError(ValueError):
    """Raised when a portable Patch 21.4 objective input violates its contract."""


def _as_bool(value: Any, name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in {"true", "1", "yes"}:
        return True
    if isinstance(value, str) and value.strip().lower() in {"false", "0", "no"}:
        return False
    raise HierarchicalObjectiveError(f"{name} must be boolean")


def _finite(value: Any, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise HierarchicalObjectiveError(f"{name} must be numeric") from exc
    if not math.isfinite(number):
        raise HierarchicalObjectiveError(f"{name} must be finite")
    return number


def _finite_or_none(value: Any, name: str) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise HierarchicalObjectiveError(f"{name} must be numeric or null") from exc
    return number if math.isfinite(number) else None


def _integer(value: Any, name: str) -> int:
    number = _finite(value, name)
    if not number.is_integer():
        raise HierarchicalObjectiveError(f"{name} must be an integer")
    return int(number)


def _mean(values: Sequence[float], name: str) -> float:
    if not values:
        raise HierarchicalObjectiveError(f"cannot average empty {name}")
    return float(sum(values) / len(values))


def _member_identity(row: Mapping[str, Any]) -> str:
    value = row.get("member_identity")
    if value is not None and str(value).strip() != "":
        return str(value)
    acquisition_set_id = row.get("acquisition_set_id")
    part_number = row.get("part_number")
    if acquisition_set_id is not None and part_number is not None:
        return f"{acquisition_set_id}:part_{_integer(part_number, 'part_number')}"
    value = row.get("portable_member_identity")
    if value is None or str(value).strip() == "":
        raise HierarchicalObjectiveError("frame row is missing member_identity")
    return str(value)


def _track_id(row: Mapping[str, Any]) -> str:
    value = row.get("scan_track_id", row.get("track_id"))
    if value is None or str(value).strip() == "":
        raise HierarchicalObjectiveError("frame row is missing scan_track_id")
    return str(value)


def _frame_index(row: Mapping[str, Any]) -> int:
    value = row.get("frame_index", row.get("frame_id"))
    if value is None:
        raise HierarchicalObjectiveError("frame row is missing frame_index")
    return _integer(value, "frame_index")


def _raw_frame_key(row: Mapping[str, Any]) -> tuple[str, str, int]:
    return (_member_identity(row), _track_id(row), _frame_index(row))


def _frame_identity_string(key: tuple[str, str, int]) -> str:
    member, track, frame = key
    return f"{member}|track={track}|frame={frame}"


def frame_identity_digest(records: Sequence[Mapping[str, Any]]) -> str:
    """Return the deterministic digest of the complete synchronized frame set."""

    keys = [_raw_frame_key(row) for row in records]
    if len(set(keys)) != len(keys):
        raise HierarchicalObjectiveError("duplicate member/track/frame identity")
    identities = [_frame_identity_string(key) for key in sorted(keys)]
    return canonical_sha256(
        {
            "frame_identity_schema": FRAME_IDENTITY_SCHEMA,
            "frame_identities": identities,
        }
    )


@dataclass(frozen=True)
class FrameSetContract:
    """Frozen identity set reused for every candidate evaluation."""

    frame_count: int
    frame_identity_digest: str

    @classmethod
    def from_records(cls, records: Sequence[Mapping[str, Any]]) -> "FrameSetContract":
        return cls(
            frame_count=len(records),
            frame_identity_digest=frame_identity_digest(records),
        )

    def validate(self, records: Sequence[Mapping[str, Any]]) -> None:
        actual_count = len(records)
        actual_digest = frame_identity_digest(records)
        if actual_count != int(self.frame_count) or actual_digest != self.frame_identity_digest:
            raise HierarchicalObjectiveError(
                "candidate changed the frozen experimental frame set: "
                f"expected count/digest {self.frame_count}/{self.frame_identity_digest}, "
                f"received {actual_count}/{actual_digest}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "frame_count": int(self.frame_count),
            "frame_identity_digest": self.frame_identity_digest,
            "frame_identity_schema": FRAME_IDENTITY_SCHEMA,
        }


def _observation_values(row: Mapping[str, Any]) -> tuple[float | None, float | None]:
    h_value = row.get("experimental_H_pixels", row.get("H_pixels"))
    w_value = row.get("experimental_W_pixels", row.get("W_pixels"))
    if h_value is None or w_value is None:
        return None, None
    try:
        h_float = float(h_value)
        w_float = float(w_value)
    except (TypeError, ValueError):
        return None, None
    # Nonfinite source values are represented as null in portable JSON while
    # their invalid/nonfinite status remains explicit in observation_status.
    if not math.isfinite(h_float) or not math.isfinite(w_float):
        return None, None
    return h_float, w_float


def _observation_status(row: Mapping[str, Any]) -> tuple[str, str]:
    source = str(row.get("observation_status", row.get("hw_status", "")))
    aliases = {
        "positive": _ELIGIBLE_FINITE,
        "finite": _ELIGIBLE_FINITE,
        "zero_footprint": _ELIGIBLE_ZERO,
        "nonfinite": "INVALID_NONFINITE_HW",
        "invalid": "INVALID_NONFINITE_HW",
        "invalid_H_or_W": "INVALID_NONFINITE_HW",
    }
    return aliases.get(source, source), source


def _candidate_values(row: Mapping[str, Any]) -> tuple[float, float]:
    h_sim = _finite(row.get("simulated_H_pixels"), "simulated_H_pixels")
    w_sim = _finite(row.get("simulated_W_pixels"), "simulated_W_pixels")
    if h_sim < 0.0 or w_sim < 0.0:
        raise HierarchicalObjectiveError("simulated H/W must be nonnegative")
    return h_sim, w_sim


def _normalise_input_row(raw: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise HierarchicalObjectiveError("each objective row must be a mapping")
    member = _member_identity(raw)
    track = _track_id(raw)
    frame = _frame_index(raw)
    try:
        cid = condition_id(raw["power_W"], raw["speed_mm_s"])
    except KeyError as exc:
        raise HierarchicalObjectiveError("frame row is missing power_W or speed_mm_s") from exc
    supplied_condition = raw.get("exact_condition_id")
    if supplied_condition is not None and str(supplied_condition) != cid:
        raise HierarchicalObjectiveError(
            f"condition identity mismatch for {member}/{track}/{frame}: "
            f"{supplied_condition!r} != {cid!r}"
        )

    eligible = _as_bool(
        raw.get("observation_eligible", raw.get("eligible_melt_pool_observation", False)),
        "observation_eligible",
    )
    observation_status, source_observation_status = _observation_status(raw)
    h_exp, w_exp = _observation_values(raw)
    # Preserve the upstream zero-footprint flag for both-zero and one-sided
    # zero footprints.  Both remain finite, nonnegative observations and are
    # retained in the objective when marked eligible.
    zero = h_exp == 0.0 or w_exp == 0.0 if h_exp is not None and w_exp is not None else False

    if eligible:
        if h_exp is None or w_exp is None or not math.isfinite(h_exp) or not math.isfinite(w_exp):
            raise HierarchicalObjectiveError(
                f"eligible frame {member}/{track}/{frame} has nonfinite/missing H/W"
            )
        if h_exp < 0.0 or w_exp < 0.0:
            raise HierarchicalObjectiveError(
                f"eligible frame {member}/{track}/{frame} has negative H/W"
            )
        expected_status = _ELIGIBLE_ZERO if zero else _ELIGIBLE_FINITE
        if observation_status and observation_status not in {_ELIGIBLE_FINITE, _ELIGIBLE_ZERO}:
            raise HierarchicalObjectiveError(
                f"eligible frame {member}/{track}/{frame} has invalid observation_status "
                f"{observation_status!r}"
            )
        observation_status = expected_status
    else:
        if not observation_status:
            observation_status = "INELIGIBLE_NOT_OBJECTIVE"

    # Patch 22.3.7 frame classes: SCORED enters residuals; UNDEFINED and
    # EXCLUDED_BY_RULE are retained for coverage; FAIL is an infrastructure
    # failure that penalizes the candidate; INELIGIBLE is experimental-side.
    candidate_status = str(raw.get("status", PASS_STATUS))
    scored_frame = _as_bool(raw.get("scored_frame", True), "scored_frame")
    if candidate_status not in _NON_FAILURE_STATUSES:
        frame_class = "FAIL"
    elif not eligible:
        frame_class = "INELIGIBLE"
    elif candidate_status == EXCLUDED_FRAME_STATUS or not scored_frame:
        frame_class = "EXCLUDED_BY_RULE"
    elif candidate_status == UNDEFINED_FRAME_STATUS:
        frame_class = "UNDEFINED"
    else:
        frame_class = "SCORED"

    key = (member, track, frame)
    acquisition_set_id = raw.get("acquisition_set_id")
    if acquisition_set_id is None and ":" in member:
        acquisition_set_id = member.split(":", 1)[0]
    part_number = raw.get("part_number")
    if part_number is None and "_part_" in member:
        part_number = member.rsplit("_part_", 1)[-1]
    return {
        "member_identity": member,
        "portable_member_identity": str(raw.get("portable_member_identity", member)),
        "acquisition_set_id": None if acquisition_set_id is None else str(acquisition_set_id),
        "part_number": part_number,
        "power_W": float(raw["power_W"]),
        "speed_mm_s": float(raw["speed_mm_s"]),
        "exact_condition_id": cid,
        "scan_track_id": track,
        "frame_index": frame,
        "frame_identity": _frame_identity_string(key),
        "observation_eligible": eligible,
        "observation_status": observation_status,
        "source_observation_status": source_observation_status,
        "experimental_H_pixels": h_exp,
        "experimental_W_pixels": w_exp,
        "zero_footprint": bool(zero),
        "candidate_status": candidate_status,
        "scored_frame": scored_frame,
        "frame_class": frame_class,
        "exclusion_reason": raw.get("exclusion_reason"),
        "undefined_reason": raw.get("undefined_reason"),
        "failure": raw.get("failure"),
        "raw": dict(raw),
    }


def _failure_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in rows:
        if row["frame_class"] == "FAIL":
            output.append(
                {
                    "member_identity": row["member_identity"],
                    "exact_condition_id": row["exact_condition_id"],
                    "scan_track_id": row["scan_track_id"],
                    "frame_index": row["frame_index"],
                    "status": row["candidate_status"],
                    "failure": row["failure"],
                }
            )
    return output


def _penalty_result(
    rows: Sequence[Mapping[str, Any]],
    *,
    candidate_id: str | None,
    reason: str,
    failure_rows: Sequence[Mapping[str, Any]] = (),
    penalty: float = FAILED_CANDIDATE_PENALTY,
) -> dict[str, Any]:
    failed = [dict(row) for row in failure_rows]
    return {
        "schema": SCHEMA,
        "schema_version": PATCH_VERSION,
        "status": FAILED_CANDIDATE_STATUS,
        "candidate_id": candidate_id,
        "objective_value": float(penalty),
        "penalty_applied": True,
        "failure_reason": reason,
        "failed_member_records": failed,
        "fabricated_residuals_used": False,
        "coverage_flag": None,
        "low_coverage_coupons": [],
        "frame_identity_digest": frame_identity_digest(rows),
        "frame_count": len(rows),
        "frame_rows": [],
        "track_rows": [],
        "coupon_rows": [],
        "condition_rows": [],
        "condition_objective_contributions": {},
        "diagnostics": {
            "temperature_diagnostics_in_objective": False,
            "h_over_w_ratio_in_objective": False,
            "raw_frame_count_weight_used": False,
            "track_length_weight_used": False,
            "replicate_count_weight_used": False,
            "validation_used": False,
            "parameter_selection_performed": False,
            "thermal_simulation_performed": False,
        },
    }


def _metric_bundle(
    h_residuals: Sequence[float],
    w_residuals: Sequence[float],
) -> dict[str, float]:
    if not h_residuals or len(h_residuals) != len(w_residuals):
        raise HierarchicalObjectiveError("H/W metric bundle has no aligned values")
    h_sq = [value * value for value in h_residuals]
    w_sq = [value * value for value in w_residuals]
    return {
        "H_bias_pixels": _mean(list(h_residuals), "H residuals"),
        "W_bias_pixels": _mean(list(w_residuals), "W residuals"),
        "H_MAE_pixels": _mean([abs(value) for value in h_residuals], "H absolute errors"),
        "W_MAE_pixels": _mean([abs(value) for value in w_residuals], "W absolute errors"),
        "H_MSE_pixels_squared": _mean(h_sq, "H squared errors"),
        "W_MSE_pixels_squared": _mean(w_sq, "W squared errors"),
        "H_RMSE_pixels": math.sqrt(_mean(h_sq, "H squared errors")),
        "W_RMSE_pixels": math.sqrt(_mean(w_sq, "W squared errors")),
        "H_normalized_MSE": _mean(
            [(value / H_REPEATABILITY_SCALE_PIXELS) ** 2 for value in h_residuals],
            "H normalized errors",
        ),
        "W_normalized_MSE": _mean(
            [(value / W_REPEATABILITY_SCALE_PIXELS) ** 2 for value in w_residuals],
            "W normalized errors",
        ),
    }


def _metric_mean(rows: Sequence[Mapping[str, Any]], key: str) -> float:
    return _mean([float(row[key]) for row in rows], key)


def _hierarchical_metric_bundle(rows: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    if not rows:
        raise HierarchicalObjectiveError("cannot summarize an empty hierarchy level")
    h_bias = _metric_mean(rows, "H_bias_pixels")
    w_bias = _metric_mean(rows, "W_bias_pixels")
    h_mae = _metric_mean(rows, "H_MAE_pixels")
    w_mae = _metric_mean(rows, "W_MAE_pixels")
    h_mse = _metric_mean(rows, "H_MSE_pixels_squared")
    w_mse = _metric_mean(rows, "W_MSE_pixels_squared")
    return {
        "H_bias_pixels": h_bias,
        "W_bias_pixels": w_bias,
        "H_MAE_pixels": h_mae,
        "W_MAE_pixels": w_mae,
        "H_MSE_pixels_squared": h_mse,
        "W_MSE_pixels_squared": w_mse,
        "H_RMSE_pixels": math.sqrt(h_mse),
        "W_RMSE_pixels": math.sqrt(w_mse),
        "H_normalized_MSE": _metric_mean(rows, "H_normalized_MSE"),
        "W_normalized_MSE": _metric_mean(rows, "W_normalized_MSE"),
    }


def _physical_error_summary(
    metrics: Mapping[str, float],
    *,
    level: str,
    row_count: int,
    weighting_basis: str,
    objective_relevant: bool,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "level": level,
        "row_count": int(row_count),
        "weighting_basis": weighting_basis,
        "objective_relevant": bool(objective_relevant),
        "H_normalized_MSE": float(metrics["H_normalized_MSE"]),
        "W_normalized_MSE": float(metrics["W_normalized_MSE"]),
    }
    for metric in ("bias", "MAE", "RMSE"):
        for channel in ("H", "W"):
            pixels_key = f"{channel}_{metric}_pixels"
            pixels = float(metrics[pixels_key])
            micrometers = pixels * PIXEL_SIZE_UM
            result[f"{channel}_{metric}_pixels"] = pixels
            result[f"{channel}_{metric}_um"] = micrometers
            result[f"{channel}_{metric}_mm"] = micrometers / 1000.0
    return result


def _validate_requested_partition(
    rows: Sequence[Mapping[str, Any]],
    *,
    calibration_member_ids: frozenset[str],
    calibration_condition_ids: frozenset[str],
    require_complete: bool,
) -> None:
    observed_members = {row["member_identity"] for row in rows}
    if observed_members - calibration_member_ids:
        unknown = sorted(observed_members - calibration_member_ids)
        raise HierarchicalObjectiveError(f"unknown/non-calibration member identities: {unknown}")
    if require_complete and observed_members != calibration_member_ids:
        missing = sorted(calibration_member_ids - observed_members)
        raise HierarchicalObjectiveError(
            f"all calibration members are required; missing={missing}"
        )
    observed_conditions = {row["exact_condition_id"] for row in rows}
    unknown_conditions = observed_conditions - calibration_condition_ids
    if unknown_conditions:
        raise HierarchicalObjectiveError(
            f"objective rows contain unknown/non-calibration conditions: {sorted(unknown_conditions)}"
        )
    if require_complete and observed_conditions != calibration_condition_ids:
        missing = sorted(calibration_condition_ids - observed_conditions)
        raise HierarchicalObjectiveError(
            f"all calibration conditions are required; missing={missing}"
        )


def _coverage_by_coupon(rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Scored / (eligible minus excluded-by-rule) per coupon; the denominator never counts rule exclusions."""

    coverage: dict[str, dict[str, Any]] = {}
    for row in rows:
        item = coverage.setdefault(
            row["member_identity"],
            {"scored": 0, "undefined": 0, "excluded_by_rule": 0, "denominator": 0, "coverage": None},
        )
        frame_class = row["frame_class"]
        if frame_class == "SCORED":
            item["scored"] += 1
            item["denominator"] += 1
        elif frame_class == "UNDEFINED":
            item["undefined"] += 1
            item["denominator"] += 1
        elif frame_class == "EXCLUDED_BY_RULE":
            item["excluded_by_rule"] += 1
    for item in coverage.values():
        item["coverage"] = (item["scored"] / item["denominator"]) if item["denominator"] else None
    return coverage


def aggregate_hierarchical_records(
    records: Sequence[Mapping[str, Any]],
    *,
    calibration_member_ids: Iterable[str] | None = None,
    calibration_condition_ids: Iterable[str] | None = None,
    require_complete: bool = True,
    frame_set_contract: FrameSetContract | None = None,
    candidate_id: str | None = None,
    failed_penalty: float = FAILED_CANDIDATE_PENALTY,
) -> dict[str, Any]:
    """Aggregate one candidate's portable observations through all hierarchy levels.

    ``records`` may contain retained invalid/nonfinite experimental rows.  Such
    rows remain in the frozen frame set and in the audit frame rows but do not
    contribute to finite H/W statistics.  Eligible zero-footprint rows are
    finite observations and do contribute to the objective.
    """

    if not records:
        raise HierarchicalObjectiveError("hierarchical objective requires frame records")
    if frame_set_contract is not None:
        frame_set_contract.validate(records)

    rows = [_normalise_input_row(raw) for raw in records]
    keys = [(row["member_identity"], row["scan_track_id"], row["frame_index"]) for row in rows]
    if len(set(keys)) != len(keys):
        raise HierarchicalObjectiveError("duplicate member/track/frame identity")

    calibration_members = frozenset(
        str(value) for value in calibration_member_ids
    ) if calibration_member_ids is not None else frozenset(
        row["member_identity"] for row in rows
    )
    calibration_conditions = frozenset(
        str(value) for value in calibration_condition_ids
    ) if calibration_condition_ids is not None else frozenset(
        row["exact_condition_id"] for row in rows
    )
    _validate_requested_partition(
        rows,
        calibration_member_ids=calibration_members,
        calibration_condition_ids=calibration_conditions,
        require_complete=require_complete,
    )

    member_metadata: dict[str, tuple[str | None, str | None, str]] = {}
    track_conditions: dict[tuple[str, str], str] = {}
    for row in rows:
        member = row["member_identity"]
        metadata = (
            row["acquisition_set_id"],
            None if row["part_number"] is None else str(row["part_number"]),
            row["portable_member_identity"],
        )
        previous = member_metadata.setdefault(member, metadata)
        if previous != metadata:
            raise HierarchicalObjectiveError(
                f"member identity metadata drifted for {member}: {previous!r} != {metadata!r}"
            )
        track_key = (member, row["scan_track_id"])
        previous_condition = track_conditions.setdefault(track_key, row["exact_condition_id"])
        if previous_condition != row["exact_condition_id"]:
            raise HierarchicalObjectiveError(
                f"scan track {track_key} spans multiple exact conditions"
            )

    candidate_failures = _failure_rows(rows)
    if candidate_failures:
        return _penalty_result(
            rows,
            candidate_id=candidate_id,
            reason="candidate member/frame evaluation reported failure",
            failure_rows=candidate_failures,
            penalty=failed_penalty,
        )

    coverage = _coverage_by_coupon(rows)
    empty_coupons = sorted(
        member for member, item in coverage.items() if item["denominator"] > 0 and item["scored"] == 0
    )
    if empty_coupons:
        return _penalty_result(
            rows,
            candidate_id=candidate_id,
            reason=f"coupon has no scored frames: {empty_coupons}",
            failure_rows=[{"member_identity": member, "status": "NO_SCORED_FRAMES"} for member in empty_coupons],
            penalty=failed_penalty,
        )
    valid_rows = [row for row in rows if row["frame_class"] == "SCORED"]
    if not valid_rows:
        raise HierarchicalObjectiveError(
            "no eligible finite H/W observations remain after retained invalid rows"
        )

    frame_rows: list[dict[str, Any]] = []
    valid_metric_rows: list[dict[str, Any]] = []
    valid_track_counts: dict[tuple[str, str], int] = {}
    for row in valid_rows:
        key = (row["member_identity"], row["scan_track_id"])
        valid_track_counts[key] = valid_track_counts.get(key, 0) + 1
    simulation_failure: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda item: (item["member_identity"], item["scan_track_id"], item["frame_index"])):
        frame_output: dict[str, Any] = {
            "frame_identity": row["frame_identity"],
            "portable_member_identity": row["portable_member_identity"],
            "member_identity": row["member_identity"],
            "acquisition_set_id": row["acquisition_set_id"],
            "part_number": row["part_number"],
            "exact_condition_id": row["exact_condition_id"],
            "scan_track_id": row["scan_track_id"],
            "frame_index": row["frame_index"],
            "power_W": row["power_W"],
            "speed_mm_s": row["speed_mm_s"],
            "observation_status": row["observation_status"],
            "source_observation_status": row["source_observation_status"],
            "observation_eligible": row["observation_eligible"],
            "scored_frame": row["scored_frame"],
            "frame_class": row["frame_class"],
            "exclusion_reason": row["exclusion_reason"],
            "undefined_reason": row["undefined_reason"],
            "objective_inclusion": False,
            "zero_footprint": row["zero_footprint"],
            "experimental_H_pixels": row["experimental_H_pixels"],
            "experimental_W_pixels": row["experimental_W_pixels"],
            "observation_weight_within_track": (
                1.0 / valid_track_counts[(row["member_identity"], row["scan_track_id"])]
                if row["frame_class"] == "SCORED"
                else None
            ),
        }
        if row["frame_class"] != "SCORED":
            frame_output.update(
                {
                    "simulated_H_pixels": None,
                    "simulated_W_pixels": None,
                    "H_residual_pixels": None,
                    "W_residual_pixels": None,
                    "H_normalized_squared_error": None,
                    "W_normalized_squared_error": None,
                    "scalar_objective_contribution": None,
                    "H_over_W_ratio_diagnostic": None,
                }
            )
            frame_rows.append(frame_output)
            continue
        try:
            h_sim, w_sim = _candidate_values(row["raw"])
        except (KeyError, HierarchicalObjectiveError) as exc:
            simulation_failure.append(
                {
                    "member_identity": row["member_identity"],
                    "exact_condition_id": row["exact_condition_id"],
                    "scan_track_id": row["scan_track_id"],
                    "frame_index": row["frame_index"],
                    "status": "INVALID_CANDIDATE_H_W",
                    "failure": str(exc),
                }
            )
            continue
        h_residual = h_sim - float(row["experimental_H_pixels"])
        w_residual = w_sim - float(row["experimental_W_pixels"])
        h_norm_sq = (h_residual / H_REPEATABILITY_SCALE_PIXELS) ** 2
        w_norm_sq = (w_residual / W_REPEATABILITY_SCALE_PIXELS) ** 2
        scalar = H_METRIC_WEIGHT * h_norm_sq + W_METRIC_WEIGHT * w_norm_sq
        frame_output.update(
            {
                "simulated_H_pixels": h_sim,
                "simulated_W_pixels": w_sim,
                "H_residual_pixels": h_residual,
                "W_residual_pixels": w_residual,
                "H_normalized_squared_error": h_norm_sq,
                "W_normalized_squared_error": w_norm_sq,
                "scalar_objective_contribution": scalar,
                "H_over_W_ratio_diagnostic": (
                    h_sim / w_sim if w_sim > 0.0 else None
                ),
                "objective_inclusion": True,
            }
        )
        frame_rows.append(frame_output)
        valid_metric_rows.append(
            {
                **row,
                "simulated_H_pixels": h_sim,
                "simulated_W_pixels": w_sim,
                "H_residual_pixels": h_residual,
                "W_residual_pixels": w_residual,
                "H_normalized_squared_error": h_norm_sq,
                "W_normalized_squared_error": w_norm_sq,
                "scalar_objective_contribution": scalar,
            }
        )

    if simulation_failure:
        return _penalty_result(
            rows,
            candidate_id=candidate_id,
            reason="candidate produced missing, nonfinite, or negative simulated H/W",
            failure_rows=simulation_failure,
            penalty=failed_penalty,
        )

    # Each finite eligible row now has a frame-level residual.  No later level
    # can look back at raw frame cardinality to choose its weight.
    track_groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in valid_metric_rows:
        track_groups.setdefault((row["member_identity"], row["scan_track_id"]), []).append(row)

    track_rows: list[dict[str, Any]] = []
    for (member, track), group in sorted(track_groups.items()):
        synchronized_track_rows = [
            row
            for row in rows
            if row["member_identity"] == member and row["scan_track_id"] == track
        ]
        metrics = _metric_bundle(
            [row["H_residual_pixels"] for row in group],
            [row["W_residual_pixels"] for row in group],
        )
        track_rows.append(
            {
                "member_identity": member,
                "portable_member_identity": group[0]["portable_member_identity"],
                "acquisition_set_id": group[0]["acquisition_set_id"],
                "part_number": group[0]["part_number"],
                "scan_track_id": track,
                "exact_condition_id": group[0]["exact_condition_id"],
                "frame_count": len(group),
                "synchronized_frame_count": len(synchronized_track_rows),
                "invalid_excluded_count": sum(
                    1 for row in synchronized_track_rows if not row["observation_eligible"]
                ),
                "scored_count": len(group),
                "undefined_count": sum(
                    1 for row in synchronized_track_rows if row["frame_class"] == "UNDEFINED"
                ),
                "excluded_by_rule_count": sum(
                    1 for row in synchronized_track_rows if row["frame_class"] == "EXCLUDED_BY_RULE"
                ),
                "zero_footprint_count": sum(
                    1
                    for row in synchronized_track_rows
                    if row["observation_eligible"] and row["zero_footprint"]
                ),
                "observation_weight_within_track": 1.0 / len(group),
                **metrics,
                "track_scalar_objective": H_METRIC_WEIGHT * metrics["H_normalized_MSE"]
                + W_METRIC_WEIGHT * metrics["W_normalized_MSE"],
            }
        )

    tracks_by_member: dict[str, list[dict[str, Any]]] = {}
    for row in track_rows:
        tracks_by_member.setdefault(row["member_identity"], []).append(row)

    coupon_rows: list[dict[str, Any]] = []
    for member, group in sorted(tracks_by_member.items()):
        metrics = _hierarchical_metric_bundle(group)
        coupon_rows.append(
            {
                "member_identity": member,
                "portable_member_identity": group[0]["portable_member_identity"],
                "acquisition_set_id": group[0]["acquisition_set_id"],
                "part_number": group[0]["part_number"],
                "exact_condition_id": group[0]["exact_condition_id"],
                "track_count": len(group),
                "coverage": coverage[member]["coverage"],
                "scored_frame_count": coverage[member]["scored"],
                "undefined_frame_count": coverage[member]["undefined"],
                "excluded_by_rule_count": coverage[member]["excluded_by_rule"],
                "track_weight_within_coupon": 1.0 / len(group),
                "track_weights": [
                    {
                        "scan_track_id": row["scan_track_id"],
                        "weight": 1.0 / len(group),
                    }
                    for row in group
                ],
                **metrics,
                "coupon_scalar_objective": H_METRIC_WEIGHT * metrics["H_normalized_MSE"]
                + W_METRIC_WEIGHT * metrics["W_normalized_MSE"],
            }
        )

    coupons_by_condition: dict[str, list[dict[str, Any]]] = {}
    for row in coupon_rows:
        coupons_by_condition.setdefault(row["exact_condition_id"], []).append(row)
    if not coupons_by_condition:
        raise HierarchicalObjectiveError("no observation-bearing coupons remain")
    if require_complete and set(coupons_by_condition) != calibration_conditions:
        missing = sorted(calibration_conditions - set(coupons_by_condition))
        raise HierarchicalObjectiveError(
            f"calibration conditions lack eligible observation-bearing coupons: {missing}"
        )

    condition_rows: list[dict[str, Any]] = []
    for cid, group in sorted(coupons_by_condition.items()):
        metrics = _hierarchical_metric_bundle(group)
        condition_rows.append(
            {
                "exact_condition_id": cid,
                "replicate_coupon_count": len(group),
                "replicate_coupon_weight_within_condition": 1.0 / len(group),
                "replicate_coupon_weights": [
                    {
                        "member_identity": row["member_identity"],
                        "weight": 1.0 / len(group),
                    }
                    for row in group
                ],
                **metrics,
                "condition_objective_contribution": H_METRIC_WEIGHT * metrics["H_normalized_MSE"]
                + W_METRIC_WEIGHT * metrics["W_normalized_MSE"],
                "member_identities": [row["member_identity"] for row in group],
                "portable_member_identities": [
                    row["portable_member_identity"] for row in group
                ],
                "acquisition_set_ids": sorted(
                    {
                        row["acquisition_set_id"]
                        for row in group
                        if row["acquisition_set_id"] is not None
                    }
                ),
            }
        )

    if require_complete and {row["exact_condition_id"] for row in condition_rows} != calibration_conditions:
        raise HierarchicalObjectiveError("condition rows do not match the frozen calibration conditions")

    acquisition_groups: dict[str, list[dict[str, Any]]] = {}
    for row in coupon_rows:
        acquisition_set_id = row["acquisition_set_id"]
        if acquisition_set_id is not None:
            acquisition_groups.setdefault(str(acquisition_set_id), []).append(row)
    acquisition_set_rows: list[dict[str, Any]] = []
    for acquisition_set_id, group in sorted(acquisition_groups.items()):
        metrics = _hierarchical_metric_bundle(group)
        acquisition_set_rows.append(
            {
                "acquisition_set_id": acquisition_set_id,
                "coupon_count": len(group),
                "condition_ids": sorted({row["exact_condition_id"] for row in group}),
                "member_identities": [row["member_identity"] for row in group],
                "portable_member_identities": [
                    row["portable_member_identity"] for row in group
                ],
                "weighting_basis": "descriptive_equal_coupon_mean_within_acquisition_set",
                **metrics,
            }
        )

    h_component = _mean(
        [row["H_normalized_MSE"] for row in condition_rows],
        "condition H objective contributions",
    )
    w_component = _mean(
        [row["W_normalized_MSE"] for row in condition_rows],
        "condition W objective contributions",
    )
    objective_value = H_METRIC_WEIGHT * h_component + W_METRIC_WEIGHT * w_component

    eligible_frame_rows = [row for row in frame_rows if row["objective_inclusion"]]
    frame_metrics = _metric_bundle(
        [row["H_residual_pixels"] for row in eligible_frame_rows],
        [row["W_residual_pixels"] for row in eligible_frame_rows],
    )
    track_metrics = _hierarchical_metric_bundle(track_rows)
    coupon_metrics = _hierarchical_metric_bundle(coupon_rows)
    condition_metrics = _hierarchical_metric_bundle(condition_rows)
    invalid_count = sum(1 for row in rows if not row["observation_eligible"])
    zero_count = sum(1 for row in rows if row["zero_footprint"] and row["frame_class"] == "SCORED")
    eligible_count = sum(1 for row in rows if row["observation_eligible"])
    undefined_count = sum(1 for row in rows if row["frame_class"] == "UNDEFINED")
    excluded_count = sum(1 for row in rows if row["frame_class"] == "EXCLUDED_BY_RULE")
    coverage_denominator = sum(item["denominator"] for item in coverage.values())
    overall_coverage = (len(valid_metric_rows) / coverage_denominator) if coverage_denominator else None
    low_coverage = sorted(
        member
        for member, item in coverage.items()
        if item["coverage"] is not None and item["coverage"] < COVERAGE_FLOOR
    )

    return {
        "schema": SCHEMA,
        "schema_version": PATCH_VERSION,
        "status": PASS_STATUS,
        "candidate_id": candidate_id,
        "objective_value": float(objective_value),
        "penalty_applied": False,
        "coverage_flag": bool(low_coverage),
        "low_coverage_coupons": low_coverage,
        "fabricated_residuals_used": False,
        "frame_identity_digest": frame_identity_digest(rows),
        "frame_count": len(rows),
        "frame_set_contract": FrameSetContract.from_records(records).to_dict(),
        "counts": {
            "synchronized_frame_count": len(rows),
            "eligible_frame_count": eligible_count,
            "scored_frame_count": len(valid_metric_rows),
            "undefined_frame_count": undefined_count,
            "excluded_by_rule_count": excluded_count,
            "coverage_denominator": coverage_denominator,
            "coverage": overall_coverage,
            "coverage_floor": COVERAGE_FLOOR,
            "coverage_by_coupon": {member: item["coverage"] for member, item in sorted(coverage.items())},
            "low_coverage_coupons": low_coverage,
            "invalid_excluded_count": invalid_count,
            "zero_footprint_eligible_count": zero_count,
            "observation_bearing_track_count": len(track_rows),
            "coupon_count": len(coupon_rows),
            "condition_count": len(condition_rows),
            "acquisition_set_count": len(acquisition_set_rows),
            "calibration_member_count_present": len({row["member_identity"] for row in rows}),
        },
        "aggregation_hierarchy": [
            "camera_frame",
            "scan_track",
            "coupon",
            "exact_condition_replicate",
            "unique_calibration_condition",
        ],
        "objective_definition": {
            "normalization_scales_pixels": {
                "H_pixels": H_REPEATABILITY_SCALE_PIXELS,
                "W_pixels": W_REPEATABILITY_SCALE_PIXELS,
            },
            "metric_weights": {
                "H_pixels": H_METRIC_WEIGHT,
                "W_pixels": W_METRIC_WEIGHT,
            },
            "H_component_unweighted_condition_mean": float(h_component),
            "W_component_unweighted_condition_mean": float(w_component),
            "failed_candidate_scalar_penalty": float(failed_penalty),
        },
        "H_component_unweighted_condition_mean": float(h_component),
        "W_component_unweighted_condition_mean": float(w_component),
        "H_weight": H_METRIC_WEIGHT,
        "W_weight": W_METRIC_WEIGHT,
        "condition_objective_contributions": {
            row["exact_condition_id"]: float(row["condition_objective_contribution"])
            for row in condition_rows
        },
        "frame_rows": frame_rows,
        "track_rows": track_rows,
        "coupon_rows": coupon_rows,
        "acquisition_set_rows": acquisition_set_rows,
        "condition_rows": condition_rows,
        "hierarchical_error_summaries": {
            "frame": _physical_error_summary(
                frame_metrics,
                level="frame",
                row_count=len(eligible_frame_rows),
                weighting_basis="descriptive_equal_weight_per_eligible_frame_only",
                objective_relevant=False,
            ),
            "track": _physical_error_summary(
                track_metrics,
                level="track",
                row_count=len(track_rows),
                weighting_basis="equal_weight_per_observation_bearing_track_for_coupon_aggregation",
                objective_relevant=True,
            ),
            "coupon": _physical_error_summary(
                coupon_metrics,
                level="coupon",
                row_count=len(coupon_rows),
                weighting_basis="equal_weight_per_observation_bearing_coupon_for_condition_aggregation",
                objective_relevant=True,
            ),
            "condition": _physical_error_summary(
                condition_metrics,
                level="condition",
                row_count=len(condition_rows),
                weighting_basis="equal_weight_per_unique_calibration_condition",
                objective_relevant=True,
            ),
            "acquisition_set": {
                "row_count": len(acquisition_set_rows),
                "weighting_basis": "descriptive_only; no acquisition-set weighting in objective",
                "objective_relevant": False,
            },
        },
        "diagnostics": {
            "temperature_diagnostics_in_objective": False,
            "h_over_w_ratio_in_objective": False,
            "raw_frame_count_weight_used": False,
            "track_length_weight_used": False,
            "replicate_count_weight_used": False,
            "validation_used": False,
            "parameter_selection_performed": False,
            "thermal_simulation_performed": False,
        },
        "retained_observation_flags": {
            "zero_footprint_observations_retained": zero_count,
            "invalid_nonfinite_observations_retained_and_excluded": invalid_count,
        },
    }


def evaluate_hierarchical_objective(
    records: Sequence[Mapping[str, Any]],
    *,
    frame_set_contract: FrameSetContract | None = None,
    contract: Mapping[str, Any] | None = None,
    candidate_id: str | None = None,
) -> dict[str, Any]:
    """Evaluate a production Patch 21.4 candidate against frozen calibration rows."""

    design = load_patch21_0_contract() if contract is None else contract
    calibration = calibration_member_identities(design)
    validation = validation_member_identities(design)
    present = {
        _member_identity(row)
        for row in records
        if isinstance(row, Mapping)
    }
    leaked = sorted(present & validation)
    if leaked:
        raise HierarchicalObjectiveError(
            f"held-out validation members may not enter Patch 21.4 objective: {leaked}"
        )
    condition_ids = frozenset(str(value) for value in design["data_partition"]["calibration_condition_ids"])
    return aggregate_hierarchical_records(
        records,
        calibration_member_ids=calibration,
        calibration_condition_ids=condition_ids,
        require_complete=True,
        frame_set_contract=frame_set_contract,
        candidate_id=candidate_id,
        failed_penalty=float(design["objective"]["failed_candidate_scalar_penalty"]),
    )


def validate_hierarchical_objective_contract(
    contract: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate the Patch 21.4 JSON freeze and its inherited partition locks."""

    inherited = load_patch21_0_contract()
    design: Mapping[str, Any] = contract if contract is not None else {
        "schema": SCHEMA,
        "schema_version": PATCH_VERSION,
        "patch": "21.4",
        "objective": {
            "normalization_scales_pixels": {
                "H_pixels": H_REPEATABILITY_SCALE_PIXELS,
                "W_pixels": W_REPEATABILITY_SCALE_PIXELS,
            },
            "metric_weights": {
                "H_pixels": H_METRIC_WEIGHT,
                "W_pixels": W_METRIC_WEIGHT,
            },
            "failed_candidate_scalar_penalty": FAILED_CANDIDATE_PENALTY,
            "coverage_floor": COVERAGE_FLOOR,
        },
        "partition": {
            "calibration_member_count": 16,
            "calibration_unique_condition_count": 12,
            "validation_member_count": 8,
            "validation_unique_condition_count": 6,
            "validation_partition_used": False,
        },
        "selection_lock": {
            "parameter_selection_performed": False,
            "model_fitting_performed": False,
            "validation_used": False,
        },
    }
    if design.get("schema") != SCHEMA:
        raise HierarchicalObjectiveError("unexpected Patch 21.4 objective-contract schema")
    if design.get("schema_version") != PATCH_VERSION:
        raise HierarchicalObjectiveError("unexpected Patch 21.4 objective-contract version")
    objective = design.get("objective", {})
    scales = objective.get("normalization_scales_pixels", {})
    weights = objective.get("metric_weights", {})
    if float(scales.get("H_pixels")) != H_REPEATABILITY_SCALE_PIXELS:
        raise HierarchicalObjectiveError("H repeatability scale drifted")
    if float(scales.get("W_pixels")) != W_REPEATABILITY_SCALE_PIXELS:
        raise HierarchicalObjectiveError("W repeatability scale drifted")
    if float(weights.get("H_pixels")) != H_METRIC_WEIGHT or float(weights.get("W_pixels")) != W_METRIC_WEIGHT:
        raise HierarchicalObjectiveError("H/W metric weights drifted")
    if float(objective.get("failed_candidate_scalar_penalty")) != FAILED_CANDIDATE_PENALTY:
        raise HierarchicalObjectiveError("failed-candidate penalty drifted")
    if float(objective.get("coverage_floor", COVERAGE_FLOOR)) != COVERAGE_FLOOR:
        raise HierarchicalObjectiveError("coverage floor drifted")

    inherited_partition = inherited["data_partition"]
    expected_partition = {
        "calibration_member_count": 16,
        "calibration_unique_condition_count": 12,
        "validation_member_count": 8,
        "validation_unique_condition_count": 6,
    }
    for key, expected in expected_partition.items():
        if int(inherited_partition[key]) != expected:
            raise HierarchicalObjectiveError(f"inherited partition drifted at {key}")
        if "partition" in design and int(design["partition"].get(key, expected)) != expected:
            raise HierarchicalObjectiveError(f"Patch 21.4 partition drifted at {key}")
    selection_lock = design.get("selection_lock", {})
    for key in ("parameter_selection_performed", "model_fitting_performed", "validation_used"):
        if bool(selection_lock.get(key, False)):
            raise HierarchicalObjectiveError(f"Patch 21.4 selection lock is open: {key}")
    if bool(design.get("partition", {}).get("validation_partition_used", False)):
        raise HierarchicalObjectiveError("validation partition is not available to Patch 21.4 objective")
    if tuple(COEFFICIENT_ORDER) != (
        "abs_depth_identifiable_coordinate",
        "liquid_conductivity_enhancement_factor",
        "eta_directional",
    ):
        raise HierarchicalObjectiveError("inherited optimizer coefficient order drifted")
    return {
        "status": "PASS",
        "schema": SCHEMA,
        "schema_version": PATCH_VERSION,
        "calibration_member_count": 16,
        "calibration_condition_count": 12,
        "validation_member_count": 8,
        "validation_condition_count": 6,
        "validation_partition_used": False,
        "parameter_selection_performed": False,
        "model_fitting_performed": False,
        "objective_scales_locked": True,
        "objective_weights_locked": True,
        "coverage_floor": COVERAGE_FLOOR,
    }


def _synthetic_records(
    *,
    member_values: Sequence[tuple[str, str, float, float]],
    frames_per_track: int = 1,
    track_count: int = 1,
    residual_h: float = 0.10,
    residual_w: float = 0.20,
    include_zero: bool = False,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for member, cid, base_h, base_w in member_values:
        power, speed = cid[1:].split("_V")
        for track_index in range(track_count):
            for frame_index in range(frames_per_track):
                h = 0.0 if include_zero and track_index == 0 and frame_index == 0 else base_h
                w = 0.0 if include_zero and track_index == 0 and frame_index == 0 else base_w
                records.append(
                    {
                        "member_identity": member,
                        "portable_member_identity": member,
                        "acquisition_set_id": member.split(":", 1)[0],
                        "part_number": member.rsplit("_", 1)[-1].replace("part", ""),
                        "power_W": int(power),
                        "speed_mm_s": int(speed),
                        "exact_condition_id": cid,
                        "scan_track_id": str(track_index),
                        "frame_index": frame_index,
                        "experimental_H_pixels": h,
                        "experimental_W_pixels": w,
                        "simulated_H_pixels": h + residual_h,
                        "simulated_W_pixels": w + residual_w,
                        "observation_eligible": True,
                        "observation_status": _ELIGIBLE_ZERO if h == 0.0 and w == 0.0 else _ELIGIBLE_FINITE,
                        "status": PASS_STATUS,
                    }
                )
    return records


def run_design_only_verification() -> dict[str, Any]:
    """Run deterministic weighting and fail-closed checks without HDF5 or simulation."""

    one = [("toy:part_1", "P140_V600", 10.0, 5.0)]
    base = _synthetic_records(member_values=one, frames_per_track=1)
    longer = _synthetic_records(member_values=one, frames_per_track=4)
    one_result = aggregate_hierarchical_records(
        base,
        calibration_member_ids={"toy:part_1"},
        calibration_condition_ids={"P140_V600"},
        require_complete=False,
    )
    longer_result = aggregate_hierarchical_records(
        longer,
        calibration_member_ids={"toy:part_1"},
        calibration_condition_ids={"P140_V600"},
        require_complete=False,
    )
    if one_result["objective_value"] != longer_result["objective_value"]:
        raise HierarchicalObjectiveError("frame duplication changed a track's objective weight")

    two_tracks = _synthetic_records(member_values=one, frames_per_track=1, track_count=2)
    two_track_result = aggregate_hierarchical_records(
        two_tracks,
        calibration_member_ids={"toy:part_1"},
        calibration_condition_ids={"P140_V600"},
        require_complete=False,
    )
    if two_track_result["objective_value"] != one_result["objective_value"]:
        raise HierarchicalObjectiveError("adding an identical track changed the coupon objective")
    if [row["track_weight_within_coupon"] for row in two_track_result["coupon_rows"]] != [0.5]:
        raise HierarchicalObjectiveError("track weight audit is not equal within coupon")

    replicate_records = _synthetic_records(member_values=[
        ("toy:part_1", "P140_V600", 10.0, 5.0),
        ("toy:part_2", "P140_V600", 10.0, 5.0),
    ])
    replicate_result = aggregate_hierarchical_records(
        replicate_records,
        calibration_member_ids={"toy:part_1", "toy:part_2"},
        calibration_condition_ids={"P140_V600"},
        require_complete=False,
    )
    if replicate_result["objective_value"] != one_result["objective_value"]:
        raise HierarchicalObjectiveError("adding an identical replicate changed condition objective")
    if replicate_result["condition_rows"][0]["replicate_coupon_weight_within_condition"] != 0.5:
        raise HierarchicalObjectiveError("replicate weights do not sum to one")

    zero_records = _synthetic_records(member_values=one, include_zero=True)
    zero_result = aggregate_hierarchical_records(
        zero_records,
        calibration_member_ids={"toy:part_1"},
        calibration_condition_ids={"P140_V600"},
        require_complete=False,
    )
    if zero_result["counts"]["zero_footprint_eligible_count"] != 1:
        raise HierarchicalObjectiveError("zero-footprint eligible frame was not retained")
    invalid = dict(base[0])
    invalid.update(
        {
            "frame_index": 1,
            "experimental_H_pixels": float("nan"),
            "experimental_W_pixels": float("nan"),
            "observation_eligible": False,
            "observation_status": "INVALID_NONFINITE_HW",
            "simulated_H_pixels": None,
            "simulated_W_pixels": None,
        }
    )
    invalid_result = aggregate_hierarchical_records(
        base + [invalid],
        calibration_member_ids={"toy:part_1"},
        calibration_condition_ids={"P140_V600"},
        require_complete=False,
    )
    if invalid_result["counts"]["invalid_excluded_count"] != 1:
        raise HierarchicalObjectiveError("invalid/nonfinite frame was not retained and excluded")
    if invalid_result["objective_value"] != one_result["objective_value"]:
        raise HierarchicalObjectiveError("invalid/nonfinite frame changed finite objective")

    undefined_rows = [dict(row) for row in longer]
    undefined_rows[1].update(
        {
            "status": UNDEFINED_FRAME_STATUS,
            "undefined_reason": "FAIL_CLOSED_TIED_SHARE",
            "simulated_H_pixels": None,
            "simulated_W_pixels": None,
        }
    )
    undefined_result = aggregate_hierarchical_records(
        undefined_rows,
        calibration_member_ids={"toy:part_1"},
        calibration_condition_ids={"P140_V600"},
        require_complete=False,
    )
    if (
        undefined_result["counts"]["undefined_frame_count"] != 1
        or undefined_result["objective_value"] != longer_result["objective_value"]
    ):
        raise HierarchicalObjectiveError("undefined frame was not excluded from residuals")
    if undefined_result["coverage_flag"] is not True:  # 3 of 4 scored = 0.75 < COVERAGE_FLOOR
        raise HierarchicalObjectiveError("coverage below the floor did not flag the candidate")

    frozen = FrameSetContract.from_records(base)
    altered = list(base)
    altered.append(dict(base[0], frame_index=99))
    try:
        aggregate_hierarchical_records(
            altered,
            calibration_member_ids={"toy:part_1"},
            calibration_condition_ids={"P140_V600"},
            require_complete=False,
            frame_set_contract=frozen,
        )
    except HierarchicalObjectiveError:
        pass
    else:
        raise HierarchicalObjectiveError("frame-set digest did not fail closed")

    failed = dict(base[0], status="FAIL", failure="synthetic candidate failure")
    failed_result = aggregate_hierarchical_records(
        [failed],
        calibration_member_ids={"toy:part_1"},
        calibration_condition_ids={"P140_V600"},
        require_complete=False,
    )
    if failed_result["status"] != FAILED_CANDIDATE_STATUS or failed_result["objective_value"] != FAILED_CANDIDATE_PENALTY:
        raise HierarchicalObjectiveError("failed candidate did not receive the frozen penalty")
    if failed_result["frame_rows"] or failed_result["fabricated_residuals_used"]:
        raise HierarchicalObjectiveError("failed candidate emitted fabricated residual rows")

    contract_result = validate_hierarchical_objective_contract()
    return {
        "status": "PASS_PATCH_21_4_HIERARCHICAL_ALL_OBSERVATION_OBJECTIVE_VERIFIED",
        "schema": SCHEMA,
        "schema_version": PATCH_VERSION,
        "contract_validation": contract_result,
        "checks": {
            "frame_duplication_is_weight_neutral": True,
            "track_duplication_is_weight_neutral": True,
            "replicate_duplication_is_weight_neutral": True,
            "zero_footprint_retained": True,
            "nonfinite_excluded_from_finite_statistics": True,
            "undefined_frames_excluded_with_coverage": True,
            "frame_identity_digest_is_frozen": True,
            "failed_candidates_fail_closed_without_fabricated_residuals": True,
        },
        "raw_HDF5_read": False,
        "raw_camera_images_reprocessed": False,
        "thermal_simulation_performed": False,
        "parameter_selection_performed": False,
        "model_fitting_performed": False,
        "validation_used": False,
    }


__all__ = [
    "COVERAGE_FLOOR",
    "EXCLUDED_FRAME_STATUS",
    "FAILED_CANDIDATE_STATUS",
    "PASS_STATUS",
    "UNDEFINED_FRAME_STATUS",
    "PATCH_VERSION",
    "SCHEMA",
    "H_REPEATABILITY_SCALE_PIXELS",
    "W_REPEATABILITY_SCALE_PIXELS",
    "H_METRIC_WEIGHT",
    "W_METRIC_WEIGHT",
    "FAILED_CANDIDATE_PENALTY",
    "HierarchicalObjectiveError",
    "FrameSetContract",
    "frame_identity_digest",
    "aggregate_hierarchical_records",
    "evaluate_hierarchical_objective",
    "validate_hierarchical_objective_contract",
    "run_design_only_verification",
]
