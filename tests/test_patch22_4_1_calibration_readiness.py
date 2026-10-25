from lpbf.model.laser_component_association import POLICY_VERSION as PRODUCTION_HW_ASSOCIATION_POLICY_VERSION
from lpbf.model.production_hw import PRODUCTION_HW_SEMANTICS_VERSION
from lpbf.patch22_4_1_calibration_readiness import build_freeze, STATUS

def test_patch22_4_1_freeze_passes():
    x=build_freeze(); assert x["status"] == STATUS; assert x["all_acceptance_gates_pass"]

def test_partition_and_roles_are_frozen():
    x=build_freeze(); c=x["campaign"]; assert (c["calibration_member_count"],c["validation_member_count"])==(16,8); assert (c["calibration_condition_count"],c["validation_condition_count"])==(12,6); assert set(c["calibration_members"]).isdisjoint(c["validation_members"])

def test_parameter_vector_is_three_coordinate_global():
    p=build_freeze()["parameter_vector"]; assert p["coefficient_order"] == ["abs_depth_identifiable_coordinate","liquid_conductivity_enhancement_factor","eta_directional"]; assert p["policy_scope"] == "global_shared_across_all_calibration_coupons"; assert not p["quadratic_boiling_optimizer_controlled"]

def test_current_objective_supersedes_middle_track():
    x=build_freeze(); o=x["observation_contract"]; assert o["historical_deterministic_middle_track_contract_superseded"]; assert o["observation_population"] == "all_synchronized_eligible_camera_frames"; assert o["production_hw_semantics_version"] == PRODUCTION_HW_SEMANTICS_VERSION; assert o["production_hw_association_policy_version"] == PRODUCTION_HW_ASSOCIATION_POLICY_VERSION

def test_objective_weights_and_failure_policy():
    x=build_freeze(); o=x["objective_contract"]; assert o["normalization_scales_pixels"]=={"H_pixels":0.9,"W_pixels":0.65}; assert o["metric_weights"]=={"H_pixels":0.5,"W_pixels":0.5}; assert o["failed_candidate_scalar_penalty"]==1e12; assert not o["failed_rows_fabricated_residuals"]

def test_search_stays_locked():
    s=build_freeze()["search_authorization"]; assert not s["calibration_search_authorized"]; assert not s["parameter_fitting_performed"]; assert not s["validation_partition_used_for_selection"]
