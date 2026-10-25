"""Patch 22.4.3 real parallel coarse-calibration execution.

Patch 22.4.3 executes the Patch 22.4.2-authorized 17 x 16 coarse thermal
campaign against the frozen calibration partition.  It preserves the accepted
99-cell production window, Patch 22.3.5 laser-associated H/W semantics, and
the Patch 22.4.1 hierarchical all-observation objective.

The module is deliberately split into three layers:

* deterministic preflight binds runtime HDF5 members and portable frame tables
  to the already-authorized 272 immutable campaign work units;
* Windows-spawn workers execute one candidate x coupon thermal trial and return
  provenance-bound scientific payloads without writing shared artifacts;
* the parent checkpoints each completed work unit immediately, reconciles all
  272 identities, evaluates the frozen hierarchical objective, and emits a
  review bundle.  No regional refinement or held-out validation is authorized
  by this patch automatically.

Patch 22.3.5.2 locks campaign dispatch.  The Patch 22.4.2 authorization was
revoked by the association recovery sequence, so ``run_search`` and the thermal
worker fail closed until Patch 22.4.3.2 sets ``CAMPAIGN_DISPATCH_AUTHORIZED_BY``
in its own reviewed change.  The non-thermal preflight stays available.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
import csv
import json
import math
from multiprocessing import get_context
from pathlib import Path
import traceback
from typing import Any, Mapping, Sequence
import zipfile

from lpbf.calibration_contract import (
    COEFFICIENT_ORDER,
    Patch21GlobalParameterPolicy,
    condition_id,
    member_identity,
)
from lpbf.execution.campaign_provenance import (
    CampaignExecutionManifest,
    CampaignWorkUnit,
    deterministic_result_relative_path,
    reconcile_result_records,
    result_record,
    simulation_job_for_work_unit,
    validate_result_record,
    write_result_once,
)
from lpbf.execution.work_units import SimulationJob
from lpbf.data.full_coupon_manifest import EXPECTED_MEMBER_COUNT
from lpbf.experiments.dataset import DatasetMember, resolve_full_coupon_members
from lpbf.hierarchical_objective import FrameSetContract, evaluate_hierarchical_objective
from lpbf.infrastructure import (
    canonical_sha256,
    read_json,
    sha256_file,
    write_csv_rows,
    write_json,
)
from lpbf.model.laser_component_association import POLICY_VERSION as PRODUCTION_HW_ASSOCIATION_POLICY_VERSION
from lpbf.scored_frame_rule import SCORED_FRAME_RULE_VERSION, apply_scored_frame_rule, scored_frame_indices
from lpbf.model.production_hw import PRODUCTION_HW_DEFINITION, PRODUCTION_HW_SEMANTICS_VERSION
from lpbf.patch22_4_1_calibration_readiness import build_freeze as build_patch22_4_1_freeze
from lpbf.patch22_4_2_parallel_coarse_calibration import (
    EXPECTED_CALIBRATION_CONDITIONS,
    EXPECTED_CALIBRATION_MEMBERS,
    EXPECTED_CANDIDATES,
    EXPECTED_WORKERS,
    EXPECTED_WORK_UNITS,
    WINDOW_CELLS,
    _coarse_design,
    _validate_accepted_core_hashes,
    build_authorization_record,
    build_coarse_calibration_manifest,
)

PATCH_VERSION = "22.4.3.1"
SCHEMA = "lpbf_patch22_4_3_1_parallel_coarse_calibration_execution"
PREFLIGHT_STATUS = "PASS_PATCH_22_4_3_REAL_COARSE_CALIBRATION_PREFLIGHT"
REVIEW_STATUS = "READY_FOR_PATCH_22_4_3_COARSE_CALIBRATION_SCIENTIFIC_REVIEW"
FAIL_STATUS = "FAIL_CLOSED_PATCH_22_4_3_PARALLEL_COARSE_CALIBRATION_EXECUTION"
WORK_UNIT_PAYLOAD_SCHEMA = "lpbf_patch22_4_3_1_coarse_calibration_work_unit_payload"
MINIMUM_SUCCESSFUL_CANDIDATES_FOR_REFINEMENT_REVIEW = 12

# Patch 22.3.5.2 campaign dispatch lock.  Only Patch 22.4.3.2 may lift it, by
# setting CAMPAIGN_DISPATCH_AUTHORIZED_BY = "22.4.3.2" after its gates pass.
# Patch 22.3.7 (F3): a trial completes with undefined frames; they carry a reason
# and are excluded from residuals with coverage reported.  "reject" is the
# historical all-or-nothing behavior and remains the default for old callers.
UNDEFINED_OBSERVATION_POLICY = "record_undefined"
CAMPAIGN_DISPATCH_LOCK_PATCH = "22.3.5.2"
CAMPAIGN_DISPATCH_REQUIRED_AUTHORIZER = "22.4.3.2"
CAMPAIGN_DISPATCH_LOCKED_STATUS = "BLOCKED_PATCH_22_3_5_2_CAMPAIGN_DISPATCH_LOCKED"
CAMPAIGN_DISPATCH_AUTHORIZED_BY: str | None = None

# This is the frozen 24-member process-condition contract used by the
# accepted calibration/validation partition.  It is intentionally explicit at
# the execution boundary so a swapped or edited manifest cannot silently
# change the physical condition assigned to a work unit.
EXPECTED_PROCESS_CONDITIONS: dict[str, tuple[tuple[float, float], ...]] = {
    "20260730": (
        (140.0, 850.0), (150.0, 900.0), (160.0, 950.0),
        (170.0, 1000.0), (180.0, 1050.0), (190.0, 1100.0),
    ),
    "20260731": (
        (140.0, 850.0), (150.0, 900.0), (160.0, 950.0),
        (170.0, 1000.0), (180.0, 1050.0), (190.0, 1100.0),
    ),
    "20260904": (
        (140.0, 600.0), (140.0, 1000.0), (140.0, 1400.0),
        (180.0, 600.0), (180.0, 1000.0), (180.0, 1400.0),
    ),
    "20260910": (
        (140.0, 700.0), (160.0, 700.0), (180.0, 700.0),
        (140.0, 1200.0), (160.0, 1200.0), (180.0, 1200.0),
    ),
}
EXPECTED_SPOT_DIAMETER_MM = 0.08

_ROOT = Path(__file__).resolve().parents[2]
_DESIGN_PATH = _ROOT / "src" / "lpbf" / "data" / "patch21_3_coarse_global_search_design.json"


class Patch2243Error(RuntimeError):
    """Raised when the Patch 22.4.3 execution contract cannot be honored."""


class CampaignDispatchLocked(Patch2243Error):
    """Raised when thermal campaign dispatch is attempted while the Patch 22.3.5.2 lock is active."""


def _require_campaign_dispatch_authorized() -> None:
    if CAMPAIGN_DISPATCH_AUTHORIZED_BY != CAMPAIGN_DISPATCH_REQUIRED_AUTHORIZER:
        raise CampaignDispatchLocked(
            f"{CAMPAIGN_DISPATCH_LOCKED_STATUS}: the 272-work-unit campaign authorization was revoked; "
            f"only Patch {CAMPAIGN_DISPATCH_REQUIRED_AUTHORIZER} may lift the "
            f"Patch {CAMPAIGN_DISPATCH_LOCK_PATCH} dispatch lock"
        )


@dataclass(frozen=True)
class PreflightBundle:
    manifest: CampaignExecutionManifest
    jobs: tuple[SimulationJob, ...]
    frame_set_contract: FrameSetContract
    base_rows: tuple[Mapping[str, Any], ...]
    preflight_record: Mapping[str, Any]




def _json_safe(value: Any) -> Any:
    """Return finite JSON-compatible diagnostics without fabricating scientific values."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    # NumPy scalar-like values are normalized through float/int where possible.
    try:
        if hasattr(value, "item"):
            return _json_safe(value.item())
    except Exception:
        pass
    return str(value)

