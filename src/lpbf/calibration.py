"""The narrow-window calibration of the thesis (65-85 J/mm3) under the log-ratio objective contract 22.4.3.2.

Stages, as predeclared in ``results/calibration/PREDECLARED_PLAN.md``:

* ``smoke``     - the gate unit ``anchor_center`` x ``20260730:part_1`` must reproduce the frozen reference frame
  records (``results/smoke_reference/``) bit for bit, and their pixel coupon objective;
* ``calibrate`` - the 17 frozen design candidates on the 9 in-window calibration members (153 units);
* ``confirm``   - a least-squares quadratic of J in coded coordinates, minimized over the box under the coupled guard,
  proposes at most three confirmation candidates, which run on the same 9 members;
* ``freeze``    - selection by the lowest *measured* J (reading C); writes ``selection_freeze.json``, which is
  recorded in the release before anything else happens;
* ``evaluate``  - only against the recorded, unmodified freeze whose SHA-256 is given: the E-set on the 15 evaluation
  members, and the selected candidate on the 9 calibration members with field capture (readings V and X).

Every unit is the frame-record path (association policy and H/W semantics 22.3.7, scored-frame rule,
``record_undefined``) run inside the field-capture instrumentation, which only observes; the per-frame peak of the
top-surface field is kept for the boiling fraction.  Held-out members are refused outside ``evaluate``, and only the
requested members' HDF5 files are hashed and read.

The version strings ``22.4.3.2`` and ``22.3.7`` are the identifiers of the objective contract and of the production
H/W semantics; they are recorded in every unit file and manifest of the thesis run and are kept unchanged.
"""
from __future__ import annotations

import argparse
import json
import math
import platform
import subprocess
import sys
import time
from itertools import product
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import numpy as np

from lpbf import frame_records
from lpbf.calibration_contract import (
    COEFFICIENT_ORDER,
    Patch21GlobalParameterPolicy,
    load_patch21_0_contract,
    member_identity,
    patch21_candidate_admissibility,
    validation_member_identities as a8_held_out_members,
)
from lpbf.calibration_design import DESIGN_PATH, WINDOW_CELLS, candidate_coordinates, coordinate_bounds
from lpbf.configuration import BOILING_K, load_final_model
from lpbf.data.full_coupon_manifest import load_full_coupon_manifest, resolve_manifest_files
from lpbf.dataset_split import (  # noqa: F401  (re-exported: the synthetic-camera stage and the analysis scripts read them here)
    CALIBRATION_CONDITIONS,
    CALIBRATION_MEMBERS,
    CROSS_CAMPAIGN_HELD_OUT,
    EVALUATION_MEMBERS,
    HATCH_MM,
    IN_WINDOW_HELD_OUT,
    LAYER_MM,
    OUT_OF_WINDOW,
    OUT_OF_WINDOW_BLIND,
    OUT_OF_WINDOW_EXAMINED,
    VED_WINDOW_J_MM3,
    derive_member_roles,
    member_records,
    ved_j_mm3,
)
from lpbf.execution.parallel import execute_parallel_jobs
from lpbf.execution.work_units import SimulationJob, SimulationResult, execute_serial_jobs
from lpbf.experiments.current_framework import CalibrationExecutionScope
from lpbf.experiments.dataset import DatasetMember, _dataset_member_from_resolved
from lpbf.field_capture import (
    SMOKE_REFERENCE_COMPARE_COLUMNS,
    SMOKE_REFERENCE_FRAMES_CSV,
    SMOKE_REFERENCE_REPORT_JSON,
    _reference_rows,
    assemble_unit_capture,
    compare_with_smoke_reference,
    dispatch_lock_check,
    field_capture_instrumentation,
    frozen_core_check,
    store_unit_fields,
)
from lpbf.frame_records import (
    UNDEFINED_OBSERVATION_POLICY,
    _dataset_member_context,
    _dataset_member_from_context,
    _find_frame_file,
    _frame_records_from_evaluation,
    _json_safe,
    _portable_frame_rows,
)
from lpbf.hierarchical_objective import COVERAGE_FLOOR, HierarchicalObjectiveError, aggregate_hierarchical_records
from lpbf.infrastructure import canonical_sha256, git_metadata, sha256_file, validated_workers, write_json
from lpbf.log_ratio_objective import OBJECTIVE_CONTRACT_VERSION, PIXEL_FLOOR, aggregate_log_ratio_records
from lpbf.model.laser_component_association import BEAM_SHARE_FLOOR, NO_LASER_ASSOCIATED_MELT_STATUS, POLICY_VERSION
from lpbf.model.production_hw import PRODUCTION_HW_DEFINITION, PRODUCTION_HW_SEMANTICS_VERSION
from lpbf.paths import repository_root
from lpbf.scored_frame_rule import SCORED_FRAME_RULE_VERSION, apply_scored_frame_rule, scored_frame_indices

PATCH_VERSION = "22.4.3.2"  # objective-contract identifier, recorded in every manifest
SCHEMA = "lpbf_patch22_4_3_2_window_calibration"
DEFAULT_WORKERS = 4
DEFAULT_OUTPUT_DIRECTORY = "runs/calibration"  # new runs; the recorded run of the thesis unpacks to runs/recorded_calibration
REPO_ROOT = repository_root()
PLAN_PATH = REPO_ROOT / "results" / "calibration" / "PREDECLARED_PLAN.md"

# ---------------------------------------------------------------------- data roles: see dataset_split.py

SMOKE_UNIT = ("anchor_center", "20260730:part_1")
DESIGN_UNIT_COUNT = 153
SET_ORDINALS = {"20260730": 1, "20260731": 2, "20260904": 3, "20260910": 4}

# ---------------------------------------------------------------------- search and selection constants (plan)

CODED_CENTER = (0.0, 2.0, 0.5)
CODED_HALF_RANGE = (3.0, 0.5, 0.5)
MAX_CONFIRMATION_CANDIDATES = 3
DESIGN_PROXIMITY_CODED = 0.05
FLAT_EIGENVALUE_FRACTION = 0.10
NEAR_BEST_FACTOR = 1.10
EDGE_CODED = 0.9
EDGE_GUARD_FRACTION = 0.95
E_SET_EXTRA = 2
E_SET_MIN_DISTANCE_CODED = 0.2
SURROGATE_GRID_STEP = 0.1
SURROGATE_INITIAL_STEP = 0.1
SURROGATE_FINAL_STEP = 1.0e-4
V_RATIO_LIMIT = 1.25
X_SPEARMAN_MINIMUM = 0.6
X_OVER_VED = 95.0
X_UNDER_VED = 62.5

READING_C_INTERIOR = "C_INTERIOR"
READING_C_EDGE = "C_EDGE"
READING_V_PASS = "V_PASS"
READING_V_PARTIAL = "V_PARTIAL"
READING_V_FAIL = "V_FAIL"
READING_X_CONFIRMED = "X_CONFIRMED"
READING_X_PARTIAL = "X_PARTIAL"
READING_X_CONTRADICTED = "X_CONTRADICTED"
READING_UNDEFINED = "UNDEFINED"

SMOKE_PASS = "PASS_PATCH_22_4_3_2_SMOKE_GATE"
SMOKE_FAIL = "FAIL_PATCH_22_4_3_2_SMOKE_GATE"

ProgressCallback = Callable[[int, int, Mapping[str, Any]], None]


class WindowCalibrationError(RuntimeError):
    """Fail-closed error for the window calibration."""


def require_stage_members(stage: str, identities: Sequence[str], *, freeze_verified: bool = False) -> tuple[str, ...]:
    """Refuse held-out and out-of-window members outside ``evaluate``; ``evaluate`` needs a verified freeze."""

    requested = tuple(sorted({str(value) for value in identities}))
    if not requested:
        raise WindowCalibrationError("no members requested")
    held_out = a8_held_out_members()
    if stage == "evaluate":
        if not freeze_verified:
            raise WindowCalibrationError("evaluate requires a verified, committed selection freeze")
        unknown = sorted(set(requested) - set(EVALUATION_MEMBERS) - set(CALIBRATION_MEMBERS))
        if unknown:
            raise WindowCalibrationError(f"not a Patch 22.4.3.2 member: {unknown}")
        return requested
    refused = sorted(set(requested) & held_out)
    if refused:
        raise WindowCalibrationError(f"held-out members refused outside the evaluation stage: {refused}")
    outside = sorted(set(requested) - set(CALIBRATION_MEMBERS))
    if outside:
        raise WindowCalibrationError(f"not an in-window calibration member: {outside}")
    return requested


# ---------------------------------------------------------------------- coordinates and guard


def guard_maximum() -> float:
    return float(load_patch21_0_contract()["coupled_transport_guard"]["maximum_allowed"])


def to_coded(coordinates: Mapping[str, float]) -> np.ndarray:
    return np.array([(float(coordinates[name]) - c) / h for name, c, h in zip(COEFFICIENT_ORDER, CODED_CENTER, CODED_HALF_RANGE)])


