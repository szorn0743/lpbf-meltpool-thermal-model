"""The frozen final configuration and the dataset split cannot drift from the code and the recorded freeze."""
from __future__ import annotations

import json
from pathlib import Path

from lpbf import configuration, dataset_split
from lpbf.calibration_contract import Patch21GlobalParameterPolicy, calibration_member_identities, validation_member_identities
from lpbf.infrastructure import sha256_file

ROOT = Path(__file__).resolve().parents[1]


def test_committed_final_model_equals_the_assembly_from_code_and_freeze():
    committed = configuration.load_final_model()
    assembled = json.loads(json.dumps(configuration.final_configuration()))
    assert committed == assembled


def test_final_model_pins_the_thesis_values():
    final = configuration.load_final_model()
    selected = final["selected_parameters"]
    assert selected["candidate_id"] == "confirm_c1"
    assert selected["coordinates"] == {"abs_depth_identifiable_coordinate": -3.0, "liquid_conductivity_enhancement_factor": 2.4177408854166664, "eta_directional": 0.0}
    assert round(selected["absorptivity"], 3) == 0.490 and round(selected["deposition_depth_mm"], 3) == 0.098
    assert round(selected["calibration_objective_J"], 3) == 0.298
    assert final["numerical_model"]["window_cells_xy"] == 99 and final["numerical_model"]["grid_spacing_um"] == 16.0
    assert final["observation"]["beam_share_floor"] == 0.02 and final["observation"]["camera_threshold"] == 150
    assert final["scoring"]["coverage_floor"] == 0.95 and final["scoring"]["pixel_floor"] == 1.0
    assert final["scoring"]["aggregation_hierarchy"][0] == "camera_frame"
    assert final["calibration"]["energy_density_window_J_mm3"] == [65.0, 85.0]
    assert final["calibration"]["members_per_role"] == {"calibration": 9, "in_window_held_out": 5, "out_of_window_examined": 7, "out_of_window_blind": 3}


def test_recorded_freeze_hash_matches_the_file_in_results():
    final = configuration.load_final_model()
    freeze = ROOT / final["selected_parameters"]["selection_freeze_file"]
    assert sha256_file(freeze) == final["selected_parameters"]["selection_freeze_sha256"]
    payload = json.loads(freeze.read_text(encoding="utf-8"))
    assert payload["content_sha256"] == final["selected_parameters"]["selection_freeze_content_sha256"]
    assert payload["selected"]["coordinates"] == final["selected_parameters"]["coordinates"]


def test_realized_parameters_follow_from_the_selected_coordinates():
    final = configuration.load_final_model()["selected_parameters"]
    policy = Patch21GlobalParameterPolicy.from_values(**final["coordinates"])
    physics = policy.coefficients.realized_parameters()
    assert physics.absorptivity == final["absorptivity"]
    assert physics.deposition_depth_mm == final["deposition_depth_mm"]
    assert physics.liquid_conductivity_enhancement_factor == final["liquid_conductivity_enhancement_factor"]
    assert physics.eta_directional == final["eta_directional"]


def test_dataset_split_is_stored_explicitly_and_equals_its_derivation():
    stored = dataset_split.stored_member_roles()
    assert stored == dataset_split.derive_member_roles()
    members = [m for role in stored.values() for m in role]
    assert len(members) == 24 and len(set(members)) == 24
    assert set(stored["calibration"]) | set(stored["out_of_window_examined"]) == calibration_member_identities()
    assert set(stored["in_window_held_out"]) | set(stored["out_of_window_blind"]) == validation_member_identities()
    assert dataset_split.CROSS_CAMPAIGN_HELD_OUT in stored["in_window_held_out"]
    low, high = dataset_split.VED_WINDOW_J_MM3
    records = dataset_split.member_records()
    for member in stored["calibration"] + stored["in_window_held_out"]:
        assert low <= records[member]["ved_J_mm3"] <= high
    for member in stored["out_of_window_examined"] + stored["out_of_window_blind"]:
        assert not (low <= records[member]["ved_J_mm3"] <= high)
