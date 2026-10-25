"""Patch 22.3.5.1 frozen association-failure revalidation.

This module is diagnostic only.  It reads the immutable Patch 22.4.3 result
artifacts, freezes the historical ``FAIL_CLOSED_DISTANCE_EXCEEDED`` population,
and optionally replays only the candidate/member/frame groups represented by
that population under Patch 22.3.5.

It deliberately does not call the Patch 22.4.3 campaign dispatcher, select
parameters, fit parameters, use held-out data, or alter the accepted thermal
numerical core.  The historical audit is treated as an input contract: a
revalidation is incomplete unless the expected 516 rows and distance bins are
present after duplicate work-unit records are reconciled.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
import zipfile

from lpbf.calibration_contract import COEFFICIENT_ORDER, Patch21GlobalParameterPolicy, member_identity
from lpbf.experiments.dataset import DatasetMember, resolve_full_coupon_members
from lpbf.experiments.current_framework import CalibrationExecutionScope, evaluate_calibration_trial
from lpbf.infrastructure import write_json
from lpbf.model.production_hw import (
    PRODUCTION_HW_DEFINITION,
    PRODUCTION_HW_SEMANTICS_VERSION,
)
from lpbf.model.laser_component_association import (
    CONTINUOUS_DISTANCE_METRIC,
    POLICY_VERSION,
)
from lpbf.patch22_4_3_parallel_coarse_calibration_execution import (
    WINDOW_CELLS,
    _coarse_design,
    _find_frame_file,
    _json_safe,
    _portable_frame_rows,
)


PATCH_VERSION = "22.3.5.1"
HISTORICAL_PATCH_VERSION = "22.3.4"
HISTORICAL_ASSOCIATION_POLICY_VERSION = "22.3.3"
EXPECTED_AUDITED_FAILURE_COUNT = 516
EXPECTED_DISTANCE_BINS = {
    "exact_sqrt2": 475,
    "exact_two": 2,
    "between_two_and_five": 4,
    "greater_than_five": 35,
}
LEGACY_DISTANCE_TOLERANCE = 1.0e-12
FROZEN_AUDIT_STATUS = "FAIL_CLOSED_DISTANCE_EXCEEDED"
RECLASSIFICATION_CLASSES = (
    "CORRECTED_BY_CONTINUOUS_DISTANCE",
    "STILL_OUTSIDE_PHYSICAL_TOLERANCE",
    "AMBIGUOUS_TIED",
    "OTHER_FAILURE",
    "REPLAY_INCOMPLETE",
)


class FrozenRevalidationError(RuntimeError):
    """Raised when the frozen diagnostic input cannot be trusted."""


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _optional_float(value: Any) -> float | None:
    return float(value) if _finite(value) else None


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _result_sources(root: str | Path) -> list[tuple[str, bytes]]:
    """Return result.json bytes from a directory or a review ZIP archive."""

    path = Path(root).expanduser().resolve()
    if path.is_dir():
        return [
            (str(item), item.read_bytes())
            for item in sorted(path.rglob("result.json"))
            if item.is_file()
        ]
    if path.is_file() and path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as archive:
            names = sorted(
                name
                for name in archive.namelist()
                if name.lower().endswith("result.json")
            )
            return [(f"{path}!{name}", archive.read(name)) for name in names]
    raise FrozenRevalidationError(
        f"partial campaign input must be a directory or .zip archive: {path}"
    )


def _decode_json(source: str, content: bytes) -> Mapping[str, Any]:
    try:
        value = json.loads(content.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FrozenRevalidationError(f"invalid JSON result artifact: {source}") from exc
    if not isinstance(value, Mapping):
        raise FrozenRevalidationError(f"result artifact is not a JSON object: {source}")
    return value


def _payload_from_result(result: Mapping[str, Any]) -> Mapping[str, Any]:
    payload = result.get("payload")
    if not isinstance(payload, Mapping):
        raise FrozenRevalidationError("result artifact is missing its payload object")
    return payload


def _candidate_id(payload: Mapping[str, Any]) -> str:
    identity = _mapping(payload.get("identity"))
    value = payload.get("candidate_id") or identity.get("parameter_point_id")
    if not str(value or "").strip():
        raise FrozenRevalidationError("historical result is missing candidate_id")
    return str(value)


def _member_identity(payload: Mapping[str, Any]) -> str:
    identity = _mapping(payload.get("identity"))
    value = payload.get("member_identity") or identity.get("member_identity")
    if not str(value or "").strip():
        raise FrozenRevalidationError("historical result is missing member_identity")
    return str(value)


def _distance_bin(distance: float) -> str:
    if math.isclose(distance, math.sqrt(2.0), rel_tol=0.0, abs_tol=LEGACY_DISTANCE_TOLERANCE):
        return "exact_sqrt2"
    if math.isclose(distance, 2.0, rel_tol=0.0, abs_tol=LEGACY_DISTANCE_TOLERANCE):
        return "exact_two"
    if distance > 2.0 + LEGACY_DISTANCE_TOLERANCE and distance <= 5.0 + LEGACY_DISTANCE_TOLERANCE:
        return "between_two_and_five"
    if distance > 5.0 + LEGACY_DISTANCE_TOLERANCE:
        return "greater_than_five"
    return "other"


def _historical_failure_rows(source: str, content: bytes) -> list[dict[str, Any]]:
    result = _decode_json(source, content)
    payload = _payload_from_result(result)
    old_semantics = str(payload.get("production_hw_semantics_version") or "")
    old_policy = str(payload.get("production_hw_association_policy_version") or "")
    if old_semantics != HISTORICAL_PATCH_VERSION or old_policy != HISTORICAL_ASSOCIATION_POLICY_VERSION:
        raise FrozenRevalidationError(
            f"historical result does not carry frozen Patch 22.3.4/22.3.3 semantics: {source}"
        )

    candidate = _candidate_id(payload)
    member = _member_identity(payload)
    work_unit_id = str(payload.get("work_unit_id") or "")
    evaluation = _mapping(payload.get("atomic_failure_evaluation"))
    observations = evaluation.get("observations")
    if not isinstance(observations, Sequence) or isinstance(observations, (str, bytes)):
        return []

    result_hash = _sha256_bytes(content)
    rows: list[dict[str, Any]] = []
    for observation in observations:
        observation_map = _mapping(observation)
        diagnostics = _mapping(observation_map.get("observation_diagnostics"))
        if diagnostics.get("production_hw_association_status") != FROZEN_AUDIT_STATUS:
            continue
        distance = _optional_float(
            diagnostics.get("production_hw_association_min_distance_cells")
        )
        if distance is None:
            raise FrozenRevalidationError(
                f"historical association failure has no finite distance: {source}"
            )
        frame_value = observation_map.get("frame_index", diagnostics.get("frame_index"))
        row_value = observation_map.get(
            "mapped_process_row", diagnostics.get("mapped_process_row")
        )
        try:
            frame_index = int(frame_value)
            process_row = int(row_value)
        except (TypeError, ValueError) as exc:
            raise FrozenRevalidationError(
                f"historical association failure has malformed frame identity: {source}"
            ) from exc
        rows.append(
            {
                "source": source,
                "result_sha256": result_hash,
                "work_unit_id": work_unit_id,
                "candidate_id": candidate,
                "member_identity": member,
                "frame_index": frame_index,
                "mapped_process_row": process_row,
                "old_status": FROZEN_AUDIT_STATUS,
                "old_association_policy_version": old_policy,
                "old_production_hw_semantics_version": old_semantics,
                "old_distance_cells": distance,
                "old_distance_bin": _distance_bin(distance),
                "old_distance_metric": diagnostics.get(
                    "production_hw_association_distance_metric"
                ),
                "old_source_center_x_mm": _optional_float(
                    diagnostics.get("source_center_local_x_mm")
                ),
                "old_source_center_y_mm": _optional_float(
                    diagnostics.get("source_center_local_y_mm")
                ),
                "old_peak_surface_radial_distance_mm": _optional_float(
                    diagnostics.get("peak_surface_radial_distance_from_laser_mm")
                ),
                "old_cell_spacing_um": _optional_float(diagnostics.get("cell_spacing_um")),
                "old_liquidus_component_count": diagnostics.get("liquidus_component_count"),
                "old_boundary_contact": diagnostics.get(
                    "liquidus_contour_boundary_contact"
                ),
            }
        )
    return rows


def _deduplicate_rows(rows: Iterable[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    unique: dict[tuple[str, str, int, int], dict[str, Any]] = {}
    duplicates: list[dict[str, Any]] = []
    for raw in rows:
        row = dict(raw)
        key = (
            str(row["candidate_id"]),
            str(row["member_identity"]),
            int(row["frame_index"]),
            int(row["mapped_process_row"]),
        )
        existing = unique.get(key)
        if existing is None:
            unique[key] = row
            continue
        if not math.isclose(
            float(existing["old_distance_cells"]),
            float(row["old_distance_cells"]),
            rel_tol=0.0,
            abs_tol=LEGACY_DISTANCE_TOLERANCE,
        ):
            raise FrozenRevalidationError(
                f"conflicting duplicate historical failure for {key}"
            )
        duplicates.append(
            {
                "key": list(key),
                "kept_source": existing["source"],
                "duplicate_source": row["source"],
            }
        )
    return sorted(
        unique.values(),
        key=lambda row: (
            str(row["member_identity"]),
            str(row["candidate_id"]),
            int(row["frame_index"]),
            int(row["mapped_process_row"]),
        ),
    ), duplicates


def _distance_bin_counts(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts = {key: 0 for key in (*EXPECTED_DISTANCE_BINS.keys(), "other")}
    for row in rows:
        counts[str(row["old_distance_bin"])] += 1
    return counts


def freeze_historical_audit(
    partial_run_input: str | Path,
    *,
    expected_failure_count: int = EXPECTED_AUDITED_FAILURE_COUNT,
    expected_distance_bins: Mapping[str, int] = EXPECTED_DISTANCE_BINS,
) -> dict[str, Any]:
    """Extract and validate the immutable historical failure population."""

    sources = _result_sources(partial_run_input)
    all_rows: list[dict[str, Any]] = []
    source_summaries: list[dict[str, Any]] = []
    for source, content in sources:
        rows = _historical_failure_rows(source, content)
        source_summaries.append(
            {
                "source": source,
                "sha256": _sha256_bytes(content),
                "historical_failure_row_count": len(rows),
            }
        )
        all_rows.extend(rows)
    rows, duplicates = _deduplicate_rows(all_rows)
    observed_bins = _distance_bin_counts(rows)
    failures: list[str] = []
    if len(rows) != int(expected_failure_count):
        failures.append(
            f"expected {expected_failure_count} unique historical failures, found {len(rows)}"
        )
    for key, expected in expected_distance_bins.items():
        observed = int(observed_bins.get(key, 0))
        if observed != int(expected):
            failures.append(
                f"distance bin {key} expected {expected}, found {observed}"
            )
    if observed_bins.get("other", 0):
        failures.append(
            f"historical distance bin 'other' contains {observed_bins['other']} rows"
        )
    candidate_counts: dict[str, int] = {}
    member_counts: dict[str, int] = {}
    for row in rows:
        candidate_counts[str(row["candidate_id"])] = candidate_counts.get(
            str(row["candidate_id"]), 0
        ) + 1
        member_counts[str(row["member_identity"])] = member_counts.get(
            str(row["member_identity"]), 0
        ) + 1
    return {
        "schema": "lpbf_patch22_3_5_1_frozen_historical_association_audit",
        "schema_version": PATCH_VERSION,
        "status": (
            "PASS_PATCH_22_3_5_1_FROZEN_AUDIT_INPUT"
            if not failures
            else "FAIL_PATCH_22_3_5_1_FROZEN_AUDIT_INPUT"
        ),
        "source_input": str(Path(partial_run_input).expanduser().resolve()),
        "source_result_file_count": len(sources),
        "source_summaries": source_summaries,
        "expected_failure_count": int(expected_failure_count),
        "observed_unique_failure_count": len(rows),
        "expected_distance_bins": dict(expected_distance_bins),
        "observed_distance_bins": observed_bins,
        "candidate_counts": dict(sorted(candidate_counts.items())),
        "member_counts": dict(sorted(member_counts.items())),
        "duplicate_row_count": len(duplicates),
        "duplicates": duplicates,
        "failures": failures,
        "historical_failures": rows,
        "calibration_search_authorized": False,
        "parameter_selection_performed": False,
        "parameter_fitting_performed": False,
        "validation_partition_used": False,
        "full_campaign_dispatched": False,
    }


def _finite_hw(observation: Mapping[str, Any], diagnostics: Mapping[str, Any]) -> bool:
    values = (
        observation.get("simulated_H_pixels"),
        observation.get("simulated_W_pixels"),
        diagnostics.get("production_hw_simulated_H_pixels"),
        diagnostics.get("production_hw_simulated_W_pixels"),
    )
    pairs = ((values[0], values[1]), (values[2], values[3]))
    return any(_finite(h) and _finite(w) for h, w in pairs)


def classify_replay_observation(
    observation: Mapping[str, Any] | None,
    *,
    historical_row: Mapping[str, Any],
) -> dict[str, Any]:
    """Classify one historical failure against one Patch 22.3.5 observation."""

    base = {
        "candidate_id": historical_row["candidate_id"],
        "member_identity": historical_row["member_identity"],
        "frame_index": int(historical_row["frame_index"]),
        "mapped_process_row": int(historical_row["mapped_process_row"]),
        "old_distance_cells": historical_row["old_distance_cells"],
        "old_distance_bin": historical_row["old_distance_bin"],
    }
    if observation is None:
        return {
            **base,
            "reclassification": "REPLAY_INCOMPLETE",
            "reclassification_reason": "target_frame_missing_from_replay_output",
            "new_status": None,
            "new_distance_metric": None,
            "new_distance_cells": None,
            "new_distance_mm": None,
            "new_selection_mode": None,
            "new_finite_hw": False,
            "new_boundary_contact": None,
        }

    diagnostics = _mapping(observation.get("observation_diagnostics"))
    status = str(diagnostics.get("production_hw_association_status") or "")
    metric = diagnostics.get("production_hw_association_distance_metric")
    boundary_contact = diagnostics.get("liquidus_contour_boundary_contact")
    finite_hw = _finite_hw(observation, diagnostics)
    if status == "SELECTED" and metric == CONTINUOUS_DISTANCE_METRIC:
        if boundary_contact is True:
            classification = "OTHER_FAILURE"
            reason = "selected_component_touches_computational_boundary"
        elif not finite_hw:
            classification = "OTHER_FAILURE"
            reason = "selected_component_did_not_produce_finite_hw"
        else:
            classification = "CORRECTED_BY_CONTINUOUS_DISTANCE"
            reason = "continuous_metric_selected_finite_enclosed_component"
    elif status == "FAIL_CLOSED_DISTANCE_EXCEEDED":
        classification = "STILL_OUTSIDE_PHYSICAL_TOLERANCE"
        reason = "continuous_metric_remains_outside_one_cell_radius"
    elif status == "FAIL_CLOSED_TIED_NEAREST":
        classification = "AMBIGUOUS_TIED"
        reason = "continuous_metric_retains_tied_nearest_components"
    else:
        classification = "OTHER_FAILURE"
        reason = status or "new_observation_diagnostics_missing_association_status"
    return {
        **base,
        "reclassification": classification,
        "reclassification_reason": reason,
        "new_status": status or None,
        "new_distance_metric": metric,
        "new_distance_cells": _optional_float(
            diagnostics.get("production_hw_association_min_distance_cells")
        ),
        "new_distance_mm": _optional_float(
            diagnostics.get("production_hw_association_min_distance_mm")
        ),
        "new_selection_mode": diagnostics.get("production_hw_association_mode"),
        "new_finite_hw": finite_hw,
        "new_boundary_contact": boundary_contact,
        "new_component_status": diagnostics.get("production_hw_component_status"),
        "new_source_center_x_mm": _optional_float(
            diagnostics.get("source_center_local_x_mm")
        ),
        "new_source_center_y_mm": _optional_float(
            diagnostics.get("source_center_local_y_mm")
        ),
    }


def summarize_reclassification(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    counts = {key: 0 for key in RECLASSIFICATION_CLASSES}
    sqrt2_counts = {key: 0 for key in RECLASSIFICATION_CLASSES}
    for row in rows:
        classification = str(row.get("reclassification"))
        counts[classification] = counts.get(classification, 0) + 1
        if row.get("old_distance_bin") == "exact_sqrt2":
            sqrt2_counts[classification] = sqrt2_counts.get(classification, 0) + 1
    return {
        "total_reclassified_rows": len(rows),
        "counts": counts,
        "sqrt2_total": sum(sqrt2_counts.values()),
        "sqrt2_counts": sqrt2_counts,
        "corrected_by_continuous_distance": counts.get(
            "CORRECTED_BY_CONTINUOUS_DISTANCE", 0
        ),
        "remaining_remote_or_nonlocal": counts.get(
            "STILL_OUTSIDE_PHYSICAL_TOLERANCE", 0
        ),
        "ambiguous_or_other": counts.get("AMBIGUOUS_TIED", 0)
        + counts.get("OTHER_FAILURE", 0)
        + counts.get("REPLAY_INCOMPLETE", 0),
    }


def _candidate_coordinates() -> dict[str, dict[str, float]]:
    design = _coarse_design()
    return {
        str(row["candidate_id"]): {
            name: float(row["coordinates"][name]) for name in COEFFICIENT_ORDER
        }
        for row in design["search_design"]["candidates"]
    }


def _member_map(data_directory: str | Path) -> dict[str, DatasetMember]:
    members = resolve_full_coupon_members(Path(data_directory).expanduser().resolve())
    return {
        member_identity(member.acquisition_set_id, member.coupon_position): member
        for member in members
    }


def _targeted_scope(
    *,
    candidate_id: str,
    member: DatasetMember,
    frame_indices: Sequence[int],
    source_audit_digest: str,
) -> CalibrationExecutionScope:
    coordinates = _candidate_coordinates()[candidate_id]
    return CalibrationExecutionScope(
        scope_id=f"patch22_3_5_1:frozen_revalidation:{candidate_id}:{member_identity(member.acquisition_set_id, member.coupon_position)}",
        observation_frame_indices=tuple(sorted(set(int(value) for value in frame_indices))),
        trial_context={
            "patch": PATCH_VERSION,
            "objective_branch": "frozen_association_failure_revalidation",
            "candidate_id": candidate_id,
            "candidate_coordinates": coordinates,
            "source_audit_digest": source_audit_digest,
            "production_hw_definition": PRODUCTION_HW_DEFINITION,
            "production_hw_semantics_version": PRODUCTION_HW_SEMANTICS_VERSION,
            "production_hw_association_policy_version": POLICY_VERSION,
            "validation_partition_used": False,
            "parameter_selection_performed": False,
            "parameter_fitting_performed": False,
            "full_campaign_dispatched": False,
        },
        unenclosed_contour_policy="record_nan",
        window_cells=WINDOW_CELLS,
    )


def _replay_group(
    *,
    member: DatasetMember,
    candidate_id: str,
    historical_rows: Sequence[Mapping[str, Any]],
    characterization_directory: str | Path,
    source_audit_digest: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    member_id = member_identity(member.acquisition_set_id, member.coupon_position)
    frame_path = _find_frame_file(
        Path(characterization_directory).expanduser().resolve(), member
    )
    frame_rows = _portable_frame_rows(frame_path, member)
    eligible = {
        int(row["frame_index"]): bool(row.get("observation_eligible"))
        for row in frame_rows
    }
    requested = sorted({int(row["frame_index"]) for row in historical_rows})
    missing = [frame for frame in requested if not eligible.get(frame, False)]
    if missing:
        raise FrozenRevalidationError(
            f"historical target frames are not eligible in {frame_path}: {missing[:8]}"
        )
    coordinates = _candidate_coordinates()
    if candidate_id not in coordinates:
        raise FrozenRevalidationError(f"candidate is not in the frozen coarse design: {candidate_id}")
    policy = Patch21GlobalParameterPolicy.from_values(
        *(float(coordinates[candidate_id][name]) for name in COEFFICIENT_ORDER)
    )
    scope = _targeted_scope(
        candidate_id=candidate_id,
        member=member,
        frame_indices=requested,
        source_audit_digest=source_audit_digest,
    )
    evaluation = evaluate_calibration_trial(member, policy, scope).to_dict()
    observations = {
        int(item["frame_index"]): item
        for item in list(evaluation.get("observations") or [])
        if isinstance(item, Mapping) and item.get("frame_index") is not None
    }
    rows = [
        classify_replay_observation(observations.get(int(historical["frame_index"])), historical_row=historical)
        for historical in historical_rows
    ]
    return rows, {
        "candidate_id": candidate_id,
        "member_identity": member_id,
        "frame_path": str(frame_path),
        "requested_frame_count": len(requested),
        "returned_frame_count": len(observations),
        "evaluation_status": evaluation.get("status"),
        "evaluation_stage": evaluation.get("stage"),
        "evaluation_failure": evaluation.get("failure"),
        "thermal_execution_performed": True,
    }


def run_frozen_reference_panel(
    *,
    reference_path: str | Path,
    data_directory: str | Path,
    characterization_directory: str | Path,
) -> dict[str, Any]:
    """Replay the frozen 16-case Patch 22.3.x production-H/W reference panel.

    Strict-center and zero-footprint cases are invariance gates: their selected
    component and H/W must remain unchanged.  Fallback cases are retained as
    diagnostic records because the continuous metric is precisely the behavior
    being revalidated there.
    """

    path = Path(reference_path).expanduser().resolve()
    try:
        reference = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FrozenRevalidationError(f"cannot read frozen reference panel: {path}") from exc
    if not isinstance(reference, Mapping):
        raise FrozenRevalidationError("frozen reference panel is not a JSON object")
    rows = reference.get("rows")
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        raise FrozenRevalidationError("frozen reference panel has no rows")
    if int(reference.get("case_count", len(rows))) != 16 or len(rows) != 16:
        raise FrozenRevalidationError(
            f"frozen reference panel must contain 16 cases, found {len(rows)}"
        )
    if int(reference.get("production_window_cells", WINDOW_CELLS)) != WINDOW_CELLS:
        raise FrozenRevalidationError("frozen reference panel is not the 99-cell production window")

    members = _member_map(data_directory)
    coordinates = _candidate_coordinates()
    characterization_path = Path(characterization_directory).expanduser().resolve()
    records: list[dict[str, Any]] = []
    failures: list[str] = []
    for raw in rows:
        row = _mapping(raw)
        case_index = int(row["case_index"])
        candidate_id = str(row["candidate_id"])
        member_id = str(row["member_identity"])
        frame_index = int(row["frame_index"])
        member = members.get(member_id)
        if member is None:
            failures.append(f"case {case_index}: missing dataset member {member_id}")
            continue
        if candidate_id not in coordinates:
            failures.append(f"case {case_index}: missing candidate {candidate_id}")
            continue
        frame_path = _find_frame_file(characterization_path, member)
        frame_rows = _portable_frame_rows(frame_path, member)
        frame_row = next(
            (item for item in frame_rows if int(item["frame_index"]) == frame_index),
            None,
        )
        if frame_row is None or not bool(frame_row.get("observation_eligible")):
            failures.append(f"case {case_index}: frame {frame_index} is not eligible")
            continue
        policy = Patch21GlobalParameterPolicy.from_values(
            *(float(coordinates[candidate_id][name]) for name in COEFFICIENT_ORDER)
        )
        scope = CalibrationExecutionScope(
            scope_id=f"patch22_3_5_1:reference_panel:case_{case_index}",
            observation_frame_indices=(frame_index,),
            trial_context={
                "patch": PATCH_VERSION,
                "objective_branch": "frozen_patch22_3_x_reference_panel",
                "reference_case_index": case_index,
                "candidate_id": candidate_id,
                "candidate_coordinates": coordinates[candidate_id],
                "production_hw_definition": PRODUCTION_HW_DEFINITION,
                "production_hw_semantics_version": PRODUCTION_HW_SEMANTICS_VERSION,
                "production_hw_association_policy_version": POLICY_VERSION,
                "validation_partition_used": False,
                "parameter_selection_performed": False,
                "parameter_fitting_performed": False,
                "full_campaign_dispatched": False,
            },
            unenclosed_contour_policy="record_nan",
            window_cells=WINDOW_CELLS,
        )
        evaluation = evaluate_calibration_trial(member, policy, scope).to_dict()
        observation = next(
            (
                item
                for item in list(evaluation.get("observations") or [])
                if int(item.get("frame_index", -1)) == frame_index
            ),
            None,
        )
        diagnostics = _mapping(
            None if observation is None else observation.get("observation_diagnostics")
        )
        observed_h = None if observation is None else _optional_float(
            observation.get("simulated_H_pixels")
        )
        observed_w = None if observation is None else _optional_float(
            observation.get("simulated_W_pixels")
        )
        expected_h = _optional_float(row.get("simulated_H_pixels"))
        expected_w = _optional_float(row.get("simulated_W_pixels"))
        strict_case = str(row.get("production_hw_association_mode") or "") == "strict_center"
        zero_case = expected_h == 0.0 and expected_w == 0.0
        record = {
            "case_index": case_index,
            "candidate_id": candidate_id,
            "member_identity": member_id,
            "frame_index": frame_index,
            "mapped_process_row": int(row["mapped_process_row"]),
            "historical_mode": row.get("production_hw_association_mode"),
            "invariance_gate": "strict_center_or_zero_footprint" if strict_case or zero_case else "fallback_diagnostic",
            "expected_H_pixels": expected_h,
            "expected_W_pixels": expected_w,
            "observed_H_pixels": observed_h,
            "observed_W_pixels": observed_w,
            "observed_association_status": diagnostics.get(
                "production_hw_association_status"
            ),
            "observed_association_mode": diagnostics.get(
                "production_hw_association_mode"
            ),
            "observed_distance_metric": diagnostics.get(
                "production_hw_association_distance_metric"
            ),
            "observed_distance_cells": _optional_float(
                diagnostics.get("production_hw_association_min_distance_cells")
            ),
            "observed_boundary_contact": diagnostics.get(
                "liquidus_contour_boundary_contact"
            ),
            "evaluation_status": evaluation.get("status"),
            "evaluation_stage": evaluation.get("stage"),
        }
        records.append(record)
        if observation is None:
            failures.append(f"case {case_index}: replay did not emit frame {frame_index}")
            continue
        if diagnostics.get("production_hw_definition") != PRODUCTION_HW_DEFINITION:
            failures.append(f"case {case_index}: production H/W definition drifted")
        if diagnostics.get("production_hw_semantics_version") != PRODUCTION_HW_SEMANTICS_VERSION:
            failures.append(f"case {case_index}: production H/W semantics version drifted")
        if diagnostics.get("production_hw_association_policy_version") != POLICY_VERSION:
            failures.append(f"case {case_index}: association policy version drifted")
        if diagnostics.get("production_hw_association_distance_metric") != CONTINUOUS_DISTANCE_METRIC:
            failures.append(f"case {case_index}: continuous distance metric missing")
        if strict_case:
            if diagnostics.get("production_hw_association_mode") != "strict_center":
                failures.append(f"case {case_index}: strict-center association changed")
            if observed_h is None or observed_w is None:
                failures.append(f"case {case_index}: strict-center H/W is nonfinite")
            elif not (
                math.isclose(observed_h, float(expected_h), rel_tol=0.0, abs_tol=1.0e-9)
                and math.isclose(observed_w, float(expected_w), rel_tol=0.0, abs_tol=1.0e-9)
            ):
                failures.append(f"case {case_index}: strict-center H/W changed")
        elif zero_case:
            if diagnostics.get("production_hw_association_status") != "ZERO_FOOTPRINT":
                failures.append(f"case {case_index}: zero-footprint status changed")
            if observed_h != 0.0 or observed_w != 0.0:
                failures.append(f"case {case_index}: zero-footprint H/W changed")

    return {
        "schema": "lpbf_patch22_3_5_1_frozen_reference_panel",
        "schema_version": PATCH_VERSION,
        "status": (
            "PASS_PATCH_22_3_5_1_FROZEN_REFERENCE_PANEL"
            if not failures
            else "FAIL_PATCH_22_3_5_1_FROZEN_REFERENCE_PANEL"
        ),
        "reference_path": str(path),
        "case_count": len(records),
        "records": records,
        "failures": failures,
        "production_hw_definition": PRODUCTION_HW_DEFINITION,
        "production_hw_semantics_version": PRODUCTION_HW_SEMANTICS_VERSION,
        "production_hw_association_policy_version": POLICY_VERSION,
        "window_cells": WINDOW_CELLS,
        "thermal_execution_performed": True,
        "calibration_search_authorized": False,
        "parameter_selection_performed": False,
        "parameter_fitting_performed": False,
        "validation_partition_used": False,
        "full_campaign_dispatched": False,
    }


def _source_audit_digest(frozen: Mapping[str, Any]) -> str:
    material = {
        "source_summaries": frozen.get("source_summaries"),
        "observed_unique_failure_count": frozen.get("observed_unique_failure_count"),
        "observed_distance_bins": frozen.get("observed_distance_bins"),
    }
    return hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def run_frozen_revalidation(
    *,
    partial_run_input: str | Path,
    output_directory: str | Path,
    data_directory: str | Path | None = None,
    characterization_directory: str | Path | None = None,
    run_live: bool = False,
) -> dict[str, Any]:
    """Freeze the audit and optionally replay only its historical targets."""

    output = Path(output_directory).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    frozen = freeze_historical_audit(partial_run_input)
    frozen_path = output / "PATCH_22_3_5_1_FROZEN_FAILURE_MANIFEST.json"
    write_json(frozen_path, _json_safe(frozen))

    report: dict[str, Any] = {
        "schema": "lpbf_patch22_3_5_1_frozen_revalidation",
        "schema_version": PATCH_VERSION,
        "status": frozen["status"],
        "patch": PATCH_VERSION,
        "historical_patch_semantics": HISTORICAL_PATCH_VERSION,
        "active_production_hw_semantics_version": PRODUCTION_HW_SEMANTICS_VERSION,
        "active_association_policy_version": POLICY_VERSION,
        "active_distance_metric": CONTINUOUS_DISTANCE_METRIC,
        "production_hw_definition": PRODUCTION_HW_DEFINITION,
        "window_cells": WINDOW_CELLS,
        "frozen_failure_manifest": str(frozen_path),
        "run_live": bool(run_live),
        "calibration_search_authorized": False,
        "parameter_selection_performed": False,
        "parameter_fitting_performed": False,
        "validation_partition_used": False,
        "full_campaign_dispatched": False,
        "groups": [],
        "reclassification": None,
        "failures": list(frozen.get("failures") or []),
    }
    if frozen["status"] != "PASS_PATCH_22_3_5_1_FROZEN_AUDIT_INPUT":
        report["status"] = "FAIL_PATCH_22_3_5_1_FROZEN_REVALIDATION_INPUT"
        report_path = output / "PATCH_22_3_5_1_FROZEN_REVALIDATION_REPORT.json"
        write_json(report_path, _json_safe(report))
        report["report_path"] = str(report_path)
        return report
    if not run_live:
        report["status"] = "PASS_PATCH_22_3_5_1_FROZEN_AUDIT_INPUT"
        report_path = output / "PATCH_22_3_5_1_FROZEN_REVALIDATION_REPORT.json"
        write_json(report_path, _json_safe(report))
        report["report_path"] = str(report_path)
        return report
    if data_directory is None or characterization_directory is None:
        raise FrozenRevalidationError(
            "data_directory and characterization_directory are required for live revalidation"
        )

    members = _member_map(data_directory)
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in frozen["historical_failures"]:
        key = (str(row["candidate_id"]), str(row["member_identity"]))
        groups.setdefault(key, []).append(dict(row))
    audit_digest = _source_audit_digest(frozen)
    all_reclassified: list[dict[str, Any]] = []
    group_reports: list[dict[str, Any]] = []
    for (candidate_id, member_id), historical_rows in sorted(groups.items()):
        member = members.get(member_id)
        if member is None:
            raise FrozenRevalidationError(
                f"historical failure member is missing from the current dataset: {member_id}"
            )
        reclassified, group_report = _replay_group(
            member=member,
            candidate_id=candidate_id,
            historical_rows=historical_rows,
            characterization_directory=characterization_directory,
            source_audit_digest=audit_digest,
        )
        all_reclassified.extend(reclassified)
        group_reports.append(
            {
                **group_report,
                "historical_failure_count": len(historical_rows),
                "reclassification": summarize_reclassification(reclassified),
            }
        )
    report["groups"] = group_reports
    report["reclassification"] = summarize_reclassification(all_reclassified)
    report["status"] = (
        "PASS_PATCH_22_3_5_1_FROZEN_REVALIDATION"
        if not any(
            row["reclassification"] in {"REPLAY_INCOMPLETE", "OTHER_FAILURE"}
            for row in all_reclassified
        )
        else "FAIL_PATCH_22_3_5_1_FROZEN_REVALIDATION"
    )
    if len(all_reclassified) != EXPECTED_AUDITED_FAILURE_COUNT:
        report["status"] = "FAIL_PATCH_22_3_5_1_FROZEN_REVALIDATION"
        report["failures"].append(
            f"reclassified {len(all_reclassified)} rows instead of {EXPECTED_AUDITED_FAILURE_COUNT}"
        )
    report["reclassification_rows"] = all_reclassified
    csv_path = output / "PATCH_22_3_5_1_RECLASSIFICATION.csv"
    if all_reclassified:
        fields = sorted({key for row in all_reclassified for key in row})
        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(all_reclassified)
    report["reclassification_csv"] = str(csv_path)
    report_path = output / "PATCH_22_3_5_1_FROZEN_REVALIDATION_REPORT.json"
    write_json(report_path, _json_safe(report))
    report["report_path"] = str(report_path)
    return report


__all__ = [
    "EXPECTED_AUDITED_FAILURE_COUNT",
    "EXPECTED_DISTANCE_BINS",
    "FrozenRevalidationError",
    "HISTORICAL_ASSOCIATION_POLICY_VERSION",
    "HISTORICAL_PATCH_VERSION",
    "PATCH_VERSION",
    "classify_replay_observation",
    "freeze_historical_audit",
    "run_frozen_reference_panel",
    "run_frozen_revalidation",
    "summarize_reclassification",
]
