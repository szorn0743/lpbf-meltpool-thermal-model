"""Patch 22.4.2 parallel coarse-calibration campaign authorization.

This patch is an execution-contract gate. It binds the accepted 17-point
coarse global design to the Patch 22.4.0 immutable work-unit identity layer,
filters dispatch to the 16 Patch 22.4.1 calibration coupons only, and verifies
Windows-spawn 4-worker scheduling with deterministic result reconciliation.

No thermal simulation or parameter selection is performed by this module.
Successful acceptance authorizes the subsequent real coarse thermal campaign.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import replace
import json
from pathlib import Path
from typing import Any, Mapping

from lpbf.execution.campaign_provenance import (
    CampaignExecutionManifest,
    CampaignStageSpec,
    ParameterPointSpec,
    PRODUCTION_SEMANTICS_ID,
    build_campaign_execution_manifest,
    canonical_coupon_roster,
    reconcile_result_records,
    result_record,
    simulation_job_for_work_unit,
)
from lpbf.execution.parallel import execute_parallel_jobs
from lpbf.execution.work_units import execute_serial_jobs, SimulationJob
from lpbf.infrastructure import canonical_sha256, sha256_file, write_json
from lpbf.model.laser_component_association import POLICY_VERSION as PRODUCTION_HW_ASSOCIATION_POLICY_VERSION
from lpbf.model.production_hw import PRODUCTION_HW_SEMANTICS_VERSION
from lpbf.patch22_4_1_calibration_readiness import build_freeze as build_patch22_4_1_freeze

PATCH_VERSION = "22.4.2"
SCHEMA = "lpbf_patch22_4_2_parallel_coarse_calibration_authorization"
STATUS = "PASS_PATCH_22_4_2_PARALLEL_COARSE_CALIBRATION_CAMPAIGN_AUTHORIZED"
FAIL_STATUS = "FAIL_PATCH_22_4_2_PARALLEL_COARSE_CALIBRATION_CAMPAIGN_AUTHORIZATION"
EXPECTED_WORKERS = 4
EXPECTED_CANDIDATES = 17
EXPECTED_ANCHORS = 5
EXPECTED_HALTON = 12
EXPECTED_CALIBRATION_MEMBERS = 16
EXPECTED_CALIBRATION_CONDITIONS = 12
EXPECTED_WORK_UNITS = EXPECTED_CANDIDATES * EXPECTED_CALIBRATION_MEMBERS
WINDOW_CELLS = 99

_ROOT = Path(__file__).resolve().parents[2]
_DESIGN_PATH = _ROOT / "src" / "lpbf" / "data" / "patch21_3_coarse_global_search_design.json"
_FROZEN_CONFIG_PATH = _ROOT / "src" / "lpbf" / "data" / "frozen_configuration.json"
_ACCEPTED_CORE_HASHES_PATH = _ROOT / "PATCH_22_3_4_ACCEPTED_CORE_HASHES.json"


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _validate_accepted_core_hashes() -> bool:
    record = _load_json(_ACCEPTED_CORE_HASHES_PATH)
    if record.get("schema") != "lpbf_patch22_3_4_accepted_core_hashes":
        return False
    for row in record.get("files", []):
        path = _ROOT / str(row["path"])
        if not path.is_file() or sha256_file(path) != str(row["sha256"]):
            return False
    return True


def _coarse_design() -> dict[str, Any]:
    design = _load_json(_DESIGN_PATH)
    search = design.get("search_design") or {}
    parameter_space = design.get("parameter_space") or {}
    if design.get("schema") != "lpbf_patch21_3_coarse_global_search_design":
        raise ValueError("coarse-search design schema drifted")
    if design.get("schema_version") != "21.3.0":
        raise ValueError("coarse-search design version drifted")
    if int(search.get("candidate_count", -1)) != EXPECTED_CANDIDATES:
        raise ValueError("coarse-search candidate count drifted")
    if int(search.get("anchor_count", -1)) != EXPECTED_ANCHORS:
        raise ValueError("coarse-search anchor count drifted")
    if int(search.get("halton_candidate_count", -1)) != EXPECTED_HALTON:
        raise ValueError("coarse-search Halton count drifted")
    if int(search.get("expected_trials_per_candidate", -1)) != EXPECTED_CALIBRATION_MEMBERS:
        raise ValueError("coarse-search calibration-member count drifted")
    if int(search.get("expected_maximum_atomic_trial_count", -1)) != EXPECTED_WORK_UNITS:
        raise ValueError("coarse-search trial count drifted")
    expected_order = [
        "abs_depth_identifiable_coordinate",
        "liquid_conductivity_enhancement_factor",
        "eta_directional",
    ]
    if list(parameter_space.get("coefficient_order", [])) != expected_order:
        raise ValueError("coarse-search coefficient order drifted")
    return design


def _parameter_points(design: Mapping[str, Any]) -> tuple[ParameterPointSpec, ...]:
    candidates = list((design.get("search_design") or {}).get("candidates") or [])
    if len(candidates) != EXPECTED_CANDIDATES:
        raise ValueError("coarse-search candidate list is incomplete")
    points = tuple(
        ParameterPointSpec(
            parameter_point_id=str(row["candidate_id"]),
            values={name: float(value) for name, value in dict(row["coordinates"]).items()},
        )
        for row in candidates
    )
    if len({point.parameter_point_id for point in points}) != EXPECTED_CANDIDATES:
        raise ValueError("coarse-search candidate IDs are not unique")
    return points


def build_coarse_calibration_manifest() -> CampaignExecutionManifest:
    freeze = build_patch22_4_1_freeze()
    if freeze.get("status") != "PASS_PATCH_22_4_1_CALIBRATION_READINESS_AND_OBJECTIVE_FREEZE":
        raise ValueError("Patch 22.4.1 predecessor is not accepted")
    calibration_members = set(freeze["campaign"]["calibration_members"])
    validation_members = set(freeze["campaign"]["validation_members"])
    if len(calibration_members) != EXPECTED_CALIBRATION_MEMBERS or calibration_members & validation_members:
        raise ValueError("Patch 22.4.1 partition drifted")

    design = _coarse_design()
    points = _parameter_points(design)
    set_ids = tuple(dict.fromkeys(row["acquisition_set_id"] for row in canonical_coupon_roster()))
    context = {
        set_id: {
            "patch": PATCH_VERSION,
            "population": "calibration_only",
            "objective": "hierarchical_all_observation",
            "production_hw_semantics_version": PRODUCTION_HW_SEMANTICS_VERSION,
            "production_hw_association_policy_version": PRODUCTION_HW_ASSOCIATION_POLICY_VERSION,
            "window_cells": WINDOW_CELLS,
            "validation_partition_permitted": False,
        }
        for set_id in set_ids
    }
    stage = CampaignStageSpec(
        stage_id="coarse_calibration",
        stage_ordinal=1,
        experiment_id="hierarchical_coarse_global_search",
        parameter_sweep_id="frozen_17_point_design",
        parameter_points=points,
        set_execution_context=context,
        acquisition_set_ids=set_ids,
        replicate_id="r1",
    )
    full = build_campaign_execution_manifest(
        (stage,),
        model_configuration_sha256=sha256_file(_FROZEN_CONFIG_PATH),
        production_semantics_id=PRODUCTION_SEMANTICS_ID,
    )
    selected = tuple(
        replace(unit, sequence_index=index)
        for index, unit in enumerate(
            unit for unit in full.work_units if unit.member_identity in calibration_members
        )
    )
    if len(selected) != EXPECTED_WORK_UNITS:
        raise ValueError(f"expected {EXPECTED_WORK_UNITS} calibration work units, got {len(selected)}")
    if any(unit.member_identity in validation_members for unit in selected):
        raise ValueError("held-out validation member leaked into coarse calibration manifest")
    seed = {
        "schema": "lpbf_patch22_4_2_coarse_calibration_execution_manifest",
        "schema_version": PATCH_VERSION,
        "predecessor_freeze_sha256": freeze["freeze_sha256"],
        "source_design_sha256": sha256_file(_DESIGN_PATH),
        "model_configuration_sha256": full.model_configuration_sha256,
        "production_semantics_id": full.production_semantics_id,
        "work_units": [u.identity_record() | {"sequence_index": u.sequence_index} for u in selected],
    }
    return CampaignExecutionManifest(
        campaign_id=full.campaign_id,
        canonical_dataset_manifest_sha256=full.canonical_dataset_manifest_sha256,
        model_configuration_sha256=full.model_configuration_sha256,
        production_semantics_id=full.production_semantics_id,
        work_units=selected,
        manifest_sha256=canonical_sha256(seed),
    )


def _synthetic_worker(job: SimulationJob) -> dict[str, Any]:
    """Spawn-safe deterministic payload; deliberately performs no thermal work."""
    coords = job.candidate_coordinates_dict
    return {
        "work_unit_id": job.work_unit_id,
        "member_identity": job.member_identity,
        "window_cells": list(job.window_sequence),
        "coordinate_checksum": canonical_sha256(coords),
        "synthetic_objective_component": sum((i + 1) * float(v) ** 2 for i, (_, v) in enumerate(sorted(coords.items()))),
    }


def _records(manifest: CampaignExecutionManifest, results) -> list[dict[str, Any]]:
    by_id = {unit.work_unit_id: unit for unit in manifest.work_units}
    return [
        result_record(by_id[result.job.work_unit_id], result.payload, attempts=result.attempts)
        for result in results
    ]


def build_authorization_record(*, workers: int = EXPECTED_WORKERS, execute_spawn_test: bool = True) -> dict[str, Any]:
    if int(workers) != workers or int(workers) < 1:
        raise ValueError("workers must be a positive integer")
    workers = int(workers)
    freeze = build_patch22_4_1_freeze()
    design = _coarse_design()
    manifest = build_coarse_calibration_manifest()
    cal_members = set(freeze["campaign"]["calibration_members"])
    val_members = set(freeze["campaign"]["validation_members"])
    cal_conditions = set(freeze["campaign"]["calibration_condition_ids"])
    candidate_counts = Counter(unit.parameter_point_id for unit in manifest.work_units)
    member_counts = Counter(unit.member_identity for unit in manifest.work_units)

    jobs = tuple(
        simulation_job_for_work_unit(
            unit,
            frame_index=0,
            window_cells=WINDOW_CELLS,
            extra_experiment_context={"patch22_4_2_dispatch_validation": True},
        )
        for unit in manifest.work_units
    )
    serial = execute_serial_jobs(jobs, _synthetic_worker)
    serial_records = _records(manifest, serial)
    serial_reconciliation = reconcile_result_records(manifest, serial_records)

    parallel_equivalent = None
    parallel_reconciliation = None
    if execute_spawn_test:
        parallel = execute_parallel_jobs(jobs, _synthetic_worker, workers=workers)
        parallel_records = _records(manifest, parallel)
        parallel_reconciliation = reconcile_result_records(manifest, parallel_records)
        serial_payloads = {r["work_unit_id"]: r["payload"] for r in serial_records}
        parallel_payloads = {r["work_unit_id"]: r["payload"] for r in parallel_records}
        parallel_equivalent = serial_payloads == parallel_payloads

    gates = {
        "patch22_4_1_predecessor_passes": freeze.get("all_acceptance_gates_pass") is True,
        "accepted_numerical_core_hashes_unchanged": _validate_accepted_core_hashes(),
        "production_hw_semantics_remain_22_3_5": freeze["observation_contract"]["production_hw_semantics_version"] == PRODUCTION_HW_SEMANTICS_VERSION and freeze["observation_contract"]["production_hw_association_policy_version"] == PRODUCTION_HW_ASSOCIATION_POLICY_VERSION,
        "frozen_search_has_17_candidates": int(design["search_design"]["candidate_count"]) == EXPECTED_CANDIDATES,
        "frozen_search_has_5_anchors_12_halton": int(design["search_design"]["anchor_count"]) == EXPECTED_ANCHORS and int(design["search_design"]["halton_candidate_count"]) == EXPECTED_HALTON,
        "manifest_has_272_work_units": len(manifest.work_units) == EXPECTED_WORK_UNITS,
        "manifest_has_exactly_16_calibration_members": set(member_counts) == cal_members and all(v == EXPECTED_CANDIDATES for v in member_counts.values()),
        "each_candidate_has_16_members": len(candidate_counts) == EXPECTED_CANDIDATES and all(v == EXPECTED_CALIBRATION_MEMBERS for v in candidate_counts.values()),
        "held_out_validation_members_absent": not any(unit.member_identity in val_members for unit in manifest.work_units),
        "calibration_condition_count_frozen_at_12": len(cal_conditions) == EXPECTED_CALIBRATION_CONDITIONS,
        "serial_reconciliation_passes": serial_reconciliation["pass"] is True,
        "parallel_spawn_reconciliation_passes": (parallel_reconciliation is not None and parallel_reconciliation["pass"] is True) if execute_spawn_test else True,
        "serial_parallel_scientific_payloads_identical": parallel_equivalent is True if execute_spawn_test else True,
        "requested_worker_count_is_4": workers == EXPECTED_WORKERS,
        "production_window_is_99_cells": all(job.window_sequence == (WINDOW_CELLS,) for job in jobs),
    }
    all_pass = all(gates.values())
    return {
        "schema": SCHEMA,
        "schema_version": PATCH_VERSION,
        "status": STATUS if all_pass else FAIL_STATUS,
        "predecessor_status": freeze["status"],
        "all_acceptance_gates_pass": all_pass,
        "acceptance_gates": gates,
        "campaign": {
            "calibration_member_count": len(cal_members),
            "validation_member_count": len(val_members),
            "calibration_condition_count": len(cal_conditions),
            "candidate_count": EXPECTED_CANDIDATES,
            "anchor_count": EXPECTED_ANCHORS,
            "halton_candidate_count": EXPECTED_HALTON,
            "coarse_work_unit_count": len(manifest.work_units),
            "workers": workers,
            "multiprocessing_start_method": "spawn" if execute_spawn_test and workers > 1 else None,
            "production_window_cells": WINDOW_CELLS,
            "manifest_sha256": manifest.manifest_sha256,
            "source_design_sha256": sha256_file(_DESIGN_PATH),
        },
        "authorization": {
            "coarse_calibration_search_authorized_after_acceptance": all_pass,
            "regional_refinement_authorized": False,
            "focused_optimization_authorized": False,
            "held_out_validation_authorized": False,
            "validation_partition_use_for_candidate_selection_permitted": False,
            "parameter_fitting_performed": False,
            "thermal_search_performed": False,
            "preferred_parameter_values_selected": False,
            "next_stage": "real_272_work_unit_coarse_thermal_search_and_scientific_review",
        },
        "immutability": {
            "accepted_numerical_core_modified": False,
            "production_hw_definition_changed": False,
            "objective_contract_changed": False,
            "calibration_partition_changed": False,
        },
        "serial_reconciliation": serial_reconciliation,
        "parallel_reconciliation": parallel_reconciliation,
    }


def run_validation(output_directory: str | Path, *, workers: int = EXPECTED_WORKERS) -> dict[str, Any]:
    output = Path(output_directory).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    manifest = build_coarse_calibration_manifest()
    record = build_authorization_record(workers=workers, execute_spawn_test=True)
    manifest_payload = {
        "schema": "lpbf_patch22_4_2_coarse_calibration_execution_manifest",
        "schema_version": PATCH_VERSION,
        "campaign_id": manifest.campaign_id,
        "canonical_dataset_manifest_sha256": manifest.canonical_dataset_manifest_sha256,
        "model_configuration_sha256": manifest.model_configuration_sha256,
        "production_semantics_id": manifest.production_semantics_id,
        "work_unit_count": len(manifest.work_units),
        "manifest_sha256": manifest.manifest_sha256,
        "work_units": [u.identity_record() | {"sequence_index": u.sequence_index} for u in manifest.work_units],
    }
    write_json(output / "PATCH_22_4_2_COARSE_CALIBRATION_EXECUTION_MANIFEST.json", manifest_payload)
    write_json(output / "PATCH_22_4_2_PARALLEL_COARSE_CALIBRATION_AUTHORIZATION.json", record)
    status = {
        "schema": "lpbf_patch22_4_2_status",
        "schema_version": PATCH_VERSION,
        "status": record["status"],
        "all_acceptance_gates_pass": record["all_acceptance_gates_pass"],
        "candidate_count": EXPECTED_CANDIDATES,
        "calibration_member_count": EXPECTED_CALIBRATION_MEMBERS,
        "calibration_condition_count": EXPECTED_CALIBRATION_CONDITIONS,
        "coarse_work_unit_count": EXPECTED_WORK_UNITS,
        "parallel_worker_count": workers,
        "production_window_cells": WINDOW_CELLS,
        "production_hw_semantics_version": PRODUCTION_HW_SEMANTICS_VERSION,
        "production_hw_association_policy_version": PRODUCTION_HW_ASSOCIATION_POLICY_VERSION,
        "held_out_validation_member_count": len(build_patch22_4_1_freeze()["campaign"]["validation_members"]),
        "validation_partition_used_for_selection": False,
        "coarse_calibration_search_authorized_after_acceptance": record["authorization"]["coarse_calibration_search_authorized_after_acceptance"],
        "regional_refinement_authorized": False,
        "focused_optimization_authorized": False,
        "held_out_validation_authorized": False,
        "parameter_fitting_performed": False,
        "thermal_search_performed": False,
        "accepted_numerical_core_modified": False,
        "production_hw_definition_changed": False,
        "result_file": "PATCH_22_4_2_PARALLEL_COARSE_CALIBRATION_AUTHORIZATION.json",
    }
    write_json(output / "PATCH_22_4_2_PARALLEL_COARSE_CALIBRATION_AUTHORIZATION_STATUS.json", status)
    return status


__all__ = [
    "PATCH_VERSION", "SCHEMA", "STATUS", "FAIL_STATUS", "EXPECTED_WORKERS",
    "EXPECTED_CANDIDATES", "EXPECTED_CALIBRATION_MEMBERS", "EXPECTED_WORK_UNITS",
    "build_coarse_calibration_manifest", "build_authorization_record", "run_validation",
]
