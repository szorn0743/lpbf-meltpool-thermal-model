"""The frozen calibration design (``data/calibration_design.json``).

Three global coordinates (absorptivity/deposition-depth coordinate t, liquid-conductivity enhancement factor ck,
directional transport factor eta) and 17 design candidates: 5 anchors and 12 Halton points. The design was frozen
before any calibration ran; this module only loads and checks it.
"""
from __future__ import annotations

from importlib.resources import files
import json
from pathlib import Path
from typing import Any

from lpbf.calibration_contract import COEFFICIENT_ORDER

DESIGN_RESOURCE = "calibration_design.json"
DESIGN_PATH = Path(str(files("lpbf.data").joinpath(DESIGN_RESOURCE)))
WINDOW_CELLS = 99
EXPECTED_CANDIDATES = 17
EXPECTED_ANCHORS = 5
EXPECTED_HALTON = 12
EXPECTED_CALIBRATION_MEMBERS = 16  # the design was written for the 16-member calibration partition
EXPECTED_WORK_UNITS = EXPECTED_CANDIDATES * EXPECTED_CALIBRATION_MEMBERS


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _coarse_design() -> dict[str, Any]:
    design = _load_json(DESIGN_PATH)
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


def load_design() -> dict[str, Any]:
    """The frozen design, after its schema and count checks."""

    return _coarse_design()


def _candidate_coordinates() -> dict[str, dict[str, float]]:
    design = _coarse_design()
    return {
        str(row["candidate_id"]): {
            name: float(row["coordinates"][name]) for name in COEFFICIENT_ORDER
        }
        for row in design["search_design"]["candidates"]
    }


def candidate_coordinates() -> dict[str, dict[str, float]]:
    """The 17 design candidates as ``{candidate_id: {coordinate: value}}``."""

    return _candidate_coordinates()


def coordinate_bounds() -> dict[str, tuple[float, float]]:
    bounds = _load_json(DESIGN_PATH)["parameter_space"]["coordinate_bounds"]
    return {name: (float(bounds[name]["minimum"]), float(bounds[name]["maximum"])) for name in COEFFICIENT_ORDER}


__all__ = ["DESIGN_PATH", "WINDOW_CELLS", "candidate_coordinates", "coordinate_bounds", "load_design"]
