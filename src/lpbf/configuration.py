"""The frozen final configuration of the thesis model, in one place.

The authoritative values live in the code (the frozen numerical core and its ``frozen_configuration.json``, the
association, scoring and objective modules) and in the recorded selection freeze
(``results/calibration/selection_freeze.json``). ``final_configuration()`` assembles them into one readable
record; ``python -m lpbf.configuration`` writes that record to ``data/final_model.json``, and the test suite asserts
that the committed file equals the assembly, so the snapshot cannot drift from the code.

This module also holds the few scalar constants that several modules and analysis scripts share and that have no
other natural home: the boiling temperature used to report "peak above boiling" (``BOILING_K``) and the camera's
fixed observation definition (threshold, layer, frame size).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lpbf.paths import repository_root

# Camera observation definition (the coaxial camera's fixed convention).
CAMERA_LAYER = "layer53"           # the one observed layer of every coupon
CAMERA_THRESHOLD = 150             # bright-blob threshold on the 8-bit frame
CAMERA_SATURATION_LEVEL = 255
CAMERA_ROWS, CAMERA_COLS = 24, 64  # stored frame size (64 px wide, 24 px tall)

# Boiling temperature used only to report the fraction of scored frames whose peak exceeds it (strict ">").
BOILING_K = 3133.0

FINAL_MODEL_RESOURCE = "final_model.json"
SELECTION_FREEZE_RELATIVE = Path("results") / "calibration" / "selection_freeze.json"


def selection_freeze_path(root: Path | None = None) -> Path:
    return (repository_root() if root is None else Path(root)) / SELECTION_FREEZE_RELATIVE


def load_final_model() -> dict[str, Any]:
    """The committed snapshot (package data)."""

    from importlib.resources import files

    return json.loads(files("lpbf.data").joinpath(FINAL_MODEL_RESOURCE).read_text(encoding="utf-8"))


def final_configuration(freeze_path: str | Path | None = None) -> dict[str, Any]:
    """Assemble the frozen configuration from the code's own constants and the recorded selection freeze."""

    from lpbf import __version__
    from lpbf.calibration_contract import COEFFICIENT_ORDER, _abs_depth_mapping, load_patch21_0_contract
    from lpbf.calibration_design import WINDOW_CELLS, coordinate_bounds, load_design
    from lpbf.dataset_split import HATCH_MM, LAYER_MM, VED_WINDOW_J_MM3, stored_member_roles
    from lpbf.experiments.current_framework import (
        DEFAULT_ENERGY_RELATIVE_ERROR_LIMIT,
        FROZEN_BOILING_AUDIT_TMAX_K,
        FROZEN_BOUNDARY_EXPLICIT_FRACTION_LIMIT,
        PRODUCTION_CALIBRATION_WINDOW_CELLS,
    )
    from lpbf.geometry import FROZEN_SPACING_UM
    from lpbf.hierarchical_objective import (
        COVERAGE_FLOOR,
        H_METRIC_WEIGHT,
        H_REPEATABILITY_SCALE_PIXELS,
        PIXEL_SIZE_UM,
        W_METRIC_WEIGHT,
        W_REPEATABILITY_SCALE_PIXELS,
    )
    from lpbf.infrastructure import sha256_file
    from lpbf.log_ratio_objective import AGGREGATION_HIERARCHY, H_WEIGHT, OBJECTIVE_CONTRACT_VERSION, PIXEL_FLOOR, W_WEIGHT
    from lpbf.model._accepted_core.parameters import C_TO_K, MACHINE_GAUSSIAN_RADIUS_MM, MACHINE_SPOT_DIAMETER_UM
    from lpbf.model.current_configuration import CURRENT_MODEL_CONFIGURATION
    from lpbf.model.input_data import PRODUCTION_DAQ_DT_S, PRODUCTION_DAQ_FREQUENCY_HZ, PRODUCTION_LASER_DRIVE_THRESHOLD
    from lpbf.model.laser_component_association import BEAM_SHARE_FLOOR, POLICY_VERSION
    from lpbf.model.production_hw import PRODUCTION_HW_DEFINITION, PRODUCTION_HW_SEMANTICS_VERSION
    from lpbf.runtime.configuration import load_frozen_experiment_configuration
    from lpbf.runtime.parameters import THERMAL_DT_S, THERMAL_SUBSTEPS_PER_DAQ
    from lpbf.scored_frame_rule import SCORED_FRAME_RULE_ID, SCORED_FRAME_RULE_VERSION

    if PRODUCTION_CALIBRATION_WINDOW_CELLS != WINDOW_CELLS:
        raise RuntimeError("window-cell constants disagree")

    frozen = load_frozen_experiment_configuration()
    fields = frozen.to_dict()["frozen_parameter_fields"]
    material = dict(fields["material"])
    contract = load_patch21_0_contract()
    design = load_design()

    freeze_file = selection_freeze_path() if freeze_path is None else Path(freeze_path)
    if not freeze_file.is_file():
        raise FileNotFoundError(f"selection freeze not found: {freeze_file} (see results/calibration/)")
    freeze = json.loads(freeze_file.read_text(encoding="utf-8"))
    selected = freeze["selected"]
    coordinates = {name: float(selected["coordinates"][name]) for name in COEFFICIENT_ORDER}
    absorptivity, deposition_depth_mm = _abs_depth_mapping(coordinates["abs_depth_identifiable_coordinate"])

    nz = int(fields["grid"]["Nz"])
    return {
        "schema": "lpbf_final_model_configuration",
        "package_version": __version__,
        "numerical_model": {
            "window_cells_xy": WINDOW_CELLS,
            "grid_spacing_um": FROZEN_SPACING_UM,
            "window_size_mm": WINDOW_CELLS * FROZEN_SPACING_UM / 1000.0,
            "depth_cells": nz,
            "depth_mm": float(fields["geometry"]["Lz_mm"]),
            "thermal_timestep_s": THERMAL_DT_S,
            "thermal_substeps_per_process_row": THERMAL_SUBSTEPS_PER_DAQ,
            "process_row_period_s": PRODUCTION_DAQ_DT_S,
            "process_sample_frequency_hz": PRODUCTION_DAQ_FREQUENCY_HZ,
            "explicit_stability_safety_factor": float(fields["time"]["explicit_stability_safety_factor"]),
            "boundary_explicit_fraction_limit": FROZEN_BOUNDARY_EXPLICIT_FRACTION_LIMIT,
            "energy_balance_relative_error_limit": DEFAULT_ENERGY_RELATIVE_ERROR_LIMIT,
            "boiling_audit_maximum_temperature_K": FROZEN_BOILING_AUDIT_TMAX_K,
            "frozen_core_hash_manifest": "src/lpbf/data/accepted_core_hashes.json",
            "frozen_configuration_sha256": frozen.sha256,
        },
        "material": {
            **material,
            "T_solidus_K": float(material["T_solidus_C"]) + C_TO_K,
            "T_liquidus_K": float(material["T_liquidus_C"]) + C_TO_K,
            "T_boiling_K": float(material["T_boiling_C"]) + C_TO_K,
            "note": "liquid_conductivity_enhancement_factor in this block is the pre-calibration default; the calibrated value is under selected_parameters",
        },
        "boundary_conditions": dict(fields["boundary_conditions"]),
        "initial_condition": dict(fields["initial_condition"]),
        "laser_source": {
            "machine_spot_diameter_um": MACHINE_SPOT_DIAMETER_UM,
            "gaussian_radius_mm": MACHINE_GAUSSIAN_RADIUS_MM,
            "laser_drive_on_threshold_V": PRODUCTION_LASER_DRIVE_THRESHOLD,
            "absorptivity_semantics": CURRENT_MODEL_CONFIGURATION.absorptivity_semantics,
            "deposition_depth_mode": CURRENT_MODEL_CONFIGURATION.deposition_depth_mode,
            "ted_treatment_identifier": frozen.to_dict()["ted_treatment_identifier"],
            "input": dict(fields["input"]),
        },
        "moving_window": dict(fields["moving_window"]),
        "boiling_regulator": {
            "quadratic_boiling_strength": CURRENT_MODEL_CONFIGURATION.quadratic_boiling_strength,
            "quadratic_boiling_loss_law": CURRENT_MODEL_CONFIGURATION.quadratic_boiling_loss_law,
            "optimizer_controlled": False,
            "reported_boiling_K": BOILING_K,
        },
        "observation": {
            "model_hw_definition": PRODUCTION_HW_DEFINITION,
            "model_hw_semantics_version": PRODUCTION_HW_SEMANTICS_VERSION,
            "association_policy_version": POLICY_VERSION,
            "beam_share_floor": float(BEAM_SHARE_FLOOR),
            "camera_pixel_size_um_nominal": PIXEL_SIZE_UM,
            "camera_threshold": CAMERA_THRESHOLD,
            "camera_layer": CAMERA_LAYER,
            "camera_frame_rows_cols": [CAMERA_ROWS, CAMERA_COLS],
        },
        "scoring": {
            "scored_frame_rule_id": SCORED_FRAME_RULE_ID,
            "scored_frame_rule_version": SCORED_FRAME_RULE_VERSION,
            "coverage_floor": COVERAGE_FLOOR,
            "objective_contract_version": OBJECTIVE_CONTRACT_VERSION,
            "residual": "ln(max(sim, pixel_floor) / max(exp, pixel_floor)) for H and W",
            "pixel_floor": PIXEL_FLOOR,
            "h_weight": H_WEIGHT,
            "w_weight": W_WEIGHT,
            "aggregation_hierarchy": list(AGGREGATION_HIERARCHY),
            "pixel_objective_sensitivity": {
                "h_scale_px": H_REPEATABILITY_SCALE_PIXELS,
                "w_scale_px": W_REPEATABILITY_SCALE_PIXELS,
                "h_weight": H_METRIC_WEIGHT,
                "w_weight": W_METRIC_WEIGHT,
            },
        },
        "calibration": {
            "coordinates": list(COEFFICIENT_ORDER),
            "coordinate_bounds": {name: list(bounds) for name, bounds in coordinate_bounds().items()},
            "coupled_guard": dict(contract["coupled_transport_guard"]),
            "design_candidates": int(design["search_design"]["candidate_count"]),
            "design_method": design["search_design"]["method"],
            "energy_density_window_J_mm3": list(VED_WINDOW_J_MM3),
            "hatch_mm": HATCH_MM,
            "layer_mm": LAYER_MM,
            "members_per_role": {role: len(members) for role, members in stored_member_roles().items()},
        },
        "selected_parameters": {
            "candidate_id": selected["candidate_id"],
            "coordinates": coordinates,
            "absorptivity": absorptivity,
            "deposition_depth_mm": deposition_depth_mm,
            "liquid_conductivity_enhancement_factor": coordinates["liquid_conductivity_enhancement_factor"],
            "eta_directional": coordinates["eta_directional"],
            "calibration_objective_J": float(selected["J"]),
            "calibration_e_H": float(selected["e_H"]),
            "calibration_e_W": float(selected["e_W"]),
            "reading_C": freeze["reading_C"],
            "selection_freeze_file": SELECTION_FREEZE_RELATIVE.as_posix(),
            "selection_freeze_sha256": sha256_file(freeze_file),
            "selection_freeze_content_sha256": freeze["content_sha256"],
        },
    }


def write_final_model(path: str | Path | None = None) -> Path:
    target = Path(path) if path is not None else Path(__file__).with_name("data") / FINAL_MODEL_RESOURCE
    target.write_bytes((json.dumps(final_configuration(), indent=2) + "\n").encode("utf-8"))
    return target


if __name__ == "__main__":
    print(write_final_model())
