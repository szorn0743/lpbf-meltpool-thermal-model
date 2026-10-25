"""Patch 22.4.1 calibration-campaign readiness and objective freeze.

Offline only: freezes the current scientific calibration contract against the
accepted 24-coupon campaign and production H/W semantics.  No thermal solve,
parameter fit, search, or held-out validation is performed here.
"""
from __future__ import annotations
from typing import Any
from lpbf.calibration_contract import load_patch21_0_contract, calibration_member_identities, validation_member_identities
from lpbf.execution.campaign_provenance import canonical_coupon_roster
from lpbf.hierarchical_objective import (
    H_REPEATABILITY_SCALE_PIXELS, W_REPEATABILITY_SCALE_PIXELS,
    H_METRIC_WEIGHT, W_METRIC_WEIGHT, FAILED_CANDIDATE_PENALTY, COVERAGE_FLOOR,
)
from lpbf.infrastructure import canonical_sha256
from lpbf.model.laser_component_association import BEAM_SHARE_FLOOR, POLICY_VERSION as PRODUCTION_HW_ASSOCIATION_POLICY_VERSION
from lpbf.model.production_hw import NO_LASER_ASSOCIATED_MELT_POLICY, PRODUCTION_HW_DEFINITION, PRODUCTION_HW_SEMANTICS_VERSION
from lpbf.scored_frame_rule import scored_frame_rule_record

PATCH_VERSION = "22.4.1"
SCHEMA = "lpbf_patch22_4_1_calibration_readiness_objective_freeze"
STATUS = "PASS_PATCH_22_4_1_CALIBRATION_READINESS_AND_OBJECTIVE_FREEZE"