def from_coded(x: Sequence[float]) -> dict[str, float]:
    return {name: float(c + h * float(value)) for name, c, h, value in zip(COEFFICIENT_ORDER, CODED_CENTER, CODED_HALF_RANGE, x)}


def candidate_admissibility(coordinates: Mapping[str, float]) -> dict[str, Any]:
    """Box bounds and the frozen coupled guard (``patch21_candidate_admissibility``), fail closed."""

    values = {name: float(coordinates[name]) for name in COEFFICIENT_ORDER}
    for name, (low, high) in coordinate_bounds().items():
        if not (math.isfinite(values[name]) and low <= values[name] <= high):
            return {"admissible": False, "reason": f"{name}={values[name]!r} outside [{low}, {high}]", "guard_value": None}
    try:
        result = patch21_candidate_admissibility(Patch21GlobalParameterPolicy.from_values(*(values[name] for name in COEFFICIENT_ORDER)))
    except Exception as exc:  # any contract error rejects the candidate
        return {"admissible": False, "reason": f"{type(exc).__name__}: {exc}", "guard_value": None}
    guard = result["coupled_transport_guard"]
    return {
        "admissible": bool(result["admissible"]),
        "reason": None if result["admissible"] else "coupled guard or numerical preflight",
        "guard_value": float(guard["actual"]),
        "guard_maximum": float(guard["maximum_allowed"]),
        "preflight_status": result["frozen_numerical_preflight"].get("status"),
    }


def coded_admissible(x: Sequence[float]) -> bool:
    x = np.asarray(x, dtype=np.float64)
    if not np.all(np.abs(x) <= 1.0):
        return False
    return bool(candidate_admissibility(from_coded(x))["admissible"])


def candidate_record(candidate_id: str, coordinates: Mapping[str, float], origin: str) -> dict[str, Any]:
    """Confirmation-candidate schema; the guard is checked here for every candidate before any thermal run."""

    admissibility = candidate_admissibility(coordinates)
    if not admissibility["admissible"]:
        raise WindowCalibrationError(f"candidate {candidate_id} is not admissible: {admissibility['reason']}")
    return {
        "candidate_id": str(candidate_id),
        "origin": str(origin),
        "coordinates": {name: float(coordinates[name]) for name in COEFFICIENT_ORDER},
        "coded": [float(value) for value in to_coded(coordinates)],
        "guard_value": admissibility["guard_value"],
    }


def frozen_design_candidates() -> list[dict[str, Any]]:
    return [candidate_record(cid, coordinates, "frozen_design") for cid, coordinates in candidate_coordinates().items()]


# ---------------------------------------------------------------------- members and frame rows


def resolve_members(data_directory: str | Path, identities: Sequence[str]) -> dict[str, DatasetMember]:
    """Bind only the requested members: directory membership is checked by name, only their files are hashed."""

    root = Path(data_directory).expanduser().resolve()
    manifest = load_full_coupon_manifest()
    by_id = {member_identity(m.key.acquisition_set_id, m.key.part_number): m for m in manifest.enabled_members}
    missing = sorted(set(identities) - set(by_id))
    if missing:
        raise WindowCalibrationError(f"members not in the canonical manifest: {missing}")
    if not root.is_dir():
        raise WindowCalibrationError(f"coupon data directory does not exist: {root}")
    observed = {path.name for path in root.iterdir() if path.is_file() and path.suffix.lower() == ".h5"}
    expected = {member.expected_filename for member in by_id.values()}
    if observed != expected:
        raise WindowCalibrationError(f"HDF5 directory membership mismatch; missing={sorted(expected - observed)}, unexpected={sorted(observed - expected)}")
    selected = [by_id[identity] for identity in sorted(set(identities))]
    resolved = resolve_manifest_files(root, manifest=manifest, members=selected)
    return {
        member_identity(item.member.key.acquisition_set_id, item.member.key.part_number): _dataset_member_from_resolved(
            item, set_ordinal=SET_ORDINALS[item.member.key.acquisition_set_id]
        )
        for item in resolved
    }


def load_frame_rows(characterization_directory: str | Path, members: Mapping[str, DatasetMember]) -> dict[str, list[dict[str, Any]]]:
    """Rule-labelled portable frame rows for the given members only."""

    root = Path(characterization_directory).expanduser().resolve()
    return {
        identity: apply_scored_frame_rule([dict(row) for row in _portable_frame_rows(_find_frame_file(root, member), member)])
        for identity, member in sorted(members.items())
    }


# ---------------------------------------------------------------------- unit jobs


def unit_stem(candidate_id: str, member_id: str) -> str:
    return f"{candidate_id}__{member_id.replace(':', '_')}"


def work_unit_id(candidate_id: str, member_id: str) -> str:
    return f"{PATCH_VERSION}:{candidate_id}@{member_id}"


def build_unit_jobs(
    stage: str,
    units: Sequence[tuple[str, str]],
    candidates: Mapping[str, Mapping[str, Any]],
    members: Mapping[str, DatasetMember],
    frame_rows: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    characterization_directory: str | Path,
    capture_fields: Sequence[tuple[str, str]] = (),
) -> tuple[SimulationJob, ...]:
    """One spawn-safe job per (candidate, member); case_index follows sorted unit identity."""

    capture = {(str(c), str(m)) for c, m in capture_fields}
    characterization = str(Path(characterization_directory).expanduser().resolve())
    jobs: list[SimulationJob] = []
    for ordinal, (candidate_id, member_id) in enumerate(sorted({(str(c), str(m)) for c, m in units})):
        candidate = candidates.get(candidate_id)
        if candidate is None:
            raise WindowCalibrationError(f"unknown candidate: {candidate_id}")
        member = members.get(member_id)
        if member is None:
            raise WindowCalibrationError(f"member was not resolved: {member_id}")
        rows = [dict(row) for row in frame_rows[member_id]]
        scored = scored_frame_indices(rows)
        if not scored:
            raise WindowCalibrationError(f"no scored frames for {member_id}")
        jobs.append(
            SimulationJob(
                case_index=ordinal,
                member_identity=member_id,
                frame_index=scored[0],
                window_cells=WINDOW_CELLS,
                candidate_coordinates=dict(candidate["coordinates"]),
                work_unit_id=work_unit_id(candidate_id, member_id),
                experiment_context={
                    "stage": str(stage),
                    "candidate_id": candidate_id,
                    "candidate_origin": str(candidate["origin"]),
                    "capture_fields": (candidate_id, member_id) in capture,
                    "validation_partition_member": member_id in a8_held_out_members(),
                    "dataset_member_json": json.dumps(_dataset_member_context(member)),
                    "frame_rows_json": json.dumps(rows),
                    "characterization_directory": characterization,
                },
            )
        )
    return tuple(jobs)


def _window_scope(context: Mapping[str, Any], member: DatasetMember, coordinates: Mapping[str, float], frames: Sequence[int]) -> CalibrationExecutionScope:
    candidate_id = str(context["candidate_id"])
    return CalibrationExecutionScope(
        scope_id=f"patch22_4_3_2:{context['stage']}:{candidate_id}:{member_identity(member.acquisition_set_id, member.coupon_position)}",
        observation_frame_indices=tuple(sorted(set(int(value) for value in frames))),
        trial_context={
            "patch": PATCH_VERSION,
            "objective_branch": f"window_calibration_{context['stage']}",
            "objective_contract_version": OBJECTIVE_CONTRACT_VERSION,
            "candidate_id": candidate_id,
            "candidate_origin": context["candidate_origin"],
            "candidate_coordinates": dict(coordinates),
            "production_hw_definition": PRODUCTION_HW_DEFINITION,
            "production_hw_semantics_version": PRODUCTION_HW_SEMANTICS_VERSION,
            "production_hw_association_policy_version": POLICY_VERSION,
            "scored_frame_rule_version": SCORED_FRAME_RULE_VERSION,
            "undefined_observation_policy": UNDEFINED_OBSERVATION_POLICY,
            "validation_partition_used": bool(context["validation_partition_member"]),
            "parameter_selection_performed": False,
            "parameter_fitting_performed": False,
            "full_campaign_dispatched": False,
        },
        unenclosed_contour_policy="record_nan",
        window_cells=WINDOW_CELLS,
        undefined_observation_policy=UNDEFINED_OBSERVATION_POLICY,
    )


