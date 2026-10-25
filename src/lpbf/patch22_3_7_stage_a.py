"""Patch 22.3.7 Stage A: re-run the 22.3.6 census units under the new semantics.

Evaluates the Stage-A candidates on the two July members with association
policy 22.3.7 (beam-power share), the scored-frame rule (F1) and the
``record_undefined`` observation policy (F3), builds frame records exactly as
the campaign worker would, computes per-candidate coverage and a partial
(two-member) hierarchical objective, and verifies the production outcome of
every scored frame against the beam-share rule evaluated offline on the Patch
22.3.6 census telemetry.  No campaign is dispatched; nothing is fitted or
selected; the result is a recovery check, not a calibration.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from lpbf.calibration_contract import COEFFICIENT_ORDER, Patch21GlobalParameterPolicy, member_identity, validation_member_identities
from lpbf.execution.parallel import execute_parallel_jobs
from lpbf.execution.work_units import SimulationJob, SimulationResult, execute_serial_jobs
from lpbf.experiments.current_framework import CalibrationExecutionScope, evaluate_calibration_trial
from lpbf.experiments.dataset import DatasetMember
from lpbf.hierarchical_objective import COVERAGE_FLOOR, HierarchicalObjectiveError, aggregate_hierarchical_records
from lpbf.infrastructure import write_json
from lpbf.model.laser_component_association import (
    BEAM_SHARE_FLOOR,
    NO_LASER_ASSOCIATED_MELT_STATUS,
    POLICY_VERSION,
)
from lpbf.model.production_hw import PRODUCTION_HW_DEFINITION, PRODUCTION_HW_SEMANTICS_VERSION
from lpbf.patch22_3_5_1_frozen_revalidation import _candidate_coordinates, _member_map
from lpbf.patch22_3_6_association_census import (
    STAGE_A_CANDIDATES,
    STAGE_A_MEMBERS,
    UNDEFINED_STATUSES as CENSUS_UNDEFINED_STATUSES,
    _load_census,
    evaluate_beam_share_rule,
)
from lpbf.patch22_4_3_parallel_coarse_calibration_execution import (
    UNDEFINED_OBSERVATION_POLICY,
    WINDOW_CELLS,
    _dataset_member_context,
    _dataset_member_from_context,
    _find_frame_file,
    _frame_records_from_evaluation,
    _json_safe,
    _portable_frame_rows,
)
from lpbf.scored_frame_rule import SCORED_FRAME_RULE_VERSION, apply_scored_frame_rule, scored_frame_indices

PATCH_VERSION = "22.3.7"
STAGE_A_SCHEMA = "lpbf_patch22_3_7_stage_a_recovery"
STAGE_A_STATUS_PASS = "PASS_PATCH_22_3_7_STAGE_A_COMPLETE"
STAGE_A_STATUS_FAIL = "FAIL_PATCH_22_3_7_STAGE_A_INCOMPLETE"
DEFAULT_WORKERS = 4
REPORT_NAME = "PATCH_22_3_7_STAGE_A_REPORT.json"
FRAMES_CSV_NAME = "PATCH_22_3_7_STAGE_A_FRAMES.csv"
CENSUS_CHECK_NAME = "PATCH_22_3_7_CENSUS_PREDICTION_CHECK.json"
CENSUS_REPORT_NAME = "PATCH_22_3_6_ASSOCIATION_CENSUS_REPORT.json"

ProgressCallback = Callable[[int, int, Mapping[str, Any]], None]

_PREDICTED_PRODUCTION_STATUS = {
    "SELECTED": "SELECTED",
    "ZERO_FOOTPRINT": "ZERO_FOOTPRINT",
    "NO_LASER_ASSOCIATED_MELT": NO_LASER_ASSOCIATED_MELT_STATUS,
    "AMBIGUOUS": "FAIL_CLOSED_TIED_SHARE",
    "UNENCLOSED": "SELECTED",
    "DEGENERATE": "SELECTED",
}


class StageAError(RuntimeError):
    """Raised when the Stage-A input or execution cannot be trusted."""


def _validated_workers(workers: Any) -> int:
    if isinstance(workers, bool) or not isinstance(workers, int) or workers < 1:
        raise StageAError("workers must be a positive integer")
    return workers


def build_stage_a_jobs(
    units: Sequence[tuple[str, str]],
    members: Mapping[str, DatasetMember],
    frame_rows_by_member: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    characterization_directory: str | Path,
) -> tuple[SimulationJob, ...]:
    """One spawn-safe job per (candidate, member) carrying the rule-labelled frame rows."""

    coordinates = _candidate_coordinates()
    characterization = str(Path(characterization_directory).expanduser().resolve())
    jobs: list[SimulationJob] = []
    for ordinal, (candidate_id, member_id) in enumerate(sorted({(str(c), str(m)) for c, m in units})):
        member = members.get(member_id)
        if member is None:
            raise StageAError(f"dataset member is missing: {member_id}")
        if candidate_id not in coordinates:
            raise StageAError(f"candidate is not in the frozen coarse design: {candidate_id}")
        rows = apply_scored_frame_rule([dict(row) for row in frame_rows_by_member.get(member_id, ())])
        scored = scored_frame_indices(rows)
        if not scored:
            raise StageAError(f"no scored frames for {member_id}")
        jobs.append(
            SimulationJob(
                case_index=ordinal,
                member_identity=member_id,
                frame_index=scored[0],
                window_cells=WINDOW_CELLS,
                candidate_coordinates=coordinates[candidate_id],
                experiment_context={
                    "candidate_id": candidate_id,
                    "dataset_member_json": json.dumps(_dataset_member_context(member)),
                    "frame_rows_json": json.dumps(rows),
                    "characterization_directory": characterization,
                },
            )
        )
    return tuple(jobs)


def _stage_a_scope(candidate_id: str, member: DatasetMember, frames: Sequence[int]) -> CalibrationExecutionScope:
    coordinates = _candidate_coordinates()[candidate_id]
    return CalibrationExecutionScope(
        scope_id=f"patch22_3_7:stage_a:{candidate_id}:{member_identity(member.acquisition_set_id, member.coupon_position)}",
        observation_frame_indices=tuple(sorted(set(int(value) for value in frames))),
        trial_context={
            "patch": PATCH_VERSION,
            "objective_branch": "stage_a_recovery_check",
            "candidate_id": candidate_id,
            "candidate_coordinates": coordinates,
            "production_hw_definition": PRODUCTION_HW_DEFINITION,
            "production_hw_semantics_version": PRODUCTION_HW_SEMANTICS_VERSION,
            "production_hw_association_policy_version": POLICY_VERSION,
            "scored_frame_rule_version": SCORED_FRAME_RULE_VERSION,
            "undefined_observation_policy": UNDEFINED_OBSERVATION_POLICY,
            "validation_partition_used": False,
            "parameter_selection_performed": False,
            "parameter_fitting_performed": False,
            "full_campaign_dispatched": False,
        },
        unenclosed_contour_policy="record_nan",
        window_cells=WINDOW_CELLS,
        undefined_observation_policy=UNDEFINED_OBSERVATION_POLICY,
    )


def _annotate_frame_records(records: Sequence[dict[str, Any]], evaluation: Mapping[str, Any]) -> None:
    """Attach production-association telemetry from the evaluator's observations to each frame record.

    The evaluator's own per-frame status (``SCORED`` / ``UNDEFINED_<reason>``) is stored as
    ``evaluator_observation_status``. ``observation_status`` belongs to the experimental side of the
    frame row (``ELIGIBLE_FINITE_HW`` ...) and is what the hierarchical objective validates; it must
    not be overwritten here.
    """

    observations = {
        int(item["frame_index"]): item
        for item in list(evaluation.get("observations") or [])
        if isinstance(item, Mapping) and item.get("frame_index") is not None
    }
    for record in records:
        observation = observations.get(int(record["frame_index"])) if record.get("status") in ("PASS", "UNDEFINED") else None
        diagnostics = (observation or {}).get("observation_diagnostics") or {}
        record.update(
            {
                "production_status": diagnostics.get("production_hw_association_status"),
                "production_mode": diagnostics.get("production_hw_association_mode"),
                "production_selected_label": diagnostics.get("production_hw_association_selected_label"),
                "production_beam_share": diagnostics.get("production_hw_association_beam_share"),
                "production_contains_beam_cell": diagnostics.get("production_hw_association_contains_beam_cell"),
                "production_component_status": diagnostics.get("production_hw_component_status"),
                "melt_classification": None if observation is None else observation.get("melt_classification"),
                "evaluator_observation_status": None if observation is None else observation.get("observation_status"),
            }
        )


def _stage_a_unit_job(job: SimulationJob) -> dict[str, Any]:
    """Spawn-safe worker: one candidate on one member under the 22.3.7 semantics."""

    context = job.experiment_context_dict
    candidate_id = str(context["candidate_id"])
    member = _dataset_member_from_context(json.loads(context["dataset_member_json"]))
    rows = json.loads(context["frame_rows_json"])
    scored = scored_frame_indices(rows)
    coordinates = _candidate_coordinates()[candidate_id]
    base = {
        "schema": STAGE_A_SCHEMA,
        "patch": PATCH_VERSION,
        "candidate_id": candidate_id,
        "member_identity": member_identity(member.acquisition_set_id, member.coupon_position),
        "candidate_coordinates": coordinates,
        "requested_frame_count": len(scored),
        "production_hw_semantics_version": PRODUCTION_HW_SEMANTICS_VERSION,
        "production_hw_association_policy_version": POLICY_VERSION,
        "thermal_execution_performed": True,
    }
    policy = Patch21GlobalParameterPolicy.from_values(*(float(coordinates[name]) for name in COEFFICIENT_ORDER))
    scope = _stage_a_scope(candidate_id, member, scored)
    try:
        evaluation = evaluate_calibration_trial(member, policy, scope).to_dict()
    except Exception as exc:  # fail closed: no frames are fabricated for a unit that did not evaluate
        failed = []
        for row in rows:
            record = dict(row)
            record["status"] = "FAIL"
            record["failure"] = {"code": "PATCH_22_3_7_WORKER_EXCEPTION", "type": type(exc).__name__, "message": str(exc)}
            failed.append(record)
        return {
            **base,
            "returned_frame_count": 0,
            "frame_records": failed,
            "gate_failures": ["worker_exception"],
            "evaluation_status": "EXCEPTION",
            "evaluation_stage": "stage_a_worker",
            "evaluation_failure": {"type": type(exc).__name__, "message": str(exc)},
        }
    records, gate_failures = _frame_records_from_evaluation(
        evaluation, base_rows=rows, undefined_observation_policy=UNDEFINED_OBSERVATION_POLICY
    )
    _annotate_frame_records(records, evaluation)
    telemetry = evaluation.get("execution_telemetry") or {}
    return {
        **base,
        "returned_frame_count": sum(1 for row in records if row.get("status") in ("PASS", "UNDEFINED") and bool(row.get("scored_frame"))),
        "frame_records": records,
        "gate_failures": list(gate_failures),
        "evaluation_status": evaluation.get("status"),
        "evaluation_stage": evaluation.get("stage"),
        "evaluation_failure": evaluation.get("failure"),
        "undefined_observation_count": telemetry.get("undefined_observation_count"),
    }


def _candidate_summary(candidate_id: str, payloads: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    records = [dict(row) for payload in payloads for row in payload.get("frame_records") or []]
    members = sorted({str(payload["member_identity"]) for payload in payloads})
    conditions = {str(row.get("exact_condition_id")) for row in records if row.get("exact_condition_id") is not None}
    counts = {
        "scored_frame_count": sum(1 for row in records if row.get("status") == "PASS" and bool(row.get("scored_frame"))),
        "undefined_frame_count": sum(1 for row in records if row.get("status") == "UNDEFINED"),
        "excluded_frame_count": sum(1 for row in records if row.get("status") == "EXCLUDED"),
        "failed_frame_count": sum(1 for row in records if row.get("status") == "FAIL"),
        "no_laser_associated_melt_count": sum(1 for row in records if row.get("production_status") == NO_LASER_ASSOCIATED_MELT_STATUS),
        "zero_footprint_count": sum(1 for row in records if row.get("production_status") == "ZERO_FOOTPRINT"),
    }
    try:
        objective = aggregate_hierarchical_records(
            records,
            calibration_member_ids=members,
            calibration_condition_ids=conditions,
            require_complete=False,
            candidate_id=candidate_id,
        )
    except HierarchicalObjectiveError as exc:
        objective = {"status": "ERROR", "error": str(exc)}
    objective_counts = objective.get("counts") or {}
    return {
        "candidate_id": candidate_id,
        "members": members,
        "objective_status": objective.get("status"),
        "objective_value_partial_two_members": objective.get("objective_value"),
        "penalty_applied": objective.get("penalty_applied"),
        "coverage_flag": objective.get("coverage_flag"),
        "coverage_by_coupon": objective_counts.get("coverage_by_coupon"),
        "coverage": objective_counts.get("coverage"),
        "low_coverage_coupons": objective.get("low_coverage_coupons"),
        "coupon_scalar_objectives": {
            str(row["member_identity"]): row.get("coupon_scalar_objective") for row in objective.get("coupon_rows") or []
        },
        "objective_error": objective.get("error"),
        **counts,
    }


def compare_with_census_prediction(
    census_directory: str | Path,
    records_by_unit: Mapping[tuple[str, str], Sequence[Mapping[str, Any]]],
    *,
    floor: float = BEAM_SHARE_FLOOR,
) -> dict[str, Any]:
    """Verify production outcomes against the beam-share rule evaluated on the 22.3.6 census telemetry."""

    _, units = _load_census(census_directory)
    census_frames = {
        (str(unit["candidate_id"]), str(unit["member_identity"])): {
            int(frame["frame_index"]): frame for frame in unit.get("frames") or []
        }
        for unit in units
    }
    compared = status_matches = hw_matches = 0
    mismatches: list[dict[str, Any]] = []
    units_compared = 0
    units_missing: list[str] = []
    for key, records in sorted(records_by_unit.items()):
        frames = census_frames.get(key)
        if frames is None:
            units_missing.append(f"{key[0]} / {key[1]}")
            continue
        units_compared += 1
        for record in records:
            if record.get("status") not in ("PASS", "UNDEFINED"):
                continue
            frame_index = int(record["frame_index"])
            identity = {"candidate_id": key[0], "member_identity": key[1], "frame_index": frame_index}
            frame = frames.get(frame_index)
            if frame is None:
                mismatches.append({**identity, "reason": "frame missing from census"})
                continue
            compared += 1
            predicted = evaluate_beam_share_rule(frame.get("census_components") or [], floor=floor)
            expected_status = _PREDICTED_PRODUCTION_STATUS[str(predicted["status"])]
            actual_status = record.get("production_status")
            if actual_status != expected_status:
                mismatches.append({**identity, "reason": "status", "predicted": predicted["status"], "actual": actual_status})
                continue
            if predicted["status"] in CENSUS_UNDEFINED_STATUSES:
                if record.get("status") != "UNDEFINED":
                    mismatches.append({**identity, "reason": "expected undefined", "predicted": predicted["status"], "actual": record.get("status")})
                else:
                    status_matches += 1
                continue
            status_matches += 1
            h, w = record.get("simulated_H_pixels"), record.get("simulated_W_pixels")
            if predicted["status"] == "SELECTED":
                if record.get("status") != "PASS" or h != predicted["scored_H_pixels"] or w != predicted["scored_W_pixels"]:
                    mismatches.append({**identity, "reason": "hw", "predicted": [predicted["scored_H_pixels"], predicted["scored_W_pixels"]], "actual": [h, w]})
                else:
                    hw_matches += 1
            elif not (h == 0.0 and w == 0.0):
                mismatches.append({**identity, "reason": "zero", "predicted": [0.0, 0.0], "actual": [h, w]})
    verdict = "PASS" if compared > 0 and not mismatches and not units_missing else "FAIL"
    return {
        "schema": "lpbf_patch22_3_7_census_prediction_check",
        "schema_version": PATCH_VERSION,
        "census_directory": str(Path(census_directory).expanduser().resolve()),
        "beam_share_floor": float(floor),
        "units_compared": units_compared,
        "units_missing_from_census": units_missing,
        "frames_compared": compared,
        "status_matches": status_matches,
        "hw_matches": hw_matches,
        "mismatch_count": len(mismatches),
        "mismatches": mismatches[:200],
        "verdict": verdict,
    }


FRAME_CSV_COLUMNS = (
    "candidate_id",
    "member_identity",
    "frame_index",
    "scan_track_id",
    "track_edge_class",
    "status",
    "exclusion_reason",
    "undefined_reason",
    "experimental_H_pixels",
    "experimental_W_pixels",
    "simulated_H_pixels",
    "simulated_W_pixels",
    "production_status",
    "production_mode",
    "production_selected_label",
    "production_beam_share",
    "production_contains_beam_cell",
    "melt_classification",
)


def _csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, float):
        return repr(value)
    return value


def run_stage_a(
    *,
    data_directory: str | Path,
    characterization_directory: str | Path,
    output_directory: str | Path,
    census_directory: str | Path | None = None,
    candidates: Sequence[str] = STAGE_A_CANDIDATES,
    member_identities: Sequence[str] = STAGE_A_MEMBERS,
    workers: int = DEFAULT_WORKERS,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Run the Stage-A units under the 22.3.7 semantics and write the recovery report."""

    workers = _validated_workers(workers)
    held_out = sorted(set(str(value) for value in member_identities) & validation_member_identities())
    if held_out:  # Patch 22.4.3.2 guard gap: Stage A is a calibration-member check (ledger A8)
        raise StageAError(f"held-out members refused by Stage A: {held_out}")
    output = Path(output_directory).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    (output / "units").mkdir(exist_ok=True)
    members = _member_map(data_directory)
    characterization = Path(characterization_directory).expanduser().resolve()
    frame_rows_by_member: dict[str, list[dict[str, Any]]] = {}
    for member_id in sorted(set(str(value) for value in member_identities)):
        member = members.get(member_id)
        if member is None:
            raise StageAError(f"dataset member is missing: {member_id}")
        frame_rows_by_member[member_id] = list(_portable_frame_rows(_find_frame_file(characterization, member), member))
    units = [(str(candidate), str(member_id)) for candidate in candidates for member_id in member_identities]
    jobs = build_stage_a_jobs(units, members, frame_rows_by_member, characterization_directory=characterization)
    total = len(jobs)
    effective_workers = max(1, min(workers, total))
    finished = 0

    def report_progress(result: SimulationResult) -> None:
        nonlocal finished
        finished += 1
        if progress_callback is not None:
            payload = result.payload
            progress_callback(
                finished,
                total,
                {
                    "candidate_id": payload["candidate_id"],
                    "member_identity": payload["member_identity"],
                    "requested_frame_count": payload["requested_frame_count"],
                    "returned_frame_count": payload["returned_frame_count"],
                    "gate_failures": list(payload.get("gate_failures") or []),
                },
            )

    if effective_workers == 1:
        completed = execute_serial_jobs(jobs, _stage_a_unit_job, on_result=report_progress)
    else:
        completed = execute_parallel_jobs(jobs, _stage_a_unit_job, workers=effective_workers, on_result=report_progress)

    payloads: list[dict[str, Any]] = []
    units_out: list[dict[str, Any]] = []
    failures: list[str] = []
    for result in sorted(completed, key=lambda item: item.job.case_index):
        payload = _json_safe(result.payload)
        candidate_id, member_id = payload["candidate_id"], payload["member_identity"]
        unit_file = f"{candidate_id}__{member_id.replace(':', '_')}.json"
        write_json(output / "units" / unit_file, payload)
        payloads.append(payload)
        gate_failures = list(payload.get("gate_failures") or [])
        if gate_failures:
            failures.append(f"{candidate_id} / {member_id}: {', '.join(gate_failures)}")
        units_out.append(
            {
                "candidate_id": candidate_id,
                "member_identity": member_id,
                "unit_file": unit_file,
                "requested_frame_count": payload["requested_frame_count"],
                "returned_frame_count": payload["returned_frame_count"],
                "gate_failures": gate_failures,
                "evaluation_status": payload.get("evaluation_status"),
                "undefined_observation_count": payload.get("undefined_observation_count"),
            }
        )

    by_candidate: dict[str, list[dict[str, Any]]] = {}
    for payload in payloads:
        by_candidate.setdefault(str(payload["candidate_id"]), []).append(payload)
    summaries = {candidate_id: _candidate_summary(candidate_id, group) for candidate_id, group in sorted(by_candidate.items())}
    for candidate_id, summary in summaries.items():
        if summary["objective_status"] != "PASS":
            failures.append(f"{candidate_id}: objective {summary['objective_status']} ({summary.get('objective_error') or 'penalized'})")

    census_check = None
    if census_directory is not None and (Path(census_directory).expanduser().resolve() / CENSUS_REPORT_NAME).is_file():
        census_check = compare_with_census_prediction(
            census_directory,
            {(str(payload["candidate_id"]), str(payload["member_identity"])): payload.get("frame_records") or [] for payload in payloads},
        )
        write_json(output / CENSUS_CHECK_NAME, census_check)
        if census_check["verdict"] != "PASS":
            failures.append(f"census prediction check: {census_check['mismatch_count']} mismatches")

    frames_csv = output / FRAMES_CSV_NAME
    with frames_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(FRAME_CSV_COLUMNS)
        for payload in payloads:
            for row in sorted(payload.get("frame_records") or [], key=lambda item: int(item["frame_index"])):
                position = row.get("track_position") or {}
                flat = {**row, "candidate_id": payload["candidate_id"], "member_identity": payload["member_identity"], "track_edge_class": position.get("edge_class")}
                writer.writerow([_csv_value(flat.get(column)) for column in FRAME_CSV_COLUMNS])

    report: dict[str, Any] = {
        "schema": STAGE_A_SCHEMA,
        "schema_version": PATCH_VERSION,
        "patch": PATCH_VERSION,
        "status": STAGE_A_STATUS_PASS if not failures else STAGE_A_STATUS_FAIL,
        "calibration_result": False,
        "production_hw_definition": PRODUCTION_HW_DEFINITION,
        "production_hw_semantics_version": PRODUCTION_HW_SEMANTICS_VERSION,
        "production_hw_association_policy_version": POLICY_VERSION,
        "beam_share_floor": float(BEAM_SHARE_FLOOR),
        "scored_frame_rule_version": SCORED_FRAME_RULE_VERSION,
        "undefined_observation_policy": UNDEFINED_OBSERVATION_POLICY,
        "coverage_floor": COVERAGE_FLOOR,
        "window_cells": WINDOW_CELLS,
        "candidate_ids": [str(value) for value in candidates],
        "member_identities": [str(value) for value in member_identities],
        "unit_count": total,
        "units": units_out,
        "candidates": summaries,
        "failures": failures,
        "census_prediction_check": (
            None
            if census_check is None
            else {key: census_check[key] for key in ("verdict", "frames_compared", "status_matches", "hw_matches", "mismatch_count", "units_compared", "units_missing_from_census")}
        ),
        "stage_a_execution": {
            "execution_patch": PATCH_VERSION,
            "requested_workers": workers,
            "workers": effective_workers,
            "start_method": "serial" if effective_workers == 1 else "spawn",
        },
        "thermal_replay_performed": True,
        "full_campaign_dispatched": False,
        "calibration_search_authorized": False,
        "parameter_selection_performed": False,
        "parameter_fitting_performed": False,
        "validation_partition_used": False,
    }
    write_json(output / REPORT_NAME, report)  # paths stay out of the written record
    report["frames_csv"] = str(frames_csv)
    report["report_path"] = str(output / REPORT_NAME)
    return report


__all__ = [
    "DEFAULT_WORKERS",
    "PATCH_VERSION",
    "STAGE_A_STATUS_FAIL",
    "STAGE_A_STATUS_PASS",
    "StageAError",
    "build_stage_a_jobs",
    "compare_with_census_prediction",
    "run_stage_a",
]