def build_freeze() -> dict[str, Any]:
    legacy = load_patch21_0_contract()
    roster = canonical_coupon_roster()
    roster_ids = {r["member_identity"] for r in roster}
    calibration = set(calibration_member_identities(legacy))
    validation = set(validation_member_identities(legacy))
    cal_conditions = set(legacy["data_partition"]["calibration_condition_ids"])
    val_conditions = set(legacy["data_partition"]["validation_condition_ids"])
    p = legacy["optimizer_parameterization"]
    freeze = {
        "schema": SCHEMA,
        "schema_version": PATCH_VERSION,
        "predecessor_status": "PASS_PATCH_22_4_0_COUPON_SET_WORK_UNIT_IDENTITY_AND_CAMPAIGN_PROVENANCE",
        "campaign": {
            "coupon_count": len(roster), "coupon_set_count": len({r['acquisition_set_id'] for r in roster}),
            "calibration_member_count": len(calibration), "validation_member_count": len(validation),
            "calibration_condition_count": len(cal_conditions), "validation_condition_count": len(val_conditions),
            "calibration_members": sorted(calibration), "validation_members": sorted(validation),
            "calibration_condition_ids": sorted(cal_conditions), "validation_condition_ids": sorted(val_conditions),
            "exact_condition_leakage_permitted": False,
        },
        "parameter_vector": {
            "coefficient_order": list(p["coefficient_order"]),
            "coordinate_bounds": {
                "abs_depth_identifiable_coordinate": {"minimum": -3.0, "maximum": 3.0, "units": "dimensionless_step_coordinate"},
                "liquid_conductivity_enhancement_factor": dict(p["direct_coordinate_bounds"]["liquid_conductivity_enhancement_factor"]),
                "eta_directional": dict(p["direct_coordinate_bounds"]["eta_directional"]),
            },
            "absorptivity_depth_mapping": dict(p["absorptivity_deposition_depth_reparameterization"]["mapping"]),
            "policy_scope": "global_shared_across_all_calibration_coupons",
            "process_conditioned_parameters_selected": False,
            "quadratic_boiling_strength": 0.5,
            "quadratic_boiling_optimizer_controlled": False,
            "coupled_guard": {"quantity": "directional.selected_over_safe_limit", "maximum_allowed": 0.95, "failure_behavior": "reject_before_thermal_execution"},
        },
        "observation_contract": {
            "production_hw_definition": PRODUCTION_HW_DEFINITION,
            "production_hw_semantics_version": PRODUCTION_HW_SEMANTICS_VERSION,
            "production_hw_association_policy_version": PRODUCTION_HW_ASSOCIATION_POLICY_VERSION,
            "observation_population": "all_synchronized_eligible_camera_frames",
            "aggregation_hierarchy": ["camera_frame", "scan_track", "coupon", "exact_condition_replicate", "unique_calibration_condition"],
            "zero_footprint_policy": "retain finite eligible zero-footprint observations as H=0,W=0",
            "invalid_observation_policy": "retain identity/provenance but exclude ineligible/nonfinite H/W from residual aggregation",
            "candidate_failure_policy": "frame-level (Patch 22.3.7): undefined frames are excluded from residuals and counted in coverage; a coupon below the coverage floor flags the candidate; the whole-candidate penalty applies only to infrastructure failure",
            "undefined_observation_policy": "record_undefined",
            "scored_frame_rule": scored_frame_rule_record(),
            "no_laser_associated_melt_policy": NO_LASER_ASSOCIATED_MELT_POLICY,
            "beam_share_floor": BEAM_SHARE_FLOOR,
            "historical_deterministic_middle_track_contract_superseded": True,
        },
        "objective_contract": {
            "primary_observables": ["H_pixels", "W_pixels"],
            "normalization_scales_pixels": {"H_pixels": H_REPEATABILITY_SCALE_PIXELS, "W_pixels": W_REPEATABILITY_SCALE_PIXELS},
            "metric_weights": {"H_pixels": H_METRIC_WEIGHT, "W_pixels": W_METRIC_WEIGHT},
            "condition_weighting": "equal_weight_per_unique_calibration_condition",
            "track_weighting": "equal_weight_per_observation_bearing_track_within_coupon",
            "coupon_weighting": "equal_weight_per_observation_bearing_coupon_within_condition",
            "raw_frame_count_weight_used": False,
            "replicate_count_weight_used": False,
            "failed_candidate_scalar_penalty": FAILED_CANDIDATE_PENALTY,
            "coverage_floor": COVERAGE_FLOOR,
            "failed_rows_fabricated_residuals": False,
            "temperature_diagnostics_in_objective": False,
            "h_over_w_ratio_in_objective": False,
        },
        "search_authorization": {
            "calibration_search_authorized": False,
            "parameter_fitting_performed": False,
            "preferred_parameter_values_selected": False,
            "validation_partition_used_for_selection": False,
            "bounds_adaptation_permitted": False,
            "objective_weight_adaptation_permitted": False,
            "next_stage": "hierarchical_search_design_and_execution_only_after_patch22_4_1_acceptance",
        },
    }
    gates = {
        "canonical_campaign_is_24_coupons_4_sets": len(roster) == 24 and len({r['acquisition_set_id'] for r in roster}) == 4,
        "partition_is_complete_and_disjoint": calibration.isdisjoint(validation) and calibration | validation == roster_ids,
        "partition_counts_are_16_and_8": len(calibration) == 16 and len(validation) == 8,
        "condition_counts_are_12_and_6": len(cal_conditions) == 12 and len(val_conditions) == 6 and cal_conditions.isdisjoint(val_conditions),
        "three_coordinate_global_parameterization": list(p["coefficient_order"]) == ["abs_depth_identifiable_coordinate", "liquid_conductivity_enhancement_factor", "eta_directional"],
        "objective_constants_match_accepted_hierarchy": (H_REPEATABILITY_SCALE_PIXELS, W_REPEATABILITY_SCALE_PIXELS, H_METRIC_WEIGHT, W_METRIC_WEIGHT, FAILED_CANDIDATE_PENALTY) == (0.90, 0.65, 0.50, 0.50, 1.0e12),
        "production_hw_is_laser_associated_22_3_7": PRODUCTION_HW_SEMANTICS_VERSION == "22.3.7" and PRODUCTION_HW_ASSOCIATION_POLICY_VERSION == "22.3.7" and PRODUCTION_HW_DEFINITION == "laser_associated_component_interpolated_liquidus_contour",
        "search_remains_unauthorized": freeze["search_authorization"]["calibration_search_authorized"] is False,
    }
    freeze["acceptance_gates"] = gates
    freeze["all_acceptance_gates_pass"] = all(gates.values())
    freeze["status"] = STATUS if freeze["all_acceptance_gates_pass"] else "FAIL_PATCH_22_4_1_CALIBRATION_READINESS_AND_OBJECTIVE_FREEZE"
    freeze["freeze_sha256"] = canonical_sha256(freeze)
    return freeze