def _evaluate_unit(job: SimulationJob) -> dict[str, Any]:
    """The Patch 22.3.7 Stage-A unit path with this patch's scope and the job's own coordinates."""

    context = job.experiment_context_dict
    candidate_id = str(context["candidate_id"])
    member = _dataset_member_from_context(json.loads(context["dataset_member_json"]))
    rows = json.loads(context["frame_rows_json"])
    scored = scored_frame_indices(rows)
    coordinates = job.candidate_coordinates_dict
    base = {
        "schema": SCHEMA,
        "patch": PATCH_VERSION,
        "stage": context["stage"],
        "work_unit_id": job.work_unit_id,
        "candidate_id": candidate_id,
        "candidate_origin": context["candidate_origin"],
        "member_identity": member_identity(member.acquisition_set_id, member.coupon_position),
        "member_sha256": member.sha256,
        "frame_rows_sha256": canonical_sha256(rows),
        "candidate_coordinates": coordinates,
        "requested_frame_count": len(scored),
        "production_hw_semantics_version": PRODUCTION_HW_SEMANTICS_VERSION,
        "production_hw_association_policy_version": POLICY_VERSION,
        "scored_frame_rule_version": SCORED_FRAME_RULE_VERSION,
        "thermal_execution_performed": True,
    }
    policy = Patch21GlobalParameterPolicy.from_values(*(float(coordinates[name]) for name in COEFFICIENT_ORDER))
    scope = _window_scope(context, member, coordinates, scored)
    try:
        # called through the Stage-A module so the field-capture instrumentation observes the evaluation
        evaluation = frame_records.evaluate_calibration_trial(member, policy, scope).to_dict()
    except Exception as exc:  # fail closed: no frames are fabricated for a unit that did not evaluate
        failed = []
        for row in rows:
            record = dict(row)
            record["status"] = "FAIL"
            record["failure"] = {"code": "PATCH_22_4_3_2_WORKER_EXCEPTION", "type": type(exc).__name__, "message": str(exc)}
            failed.append(record)
        return {**base, "returned_frame_count": 0, "frame_records": failed, "gate_failures": ["worker_exception"], "evaluation_status": "EXCEPTION"}
    records, gate_failures = _frame_records_from_evaluation(evaluation, base_rows=rows, undefined_observation_policy=UNDEFINED_OBSERVATION_POLICY)
    frame_records._annotate_frame_records(records, evaluation)
    telemetry = evaluation.get("execution_telemetry") or {}
    return {
        **base,
        "returned_frame_count": sum(1 for row in records if row.get("status") in ("PASS", "UNDEFINED") and bool(row.get("scored_frame"))),
        "frame_records": records,
        "gate_failures": list(gate_failures),
        "evaluation_status": evaluation.get("status"),
        "evaluation_failure": evaluation.get("failure"),
        "undefined_observation_count": telemetry.get("undefined_observation_count"),
    }


def _window_unit_job(job: SimulationJob) -> dict[str, Any]:
    """Spawn-safe worker: one unit inside the field-capture instrumentation; fields travel back only if requested."""

    with field_capture_instrumentation() as state:
        payload = _evaluate_unit(job)
    capture, failures = assemble_unit_capture(state, payload)
    peaks = {} if capture is None else {
        str(int(frame)): float(np.max(field)) for frame, field in zip(capture["frame_index"].tolist(), capture["top_surface_temperature_K"])
    }
    keep = bool(job.experiment_context_dict.get("capture_fields"))
    payload.update(
        {
            "capture_gate_failures": failures,
            "captured_frame_count": 0 if capture is None else int(capture["frame_index"].size),
            "peak_surface_temperature_K_by_frame": peaks,
            "capture_fields": keep,
            "capture": capture if keep else None,
        }
    )
    return payload


def _unit_ok(payload: Mapping[str, Any]) -> bool:
    requested = int(payload.get("requested_frame_count") or 0)
    return bool(
        requested > 0
        and int(payload.get("returned_frame_count") or 0) == requested
        and int(payload.get("captured_frame_count") or 0) == requested
        and not payload.get("gate_failures")
        and not payload.get("capture_gate_failures")
        and len(payload.get("peak_surface_temperature_K_by_frame") or {}) == requested
    )


def _reusable(path: Path, job: SimulationJob, member: DatasetMember) -> bool:
    """Resume by work_unit_id: an existing unit file is reused only if it is complete and for the same inputs."""

    if not path.is_file():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    context = job.experiment_context_dict
    if not (
        payload.get("work_unit_id") == job.work_unit_id
        and payload.get("candidate_coordinates") == job.candidate_coordinates_dict
        and payload.get("member_sha256") == member.sha256
        and payload.get("frame_rows_sha256") == canonical_sha256(json.loads(context["frame_rows_json"]))
        and _unit_ok(payload)
    ):
        return False
    if bool(context.get("capture_fields")):
        capture = payload.get("capture_file") or {}
        field_path = path.parent.parent / str(capture.get("path", ""))
        return bool(capture) and field_path.is_file() and sha256_file(field_path) == capture.get("sha256")
    return payload.get("capture_file") is None


