"""Supported current execution API.

This module is the public import boundary for the active execution path. It
groups existing behavior by responsibility without introducing a second solver
or changing any scientific contract:

* ``experiments.dataset`` resolves hash-bound dataset members;
* ``experiments.policy`` validates and realizes explicit parameter policies;
* ``experiments.execution`` constructs frozen runtime parameters;
* ``experiments.current_framework`` performs serial trial execution, frozen
  preflight, diagnostics, and result packaging.

Historical experiment modules may continue importing compatibility names from
experiments.current_framework. New active code should import from this module
instead. Serial and Windows-spawn process-pool execution both use the
explicit work-unit contract exported here.
"""
from __future__ import annotations

from lpbf.experiments.current_framework import (
    CALIBRATION_TRIAL_EVALUATION_SCHEMA,
    CALIBRATION_TRIAL_EVALUATION_SCHEMA_VERSION,
    DEFAULT_ENERGY_RELATIVE_ERROR_LIMIT,
    FROZEN_CALIBRATION_WINDOW_CELLS,
    LEGACY_PATCH_22_2_PRODUCTION_WINDOW_CELLS,
    PRODUCTION_CALIBRATION_WINDOW_CELLS,
    CalibrationExecutionScope,
    CalibrationTrialEvaluation,
    CurrentExperimentFrameworkError,
    DatasetMember,
    EnergyAccountingRecord,
    InstrumentedTrialResult,
    PolicyRealization,
    TemperatureTraceAccumulator,
    boiling_boundary_stability_record,
    build_temperature_instrumented_runner,
    cell_volume_mm3,
    checkpoint_contract_identity,
    classify_current_peak_temperature,
    current_numerical_stability_preflight,
    evaluate_calibration_trial,
    execute_temperature_traced_trial,
    normalize_policy_realization_record_for_read,
    normalized_policy_definition,
    package_experiment_results,
    realize_policy_for_trial,
    realized_parameter_vector,
    require_energy_accounting,
    resolve_full_coupon_members,
    resolve_legacy_six_members,
)
from lpbf.experiments.execution import construct_frozen_runtime_parameters
from lpbf.execution.campaign_provenance import (
    CampaignExecutionManifest,
    CampaignProvenanceError,
    CampaignStageSpec,
    CampaignWorkUnit,
    ParameterPointSpec,
    PRODUCTION_SEMANTICS_ID,
    authorize_stage_dispatch,
    build_campaign_execution_manifest,
    canonical_coupon_roster,
    deterministic_result_relative_path,
    order_result_records_by_manifest,
    reconcile_result_records,
    result_record,
    simulation_job_for_work_unit,
    validate_result_record,
    write_result_once,
)
from lpbf.execution.parallel import execute_parallel_jobs
from lpbf.execution.work_units import (
    SimulationExecutionError,
    SimulationJob,
    SimulationResult,
    execute_serial_jobs,
)


__all__ = [
    "CALIBRATION_TRIAL_EVALUATION_SCHEMA",
    "CALIBRATION_TRIAL_EVALUATION_SCHEMA_VERSION",
    "DEFAULT_ENERGY_RELATIVE_ERROR_LIMIT",
    "FROZEN_CALIBRATION_WINDOW_CELLS",
    "LEGACY_PATCH_22_2_PRODUCTION_WINDOW_CELLS",
    "PRODUCTION_CALIBRATION_WINDOW_CELLS",
    "CalibrationExecutionScope",
    "CalibrationTrialEvaluation",
    "CurrentExperimentFrameworkError",
    "DatasetMember",
    "EnergyAccountingRecord",
    "InstrumentedTrialResult",
    "PolicyRealization",
    "TemperatureTraceAccumulator",
    "boiling_boundary_stability_record",
    "build_temperature_instrumented_runner",
    "cell_volume_mm3",
    "checkpoint_contract_identity",
    "classify_current_peak_temperature",
    "construct_frozen_runtime_parameters",
    "current_numerical_stability_preflight",
    "evaluate_calibration_trial",
    "execute_temperature_traced_trial",
    "normalize_policy_realization_record_for_read",
    "normalized_policy_definition",
    "package_experiment_results",
    "realize_policy_for_trial",
    "realized_parameter_vector",
    "require_energy_accounting",
    "resolve_full_coupon_members",
    "resolve_legacy_six_members",
    "SimulationExecutionError",
    "SimulationJob",
    "SimulationResult",
    "execute_serial_jobs",
    "execute_parallel_jobs",
    "CampaignExecutionManifest",
    "CampaignProvenanceError",
    "CampaignStageSpec",
    "CampaignWorkUnit",
    "ParameterPointSpec",
    "PRODUCTION_SEMANTICS_ID",
    "authorize_stage_dispatch",
    "build_campaign_execution_manifest",
    "canonical_coupon_roster",
    "deterministic_result_relative_path",
    "order_result_records_by_manifest",
    "reconcile_result_records",
    "result_record",
    "simulation_job_for_work_unit",
    "validate_result_record",
    "write_result_once",
]
