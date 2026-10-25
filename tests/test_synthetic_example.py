"""The synthetic example runs the whole pipeline on a fake coupon: parsing, solver, extraction, scoring, outputs."""
from __future__ import annotations

import json
import math

import numpy as np
import pytest

from lpbf import synthetic_example as ex
from lpbf.calibration_contract import Patch21GlobalParameterPolicy
from lpbf.configuration import load_final_model
from lpbf.experiments.current_framework import DEFAULT_ENERGY_RELATIVE_ERROR_LIMIT
from lpbf.geometry import FROZEN_SPACING_UM, resize_xy_window
from lpbf.model import current_execution
from lpbf.model.laser_component_association import surface_beam_profile
from lpbf.runtime.parameters import THERMAL_DT_S, exact_fixed_time_params


@pytest.fixture(scope="module")
def example(tmp_path_factory):
    out = tmp_path_factory.mktemp("synthetic_example")
    result = ex.run_example(out, progress=False)
    return out, result


def test_outputs_are_written_and_labelled_synthetic(example):
    out, result = example
    assert (out / "synthetic_coupon.h5").is_file() and (out / "example_result.json").is_file() and (out / "frame_records.csv").is_file()
    on_disk = json.loads((out / "example_result.json").read_text(encoding="utf-8"))
    assert on_disk["synthetic"] is True and "SYNTHETIC" in on_disk["note"]
    assert on_disk["objective"]["status"] == result["objective"]["status"] == "PASS"
    assert on_disk["selected_parameters"] == load_final_model()["selected_parameters"]


def test_input_parsing_and_camera_side_rule(example):
    _, result = example
    assert result["process_rows"] == 500 and result["camera_frames"] == 22
    records = result["frame_records"]
    assert len(records) == 14  # laser-on frames of two tracks
    excluded = [r for r in records if r["status"] == "EXCLUDED"]
    assert len(excluded) == 4 and {r["exclusion_reason"] for r in excluded} == {"EXCLUDED_TRACK_FIRST", "EXCLUDED_TRACK_LAST"}
    assert result["camera_blob_first_scored_frame"]["H_px"] >= result["camera_blob_first_scored_frame"]["W_px"] > 0


def test_solver_ran_at_the_frozen_numerics_and_conserved_energy(example):
    _, result = example
    assert result["numerical_preflight_status"] == "PASS"
    trace = result["temperature_trace"]
    assert trace["thermal_substep_count"] == 2 * (result["process_rows"] - 1)  # two 2.5 us substeps per 5 us process-row interval
    assert 1500.0 < float(trace["raw_global_Tmax_K"]) < 7000.0
    energy = result["energy_accounting"]
    assert abs(float(energy["energy_balance_relative_error"])) <= DEFAULT_ENERGY_RELATIVE_ERROR_LIMIT == 1.0e-9
    assert float(energy["cumulative_absorbed_laser_energy_J"]) > 0.0


def test_melt_pool_extraction_and_scoring(example):
    _, result = example
    scored = [r for r in result["frame_records"] if r["status"] == "PASS"]
    assert len(scored) == 10
    for r in scored:
        assert math.isfinite(r["simulated_H_pixels"]) and math.isfinite(r["simulated_W_pixels"])
        assert r["simulated_H_pixels"] >= r["simulated_W_pixels"] > 0.0
        assert r["melt_classification"] == "FINITE_MELT"
    objective = result["objective"]
    assert math.isfinite(objective["objective_value"]) and objective["objective_value"] > 0.0
    assert objective["counts"]["scored_frame_count"] == 10 and objective["counts"]["excluded_by_rule_count"] == 4
    assert objective["counts"]["coverage"] == 1.0 and objective["coverage_flag"] is False


def test_frozen_geometry_timestep_and_source_normalization(example):
    out, _ = example
    final = load_final_model()
    condition = ex.CouponCondition(coupon_id=1, power_W=ex.POWER_W, nominal_speed_mm_s=ex.SPEED_MM_S, spot_diameter_mm=ex.SPOT_MM, sha256="0" * 64, acquisition_set_id=ex.SYNTHETIC_SET_ID)
    base = resize_xy_window(exact_fixed_time_params(out / "synthetic_coupon.h5", condition), 99)
    assert base.grid.Nx == base.grid.Ny == 99
    assert base.grid.uniform_spacing_m(base.geometry) * 1.0e6 == pytest.approx(FROZEN_SPACING_UM, abs=1e-9)
    assert base.time.dt_s == pytest.approx(THERMAL_DT_S, abs=1e-15)
    physics = Patch21GlobalParameterPolicy.from_values(**final["selected_parameters"]["coordinates"]).coefficients.realized_parameters()
    params = current_execution.current_physics_trial_parameters(base, physics)
    assert current_execution.current_directional_stability_record(params, physics)["status"] == "PASS"
    profile = surface_beam_profile(99, 99, spacing_mm=0.016, center_x_mm=0.8, center_y_mm=0.8, gaussian_radius_mm=final["laser_source"]["gaussian_radius_mm"])
    assert profile.sum() == pytest.approx(1.0, abs=1e-12)


def test_example_is_deterministic(example, tmp_path):
    _, first = example
    second = ex.run_example(tmp_path / "again", progress=False)
    keys = ("coupon_sha256", "frame_records", "objective", "energy_accounting", "temperature_trace")
    assert json.dumps({k: first[k] for k in keys}, sort_keys=True) == json.dumps({k: second[k] for k in keys}, sort_keys=True)
    assert np.isclose(first["objective"]["objective_value"], second["objective"]["objective_value"], rtol=0, atol=0)