def run_units(
    stage_directory: Path,
    jobs: Sequence[SimulationJob],
    members: Mapping[str, DatasetMember],
    *,
    workers: int,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Run the jobs not already complete on disk; the parent writes each unit (and its fields) as it finishes."""

    workers = _validated_workers(workers)
    stage_directory.mkdir(parents=True, exist_ok=True)
    units_directory = stage_directory / "units"
    units_directory.mkdir(exist_ok=True)
    pending, reused = [], []
    for job in jobs:
        context = job.experiment_context_dict
        path = units_directory / f"{unit_stem(context['candidate_id'], job.member_identity)}.json"
        (reused if _reusable(path, job, members[job.member_identity]) else pending).append(job)
    # longest units first so the pool's tail is short; identity and output order are unaffected
    pending.sort(key=lambda job: (-len(scored_frame_indices(json.loads(job.experiment_context_dict["frame_rows_json"]))), job.case_index))
    total, finished = len(pending), 0
    started = time.monotonic()

    def on_result(result: SimulationResult) -> None:
        nonlocal finished
        payload = result.payload
        store_unit_fields(stage_directory, payload)
        stem = unit_stem(str(payload["candidate_id"]), str(payload["member_identity"]))
        write_json(units_directory / f"{stem}.json", _json_safe(payload))
        finished += 1
        if progress is not None:
            progress(
                finished,
                total,
                {
                    "candidate_id": payload["candidate_id"],
                    "member_identity": payload["member_identity"],
                    "requested_frame_count": payload.get("requested_frame_count"),
                    "ok": _unit_ok(payload),
                    "elapsed_s": round(time.monotonic() - started, 1),
                },
            )

    effective = max(1, min(workers, total)) if total else 1
    if total:
        if effective == 1:
            execute_serial_jobs(pending, _window_unit_job, on_result=on_result)
        else:
            execute_parallel_jobs(pending, _window_unit_job, workers=effective, on_result=on_result)
    return {
        "requested_workers": workers,
        "workers": effective,
        "start_method": "serial" if effective == 1 else "spawn",
        "units_run": total,
        "units_reused": len(reused),
        "wall_time_s": round(time.monotonic() - started, 1),
    }


def load_units(stage_directory: Path, units: Sequence[tuple[str, str]]) -> dict[tuple[str, str], dict[str, Any]]:
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for candidate_id, member_id in sorted(set(units)):
        path = stage_directory / "units" / f"{unit_stem(candidate_id, member_id)}.json"
        if not path.is_file():
            raise WindowCalibrationError(f"unit file missing: {path}")
        out[(candidate_id, member_id)] = json.loads(path.read_text(encoding="utf-8"))
    return out


# ---------------------------------------------------------------------- scoring


def score_candidate(candidate_id: str, payloads: Sequence[Mapping[str, Any]], *, member_ids: Sequence[str], condition_ids: Sequence[str]) -> dict[str, Any]:
    """Objective 22.4.3.2 and its predeclared companions for one candidate over a member set."""

    failures = [f"{p['member_identity']}: unit incomplete" for p in payloads if not _unit_ok(p)]
    present = sorted(str(p["member_identity"]) for p in payloads)
    if present != sorted(member_ids):
        failures.append(f"members present {present} differ from requested {sorted(member_ids)}")
    records = [dict(row) for p in payloads for row in p.get("frame_records") or []]
    log = aggregate_log_ratio_records(records, member_ids=member_ids, condition_ids=condition_ids, require_complete=True, candidate_id=candidate_id)
    try:
        pixel = aggregate_hierarchical_records(records, calibration_member_ids=member_ids, calibration_condition_ids=condition_ids, require_complete=True, candidate_id=candidate_id)
        pixel_value, pixel_status = pixel.get("objective_value"), pixel.get("status")
    except HierarchicalObjectiveError as exc:
        pixel_value, pixel_status = None, f"ERROR: {exc}"
    peaks = [float(value) for p in payloads for value in (p.get("peak_surface_temperature_K_by_frame") or {}).values()]
    status_counts: dict[str, int] = {}
    for row in records:
        if row.get("status") in ("PASS", "UNDEFINED"):
            key = str(row.get("production_status"))
            status_counts[key] = status_counts.get(key, 0) + 1
    return {
        "candidate_id": candidate_id,
        "status": "PASS" if not failures and log["status"] == "PASS" else ("INCOMPLETE" if failures else log["status"]),
        "failures": failures,
        "J": log["objective_value"],
        "H_component": log["H_component"],
        "W_component": log["W_component"],
        "e_H": log["e_H"],
        "e_W": log["e_W"],
        "sensitivity": {"H_only": log["H_component"], "W_only": log["W_component"], "pixel_22_3_7": pixel_value, "pixel_22_3_7_status": pixel_status},
        "coverage": (log.get("counts") or {}).get("coverage"),
        "coverage_by_coupon": (log.get("counts") or {}).get("coverage_by_coupon"),
        "coverage_flag": log.get("coverage_flag"),
        "low_coverage_coupons": log.get("low_coverage_coupons"),
        "penalty_applied": log.get("penalty_applied"),
        "scored_frame_count": (log.get("counts") or {}).get("scored_frame_count"),
        "floored_frame_count": (log.get("counts") or {}).get("floored_frame_count"),
        "floored_by_quantity": (log.get("counts") or {}).get("floored_by_quantity"),
        "zero_prediction_frame_count": (log.get("counts") or {}).get("zero_prediction_frame_count"),
        "no_laser_associated_melt_count": status_counts.get(NO_LASER_ASSOCIATED_MELT_STATUS, 0),
        "production_status_counts": dict(sorted(status_counts.items())),
        "captured_frame_count": len(peaks),
        "fraction_peak_above_boiling": (sum(1 for value in peaks if value > BOILING_K) / len(peaks)) if peaks else None,
        "median_peak_surface_K": float(np.median(peaks)) if peaks else None,
        "condition_rows": [
            {key: row[key] for key in ("exact_condition_id", "member_identities", "e_H", "e_W", "H_mean_log", "W_mean_log", "median_H_ratio", "median_W_ratio", "floored_frame_count", "condition_objective_contribution")}
            for row in log.get("condition_rows") or []
        ],
        "coupon_rows": [
            {key: row[key] for key in ("member_identity", "exact_condition_id", "coverage", "scored_frame_count", "e_H", "e_W", "median_r_H", "median_r_W", "median_H_ratio", "median_W_ratio", "floored_frame_count", "coupon_scalar_objective")}
            for row in log.get("coupon_rows") or []
        ],
    }


# ---------------------------------------------------------------------- surrogate


QUADRATIC_TERMS = ("1", "x1", "x2", "x3", "x1^2", "x2^2", "x3^2", "x1*x2", "x1*x3", "x2*x3")
_DIRECTIONS = tuple(np.array(d, dtype=np.float64) for d in product((-1.0, 0.0, 1.0), repeat=3) if any(d))


def quadratic_features(points: Any) -> np.ndarray:
    x = np.atleast_2d(np.asarray(points, dtype=np.float64))
    a, b, c = x[:, 0], x[:, 1], x[:, 2]
    return np.column_stack([np.ones(len(x)), a, b, c, a * a, b * b, c * c, a * b, a * c, b * c])


def fit_quadratic(points: Any, values: Sequence[float]) -> dict[str, Any]:
    """Least squares on the 10 quadratic terms; R² and leave-one-out RMSE from the hat matrix."""

    X = quadratic_features(points)
    y = np.asarray(values, dtype=np.float64)
    if X.shape[0] != y.size or not np.all(np.isfinite(y)):
        raise WindowCalibrationError("surrogate needs one finite value per design point")
    rank = int(np.linalg.matrix_rank(X))
    if rank < X.shape[1]:
        raise WindowCalibrationError(f"quadratic surrogate is not identified (rank {rank} < {X.shape[1]})")
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    residuals = y - X @ beta
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    leverage = np.einsum("ij,jk,ik->i", X, np.linalg.inv(X.T @ X), X)
    loo = residuals / (1.0 - leverage) if np.all(1.0 - leverage > 1e-12) else np.full_like(residuals, np.nan)
    return {
        "terms": list(QUADRATIC_TERMS),
        "coefficients": [float(value) for value in beta],
        "r_squared": float(1.0 - float(np.sum(residuals**2)) / ss_tot) if ss_tot > 0.0 else float("nan"),
        "loo_rmse": float(np.sqrt(np.mean(loo**2))),
        "residuals": [float(value) for value in residuals],
        "leverage": [float(value) for value in leverage],
        "point_count": int(y.size),
    }


def surrogate_value(beta: Sequence[float], x: Any) -> np.ndarray | float:
    values = quadratic_features(x) @ np.asarray(beta, dtype=np.float64)
    return float(values[0]) if np.ndim(x) == 1 else values


def surrogate_gradient(beta: Sequence[float], x: Sequence[float]) -> np.ndarray:
    b = np.asarray(beta, dtype=np.float64)
    a, c2, c3 = (float(v) for v in x)
    return np.array(
        [b[1] + 2 * b[4] * a + b[7] * c2 + b[8] * c3, b[2] + 2 * b[5] * c2 + b[7] * a + b[9] * c3, b[3] + 2 * b[6] * c3 + b[8] * a + b[9] * c2]
    )


def surrogate_hessian(beta: Sequence[float]) -> np.ndarray:
    b = np.asarray(beta, dtype=np.float64)
    return np.array([[2 * b[4], b[7], b[8]], [b[7], 2 * b[5], b[9]], [b[8], b[9], 2 * b[6]]])


def _pattern_search(f: Callable[[np.ndarray], float], admissible: Callable[[np.ndarray], bool], x0: np.ndarray) -> tuple[np.ndarray, float]:
    """Deterministic first-improvement search over the 26 lattice directions, clipped to the box, halving the step."""

    x, fx = np.asarray(x0, dtype=np.float64).copy(), f(x0)
    step = SURROGATE_INITIAL_STEP
    for _ in range(100000):
        if step < SURROGATE_FINAL_STEP:
            break
        for direction in _DIRECTIONS:
            y = np.clip(x + step * direction, -1.0, 1.0)
            if np.array_equal(y, x):
                continue
            fy = f(y)
            if fy < fx and admissible(y):
                x, fx = y, fy
                break
        else:
            step /= 2.0
    return x, float(fx)


def minimize_surrogate(beta: Sequence[float], admissible: Callable[[np.ndarray], bool], starts: Sequence[Sequence[float]]) -> dict[str, Any]:
    """Multi-start: the admissible grid minimum plus every given start, each refined by the pattern search."""

    f = lambda x: float(surrogate_value(beta, np.asarray(x)))  # noqa: E731
    axis = np.round(np.arange(-1.0, 1.0 + 1e-9, SURROGATE_GRID_STEP), 10)
    grid = np.array(list(product(axis, axis, axis)))
    grid_values = surrogate_value(beta, grid)
    grid_start = None
    for index in np.argsort(grid_values, kind="stable"):
        if admissible(grid[index]):
            grid_start = grid[index]
            break
    all_starts = [np.asarray(s, dtype=np.float64) for s in starts if admissible(np.asarray(s, dtype=np.float64))]
    if grid_start is not None:
        all_starts.append(grid_start)
    if not all_starts:
        raise WindowCalibrationError("no admissible start for the surrogate minimizer")
    best = None
    for start in all_starts:
        x, value = _pattern_search(f, admissible, start)
        if best is None or value < best[1]:
            best = (x, value, start)
    assert best is not None
    return {"x": [float(v) for v in best[0]], "predicted_J": best[1], "start": [float(v) for v in best[2]], "start_count": len(all_starts)}


def _walk(beta: Sequence[float], admissible: Callable[[np.ndarray], bool], x_star: np.ndarray, direction: np.ndarray, level: float) -> dict[str, Any]:
    """From x* along a unit direction to the surrogate level, clipped to the box, then to the guard by bisection."""

    u = direction / np.linalg.norm(direction)
    s_box = min(((1.0 - x_star[i]) / u[i]) if u[i] > 0 else ((-1.0 - x_star[i]) / u[i]) for i in range(3) if abs(u[i]) > 1e-15)
    s_box = max(0.0, float(s_box))
    j_star = float(surrogate_value(beta, x_star))
    a = float(surrogate_gradient(beta, x_star) @ u)
    kappa = float(u @ surrogate_hessian(beta) @ u)
    gap = level - j_star  # solve 0.5*kappa*s^2 + a*s - gap = 0 for the smallest positive s
    roots = np.roots([0.5 * kappa, a, -gap]) if abs(kappa) > 1e-15 else (np.array([gap / a]) if abs(a) > 1e-15 else np.array([]))
    positive = sorted(float(r.real) for r in np.atleast_1d(roots) if abs(complex(r).imag) < 1e-12 and r.real > 1e-12)
    s_level = positive[0] if positive else math.inf
    s = min(s_level, s_box)
    clipped_by = "level" if s_level <= s_box else "box"
    level_point = x_star + s_level * u if math.isfinite(s_level) else None
    if level_point is not None and s_level > s_box and float(np.linalg.norm(level_point - np.clip(level_point, -1.0, 1.0))) <= DESIGN_PROXIMITY_CODED:
        # x* on a box face with eigenvector noise pointing out of it (Patch 22.4.3.2 confirm: -6e-6 in t) would truncate
        # the walk at s = 0; a level point within the 0.05 proximity tolerance of the box is projected onto it instead
        end = np.clip(level_point, -1.0, 1.0)
        segment, clipped_by = end - x_star, "level_projected"
        if not admissible(end):
            low, high = 0.0, 1.0
            for _ in range(60):
                mid = 0.5 * (low + high)
                if admissible(x_star + mid * segment):
                    low = mid
                else:
                    high = mid
            end, clipped_by = x_star + low * segment, "guard"
        x = np.clip(end, -1.0, 1.0)
        return {"x": [float(v) for v in x], "s": float(np.linalg.norm(x - x_star)), "s_level": s_level, "s_box": s_box, "clipped_by": clipped_by, "predicted_J": float(surrogate_value(beta, x))}
    if not admissible(x_star + s * u):
        low, high = 0.0, s
        for _ in range(60):
            mid = 0.5 * (low + high)
            if admissible(x_star + mid * u):
                low = mid
            else:
                high = mid
        s, clipped_by = low, "guard"
    x = np.clip(x_star + s * u, -1.0, 1.0)
    return {"x": [float(v) for v in x], "s": float(s), "s_level": s_level, "s_box": s_box, "clipped_by": clipped_by, "predicted_J": float(surrogate_value(beta, x))}


def propose_confirmation(
    design_coded: Mapping[str, Sequence[float]],
    design_j: Mapping[str, float],
    admissible: Callable[[np.ndarray], bool] = coded_admissible,
) -> dict[str, Any]:
    """Fit the surrogate on the design points and propose c1 (minimizer) and, in a flat valley, c2/c3."""

    ids = sorted(design_coded)
    points = np.array([design_coded[cid] for cid in ids], dtype=np.float64)
    fit = fit_quadratic(points, [design_j[cid] for cid in ids])
    beta = fit["coefficients"]
    minimum = minimize_surrogate(beta, admissible, points)
    x_star = np.array(minimum["x"])
    evaluated = {cid: points[i] for i, cid in enumerate(ids)}

    def nearest(x: np.ndarray, pool: Mapping[str, np.ndarray]) -> tuple[str | None, float]:
        if not pool:
            return None, math.inf
        distances = {cid: float(np.linalg.norm(np.asarray(x) - np.asarray(p))) for cid, p in pool.items()}
        cid = min(sorted(distances), key=lambda key: distances[key])
        return cid, distances[cid]

    proposals: list[dict[str, Any]] = []
    near_id, near_d = nearest(x_star, evaluated)
    c1_run = near_d >= DESIGN_PROXIMITY_CODED
    proposals.append({"candidate_id": "confirm_c1", "role": "surrogate_minimizer", "x": minimum["x"], "predicted_J": minimum["predicted_J"], "nearest_point": near_id, "nearest_distance": near_d, "run": c1_run})
    accepted = dict(evaluated)
    if c1_run:
        accepted["confirm_c1"] = x_star
    eigenvalues, eigenvectors = np.linalg.eigh(surrogate_hessian(beta))
    lam_min, lam_max = float(eigenvalues[0]), float(eigenvalues[-1])
    flat = lam_max > 0.0 and lam_min <= FLAT_EIGENVALUE_FRACTION * lam_max
    valley = None
    if flat:
        v = eigenvectors[:, 0]
        v = v if v[int(np.argmax(np.abs(v)))] > 0 else -v
        level = minimum["predicted_J"] + 0.10 * abs(minimum["predicted_J"])
        valley = {"eigenvector": [float(value) for value in v], "level": level}
        for cid, sign in (("confirm_c2", 1.0), ("confirm_c3", -1.0)):
            walk = _walk(beta, admissible, x_star, sign * v, level)
            point = np.array(walk["x"])
            other_id, other_d = nearest(point, {**accepted, **({} if c1_run else {"confirm_c1": x_star})})
            run = other_d >= DESIGN_PROXIMITY_CODED
            proposals.append({"candidate_id": cid, "role": f"flat_valley_{'plus' if sign > 0 else 'minus'}", **walk, "nearest_point": other_id, "nearest_distance": other_d, "run": run})
            if run:
                accepted[cid] = point
    return {
        "fit": fit,
        "minimum": minimum,
        "hessian_eigenvalues": [float(value) for value in eigenvalues],
        "flat_valley": flat,
        "valley": valley,
        "proposals": proposals,
        "confirmation_candidates": [p for p in proposals if p["run"]][:MAX_CONFIRMATION_CANDIDATES],
    }


# ---------------------------------------------------------------------- selection (reading C)


def select_candidate(scores: Mapping[str, Mapping[str, Any]], candidates: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Lowest measured J; exact ties go to the lower peak-above-boiling fraction, then to the candidate id."""

    rankable = {cid: s for cid, s in scores.items() if s["status"] == "PASS" and s["J"] is not None and math.isfinite(float(s["J"]))}
    if not rankable:
        raise WindowCalibrationError("no candidate has a finite, unpenalized objective")
    order = sorted(rankable, key=lambda cid: (float(rankable[cid]["J"]), float(rankable[cid]["fraction_peak_above_boiling"] or 0.0), cid))
    selected = order[0]
    j_min = float(rankable[selected]["J"])
    near_best = [cid for cid in order if float(rankable[cid]["J"]) <= NEAR_BEST_FACTOR * j_min]
    x_sel = np.array(candidates[selected]["coded"])
    guard = float(candidates[selected]["guard_value"])
    edge_coordinates = [name for name, value in zip(COEFFICIENT_ORDER, x_sel) if abs(float(value)) >= EDGE_CODED]
    edge_guard = guard >= EDGE_GUARD_FRACTION * guard_maximum()
    extra = [cid for cid in near_best[1:] if float(np.linalg.norm(np.array(candidates[cid]["coded"]) - x_sel)) >= E_SET_MIN_DISTANCE_CODED][:E_SET_EXTRA]
    return {
        "selected": selected,
        "J_min": j_min,
        "ranking": [{"candidate_id": cid, "J": float(rankable[cid]["J"]), "coverage_flag": rankable[cid]["coverage_flag"]} for cid in order],
        "unrankable": sorted(set(scores) - set(rankable)),
        "near_best": near_best,
        "edge": {"coordinates_at_edge": edge_coordinates, "guard_value": guard, "guard_edge_threshold": EDGE_GUARD_FRACTION * guard_maximum(), "guard_at_edge": edge_guard},
        "reading_C": READING_C_EDGE if edge_coordinates or edge_guard else READING_C_INTERIOR,
        "e_set": [selected, *extra],
    }


# ---------------------------------------------------------------------- readings V and X


def spearman_rho(x: Sequence[float], y: Sequence[float]) -> float:
    def ranks(values: Sequence[float]) -> np.ndarray:
        values = np.asarray(values, dtype=np.float64)
        order = np.argsort(values, kind="stable")
        out = np.empty(values.size)
        i = 0
        while i < values.size:
            j = i
            while j + 1 < values.size and values[order[j + 1]] == values[order[i]]:
                j += 1
            out[order[i : j + 1]] = 0.5 * (i + j) + 1.0
            i = j + 1
        return out

    rx, ry = ranks(x), ranks(y)
    if rx.size < 3 or np.std(rx) == 0.0 or np.std(ry) == 0.0:
        return float("nan")
    return float(np.corrcoef(rx, ry)[0, 1])


def reading_v(e_calibration: Mapping[str, float | None], e_held_out: Mapping[str, float | None]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    passes = []
    for q in ("H", "W"):
        cal, ho = e_calibration.get(q), e_held_out.get(q)
        ratio = None if cal in (None, 0.0) or ho is None else float(ho) / float(cal)
        out[f"ratio_{q}"] = ratio
        out[f"pass_{q}"] = None if ratio is None else bool(ratio <= V_RATIO_LIMIT)
        passes.append(out[f"pass_{q}"])
    if any(value is None for value in passes):
        out["reading"] = READING_UNDEFINED
    else:
        out["reading"] = {2: READING_V_PASS, 1: READING_V_PARTIAL, 0: READING_V_FAIL}[sum(bool(v) for v in passes)]
    return out


def reading_x(coupons: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """X1 (W) and X2 (H) on the out-of-window coupons: Spearman of median signed log ratio on VED, and W's sign."""

    usable = [c for c in coupons if c.get("median_r_H") is not None and c.get("median_r_W") is not None]
    if len(usable) != len(coupons) or not usable:
        return {"reading": READING_UNDEFINED, "reason": "a coupon has no scored frames"}
    ved = [float(c["ved_J_mm3"]) for c in usable]
    rho_w = spearman_rho(ved, [float(c["median_r_W"]) for c in usable])
    rho_h = spearman_rho(ved, [float(c["median_r_H"]) for c in usable])
    over = [c for c in usable if float(c["ved_J_mm3"]) >= X_OVER_VED]
    under = [c for c in usable if float(c["ved_J_mm3"]) <= X_UNDER_VED]
    signs_ok = all(float(c["median_r_W"]) > 0.0 for c in over) and all(float(c["median_r_W"]) < 0.0 for c in under)
    x1 = bool(math.isfinite(rho_w) and rho_w >= X_SPEARMAN_MINIMUM and signs_ok)
    x2 = bool(math.isfinite(rho_h) and rho_h >= X_SPEARMAN_MINIMUM)
    reading = {2: READING_X_CONFIRMED, 1: READING_X_PARTIAL, 0: READING_X_CONTRADICTED}[int(x1) + int(x2)]
    return {
        "reading": reading,
        "X1_W": {"spearman_rho": rho_w, "signs_ok": signs_ok, "over_members": [c["member_identity"] for c in over], "under_members": [c["member_identity"] for c in under], "holds": x1},
        "X2_H": {"spearman_rho": rho_h, "holds": x2},
    }


# ---------------------------------------------------------------------- provenance


def _validated_workers(workers: Any) -> int:
    return validated_workers(workers, WindowCalibrationError)


def provenance(members: Mapping[str, DatasetMember]) -> dict[str, Any]:
    read = sorted(members)
    git = git_metadata(REPO_ROOT)  # None values in a source ZIP without .git: git is an aid, not a requirement
    return {
        "git_commit": git["commit"],
        "git_worktree_dirty": git["worktree_dirty"],
        "module_sha256": sha256_file(Path(__file__)),
        "objective_module_sha256": sha256_file(Path(__file__).with_name("log_ratio_objective.py")),
        "plan_sha256": sha256_file(PLAN_PATH) if PLAN_PATH.is_file() else "unavailable",
        "design_sha256": sha256_file(DESIGN_PATH),
        "objective_contract_version": OBJECTIVE_CONTRACT_VERSION,
        "production_hw_semantics_version": PRODUCTION_HW_SEMANTICS_VERSION,
        "production_hw_association_policy_version": POLICY_VERSION,
        "beam_share_floor": float(BEAM_SHARE_FLOOR),
        "scored_frame_rule_version": SCORED_FRAME_RULE_VERSION,
        "coverage_floor": COVERAGE_FLOOR,
        "pixel_floor": PIXEL_FLOOR,
        "window_cells": WINDOW_CELLS,
        "members_read": read,
        "member_sha256": {identity: members[identity].sha256 for identity in read},
        "held_out_members_read": sorted(set(read) & a8_held_out_members()),
        "runtime": {"python": sys.version.split()[0], "numpy": np.__version__, "platform": platform.platform()},
        "campaign_dispatch_lock": dispatch_lock_check(),
    }


def _unit_table(payloads: Mapping[tuple[str, str], Mapping[str, Any]], stage_directory: Path) -> list[dict[str, Any]]:
    return [
        {
            "work_unit_id": p.get("work_unit_id"),
            "candidate_id": c,
            "member_identity": m,
            "requested_frame_count": p.get("requested_frame_count"),
            "returned_frame_count": p.get("returned_frame_count"),
            "captured_frame_count": p.get("captured_frame_count"),
            "ok": _unit_ok(p),
            "gate_failures": list(p.get("gate_failures") or []) + list(p.get("capture_gate_failures") or []),
            "unit_sha256": sha256_file(stage_directory / "units" / f"{unit_stem(c, m)}.json"),
            "capture_file": p.get("capture_file"),
        }
        for (c, m), p in sorted(payloads.items())
    ]


def _stage_inputs(data_directory: str | Path, characterization_directory: str | Path, member_ids: Sequence[str]) -> tuple[dict[str, DatasetMember], dict[str, list[dict[str, Any]]]]:
    members = resolve_members(data_directory, member_ids)
    return members, load_frame_rows(characterization_directory, members)


def _scores_for(candidates: Sequence[str], payloads: Mapping[tuple[str, str], Mapping[str, Any]], member_ids: Sequence[str], condition_ids: Sequence[str]) -> dict[str, dict[str, Any]]:
    return {
        cid: score_candidate(cid, [payloads[(cid, m)] for m in member_ids], member_ids=list(member_ids), condition_ids=list(condition_ids))
        for cid in candidates
    }


# ---------------------------------------------------------------------- stages


def run_smoke(*, data_directory: str | Path, characterization_directory: str | Path, output_directory: str | Path, progress: ProgressCallback | None = None) -> dict[str, Any]:
    """Gate before the calibration run: one serial unit reproduces Stage A bit for bit; core frozen; lock None."""

    candidate_id, member_id = SMOKE_UNIT
    require_stage_members("smoke", [member_id])
    stage_directory = Path(output_directory).expanduser().resolve() / "smoke"
    members, frame_rows = _stage_inputs(data_directory, characterization_directory, [member_id])
    candidates = {c["candidate_id"]: c for c in frozen_design_candidates()}
    jobs = build_unit_jobs("smoke", [SMOKE_UNIT], candidates, members, frame_rows, characterization_directory=characterization_directory)
    execution = run_units(stage_directory, jobs, members, workers=1, progress=progress)
    payload = load_units(stage_directory, [SMOKE_UNIT])[SMOKE_UNIT]
    records = {int(row["frame_index"]): row for row in payload["frame_records"]}
    reference = _reference_rows(SMOKE_REFERENCE_FRAMES_CSV, SMOKE_REFERENCE_COMPARE_COLUMNS).get(SMOKE_UNIT, {})
    stage_a_check = compare_with_smoke_reference(records, reference)
    condition = member_records()[member_id]["condition_id"]
    pixel = aggregate_hierarchical_records(payload["frame_records"], calibration_member_ids=[member_id], calibration_condition_ids=[condition], require_complete=True)
    stage_a_value = json.loads(SMOKE_REFERENCE_REPORT_JSON.read_text(encoding="utf-8"))["candidates"][candidate_id]["coupon_scalar_objectives"][member_id]
    pixel_value = pixel["coupon_rows"][0]["coupon_scalar_objective"] if pixel.get("coupon_rows") else None
    score = score_candidate(candidate_id, [payload], member_ids=[member_id], condition_ids=[condition])
    checks = {
        "unit_complete": _unit_ok(payload),
        "stage_a_frame_records_bit_identical": bool(stage_a_check["pass"]),
        "pixel_objective_matches_stage_a": pixel_value == stage_a_value,
        "frozen_core": frozen_core_check(),
        "dispatch_lock": dispatch_lock_check(),
    }
    passed = bool(checks["unit_complete"] and checks["stage_a_frame_records_bit_identical"] and checks["pixel_objective_matches_stage_a"] and checks["frozen_core"]["pass"] and checks["dispatch_lock"]["pass"])
    gate = {
        "schema": SCHEMA,
        "patch": PATCH_VERSION,
        "stage": "smoke",
        "status": SMOKE_PASS if passed else SMOKE_FAIL,
        "unit": f"{candidate_id}@{member_id}",
        "checks": checks,
        "stage_a_comparison": stage_a_check,
        "pixel_coupon_objective": {"observed": pixel_value, "stage_a": stage_a_value},
        "log_ratio_score": score,
        "execution": execution,
        "provenance": provenance(members),
        "full_test_suite": "run separately: python -m pytest -q",
    }
    write_json(stage_directory / "smoke_gate.json", _json_safe(gate))
    return gate


def run_calibrate(
    *,
    data_directory: str | Path,
    characterization_directory: str | Path,
    output_directory: str | Path,
    workers: int = DEFAULT_WORKERS,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """The 17 frozen candidates on the 9 calibration members (153 units), with per-candidate scores."""

    member_ids = require_stage_members("calibrate", CALIBRATION_MEMBERS)
    stage_directory = Path(output_directory).expanduser().resolve() / "calibrate"
    members, frame_rows = _stage_inputs(data_directory, characterization_directory, member_ids)
    candidates = {c["candidate_id"]: c for c in frozen_design_candidates()}
    units = [(cid, m) for cid in candidates for m in member_ids]
    if len(units) != DESIGN_UNIT_COUNT:
        raise WindowCalibrationError(f"expected {DESIGN_UNIT_COUNT} design units, built {len(units)}")
    jobs = build_unit_jobs("calibrate", units, candidates, members, frame_rows, characterization_directory=characterization_directory)
    execution = run_units(stage_directory, jobs, members, workers=workers, progress=progress)
    payloads = load_units(stage_directory, units)
    scores = _scores_for(list(candidates), payloads, member_ids, CALIBRATION_CONDITIONS)
    manifest = {
        "schema": SCHEMA,
        "patch": PATCH_VERSION,
        "stage": "calibrate",
        "complete": all(_unit_ok(p) for p in payloads.values()),
        "candidates": list(candidates.values()),
        "units": _unit_table(payloads, stage_directory),
        "scores": scores,
        "execution": execution,
        "provenance": provenance(members),
        "guardrails": {"held_out_members_used": False, "full_campaign_dispatched": False, "production_semantics_changed": False, "workers_wrote_files": False},
    }
    write_json(stage_directory / "stage_manifest.json", _json_safe(manifest))
    return manifest


def _completed_stage(output: Path, stage: str) -> dict[str, Any]:
    path = output / stage / "stage_manifest.json"
    if not path.is_file():
        raise WindowCalibrationError(f"stage {stage!r} has not run: {path}")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not manifest.get("complete"):
        raise WindowCalibrationError(f"stage {stage!r} is incomplete; rerun it to resume")
    return manifest


def run_confirm(
    *,
    data_directory: str | Path,
    characterization_directory: str | Path,
    output_directory: str | Path,
    workers: int = DEFAULT_WORKERS,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Surrogate on the 17 measured J values, then at most 3 guard-checked confirmation candidates (<= 27 units)."""

    output = Path(output_directory).expanduser().resolve()
    calibrate = _completed_stage(output, "calibrate")
    member_ids = require_stage_members("confirm", CALIBRATION_MEMBERS)
    design = {c["candidate_id"]: c for c in calibrate["candidates"]}
    scores = calibrate["scores"]
    unrankable = sorted(cid for cid, s in scores.items() if s["status"] != "PASS")
    if unrankable:
        raise WindowCalibrationError(f"design candidates without a valid objective: {unrankable}")
    proposal = propose_confirmation({cid: c["coded"] for cid, c in design.items()}, {cid: float(scores[cid]["J"]) for cid in design})
    candidates = {p["candidate_id"]: candidate_record(p["candidate_id"], from_coded(p["x"]), "confirmation") for p in proposal["confirmation_candidates"]}
    stage_directory = output / "confirm"
    stage_directory.mkdir(parents=True, exist_ok=True)
    write_json(stage_directory / "confirmation_proposal.json", _json_safe({**proposal, "candidates": list(candidates.values())}))
    execution: dict[str, Any] = {"units_run": 0, "units_reused": 0}
    payloads: dict[tuple[str, str], dict[str, Any]] = {}
    if candidates:
        members, frame_rows = _stage_inputs(data_directory, characterization_directory, member_ids)
        units = [(cid, m) for cid in candidates for m in member_ids]
        jobs = build_unit_jobs("confirm", units, candidates, members, frame_rows, characterization_directory=characterization_directory)
        execution = run_units(stage_directory, jobs, members, workers=workers, progress=progress)
        payloads = load_units(stage_directory, units)
    else:
        members = {}
    confirm_scores = _scores_for(list(candidates), payloads, member_ids, CALIBRATION_CONDITIONS) if candidates else {}
    manifest = {
        "schema": SCHEMA,
        "patch": PATCH_VERSION,
        "stage": "confirm",
        "complete": all(_unit_ok(p) for p in payloads.values()),
        "proposal_sha256": sha256_file(stage_directory / "confirmation_proposal.json"),
        "candidates": list(candidates.values()),
        "units": _unit_table(payloads, stage_directory) if payloads else [],
        "scores": confirm_scores,
        "execution": execution,
        "provenance": provenance(members) if members else {"members_read": [], "held_out_members_read": []},
        "guardrails": {"held_out_members_used": False, "full_campaign_dispatched": False, "production_semantics_changed": False, "workers_wrote_files": False},
    }
    write_json(stage_directory / "stage_manifest.json", _json_safe(manifest))
    return manifest


def run_freeze(*, output_directory: str | Path) -> dict[str, Any]:
    """Reading C and ``selection_freeze.json``; nothing is run and no held-out member is touched."""

    output = Path(output_directory).expanduser().resolve()
    calibrate, confirm = _completed_stage(output, "calibrate"), _completed_stage(output, "confirm")
    candidates = {c["candidate_id"]: c for c in [*calibrate["candidates"], *confirm["candidates"]]}
    scores = {**calibrate["scores"], **confirm["scores"]}
    selection = select_candidate(scores, candidates)
    proposal = json.loads((output / "confirm" / "confirmation_proposal.json").read_text(encoding="utf-8"))
    held_out_read = sorted(set(calibrate["provenance"]["held_out_members_read"]) | set(confirm["provenance"]["held_out_members_read"]))
    if held_out_read:
        raise WindowCalibrationError(f"held-out members were read before the freeze: {held_out_read}")
    selected = selection["selected"]
    freeze = {
        "schema": "lpbf_patch22_4_3_2_selection_freeze",
        "patch": PATCH_VERSION,
        "objective_contract_version": OBJECTIVE_CONTRACT_VERSION,
        "reading_C": selection["reading_C"],
        "selected": {**candidates[selected], "J": scores[selected]["J"], "e_H": scores[selected]["e_H"], "e_W": scores[selected]["e_W"], "fraction_peak_above_boiling": scores[selected]["fraction_peak_above_boiling"]},
        "J_min": selection["J_min"],
        "near_best": [{**candidates[cid], "J": scores[cid]["J"], "e_H": scores[cid]["e_H"], "e_W": scores[cid]["e_W"]} for cid in selection["near_best"]],
        "e_set": [{**candidates[cid], "J": scores[cid]["J"], "e_H": scores[cid]["e_H"], "e_W": scores[cid]["e_W"]} for cid in selection["e_set"]],
        "edge": selection["edge"],
        "ranking": selection["ranking"],
        "surrogate": {"r_squared": proposal["fit"]["r_squared"], "loo_rmse": proposal["fit"]["loo_rmse"], "minimum": proposal["minimum"], "flat_valley": proposal["flat_valley"]},
        "calibration_members": list(CALIBRATION_MEMBERS),
        "calibration_conditions": list(CALIBRATION_CONDITIONS),
        "held_out_members_read_before_freeze": held_out_read,
        "inputs": {
            "calibrate_units_sha256": {u["work_unit_id"]: u["unit_sha256"] for u in calibrate["units"]},
            "confirm_units_sha256": {u["work_unit_id"]: u["unit_sha256"] for u in confirm["units"]},
            "confirmation_proposal_sha256": confirm["proposal_sha256"],
            "member_sha256": calibrate["provenance"]["member_sha256"],
            "calibrate_git_commit": calibrate["provenance"]["git_commit"],
            "module_sha256": calibrate["provenance"]["module_sha256"],
            "objective_module_sha256": calibrate["provenance"]["objective_module_sha256"],
            "plan_sha256": calibrate["provenance"]["plan_sha256"],
        },
        "git_commit": git_metadata(REPO_ROOT)["commit"],
    }
    freeze = _json_safe(freeze)  # hash exactly what is written (non-finite values become null)
    freeze["content_sha256"] = canonical_sha256(freeze)
    stage_directory = output / "freeze"
    write_json(stage_directory / "selection_freeze.json", freeze)
    reading = {"schema": SCHEMA, "patch": PATCH_VERSION, "stage": "freeze", "reading_C": selection["reading_C"], "selection": selection, "scores": scores, "candidates": list(candidates.values()), "surrogate": proposal}
    write_json(stage_directory / "calibration_reading.json", _json_safe(reading))
    return {"freeze": freeze, "freeze_path": str(stage_directory / "selection_freeze.json"), "freeze_sha256": sha256_file(stage_directory / "selection_freeze.json")}


def freeze_committed_at_head(path: Path) -> bool | None:
    """Optional extra check in a git clone: does HEAD hold this freeze? ``None`` when git or ``.git`` is absent."""

    if git_metadata(REPO_ROOT)["commit"] is None:
        return None
    try:
        relative = path.relative_to(REPO_ROOT).as_posix()
        committed = subprocess.run(["git", "show", f"HEAD:{relative}"], capture_output=True, check=True, cwd=REPO_ROOT).stdout
        return canonical_sha256(json.loads(committed.decode("utf-8"))) == canonical_sha256(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, subprocess.CalledProcessError):
        return False


def verify_committed_freeze(freeze_file: str | Path, expected_sha256: str) -> dict[str, Any]:
    """The freeze must be the release's recorded freeze, self-consistent, and match the SHA-256 given on the command line.

    The release-internal record is ``data/final_model.json`` (``selected_parameters.selection_freeze_sha256``), so
    the check needs no git metadata and passes identically in a clone and in a source ZIP. In a clone, HEAD is
    compared as well, as an additional aid only (``freeze_committed_at_head``); it never fails the check.
    """

    path = Path(freeze_file).expanduser().resolve()
    if not path.is_file():
        raise WindowCalibrationError(f"freeze file not found: {path}")
    digest = sha256_file(path)
    if digest != str(expected_sha256).strip().lower():
        raise WindowCalibrationError("freeze file SHA-256 differs from the one given")
    try:
        path.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise WindowCalibrationError("freeze file must be inside the repository") from exc
    try:
        freeze = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise WindowCalibrationError("freeze file is not JSON") from exc
    verified = verify_freeze_content(freeze)
    recorded = load_final_model()["selected_parameters"]["selection_freeze_sha256"]
    if digest != recorded:
        raise WindowCalibrationError("freeze file is not the release's recorded selection freeze (data/final_model.json)")
    verified["freeze_committed_at_head"] = freeze_committed_at_head(path)
    return verified


def verify_freeze_content(freeze: Any) -> dict[str, Any]:
    """The freeze's self-hash verifies, it is this patch's freeze, and it records no held-out read."""

    if not isinstance(freeze, Mapping) or freeze.get("schema") != "lpbf_patch22_4_3_2_selection_freeze":
        raise WindowCalibrationError("not a Patch 22.4.3.2 selection freeze")
    body = {key: value for key, value in freeze.items() if key != "content_sha256"}
    if freeze.get("content_sha256") != canonical_sha256(body):
        raise WindowCalibrationError("freeze content hash does not verify")
    if body.get("held_out_members_read_before_freeze"):
        raise WindowCalibrationError("freeze records held-out reads before the freeze")
    return dict(freeze)


def run_evaluate(
    *,
    data_directory: str | Path,
    characterization_directory: str | Path,
    output_directory: str | Path,
    freeze_file: str | Path,
    freeze_sha256: str,
    workers: int = DEFAULT_WORKERS,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """After the owner's go-ahead: the E-set on the 15 evaluation members; the selected one also on calibration, with fields."""

    freeze = verify_committed_freeze(freeze_file, freeze_sha256)
    member_ids = require_stage_members("evaluate", (*EVALUATION_MEMBERS, *CALIBRATION_MEMBERS), freeze_verified=True)
    selected = str(freeze["selected"]["candidate_id"])
    candidates = {c["candidate_id"]: candidate_record(c["candidate_id"], c["coordinates"], c["origin"]) for c in freeze["e_set"]}
    if selected not in candidates:
        raise WindowCalibrationError("the selected candidate is not in the frozen E-set")
    units = [(cid, m) for cid in candidates for m in EVALUATION_MEMBERS] + [(selected, m) for m in CALIBRATION_MEMBERS]
    capture = [(selected, m) for m in (*EVALUATION_MEMBERS, *CALIBRATION_MEMBERS)]
    stage_directory = Path(output_directory).expanduser().resolve() / "evaluate"
    members, frame_rows = _stage_inputs(data_directory, characterization_directory, member_ids)
    jobs = build_unit_jobs("evaluate", units, candidates, members, frame_rows, characterization_directory=characterization_directory, capture_fields=capture)
    execution = run_units(stage_directory, jobs, members, workers=workers, progress=progress)
    payloads = load_units(stage_directory, units)
    records = member_records()

    def group_score(cid: str, group: Sequence[str]) -> dict[str, Any]:
        conditions = sorted({records[m]["condition_id"] for m in group})
        return score_candidate(cid, [payloads[(cid, m)] for m in group], member_ids=list(group), condition_ids=conditions)

    calibration_score = group_score(selected, CALIBRATION_MEMBERS)
    e_calibration = {str(c["candidate_id"]): {"H": c["e_H"], "W": c["e_W"]} for c in freeze["e_set"]}
    e_calibration[selected] = {"H": calibration_score["e_H"], "W": calibration_score["e_W"]}
    readings: dict[str, Any] = {"V": {}, "X": None}
    for cid in candidates:
        held_out = group_score(cid, IN_WINDOW_HELD_OUT)
        cross = group_score(cid, [CROSS_CAMPAIGN_HELD_OUT])
        readings["V"][cid] = {
            "role": "selected" if cid == selected else "near_best_descriptive",
            "e_calibration": e_calibration[cid],
            "held_out": held_out,
            **reading_v(e_calibration[cid], {"H": held_out["e_H"], "W": held_out["e_W"]}),
            "cross_campaign_20260904_part_5": {"score": cross, **reading_v(e_calibration[cid], {"H": cross["e_H"], "W": cross["e_W"]})},
        }
    readings["V_reading"] = readings["V"][selected]["reading"]
    coupons = []
    for m in OUT_OF_WINDOW:
        score = group_score(selected, [m])
        row = (score["coupon_rows"] or [{}])[0]
        coupons.append(
            {
                "member_identity": m,
                "group": "blind" if m in OUT_OF_WINDOW_BLIND else "examined",
                **{key: records[m][key] for key in ("condition_id", "power_W", "speed_mm_s", "ved_J_mm3")},
                "median_r_H": row.get("median_r_H"),
                "median_r_W": row.get("median_r_W"),
                "e_H": score["e_H"],
                "e_W": score["e_W"],
                "coverage": score["coverage"],
                "coverage_flag": score["coverage_flag"],
                "fraction_peak_above_boiling": score["fraction_peak_above_boiling"],
            }
        )
    readings["X"] = {"coupons": coupons, **reading_x(coupons)}
    calibration_stage = "calibrate" if freeze["selected"]["origin"] == "frozen_design" else "confirm"
    calibration_stage_directory = Path(output_directory).expanduser().resolve() / calibration_stage
    if (calibration_stage_directory / "units").is_dir():
        original = load_units(calibration_stage_directory, [(selected, m) for m in CALIBRATION_MEMBERS])
        calibration_records_reproduced: bool | None = all(payloads[key]["frame_records"] == original[key]["frame_records"] for key in original)
    else:
        # A standalone rerun of this stage (the recorded run's calibration stages live in another directory): the
        # selected candidate's calibration-member units are compared with the recorded ones by their SHA-256 instead.
        calibration_records_reproduced = None
    manifest = {
        "schema": SCHEMA,
        "patch": PATCH_VERSION,
        "stage": "evaluate",
        "complete": all(_unit_ok(p) for p in payloads.values()),
        "freeze_sha256": sha256_file(Path(freeze_file).expanduser().resolve()),
        "freeze_content_sha256": freeze["content_sha256"],
        "selected": selected,
        "e_set": list(candidates),
        "calibration_score_selected": calibration_score,
        "calibration_records_reproduced": calibration_records_reproduced,
        "readings": readings,
        "units": _unit_table(payloads, stage_directory),
        "execution": execution,
        "provenance": provenance(members),
        "guardrails": {"held_out_used_after_committed_freeze_only": True, "full_campaign_dispatched": False, "production_semantics_changed": False, "workers_wrote_files": False},
    }
    write_json(stage_directory / "stage_manifest.json", _json_safe(manifest))
    return manifest


# ---------------------------------------------------------------------- CLI


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Patch 22.4.3.2 narrow-window calibration (never dispatches the 272-unit campaign)")
    parser.add_argument("stage", choices=("smoke", "calibrate", "confirm", "freeze", "evaluate"))
    parser.add_argument("--data-dir")
    parser.add_argument("--characterization-dir")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIRECTORY)
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS, help="Windows-spawn workers (default 4; 1 = serial)")
    parser.add_argument("--freeze-file", help="evaluate: the committed selection_freeze.json")
    parser.add_argument("--freeze-sha256", help="evaluate: SHA-256 of the committed freeze file")
    args = parser.parse_args(argv)
    if args.stage != "freeze" and not (args.data_dir and args.characterization_dir):
        parser.error("--data-dir and --characterization-dir are required for this stage")
    if args.stage == "evaluate" and not (args.freeze_file and args.freeze_sha256):
        parser.error("evaluate requires --freeze-file and --freeze-sha256")

    def progress(done: int, total: int, unit: Mapping[str, Any]) -> None:
        flag = "" if unit["ok"] else "  INCOMPLETE"
        print(f"unit {done}/{total}: {unit['candidate_id']} {unit['member_identity']} ({unit['requested_frame_count']} frames, {unit['elapsed_s']} s){flag}", flush=True)

    common = {"data_directory": args.data_dir, "characterization_directory": args.characterization_dir, "output_directory": args.output_dir}
    try:
        if args.stage == "smoke":
            gate = run_smoke(**common, progress=progress)
            print(json.dumps({"status": gate["status"], "checks": {k: (v["pass"] if isinstance(v, Mapping) else v) for k, v in gate["checks"].items()}, "J": gate["log_ratio_score"]["J"]}, indent=2))
            return 0 if gate["status"] == SMOKE_PASS else 1
        if args.stage == "calibrate":
            manifest = run_calibrate(**common, workers=args.workers, progress=progress)
        elif args.stage == "confirm":
            manifest = run_confirm(**common, workers=args.workers, progress=progress)
        elif args.stage == "freeze":
            result = run_freeze(output_directory=args.output_dir)
            print(json.dumps({"reading_C": result["freeze"]["reading_C"], "selected": result["freeze"]["selected"]["candidate_id"], "J_min": result["freeze"]["J_min"], "freeze_path": result["freeze_path"], "freeze_sha256": result["freeze_sha256"]}, indent=2))
            return 0
        else:
            manifest = run_evaluate(**common, freeze_file=args.freeze_file, freeze_sha256=args.freeze_sha256, workers=args.workers, progress=progress)
    except WindowCalibrationError as exc:
        print(f"FAIL_PATCH_22_4_3_2_{args.stage.upper()}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"stage": manifest["stage"], "complete": manifest["complete"], "execution": manifest["execution"]}, indent=2))
    return 0 if manifest["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