def _parse_bool(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes"}


def _optional_float(value: Any) -> float | None:
    if value in (None, "", "None"):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return number


def _find_frame_file(source: Path, member: DatasetMember) -> Path:
    expected_set = str(member.acquisition_set_id)
    expected_part = int(member.coupon_position)
    expected_portable_identity = member.portable_identity_text
    direct_names = (
        f"{expected_set}_part_{expected_part}_{member.layer_name}",
        f"{expected_set}_part_{expected_part}",
    )
    candidates = {
        root / "members" / name / "frame_observations.csv"
        for root in (source, source / "patch21_3_0_characterization")
        for name in direct_names
        if (root / "members" / name / "frame_observations.csv").is_file()
    }
    candidates.update(source.rglob("frame_observations.csv"))
    matching_member: list[Path] = []
    matching_portable_identity: list[Path] = []
    for path in sorted(candidates):
        try:
            with path.open("r", encoding="utf-8", newline="") as handle:
                row = next(csv.DictReader(handle), None)
            if not row:
                continue
            if (
                str(row.get("acquisition_set_id")) == expected_set
                and int(float(row.get("part_number"))) == expected_part
            ):
                matching_member.append(path)
                if str(row.get("portable_member_identity")) == expected_portable_identity:
                    matching_portable_identity.append(path)
        except (OSError, StopIteration, TypeError, ValueError, csv.Error):
            continue
    if len(matching_portable_identity) == 1:
        return matching_portable_identity[0]
    if len(matching_portable_identity) > 1:
        raise Patch2243Error(
            "ambiguous portable frame characterization files for "
            f"{expected_set}:part_{expected_part}: "
            + ", ".join(str(path) for path in matching_portable_identity)
        )
    if matching_member:
        raise Patch2243Error(
            "portable frame characterization identity mismatch for "
            f"{expected_set}:part_{expected_part}; expected {expected_portable_identity}"
        )
    raise Patch2243Error(
        f"portable frame_observations.csv is missing for {expected_set}:part_{expected_part}"
    )


def _portable_frame_rows(path: Path, member: DatasetMember) -> list[dict[str, Any]]:
    required = {
        "acquisition_set_id",
        "part_number",
        "portable_member_identity",
        "frame_index",
        "mapping_status",
        "laser_on",
        "scan_track_id",
        "H_pixels",
        "W_pixels",
        "hw_status",
        "eligible_melt_pool_observation",
    }
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = set(reader.fieldnames or ())
        missing = required - columns
        if missing:
            raise Patch2243Error(
                f"frame table {path} is missing columns: {sorted(missing)}"
            )
        output: list[dict[str, Any]] = []
        canonical = member_identity(member.acquisition_set_id, member.coupon_position)
        for raw in reader:
            observed_identity = str(raw.get("portable_member_identity") or "").strip()
            if observed_identity != member.portable_identity_text:
                raise Patch2243Error(
                    f"frame row portable_member_identity mismatch in {path}: "
                    f"{observed_identity!r} != {member.portable_identity_text!r}"
                )
            try:
                observed_set = str(raw.get("acquisition_set_id"))
                observed_part = int(float(raw.get("part_number")))
            except (TypeError, ValueError) as exc:
                raise Patch2243Error(
                    f"frame row has malformed coupon identity in {path}"
                ) from exc
            if observed_set != str(member.acquisition_set_id) or observed_part != int(
                member.coupon_position
            ):
                raise Patch2243Error(
                    f"frame row coupon identity mismatch in {path}: "
                    f"{observed_set}:part_{observed_part} != "
                    f"{member.acquisition_set_id}:part_{member.coupon_position}"
                )
            if str(raw.get("mapping_status")) != "valid_mapped" or not _parse_bool(
                raw.get("laser_on")
            ):
                continue
            hw_status = str(raw.get("hw_status") or "")
            eligible = _parse_bool(raw.get("eligible_melt_pool_observation"))
            h = _optional_float(raw.get("H_pixels"))
            w = _optional_float(raw.get("W_pixels"))
            if eligible:
                observation_status = (
                    "ELIGIBLE_ZERO_FOOTPRINT"
                    if hw_status == "zero_footprint" or h == 0.0 or w == 0.0
                    else "ELIGIBLE_FINITE_HW"
                )
            elif hw_status == "nonfinite":
                observation_status = "INVALID_NONFINITE_HW"
            elif hw_status == "negative":
                observation_status = "INVALID_NEGATIVE_HW"
            else:
                observation_status = "INELIGIBLE_NOT_OBJECTIVE"
            output.append(
                {
                    "member_identity": canonical,
                    "portable_member_identity": str(raw["portable_member_identity"]),
                    "acquisition_set_id": str(raw["acquisition_set_id"]),
                    "part_number": int(float(raw["part_number"])),
                    "power_W": float(member.power_W),
                    "speed_mm_s": float(member.nominal_speed_mm_s),
                    "spot_diameter_mm": float(member.spot_diameter_mm),
                    "source_date": member.source_date,
                    "process_condition_provenance": dict(
                        member.process_condition_provenance
                    ),
                    "exact_condition_id": condition_id(
                        member.power_W, member.nominal_speed_mm_s
                    ),
                    "scan_track_id": str(raw["scan_track_id"]),
                    "frame_index": int(float(raw["frame_index"])),
                    "experimental_H_pixels": h,
                    "experimental_W_pixels": w,
                    "observation_eligible": bool(eligible),
                    "observation_status": observation_status,
                    "source_observation_status": hw_status,
                    "status": "PASS",
                    "failure": None,
                }
            )
    if not output:
        raise Patch2243Error(f"no mapped laser-on frame rows found in {path}")
    return output


def _dataset_member_context(member: DatasetMember) -> dict[str, Any]:
    return {
        "set_id": int(member.set_id),
        "dataset_member_id": int(member.dataset_member_id),
        "coupon_position": int(member.coupon_position),
        "path": str(Path(member.path).resolve()),
        "sha256": str(member.sha256),
        "power_W": float(member.power_W),
        "nominal_speed_mm_s": float(member.nominal_speed_mm_s),
        "spot_diameter_mm": float(member.spot_diameter_mm),
        "campaign_id": str(member.campaign_id),
        "acquisition_set_id": str(member.acquisition_set_id),
        "layer_name": str(member.layer_name),
        "expected_filename": member.expected_filename,
        "portable_member_identity": member.portable_identity_text,
        "source_date": member.source_date,
        "process_condition_provenance": dict(member.process_condition_provenance),
    }


def _dataset_member_from_context(value: Mapping[str, Any]) -> DatasetMember:
    return DatasetMember(
        set_id=int(value["set_id"]),
        dataset_member_id=int(value["dataset_member_id"]),
        coupon_position=int(value["coupon_position"]),
        path=Path(str(value["path"])),
        sha256=str(value["sha256"]),
        power_W=float(value["power_W"]),
        nominal_speed_mm_s=float(value["nominal_speed_mm_s"]),
        spot_diameter_mm=float(value["spot_diameter_mm"]),
        campaign_id=str(value["campaign_id"]),
        acquisition_set_id=str(value["acquisition_set_id"]),
        layer_name=str(value["layer_name"]),
        expected_filename=(
            None
            if value.get("expected_filename") is None
            else str(value["expected_filename"])
        ),
        source_date=(
            None if value.get("source_date") is None else str(value["source_date"])
        ),
        process_condition_provenance=dict(
            value.get("process_condition_provenance") or {}
        ),
    )


def _trial_gate_failures(
    evaluation: Mapping[str, Any],
    expected_frame_count: int,
    *,
    undefined_observation_policy: str = "reject",
) -> list[str]:
    failures: list[str] = []
    if evaluation.get("status") != "PASS" or evaluation.get("stage") != "complete":
        failures.append("atomic_evaluator_not_complete_pass")
    observations = list(evaluation.get("observations") or [])
    if len(observations) != expected_frame_count:
        failures.append("all_observation_count_mismatch")
    seen_frames: set[int] = set()
    for observation in observations:
        try:
            frame_index = int(observation["frame_index"])
            exp_h = float(observation["experimental_H_pixels"])
            exp_w = float(observation["experimental_W_pixels"])
            sim_h = float(observation["simulated_H_pixels"])
            sim_w = float(observation["simulated_W_pixels"])
            if frame_index in seen_frames:
                failures.append("duplicate_evaluated_frame_index")
            seen_frames.add(frame_index)
            if not all(math.isfinite(v) for v in (exp_h, exp_w)):
                failures.append("nonfinite_primary_observation")
            if not all(math.isfinite(v) for v in (sim_h, sim_w)):
                # Patch 22.3.7: an explicitly undefined frame is allowed under record_undefined.
                undefined = str(observation.get("observation_status") or "").startswith("UNDEFINED_")
                if not (undefined_observation_policy == UNDEFINED_OBSERVATION_POLICY and undefined):
                    failures.append("nonfinite_primary_observation")
                continue
            if sim_h < 0.0 or sim_w < 0.0:
                failures.append("negative_simulated_H_or_W")
            if (sim_h == 0.0) != (sim_w == 0.0):
                failures.append("partial_zero_simulated_footprint")
        except (KeyError, TypeError, ValueError):
            failures.append("malformed_all_observation_record")
    trace = dict(evaluation.get("temperature_trace") or {})
    telemetry = dict(evaluation.get("execution_telemetry") or {})
    energy = dict(evaluation.get("energy_accounting") or {})
    try:
        if int(trace["thermal_substep_count"]) <= 0:
            failures.append("thermal_substep_count_invalid")
        if int(trace["thermal_substep_count"]) != int(telemetry["directional_step_count"]):
            failures.append("thermal_trace_telemetry_mismatch")
    except (KeyError, TypeError, ValueError):
        failures.append("thermal_trace_or_telemetry_missing")
    try:
        if abs(float(energy["energy_balance_relative_error"])) > 1.0e-9:
            failures.append("energy_balance_relative_error")
    except (KeyError, TypeError, ValueError):
        failures.append("energy_accounting_missing_or_nonnumeric")
    if not isinstance(evaluation.get("high_temperature_diagnostics"), Mapping):
        failures.append("high_temperature_diagnostics_missing")
    if telemetry.get("temperature_clipping_used") is not False:
        failures.append("temperature_clipping_used_or_unreported")
    if telemetry.get("every_substep_temperature_trace_complete") is not True:
        failures.append("every_substep_temperature_trace_incomplete")
    if telemetry.get("production_hw_semantics_version") != PRODUCTION_HW_SEMANTICS_VERSION:
        failures.append("production_hw_semantics_version_drift")
    if telemetry.get("production_hw_definition") != PRODUCTION_HW_DEFINITION:
        failures.append("production_hw_definition_missing_or_drifted")
    if telemetry.get("production_hw_association_policy_version") != (
        PRODUCTION_HW_ASSOCIATION_POLICY_VERSION
    ):
        failures.append("production_hw_association_policy_version_missing_or_drifted")
    if evaluation.get("temperature_clipping_permitted") is not False:
        failures.append("evaluation_temperature_clipping_contract_drift")
    return sorted(set(failures))


def _compact_diagnostics(evaluation: Mapping[str, Any]) -> dict[str, Any]:
    trace = dict(evaluation.get("temperature_trace") or {})
    energy = dict(evaluation.get("energy_accounting") or {})
    telemetry = dict(evaluation.get("execution_telemetry") or {})
    high_t = dict(evaluation.get("high_temperature_diagnostics") or {})
    failure = dict(evaluation.get("failure") or {})
    return {
        "atomic_evaluation_status": evaluation.get("status"),
        "atomic_evaluation_stage": evaluation.get("stage"),
        "atomic_failure_code": failure.get("code"),
        "atomic_failure_stage": failure.get("stage"),
        "atomic_failure_message": failure.get("message"),
        "solver_entered": failure.get("solver_entered"),
        "simulated_outputs_emitted": failure.get("simulated_outputs_emitted"),
        "raw_global_Tmax_K": trace.get("raw_global_Tmax_K"),
        "thermal_substep_count": trace.get("thermal_substep_count"),
        "energy_balance_relative_error": energy.get("energy_balance_relative_error"),
        "maximum_abs_source_power_relative_error": telemetry.get(
            "maximum_abs_source_power_relative_error"
        ),
        "temperature_clipping_used": telemetry.get("temperature_clipping_used"),
        "every_substep_temperature_trace_complete": telemetry.get(
            "every_substep_temperature_trace_complete"
        ),
        "maximum_boundary_temperature_K": high_t.get("maximum_boundary_temperature_K"),
        "production_hw_definition": telemetry.get("production_hw_definition"),
        "production_hw_semantics_version": telemetry.get(
            "production_hw_semantics_version"
        ),
        "production_hw_association_policy_version": telemetry.get(
            "production_hw_association_policy_version"
        ),
    }


def _row_is_scored(row: Mapping[str, Any]) -> bool:
    if "scored_frame" in row:
        return bool(row["scored_frame"])
    return bool(row.get("observation_eligible"))


def _frame_records_from_evaluation(
    evaluation: Mapping[str, Any],
    *,
    base_rows: Sequence[Mapping[str, Any]],
    undefined_observation_policy: str = "reject",
) -> tuple[list[dict[str, Any]], list[str]]:
    scored_rows = [row for row in base_rows if _row_is_scored(row)]
    failures = _trial_gate_failures(
        evaluation, len(scored_rows), undefined_observation_policy=undefined_observation_policy
    )
    atomic_failure = dict(evaluation.get("failure") or {})
    if failures:
        failure_record = {
            "code": "PATCH_22_4_3_TRIAL_GATE_FAILURE",
            "gate_failures": failures,
            "atomic_failure": atomic_failure or None,
        }
        rows = []
        for base in base_rows:
            row = dict(base)
            row["status"] = "FAIL"
            row["failure"] = failure_record
            row.pop("simulated_H_pixels", None)
            row.pop("simulated_W_pixels", None)
            rows.append(row)
        return rows, failures

    observations = {
        int(row["frame_index"]): dict(row)
        for row in list(evaluation.get("observations") or [])
        if isinstance(row, Mapping) and row.get("frame_index") is not None
    }
    records: list[dict[str, Any]] = []
    for base in base_rows:
        row = dict(base)
        eligible = bool(row.get("observation_eligible"))
        if eligible and not _row_is_scored(row):
            # Patch 22.3.7 (F1): excluded by the scored-frame rule; retained without H/W.
            row.pop("simulated_H_pixels", None)
            row.pop("simulated_W_pixels", None)
            row["status"] = "EXCLUDED"
            row["failure"] = None
            records.append(row)
            continue
        if eligible:
            observation = observations.get(int(row["frame_index"]))
            if observation is None:
                failure_record = {
                    "code": "PATCH_22_4_3_MISSING_SIMULATED_FRAME_RECORD",
                    "frame_index": row["frame_index"],
                }
                failed_rows = []
                for failed_base in base_rows:
                    failed = dict(failed_base)
                    failed["status"] = "FAIL"
                    failed["failure"] = failure_record
                    failed_rows.append(failed)
                return failed_rows, ["missing_simulated_frame_record"]
            status = str(observation.get("observation_status") or "SCORED")
            if status.startswith("UNDEFINED_"):
                # Patch 22.3.7 (F3): undefined stays undefined; never fabricated as zero.
                row["simulated_H_pixels"] = None
                row["simulated_W_pixels"] = None
                row["status"] = "UNDEFINED"
                row["undefined_reason"] = str(
                    observation.get("undefined_reason") or status[len("UNDEFINED_"):]
                )
                row["failure"] = None
                records.append(row)
                continue
            row["simulated_H_pixels"] = observation.get("simulated_H_pixels")
            row["simulated_W_pixels"] = observation.get("simulated_W_pixels")
        row["status"] = "PASS"
        row["failure"] = None
        records.append(row)
    return records, []


# Worker-local caches avoid re-reading portable frame tables repeatedly.  They
# deliberately do not bypass the atomic evaluator's per-trial dataset identity
# validation or file hash verification.
_WORKER_FRAME_CACHE: dict[tuple[str, str], tuple[dict[str, Any], ...]] = {}


def _thermal_worker(job: SimulationJob) -> dict[str, Any]:
    """Spawn-safe worker for one candidate x coupon thermal evaluation."""

    _require_campaign_dispatch_authorized()
    context = job.experiment_context_dict
    candidate_id = str(context["parameter_point_id"])
    member = _dataset_member_from_context(dict(context["dataset_member"]))
    frame_path = Path(str(context["frame_observations_path"]))
    expected_frame_sha256 = str(context["frame_observations_sha256"])
    cache_key = (job.member_identity, str(frame_path))
    try:
        provenance = _payload_provenance(job, context)
        if cache_key not in _WORKER_FRAME_CACHE:
            actual = sha256_file(frame_path)
            if actual != expected_frame_sha256:
                raise Patch2243Error(
                    f"frame table identity drifted for {job.member_identity}: {actual} != {expected_frame_sha256}"
                )
            _WORKER_FRAME_CACHE[cache_key] = tuple(_portable_frame_rows(frame_path, member))
        base_rows = apply_scored_frame_rule([dict(row) for row in _WORKER_FRAME_CACHE[cache_key]])
        eligible_indices = scored_frame_indices(base_rows)
        if not eligible_indices:
            raise Patch2243Error(f"no scored objective frames for {job.member_identity}")

        coords = job.candidate_coordinates_dict
        policy = Patch21GlobalParameterPolicy.from_values(
            *(float(coords[name]) for name in COEFFICIENT_ORDER)
        )
        from lpbf.calibration_evaluation import CalibrationExecutionScope, evaluate_calibration_trial

        scope = CalibrationExecutionScope(
            scope_id=f"patch22_4_3_1:{candidate_id}:{job.member_identity}",
            observation_frame_indices=eligible_indices,
            trial_context={
                "patch": PATCH_VERSION,
                "objective_branch": "hierarchical_all_observation",
                "candidate_id": candidate_id,
                "candidate_coordinates": coords,
                "campaign_manifest_sha256": context["campaign_manifest_sha256"],
                "work_unit_id": job.work_unit_id,
                "production_hw_semantics_version": PRODUCTION_HW_SEMANTICS_VERSION,
                "production_hw_definition": PRODUCTION_HW_DEFINITION,
                "validation_partition_used": False,
                "parameter_selection_performed": False,
                "parameter_fitting_performed": False,
                "regional_refinement_performed": False,
                "production_hw_association_policy_version": PRODUCTION_HW_ASSOCIATION_POLICY_VERSION,
                "scored_frame_rule_version": SCORED_FRAME_RULE_VERSION,
                "undefined_observation_policy": UNDEFINED_OBSERVATION_POLICY,
            },
            unenclosed_contour_policy="record_nan",
            window_cells=WINDOW_CELLS,
            undefined_observation_policy=UNDEFINED_OBSERVATION_POLICY,
        )
        evaluation = evaluate_calibration_trial(member, policy, scope).to_dict()
        frame_records, gate_failures = _frame_records_from_evaluation(
            evaluation, base_rows=base_rows, undefined_observation_policy=UNDEFINED_OBSERVATION_POLICY
        )
        safe_evaluation = _json_safe(evaluation)
        passed = not gate_failures
        diagnostics = _compact_diagnostics(evaluation)
        payload = {
            **provenance,
            "schema": WORK_UNIT_PAYLOAD_SCHEMA,
            "schema_version": PATCH_VERSION,
            "status": "PASS" if passed else "FAIL",
            "work_unit_id": job.work_unit_id,
            "candidate_id": candidate_id,
            "member_identity": job.member_identity,
            "candidate_coordinates": coords,
            "window_cells": WINDOW_CELLS,
            "production_hw_definition": PRODUCTION_HW_DEFINITION,
            "production_hw_semantics_version": PRODUCTION_HW_SEMANTICS_VERSION,
            "production_hw_association_policy_version": PRODUCTION_HW_ASSOCIATION_POLICY_VERSION,
            "scored_frame_rule_version": SCORED_FRAME_RULE_VERSION,
            "undefined_observation_policy": UNDEFINED_OBSERVATION_POLICY,
            "scored_frame_count": sum(
                1
                for row in frame_records
                if row.get("status") == "PASS" and bool(row.get("observation_eligible"))
            ),
            "undefined_frame_count": sum(1 for row in frame_records if row.get("status") == "UNDEFINED"),
            "excluded_frame_count": sum(1 for row in frame_records if row.get("status") == "EXCLUDED"),
            "frame_record_count": len(frame_records),
            "eligible_frame_count": len(eligible_indices),
            "frame_records": frame_records,
            "gate_failures": gate_failures,
            "diagnostics": diagnostics,
            "atomic_evaluation_sha256": canonical_sha256(safe_evaluation),
            "atomic_failure_evaluation": None if passed else safe_evaluation,
            "validation_partition_used": False,
            "parameter_selection_performed": False,
            "parameter_fitting_performed": False,
        }
        payload = _json_safe(payload)
        payload["payload_sha256"] = canonical_sha256(
            {k: v for k, v in payload.items() if k != "payload_sha256"}
        )
        return payload
    except Exception as exc:
        failure = {
            "type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
        }
        payload = {
            **_payload_provenance(job, context),
            "schema": WORK_UNIT_PAYLOAD_SCHEMA,
            "schema_version": PATCH_VERSION,
            "status": "FAIL",
            "work_unit_id": job.work_unit_id,
            "candidate_id": candidate_id,
            "member_identity": job.member_identity,
            "candidate_coordinates": job.candidate_coordinates_dict,
            "window_cells": WINDOW_CELLS,
            "production_hw_definition": PRODUCTION_HW_DEFINITION,
            "production_hw_semantics_version": PRODUCTION_HW_SEMANTICS_VERSION,
            "production_hw_association_policy_version": PRODUCTION_HW_ASSOCIATION_POLICY_VERSION,
            "frame_record_count": 0,
            "eligible_frame_count": 0,
            "frame_records": [],
            "gate_failures": ["worker_exception"],
            "diagnostics": {
                "atomic_evaluation_status": "WORKER_EXCEPTION",
                "atomic_failure_code": "PATCH_22_4_3_WORKER_EXCEPTION",
                "atomic_failure_message": str(exc),
            },
            "worker_exception": failure,
            "atomic_evaluation_sha256": None,
            "atomic_failure_evaluation": None,
            "validation_partition_used": False,
            "parameter_selection_performed": False,
            "parameter_fitting_performed": False,
        }
        payload = _json_safe(payload)
        payload["payload_sha256"] = canonical_sha256(
            {k: v for k, v in payload.items() if k != "payload_sha256"}
        )
        return payload


def _candidate_role_map() -> dict[str, str]:
    design = _coarse_design()
    return {
        str(row["candidate_id"]): str(row["role"])
        for row in design["search_design"]["candidates"]
    }


def _validate_process_condition_manifest(
    members: Sequence[DatasetMember],
) -> tuple[dict[str, Any], ...]:
    """Validate the complete 24-member physical process-condition mapping."""

    if len(members) != EXPECTED_MEMBER_COUNT:
        raise Patch2243Error(
            f"process-condition manifest requires {EXPECTED_MEMBER_COUNT} members, "
            f"got {len(members)}"
        )
    observed: set[tuple[str, int]] = set()
    rows: list[dict[str, Any]] = []
    for member in members:
        set_id = str(member.acquisition_set_id)
        part = int(member.coupon_position)
        key = (set_id, part)
        if key in observed:
            raise Patch2243Error(
                f"duplicate process-condition member identity: {set_id}:part_{part}"
            )
        observed.add(key)
        expected_conditions = EXPECTED_PROCESS_CONDITIONS.get(set_id)
        if expected_conditions is None or not 1 <= part <= len(expected_conditions):
            raise Patch2243Error(
                f"unexpected process-condition member: {set_id}:part_{part}"
            )
        expected_power, expected_speed = expected_conditions[part - 1]
        actual = (
            float(member.power_W),
            float(member.nominal_speed_mm_s),
            float(member.spot_diameter_mm),
        )
        expected = (expected_power, expected_speed, EXPECTED_SPOT_DIAMETER_MM)
        if any(
            not math.isclose(observed_value, expected_value, rel_tol=0.0, abs_tol=1.0e-12)
            for observed_value, expected_value in zip(actual, expected, strict=True)
        ):
            raise Patch2243Error(
                f"process-condition mismatch for {set_id}:part_{part}: "
                f"observed={actual}, expected={expected}"
            )
        source_date = None if member.source_date is None else str(member.source_date).strip()
        if not source_date:
            raise Patch2243Error(
                f"source_date is missing for {set_id}:part_{part}"
            )
        provenance = dict(member.process_condition_provenance)
        if str(provenance.get("source_date", "")).strip() != source_date:
            raise Patch2243Error(
                f"source_date provenance mismatch for {set_id}:part_{part}"
            )
        rows.append(
            {
                "member_identity": member_identity(set_id, part),
                "portable_member_identity": member.portable_identity_text,
                "acquisition_set_id": set_id,
                "part_number": part,
                "source_date": source_date,
                "power_W": float(member.power_W),
                "speed_mm_s": float(member.nominal_speed_mm_s),
                "spot_diameter_mm": float(member.spot_diameter_mm),
                "exact_condition_id": condition_id(member.power_W, member.nominal_speed_mm_s),
                "process_condition_provenance": provenance,
            }
        )
    expected_keys = {
        (set_id, part)
        for set_id, conditions in EXPECTED_PROCESS_CONDITIONS.items()
        for part in range(1, len(conditions) + 1)
    }
    if observed != expected_keys:
        raise Patch2243Error(
            "process-condition manifest membership mismatch: "
            f"missing={sorted(expected_keys - observed)}, "
            f"unexpected={sorted(observed - expected_keys)}"
        )
    return tuple(sorted(rows, key=lambda row: (row["acquisition_set_id"], row["part_number"])))


def _payload_provenance(job: SimulationJob, context: Mapping[str, Any]) -> dict[str, Any]:
    """Return immutable work-unit and preflight metadata for every payload."""

    dataset = dict(context["dataset_member"])
    return {
        "campaign_manifest_sha256": str(context["campaign_manifest_sha256"]),
        "preflight_sha256": str(context["preflight_sha256"]),
        "frame_observations_sha256": str(context["frame_observations_sha256"]),
        "frame_set_identity_digest": str(context["frame_set_identity_digest"]),
        "portable_member_identity": str(dataset["portable_member_identity"]),
        "input_sha256": str(context["input_sha256"]),
        "acquisition_set_id": str(context["acquisition_set_id"]),
        "coupon_position": int(context["coupon_position"]),
        "condition_id": str(context["condition_id"]),
        "process_condition_id": str(context["process_condition_id"]),
        "nominal_power_W": float(context["nominal_power_W"]),
        "nominal_speed_mm_s": float(context["nominal_speed_mm_s"]),
        "spot_diameter_mm": float(context["spot_diameter_mm"]),
        "source_date": None if context.get("source_date") is None else str(context["source_date"]),
        "process_condition_provenance": dict(context["process_condition_provenance"]),
        "parameter_sweep_id": str(context["parameter_sweep_id"]),
        "parameter_sha256": str(context["parameter_sha256"]),
    }


def _preflight_record(
    *,
    data_directory: Path,
    characterization_directory: Path,
    workers: int,
) -> PreflightBundle:
    if workers != EXPECTED_WORKERS:
        raise Patch2243Error(
            f"Patch 22.4.3 production campaign requires exactly {EXPECTED_WORKERS} workers"
        )
    if not data_directory.is_dir():
        raise Patch2243Error(f"data directory does not exist: {data_directory}")
    if not characterization_directory.is_dir():
        raise Patch2243Error(
            f"characterization directory does not exist: {characterization_directory}"
        )

    authorization = build_authorization_record(
        workers=EXPECTED_WORKERS, execute_spawn_test=False
    )
    if authorization.get("status") != (
        "PASS_PATCH_22_4_2_PARALLEL_COARSE_CALIBRATION_CAMPAIGN_AUTHORIZED"
    ):
        raise Patch2243Error("Patch 22.4.2 authorization contract does not pass")
    if not _validate_accepted_core_hashes():
        raise Patch2243Error("accepted numerical-core hashes have drifted")

    freeze = build_patch22_4_1_freeze()
    calibration_ids = set(freeze["campaign"]["calibration_members"])
    validation_ids = set(freeze["campaign"]["validation_members"])
    members = tuple(resolve_full_coupon_members(data_directory))
    member_map = {
        member_identity(member.acquisition_set_id, member.coupon_position): member
        for member in members
    }
    if len(member_map) != 24:
        raise Patch2243Error("canonical runtime data directory did not resolve 24 coupons")
    if set(member_map) != calibration_ids | validation_ids:
        raise Patch2243Error("runtime dataset membership disagrees with frozen 24-coupon partition")
    process_condition_manifest = _validate_process_condition_manifest(members)
    process_condition_manifest_sha256 = canonical_sha256(process_condition_manifest)

    selected = {identity: member_map[identity] for identity in sorted(calibration_ids)}
    frame_paths: dict[str, Path] = {}
    frame_hashes: dict[str, str] = {}
    base_rows_by_member: dict[str, list[dict[str, Any]]] = {}
    for identity, member in selected.items():
        frame_path = _find_frame_file(characterization_directory, member)
        frame_paths[identity] = frame_path
        frame_hashes[identity] = sha256_file(frame_path)
        base_rows_by_member[identity] = _portable_frame_rows(frame_path, member)

    base_rows = [
        row
        for identity in sorted(base_rows_by_member)
        for row in base_rows_by_member[identity]
    ]
    frame_set_contract = FrameSetContract.from_records(base_rows)
    condition_ids = {str(row["exact_condition_id"]) for row in base_rows}
    eligible_count = sum(bool(row["observation_eligible"]) for row in base_rows)
    if len(condition_ids) != EXPECTED_CALIBRATION_CONDITIONS:
        raise Patch2243Error(
            f"expected {EXPECTED_CALIBRATION_CONDITIONS} calibration conditions, got {len(condition_ids)}"
        )
    if eligible_count <= 0:
        raise Patch2243Error("no eligible calibration observations were found")

    manifest = build_coarse_calibration_manifest()
    if len(manifest.work_units) != EXPECTED_WORK_UNITS:
        raise Patch2243Error("coarse execution manifest no longer has 272 work units")
    if any(unit.member_identity in validation_ids for unit in manifest.work_units):
        raise Patch2243Error("held-out validation member leaked into production dispatch")

    candidate_counts = Counter(unit.parameter_point_id for unit in manifest.work_units)
    member_counts = Counter(unit.member_identity for unit in manifest.work_units)
    gates = {
        "patch22_4_2_authorization_revalidated": True,
        "accepted_numerical_core_hashes_unchanged": True,
        "runtime_dataset_resolves_exactly_24_coupons": len(member_map) == 24,
        "dispatch_contains_exactly_16_calibration_coupons": set(member_counts) == calibration_ids,
        "held_out_validation_members_absent": not any(
            identity in validation_ids for identity in member_counts
        ),
        "frozen_12_calibration_conditions_present": len(condition_ids) == EXPECTED_CALIBRATION_CONDITIONS,
        "frozen_17_candidates_present": len(candidate_counts) == EXPECTED_CANDIDATES,
        "each_candidate_has_16_coupon_trials": all(
            value == EXPECTED_CALIBRATION_MEMBERS for value in candidate_counts.values()
        ),
        "each_calibration_coupon_has_17_candidate_trials": all(
            value == EXPECTED_CANDIDATES for value in member_counts.values()
        ),
        "manifest_has_272_work_units": len(manifest.work_units) == EXPECTED_WORK_UNITS,
        "production_window_is_99_cells": WINDOW_CELLS == 99,
        "production_hw_semantics_is_22_3_7": PRODUCTION_HW_SEMANTICS_VERSION == "22.3.7",
        "production_hw_definition_is_laser_associated_contour": (
            PRODUCTION_HW_DEFINITION
            == "laser_associated_component_interpolated_liquidus_contour"
        ),
        "full_24_coupon_process_condition_manifest_pass": True,
        "process_condition_manifest_has_expected_spot_size": all(
            math.isclose(
                float(row["spot_diameter_mm"]),
                EXPECTED_SPOT_DIAMETER_MM,
                rel_tol=0.0,
                abs_tol=1.0e-12,
            )
            for row in process_condition_manifest
        ),
        "frame_set_has_eligible_observations": eligible_count > 0,
        "requested_worker_count_is_4": workers == EXPECTED_WORKERS,
    }
    all_pass = all(gates.values())
    preflight = {
        "schema": "lpbf_patch22_4_3_real_coarse_calibration_preflight",
        "schema_version": PATCH_VERSION,
        "status": PREFLIGHT_STATUS if all_pass else FAIL_STATUS,
        "all_preflight_gates_pass": all_pass,
        "preflight_gates": gates,
        "campaign_manifest_sha256": manifest.manifest_sha256,
        "candidate_count": EXPECTED_CANDIDATES,
        "calibration_member_count": EXPECTED_CALIBRATION_MEMBERS,
        "calibration_condition_count": EXPECTED_CALIBRATION_CONDITIONS,
        "work_unit_count": EXPECTED_WORK_UNITS,
        "worker_count": workers,
        "production_window_cells": WINDOW_CELLS,
        "production_hw_definition": PRODUCTION_HW_DEFINITION,
        "production_hw_semantics_version": PRODUCTION_HW_SEMANTICS_VERSION,
        "production_hw_association_policy_version": PRODUCTION_HW_ASSOCIATION_POLICY_VERSION,
        "process_condition_manifest": list(process_condition_manifest),
        "process_condition_manifest_sha256": process_condition_manifest_sha256,
        "frame_set_contract": frame_set_contract.to_dict(),
        "total_mapped_laser_on_frame_count": len(base_rows),
        "total_eligible_objective_frame_count": eligible_count,
        "member_frame_inputs": [
            {
                "member_identity": identity,
                "portable_member_identity": selected[identity].portable_identity_text,
                "frame_observations_path": str(frame_paths[identity]),
                "frame_observations_sha256": frame_hashes[identity],
                "input_sha256": selected[identity].sha256,
                "acquisition_set_id": selected[identity].acquisition_set_id,
                "coupon_position": selected[identity].coupon_position,
                "nominal_power_W": selected[identity].power_W,
                "nominal_speed_mm_s": selected[identity].nominal_speed_mm_s,
                "spot_diameter_mm": selected[identity].spot_diameter_mm,
                "source_date": selected[identity].source_date,
                "mapped_laser_on_frame_count": len(base_rows_by_member[identity]),
                "eligible_objective_frame_count": sum(
                    bool(row["observation_eligible"])
                    for row in base_rows_by_member[identity]
                ),
            }
            for identity in sorted(selected)
        ],
        "data_directory": str(data_directory),
        "characterization_directory": str(characterization_directory),
        "validation_partition_used": False,
        "thermal_simulation_performed": False,
        "parameter_selection_performed": False,
    }
    preflight["preflight_sha256"] = canonical_sha256(preflight)
    if not all_pass:
        raise Patch2243Error("Patch 22.4.3 preflight gates did not all pass")

    jobs: list[SimulationJob] = []
    for unit in manifest.work_units:
        member = selected[unit.member_identity]
        jobs.append(
            simulation_job_for_work_unit(
                unit,
                frame_index=0,
                window_cells=WINDOW_CELLS,
                extra_experiment_context={
                    "patch22_4_3_1_real_thermal_execution": True,
                    "data_directory": str(data_directory),
                    "characterization_directory": str(characterization_directory),
                    "dataset_member": _dataset_member_context(member),
                    "frame_observations_path": str(frame_paths[unit.member_identity]),
                    "frame_observations_sha256": frame_hashes[unit.member_identity],
                    "frame_set_identity_digest": frame_set_contract.frame_identity_digest,
                    "preflight_sha256": preflight["preflight_sha256"],
                    "input_sha256": unit.input_sha256,
                    "condition_id": unit.condition_id,
                    "parameter_sha256": unit.parameter_sha256,
                    "process_condition_id": condition_id(
                        member.power_W, member.nominal_speed_mm_s
                    ),
                    "production_hw_semantics_version": PRODUCTION_HW_SEMANTICS_VERSION,
                    "production_hw_definition": PRODUCTION_HW_DEFINITION,
                    "validation_partition_permitted": False,
                },
            )
        )
    return PreflightBundle(
        manifest=manifest,
        jobs=tuple(jobs),
        frame_set_contract=frame_set_contract,
        base_rows=tuple(dict(row) for row in base_rows),
        preflight_record=preflight,
    )


def run_preflight(
    *,
    data_directory: str | Path,
    characterization_directory: str | Path,
    output_directory: str | Path,
    workers: int = EXPECTED_WORKERS,
) -> dict[str, Any]:
    output = Path(output_directory).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    bundle = _preflight_record(
        data_directory=Path(data_directory).expanduser().resolve(),
        characterization_directory=Path(characterization_directory).expanduser().resolve(),
        workers=int(workers),
    )
    write_json(output / "PATCH_22_4_3_REAL_COARSE_CALIBRATION_PREFLIGHT.json", dict(bundle.preflight_record))
    manifest_payload = {
        "schema": "lpbf_patch22_4_3_real_coarse_calibration_execution_manifest",
        "schema_version": PATCH_VERSION,
        "campaign_id": bundle.manifest.campaign_id,
        "canonical_dataset_manifest_sha256": bundle.manifest.canonical_dataset_manifest_sha256,
        "model_configuration_sha256": bundle.manifest.model_configuration_sha256,
        "production_semantics_id": bundle.manifest.production_semantics_id,
        "work_unit_count": len(bundle.manifest.work_units),
        "manifest_sha256": bundle.manifest.manifest_sha256,
        "frame_set_identity_digest": bundle.frame_set_contract.frame_identity_digest,
        "preflight_sha256": bundle.preflight_record["preflight_sha256"],
        "process_condition_manifest_sha256": bundle.preflight_record[
            "process_condition_manifest_sha256"
        ],
        "work_units": [
            unit.identity_record() | {"sequence_index": unit.sequence_index}
            for unit in bundle.manifest.work_units
        ],
    }
    write_json(output / "PATCH_22_4_3_REAL_COARSE_CALIBRATION_EXECUTION_MANIFEST.json", manifest_payload)
    return dict(bundle.preflight_record)


def _validate_payload(
    payload: Mapping[str, Any],
    unit: CampaignWorkUnit,
    *,
    expected_preflight_sha256: str | None = None,
    expected_frame_observations_sha256: str | None = None,
    expected_frame_set_identity_digest: str | None = None,
) -> None:
    if payload.get("schema") != WORK_UNIT_PAYLOAD_SCHEMA:
        raise Patch2243Error("unexpected Patch 22.4.3 work-unit payload schema")
    if payload.get("schema_version") != PATCH_VERSION:
        raise Patch2243Error("unexpected Patch 22.4.3 work-unit payload version")
    if payload.get("work_unit_id") != unit.work_unit_id:
        raise Patch2243Error("work-unit payload identity mismatch")
    if payload.get("candidate_id") != unit.parameter_point_id:
        raise Patch2243Error("work-unit payload candidate identity mismatch")
    if payload.get("member_identity") != unit.member_identity:
        raise Patch2243Error("work-unit payload member identity mismatch")
    coordinates = payload.get("candidate_coordinates")
    if not isinstance(coordinates, Mapping):
        raise Patch2243Error("work-unit payload candidate coordinates are missing")
    try:
        normalized_coordinates = {
            str(key): float(value) for key, value in coordinates.items()
        }
    except (TypeError, ValueError) as exc:
        raise Patch2243Error("work-unit payload candidate coordinates are malformed") from exc
    expected_coordinates = {
        str(key): float(value) for key, value in unit.parameter_values.items()
    }
    if normalized_coordinates != expected_coordinates:
        raise Patch2243Error("work-unit payload candidate coordinates do not match the work unit")
    if payload.get("parameter_sha256") != unit.parameter_sha256:
        raise Patch2243Error("work-unit payload parameter SHA-256 does not match the work unit")

    expected_metadata: dict[str, Any] = {
        "campaign_manifest_sha256": unit.canonical_manifest_sha256,
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
    }
    for key, expected_value in expected_metadata.items():
        if key not in payload:
            raise Patch2243Error(f"work-unit payload is missing provenance field: {key}")
        actual_value = payload.get(key)
        if isinstance(expected_value, float):
            try:
                matches = math.isclose(
                    float(actual_value), expected_value, rel_tol=0.0, abs_tol=1.0e-12
                )
            except (TypeError, ValueError):
                matches = False
        else:
            matches = actual_value == expected_value
        if not matches:
            raise Patch2243Error(
                f"work-unit payload provenance mismatch for {key}: "
                f"{actual_value!r} != {expected_value!r}"
            )

    payload_preflight_sha256 = str(payload.get("preflight_sha256") or "")
    if not payload_preflight_sha256:
        raise Patch2243Error("work-unit payload is missing preflight SHA-256")
    if expected_preflight_sha256 is not None and payload_preflight_sha256 != str(
        expected_preflight_sha256
    ):
        raise Patch2243Error("work-unit payload preflight provenance does not match the current run")
    payload_frame_sha256 = str(payload.get("frame_observations_sha256") or "")
    if not payload_frame_sha256:
        raise Patch2243Error("work-unit payload is missing characterization SHA-256")
    if expected_frame_observations_sha256 is not None and payload_frame_sha256 != str(
        expected_frame_observations_sha256
    ):
        raise Patch2243Error(
            "work-unit payload characterization provenance does not match the current frame table"
        )
    payload_frame_set_digest = str(payload.get("frame_set_identity_digest") or "")
    if not payload_frame_set_digest:
        raise Patch2243Error("work-unit payload is missing frame-set identity digest")
    if expected_frame_set_identity_digest is not None and payload_frame_set_digest != str(
        expected_frame_set_identity_digest
    ):
        raise Patch2243Error("work-unit payload frame-set identity digest drifted")
    if int(payload.get("window_cells", -1)) != WINDOW_CELLS:
        raise Patch2243Error("work-unit payload window drifted")
    if payload.get("production_hw_definition") != PRODUCTION_HW_DEFINITION:
        raise Patch2243Error("work-unit payload production H/W definition drifted")
    if payload.get("production_hw_semantics_version") != PRODUCTION_HW_SEMANTICS_VERSION:
        raise Patch2243Error("work-unit payload production H/W semantics drifted")
    if payload.get("production_hw_association_policy_version") != (
        PRODUCTION_HW_ASSOCIATION_POLICY_VERSION
    ):
        raise Patch2243Error("work-unit payload production H/W association policy drifted")
    expected = canonical_sha256(
        {k: v for k, v in dict(payload).items() if k != "payload_sha256"}
    )
    if payload.get("payload_sha256") != expected:
        raise Patch2243Error("work-unit payload hash mismatch")
    if payload.get("validation_partition_used") is not False:
        raise Patch2243Error("work-unit payload reports validation-partition use")
    if payload.get("parameter_selection_performed") is not False:
        raise Patch2243Error("work-unit payload reports unauthorized parameter selection")
    if payload.get("parameter_fitting_performed") is not False:
        raise Patch2243Error("work-unit payload reports unauthorized parameter fitting")


def _load_completed_records(
    *,
    manifest: CampaignExecutionManifest,
    result_root: Path,
    resume: bool,
    expected_preflight_sha256: str,
    expected_frame_observations_sha256: Mapping[str, str],
    expected_frame_set_identity_digest: str,
) -> tuple[list[dict[str, Any]], set[str]]:
    records: list[dict[str, Any]] = []
    completed: set[str] = set()
    for unit in manifest.work_units:
        path = result_root / deterministic_result_relative_path(unit)
        if not path.exists():
            continue
        if not resume:
            raise Patch2243Error(
                f"existing work-unit result found while --resume is disabled: {path}"
            )
        raw = read_json(path)
        if not isinstance(raw, dict):
            raise Patch2243Error(f"existing work-unit result is not a JSON object: {path}")
        validate_result_record(unit, raw)
        payload = raw.get("payload")
        if not isinstance(payload, Mapping):
            raise Patch2243Error(f"existing work-unit payload is malformed: {path}")
        _validate_payload(
            payload,
            unit,
            expected_preflight_sha256=expected_preflight_sha256,
            expected_frame_observations_sha256=expected_frame_observations_sha256.get(
                unit.member_identity
            ),
            expected_frame_set_identity_digest=expected_frame_set_identity_digest,
        )
        records.append(dict(raw))
        completed.add(unit.work_unit_id)
    return records, completed


def _candidate_summary(
    *,
    candidate_id: str,
    role: str,
    coordinates: Mapping[str, float],
    objective: Mapping[str, Any],
    payloads: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    passed = sum(payload.get("status") == "PASS" for payload in payloads)
    failed = len(payloads) - passed
    diagnostics = [dict(payload.get("diagnostics") or {}) for payload in payloads]

    def finite_values(key: str, *, absolute: bool = False) -> list[float]:
        values: list[float] = []
        for row in diagnostics:
            value = row.get(key)
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(number):
                values.append(abs(number) if absolute else number)
        return values

    tmax = finite_values("raw_global_Tmax_K")
    energy = finite_values("energy_balance_relative_error", absolute=True)
    source = finite_values("maximum_abs_source_power_relative_error", absolute=True)
    hierarchy = dict(objective.get("hierarchical_error_summaries") or {})
    row: dict[str, Any] = {
        "candidate_id": candidate_id,
        "candidate_role": role,
        **{name: float(coordinates[name]) for name in COEFFICIENT_ORDER},
        "objective_status": objective.get("status"),
        "objective_value": objective.get("objective_value"),
        "coverage_flag": objective.get("coverage_flag"),
        "low_coverage_coupons": list(objective.get("low_coverage_coupons") or []),
        "H_component_unweighted_condition_mean": objective.get(
            "H_component_unweighted_condition_mean"
        ),
        "W_component_unweighted_condition_mean": objective.get(
            "W_component_unweighted_condition_mean"
        ),
        "successful_trial_count": passed,
        "failed_trial_count": failed,
        "trial_failure_rate": failed / len(payloads) if payloads else 1.0,
        "maximum_raw_global_Tmax_K": max(tmax) if tmax else None,
        "minimum_raw_global_Tmax_K": min(tmax) if tmax else None,
        "maximum_abs_energy_balance_relative_error": max(energy) if energy else None,
        "maximum_abs_source_power_relative_error": max(source) if source else None,
        "coarse_rank": None,
        "coarse_incumbent_is_final_parameter_selection": False,
        "validation_partition_used": False,
        "regional_refinement_performed": False,
    }
    for level in ("frame", "track", "coupon", "condition"):
        metrics = dict(hierarchy.get(level) or {})
        for metric in (
            "H_bias_pixels",
            "W_bias_pixels",
            "H_RMSE_pixels",
            "W_RMSE_pixels",
            "H_RMSE_um",
            "W_RMSE_um",
        ):
            row[f"{level}_{metric}"] = metrics.get(metric)
    return row


def _trial_summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    diag = dict(payload.get("diagnostics") or {})
    return {
        "work_unit_id": payload.get("work_unit_id"),
        "candidate_id": payload.get("candidate_id"),
        "member_identity": payload.get("member_identity"),
        "portable_member_identity": payload.get("portable_member_identity"),
        "campaign_manifest_sha256": payload.get("campaign_manifest_sha256"),
        "preflight_sha256": payload.get("preflight_sha256"),
        "frame_observations_sha256": payload.get("frame_observations_sha256"),
        "frame_set_identity_digest": payload.get("frame_set_identity_digest"),
        "acquisition_set_id": payload.get("acquisition_set_id"),
        "coupon_position": payload.get("coupon_position"),
        "source_date": payload.get("source_date"),
        "nominal_power_W": payload.get("nominal_power_W"),
        "nominal_speed_mm_s": payload.get("nominal_speed_mm_s"),
        "spot_diameter_mm": payload.get("spot_diameter_mm"),
        "condition_id": payload.get("condition_id"),
        "process_condition_id": payload.get("process_condition_id"),
        "parameter_sweep_id": payload.get("parameter_sweep_id"),
        "parameter_sha256": payload.get("parameter_sha256"),
        "candidate_coordinates": payload.get("candidate_coordinates"),
        "parameter_fitting_performed": payload.get("parameter_fitting_performed"),
        "status": payload.get("status"),
        "frame_record_count": payload.get("frame_record_count"),
        "eligible_frame_count": payload.get("eligible_frame_count"),
        "gate_failures": payload.get("gate_failures"),
        "atomic_evaluation_status": diag.get("atomic_evaluation_status"),
        "atomic_evaluation_stage": diag.get("atomic_evaluation_stage"),
        "atomic_failure_code": diag.get("atomic_failure_code"),
        "atomic_failure_message": diag.get("atomic_failure_message"),
        "raw_global_Tmax_K": diag.get("raw_global_Tmax_K"),
        "energy_balance_relative_error": diag.get("energy_balance_relative_error"),
        "maximum_abs_source_power_relative_error": diag.get(
            "maximum_abs_source_power_relative_error"
        ),
        "temperature_clipping_used": diag.get("temperature_clipping_used"),
        "production_hw_semantics_version": payload.get(
            "production_hw_semantics_version"
        ),
        "production_hw_definition": payload.get("production_hw_definition"),
        "production_hw_association_policy_version": payload.get(
            "production_hw_association_policy_version"
        ),
    }


def _write_review_bundle(output: Path, files: Sequence[Path], failed_result_paths: Sequence[Path]) -> Path:
    destination = output / "patch22_4_3_coarse_calibration_review_bundle.zip"
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            if path.is_file():
                archive.write(path, arcname=path.relative_to(output).as_posix())
        for path in failed_result_paths:
            if path.is_file():
                archive.write(path, arcname=path.relative_to(output).as_posix())
    return destination


def _aggregate_and_write(
    *,
    output: Path,
    bundle: PreflightBundle,
    records: Sequence[Mapping[str, Any]],
    workers: int,
    reused_result_count: int,
) -> dict[str, Any]:
    reconciliation = reconcile_result_records(bundle.manifest, records)
    if not reconciliation["pass"]:
        raise Patch2243Error(
            "cannot aggregate coarse search because work-unit reconciliation did not pass"
        )
    by_work_unit = {str(record["work_unit_id"]): record for record in records}
    payloads_by_candidate: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for unit in bundle.manifest.work_units:
        record = by_work_unit[unit.work_unit_id]
        payload = record["payload"]
        _validate_payload(payload, unit)
        payloads_by_candidate[unit.parameter_point_id].append(payload)

    design = _coarse_design()
    candidate_rows = {
        str(row["candidate_id"]): row for row in design["search_design"]["candidates"]
    }
    objective_dir = output / "candidate_objectives"
    objective_dir.mkdir(parents=True, exist_ok=True)
    summaries: list[dict[str, Any]] = []
    trial_summaries: list[dict[str, Any]] = []
    candidate_objective_paths: list[Path] = []
    for candidate_id in [str(row["candidate_id"]) for row in design["search_design"]["candidates"]]:
        payloads = payloads_by_candidate[candidate_id]
        if len(payloads) != EXPECTED_CALIBRATION_MEMBERS:
            raise Patch2243Error(
                f"candidate {candidate_id} does not have 16 reconciled member payloads"
            )
        candidate_records: list[dict[str, Any]] = []
        # Infrastructure failures with no frame records still need to fail the
        # candidate closed while preserving the frozen frame-set identity.
        payload_map = {str(payload["member_identity"]): payload for payload in payloads}
        base_rows_by_member: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in bundle.base_rows:
            base_rows_by_member[str(record["member_identity"])].append(dict(record))
        for member_id, payload in payload_map.items():
            rows = [dict(row) for row in payload.get("frame_records") or []]
            if not rows:
                failure = {
                    "code": "PATCH_22_4_3_NO_FRAME_RECORDS_FROM_WORKER",
                    "worker_exception": payload.get("worker_exception"),
                    "gate_failures": payload.get("gate_failures"),
                }
                rows = []
                for base in base_rows_by_member[member_id]:
                    row = dict(base)
                    row["status"] = "FAIL"
                    row["failure"] = failure
                    rows.append(row)
            candidate_records.extend(rows)
        objective = evaluate_hierarchical_objective(
            candidate_records,
            frame_set_contract=bundle.frame_set_contract,
            candidate_id=candidate_id,
        )
        objective_payload = {
            "schema": "lpbf_patch22_4_3_candidate_hierarchical_objective",
            "schema_version": PATCH_VERSION,
            "candidate_id": candidate_id,
            "candidate_role": str(candidate_rows[candidate_id]["role"]),
            "candidate_coordinates": dict(candidate_rows[candidate_id]["coordinates"]),
            "objective": objective,
            "validation_partition_used": False,
            "parameter_selection_performed": False,
        }
        path = objective_dir / f"{candidate_id}.json"
        write_json(path, objective_payload)
        candidate_objective_paths.append(path)
        summaries.append(
            _candidate_summary(
                candidate_id=candidate_id,
                role=str(candidate_rows[candidate_id]["role"]),
                coordinates=dict(candidate_rows[candidate_id]["coordinates"]),
                objective=objective,
                payloads=payloads,
            )
        )
        trial_summaries.extend(_trial_summary(payload) for payload in payloads)

    successful = [
        row
        for row in summaries
        if row.get("objective_status") == "PASS" and row.get("objective_value") is not None
    ]
    successful.sort(key=lambda row: (float(row["objective_value"]), str(row["candidate_id"])))
    rank_by_id = {row["candidate_id"]: index for index, row in enumerate(successful, start=1)}
    summaries = [
        dict(row) | {"coarse_rank": rank_by_id.get(row["candidate_id"])} for row in summaries
    ]
    incumbent = successful[0] if successful else None
    successful_count = len(successful)
    coverage_flagged_count = sum(1 for row in successful if row.get("coverage_flag"))
    failed_candidate_count = EXPECTED_CANDIDATES - successful_count
    review_gate = successful_count >= MINIMUM_SUCCESSFUL_CANDIDATES_FOR_REFINEMENT_REVIEW

    candidate_csv = output / "PATCH_22_4_3_CANDIDATE_SUMMARIES.csv"
    trial_csv = output / "PATCH_22_4_3_TRIAL_SUMMARIES.csv"
    write_csv_rows(candidate_csv, summaries)
    write_csv_rows(trial_csv, trial_summaries)

    results = {
        "schema": SCHEMA,
        "schema_version": PATCH_VERSION,
        "status": REVIEW_STATUS,
        "campaign_manifest_sha256": bundle.manifest.manifest_sha256,
        "preflight_sha256": bundle.preflight_record["preflight_sha256"],
        "process_condition_manifest_sha256": bundle.preflight_record[
            "process_condition_manifest_sha256"
        ],
        "reconciliation": reconciliation,
        "candidate_count": EXPECTED_CANDIDATES,
        "calibration_member_count": EXPECTED_CALIBRATION_MEMBERS,
        "calibration_condition_count": EXPECTED_CALIBRATION_CONDITIONS,
        "work_unit_count": EXPECTED_WORK_UNITS,
        "parallel_worker_count": workers,
        "reused_completed_work_unit_count": reused_result_count,
        "newly_executed_work_unit_count": EXPECTED_WORK_UNITS - reused_result_count,
        "successful_candidate_count": successful_count,
        "coverage_flagged_candidate_count": coverage_flagged_count,
        "failed_candidate_count": failed_candidate_count,
        "minimum_successful_candidate_count_for_refinement_review": MINIMUM_SUCCESSFUL_CANDIDATES_FOR_REFINEMENT_REVIEW,
        "refinement_scientific_review_gate_met": review_gate,
        "coarse_incumbent": None if incumbent is None else dict(incumbent),
        "coarse_incumbent_is_final_parameter_selection": False,
        "candidate_summaries": summaries,
        "candidate_objective_directory": "candidate_objectives",
        "production_window_cells": WINDOW_CELLS,
        "production_hw_definition": PRODUCTION_HW_DEFINITION,
        "production_hw_semantics_version": PRODUCTION_HW_SEMANTICS_VERSION,
        "production_hw_association_policy_version": PRODUCTION_HW_ASSOCIATION_POLICY_VERSION,
        "hierarchical_all_observation_objective_used": True,
        "validation_partition_used_for_selection": False,
        "held_out_validation_performed": False,
        "preferred_parameter_values_selected": False,
        "regional_refinement_authorized": False,
        "focused_optimization_authorized": False,
        "held_out_validation_authorized": False,
        "parameter_fitting_performed": False,
        "thermal_search_performed": True,
        "accepted_numerical_core_modified": False,
        "production_hw_definition_changed": False,
        "next_action": "scientific_review_required_before_any_regional_refinement_authorization",
    }
    results_path = output / "PATCH_22_4_3_COARSE_CALIBRATION_RESULTS.json"
    write_json(results_path, results)

    status = {
        "schema": "lpbf_patch22_4_3_status",
        "schema_version": PATCH_VERSION,
        "status": REVIEW_STATUS,
        "all_work_units_reconciled": reconciliation["pass"],
        "candidate_count": EXPECTED_CANDIDATES,
        "calibration_member_count": EXPECTED_CALIBRATION_MEMBERS,
        "calibration_condition_count": EXPECTED_CALIBRATION_CONDITIONS,
        "coarse_work_unit_count": EXPECTED_WORK_UNITS,
        "parallel_worker_count": workers,
        "successful_candidate_count": successful_count,
        "coverage_flagged_candidate_count": coverage_flagged_count,
        "failed_candidate_count": failed_candidate_count,
        "refinement_scientific_review_gate_met": review_gate,
        "coarse_incumbent_candidate_id": None if incumbent is None else incumbent["candidate_id"],
        "coarse_incumbent_objective_value": None if incumbent is None else incumbent["objective_value"],
        "coarse_incumbent_is_final_parameter_selection": False,
        "production_window_cells": WINDOW_CELLS,
        "process_condition_manifest_sha256": bundle.preflight_record[
            "process_condition_manifest_sha256"
        ],
        "production_hw_definition": PRODUCTION_HW_DEFINITION,
        "production_hw_semantics_version": PRODUCTION_HW_SEMANTICS_VERSION,
        "production_hw_association_policy_version": PRODUCTION_HW_ASSOCIATION_POLICY_VERSION,
        "validation_partition_used_for_selection": False,
        "regional_refinement_authorized": False,
        "focused_optimization_authorized": False,
        "held_out_validation_authorized": False,
        "parameter_fitting_performed": False,
        "thermal_search_performed": True,
        "accepted_numerical_core_modified": False,
        "production_hw_definition_changed": False,
        "result_file": results_path.name,
        "review_bundle": "patch22_4_3_coarse_calibration_review_bundle.zip",
    }
    status_path = output / "PATCH_22_4_3_COARSE_CALIBRATION_STATUS.json"
    write_json(status_path, status)

    failed_paths: list[Path] = []
    for unit in bundle.manifest.work_units:
        payload = by_work_unit[unit.work_unit_id]["payload"]
        if payload.get("status") != "PASS":
            failed_paths.append(
                output / "work_units" / deterministic_result_relative_path(unit)
            )

    review_files = [
        output / "PATCH_22_4_3_REAL_COARSE_CALIBRATION_PREFLIGHT.json",
        output / "PATCH_22_4_3_REAL_COARSE_CALIBRATION_EXECUTION_MANIFEST.json",
        candidate_csv,
        trial_csv,
        results_path,
        status_path,
        *candidate_objective_paths,
    ]
    review_bundle = _write_review_bundle(output, review_files, failed_paths)
    status["review_bundle_sha256"] = sha256_file(review_bundle)
    write_json(status_path, status)
    return status


def run_search(
    *,
    data_directory: str | Path,
    characterization_directory: str | Path,
    output_directory: str | Path,
    workers: int = EXPECTED_WORKERS,
    resume: bool = False,
) -> dict[str, Any]:
    _require_campaign_dispatch_authorized()
    output = Path(output_directory).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    data_path = Path(data_directory).expanduser().resolve()
    characterization_path = Path(characterization_directory).expanduser().resolve()
    workers = int(workers)

    bundle = _preflight_record(
        data_directory=data_path,
        characterization_directory=characterization_path,
        workers=workers,
    )
    write_json(
        output / "PATCH_22_4_3_REAL_COARSE_CALIBRATION_PREFLIGHT.json",
        dict(bundle.preflight_record),
    )
    manifest_payload = {
        "schema": "lpbf_patch22_4_3_real_coarse_calibration_execution_manifest",
        "schema_version": PATCH_VERSION,
        "campaign_id": bundle.manifest.campaign_id,
        "canonical_dataset_manifest_sha256": bundle.manifest.canonical_dataset_manifest_sha256,
        "model_configuration_sha256": bundle.manifest.model_configuration_sha256,
        "production_semantics_id": bundle.manifest.production_semantics_id,
        "work_unit_count": len(bundle.manifest.work_units),
        "manifest_sha256": bundle.manifest.manifest_sha256,
        "frame_set_identity_digest": bundle.frame_set_contract.frame_identity_digest,
        "preflight_sha256": bundle.preflight_record["preflight_sha256"],
        "work_units": [
            unit.identity_record() | {"sequence_index": unit.sequence_index}
            for unit in bundle.manifest.work_units
        ],
    }
    write_json(
        output / "PATCH_22_4_3_REAL_COARSE_CALIBRATION_EXECUTION_MANIFEST.json",
        manifest_payload,
    )

    result_root = output / "work_units"
    result_root.mkdir(parents=True, exist_ok=True)
    expected_frame_hashes = {
        str(row["member_identity"]): str(row["frame_observations_sha256"])
        for row in bundle.preflight_record["member_frame_inputs"]
    }
    records, completed_ids = _load_completed_records(
        manifest=bundle.manifest,
        result_root=result_root,
        resume=resume,
        expected_preflight_sha256=str(bundle.preflight_record["preflight_sha256"]),
        expected_frame_observations_sha256=expected_frame_hashes,
        expected_frame_set_identity_digest=bundle.frame_set_contract.frame_identity_digest,
    )
    unit_by_id = {unit.work_unit_id: unit for unit in bundle.manifest.work_units}
    jobs = [job for job in bundle.jobs if job.work_unit_id not in completed_ids]
    total = EXPECTED_WORK_UNITS
    completed_count = len(records)
    if completed_count:
        print(
            f"Patch 22.4.3 resume: reusing {completed_count} / {total} validated work units",
            flush=True,
        )

    if jobs:
        executor = ProcessPoolExecutor(
            max_workers=workers,
            mp_context=get_context("spawn"),
        )
        pending = {executor.submit(_thermal_worker, job): job for job in jobs}
        try:
            for future in as_completed(pending):
                job = pending[future]
                unit = unit_by_id[str(job.work_unit_id)]
                try:
                    payload = future.result()
                except Exception as exc:
                    # A process/infrastructure exception is retained as a failed
                    # scientific work unit so the remaining campaign can complete.
                    payload = {
                        **_payload_provenance(job, job.experiment_context_dict),
                        "schema": WORK_UNIT_PAYLOAD_SCHEMA,
                        "schema_version": PATCH_VERSION,
                        "status": "FAIL",
                        "work_unit_id": job.work_unit_id,
                        "candidate_id": unit.parameter_point_id,
                        "member_identity": unit.member_identity,
                        "candidate_coordinates": job.candidate_coordinates_dict,
                        "window_cells": WINDOW_CELLS,
                        "production_hw_definition": PRODUCTION_HW_DEFINITION,
                        "production_hw_semantics_version": PRODUCTION_HW_SEMANTICS_VERSION,
                        "frame_record_count": 0,
                        "eligible_frame_count": 0,
                        "frame_records": [],
                        "gate_failures": ["process_pool_future_exception"],
                        "diagnostics": {
                            "atomic_evaluation_status": "PROCESS_POOL_EXCEPTION",
                            "atomic_failure_code": "PATCH_22_4_3_PROCESS_POOL_EXCEPTION",
                            "atomic_failure_message": str(exc),
                        },
                        "worker_exception": {
                            "type": type(exc).__name__,
                            "message": str(exc),
                        },
                        "atomic_evaluation_sha256": None,
                        "atomic_failure_evaluation": None,
                        "validation_partition_used": False,
                        "parameter_selection_performed": False,
                        "parameter_fitting_performed": False,
                    }
                    payload["payload_sha256"] = canonical_sha256(
                        {k: v for k, v in payload.items() if k != "payload_sha256"}
                    )
                _validate_payload(payload, unit)
                record = result_record(unit, payload, attempts=1)
                write_result_once(result_root, unit, record)
                records.append(record)
                completed_count += 1
                print(
                    f"Patch 22.4.3 completed {completed_count:3d} / {total}: "
                    f"{unit.parameter_point_id} | {unit.member_identity} | {payload['status']}",
                    flush=True,
                )
        finally:
            executor.shutdown(wait=True, cancel_futures=False)

    return _aggregate_and_write(
        output=output,
        bundle=bundle,
        records=records,
        workers=workers,
        reused_result_count=len(completed_ids),
    )


__all__ = [
    "PATCH_VERSION",
    "SCHEMA",
    "PREFLIGHT_STATUS",
    "REVIEW_STATUS",
    "FAIL_STATUS",
    "CAMPAIGN_DISPATCH_LOCKED_STATUS",
    "CampaignDispatchLocked",
    "Patch2243Error",
    "run_preflight",
    "run_search",
]
