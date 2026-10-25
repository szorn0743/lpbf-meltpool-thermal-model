"""Patch 22.3.8 Step 1: field capture (diagnostic only; production semantics unchanged)."""
from __future__ import annotations

import inspect
import json
from pathlib import Path

import numpy as np
import pytest

import lpbf.model.current_execution as current_execution
import lpbf.patch22_3_7_stage_a as stage_a_module
import lpbf.patch22_3_8_field_capture as capture_module
from lpbf.execution.work_units import SimulationResult
from lpbf.experiments.dataset import DatasetMember
from lpbf.model._accepted_core import comparison as accepted_comparison
from lpbf.model._accepted_core.parameters import HeatSourceParameters
from lpbf.model.observation_diagnostics import _label_liquid_components, interpolated_component_contour_hw_diagnostic
from lpbf.model.production_hw import laser_associated_observation_instrumentation
from lpbf.patch22_3_8_camera_step0 import Step0Error, calibration_member_identities

LIQUIDUS = 1673.15
RADIUS = 0.040


class _Geometry:
    Lx_mm = 1.584
    Ly_mm = 1.584


class _Grid:
    Nx = 99
    Ny = 99


class _Params:
    geometry = _Geometry()
    grid = _Grid()


def _fake_builder(**kwargs):
    source = HeatSourceParameters(
        incident_power_W=140.0,
        absorptivity=0.5 if kwargs["laser_on"] else 0.0,
        gaussian_radius_mm=RADIUS,
        depth_mm=0.075,
        center_x_mm=0.792 + float(kwargs.get("accumulated_subcell_x_mm", 0.0)),
        center_y_mm=0.792 + float(kwargs.get("accumulated_subcell_y_mm", 0.0)),
    )
    return np.zeros((2, 2, 2)), source, {"row": kwargs.get("row_index")}


def _fake_accepted_builder(*args, **kwargs):
    _, source, _ = _fake_builder(laser_on=True, **{k: v for k, v in kwargs.items() if k != "params"})
    return np.zeros((2, 2, 2)), source


@pytest.fixture
def fake_sources(monkeypatch):
    monkeypatch.setattr(current_execution, "build_centered_heat_source_for_row_with_deposition_depth", _fake_builder)
    monkeypatch.setattr(accepted_comparison, "build_centered_heat_source_for_row", _fake_accepted_builder)


def _field(length: float = 6.0) -> np.ndarray:
    """A pool around the beam cell (49, 49) plus a remote liquid spot."""

    i, j = np.meshgrid(np.arange(99), np.arange(99), indexing="ij")
    field = 1000.0 + 1400.0 * np.exp(-(((i - 47.0) / length) ** 2 + ((j - 49.0) / 2.5) ** 2))
    field[70:72, 20:22] = LIQUIDUS + 50.0
    return field


def _observe(field: np.ndarray, *, row: int) -> tuple[dict, dict]:
    """One observation through the production instrumentation, the way the accepted core drives the seams."""

    current_execution.build_centered_heat_source_for_row_with_deposition_depth(
        params=_Params(), laser_on=True, row_index=row - 1, accumulated_subcell_x_mm=0.0, accumulated_subcell_y_mm=0.0
    )
    current_execution.build_centered_heat_source_for_row_with_deposition_depth(
        params=_Params(), laser_on=True, row_index=row, accumulated_subcell_x_mm=0.004, accumulated_subcell_y_mm=0.0
    )
    with laser_associated_observation_instrumentation() as interfaces:
        interfaces.heat_source_for_row(params=_Params(), accumulated_subcell_x_mm=0.004, accumulated_subcell_y_mm=0.0)
        liquid = field >= LIQUIDUS
        diagnostics = accepted_comparison.top_surface_liquid_component_diagnostics(liquid, beam_i=49, beam_j=49)
        labels, _ = _label_liquid_components(liquid)
        beam_mask = labels == labels[49, 49]
        beam_result = accepted_comparison.interpolated_component_contour_hw_diagnostic(
            field, beam_mask, liquidus_temperature_K=LIQUIDUS, cell_size_um=16.0, experimental_pixel_size_um=8.0
        )
    return diagnostics, beam_result


def _production_keys(diagnostics: dict) -> dict:
    return {key: value for key, value in diagnostics.items() if key.startswith("production_hw_")}


# ---------------------------------------------------------------------- instrumentation


def test_capture_leaves_production_identical_and_records_a_copy_of_the_field(fake_sources):
    originals = (
        accepted_comparison.top_surface_liquid_component_diagnostics,
        accepted_comparison.interpolated_component_contour_hw_diagnostic,
        stage_a_module.evaluate_calibration_trial,
    )
    field = _field()
    plain_diag, plain_beam = _observe(field.copy(), row=11)
    with capture_module.field_capture_instrumentation() as state:
        captured_field = field.copy()
        diag, beam = _observe(captured_field, row=11)
    assert _production_keys(diag) == _production_keys(plain_diag)
    assert beam == plain_beam
    assert diag["production_hw_association_status"] == "SELECTED"
    assert diag["production_hw_simulated_H_pixels"] > diag["production_hw_simulated_W_pixels"] > 0
    assert len(state["captures"]) == 1  # the second (selected-mask) call is not captured
    capture = state["captures"][0]
    assert capture["field"] is not captured_field and np.array_equal(capture["field"], field)
    captured_field[:] = 0.0
    assert np.array_equal(capture["field"], field)  # stored as a copy
    assert capture["production_status"] == "SELECTED"
    assert capture["selected_label"] == diag["production_hw_association_selected_label"]
    assert capture["source"]["row_index"] == 11 and capture["heating"]["row_index"] == 10
    assert capture["source"]["center_x_mm"] == pytest.approx(0.796)
    assert capture["beam_i"] == 49 and capture["beam_j"] == 49
    assert capture["liquid_cells"] == int(np.count_nonzero(field >= LIQUIDUS))
    assert capture["liquidus_temperature_K"] == LIQUIDUS and capture["cell_size_um"] == 16.0
    assert (
        accepted_comparison.top_surface_liquid_component_diagnostics,
        accepted_comparison.interpolated_component_contour_hw_diagnostic,
        stage_a_module.evaluate_calibration_trial,
    ) == originals
    assert current_execution.build_centered_heat_source_for_row_with_deposition_depth is _fake_builder


def test_seams_are_restored_after_an_exception(fake_sources):
    originals = (
        current_execution.build_centered_heat_source_for_row_with_deposition_depth,
        accepted_comparison.top_surface_liquid_component_diagnostics,
        accepted_comparison.interpolated_component_contour_hw_diagnostic,
        stage_a_module.evaluate_calibration_trial,
    )
    with pytest.raises(RuntimeError, match="boom"):
        with capture_module.field_capture_instrumentation():
            raise RuntimeError("boom")
    assert (
        current_execution.build_centered_heat_source_for_row_with_deposition_depth,
        accepted_comparison.top_surface_liquid_component_diagnostics,
        accepted_comparison.interpolated_component_contour_hw_diagnostic,
        stage_a_module.evaluate_calibration_trial,
    ) == originals


class _Evaluation:
    def __init__(self, pairs):
        self._pairs = list(pairs)

    def to_dict(self):
        return {"observations": [{"frame_index": f, "mapped_process_row": r} for f, r in self._pairs]}


def test_evaluation_wrapper_records_frame_rows_and_returns_the_same_object(monkeypatch):
    sentinel = _Evaluation([(5, 50), (6, 60)])
    fake = lambda *args, **kwargs: sentinel  # noqa: E731
    monkeypatch.setattr(stage_a_module, "evaluate_calibration_trial", fake)
    with capture_module.field_capture_instrumentation() as state:
        assert stage_a_module.evaluate_calibration_trial("member", "policy", "scope") is sentinel
    assert state["evaluation_frames"] == [(5, 50), (6, 60)]
    assert stage_a_module.evaluate_calibration_trial is fake


# ---------------------------------------------------------------------- keying


def _capture(row: int, *, status="SELECTED", label=1):
    return {
        "field": np.full((4, 4), float(row)),
        "beam_i": 1,
        "beam_j": 2,
        "liquid_cells": 3,
        "beam_component_cells": 3,
        "source": {"row_index": row, "laser_on": True, "center_x_mm": 0.79, "center_y_mm": 0.8, "gaussian_radius_mm": RADIUS},
        "heating": {"row_index": row - 1, "center_x_mm": 0.78, "center_y_mm": 0.8, "deposited_power_W": 70.0},
        "production_status": status,
        "selected_label": label,
        "liquidus_temperature_K": LIQUIDUS,
        "cell_size_um": 16.0,
        "experimental_pixel_size_um": 8.0,
    }


_PAYLOAD = {"frame_records": [{"frame_index": 4, "scored_frame": False}, {"frame_index": 5, "scored_frame": True}, {"frame_index": 6, "scored_frame": True}]}


def test_assemble_keys_captures_by_frame():
    state = {"evaluation_frames": [(5, 50), (6, 60)], "captures": [_capture(60), _capture(50, status="NO_LASER_ASSOCIATED_MELT", label=-1)]}
    arrays, failures = capture_module.assemble_unit_capture(state, _PAYLOAD)
    assert failures == []
    assert arrays["frame_index"].tolist() == [5, 6] and arrays["mapped_process_row"].tolist() == [50, 60]
    assert arrays["top_surface_temperature_K"][:, 0, 0].tolist() == [50.0, 60.0]
    assert arrays["production_status"].tolist() == ["NO_LASER_ASSOCIATED_MELT", "SELECTED"]
    assert arrays["selected_label"].tolist() == [-1, 1] and arrays["heating_row_index"].tolist() == [49, 59]
    assert float(arrays["liquidus_temperature_K"]) == LIQUIDUS


@pytest.mark.parametrize(
    "state, expected",
    [
        ({"evaluation_frames": [(5, 50), (6, 60)], "captures": [_capture(50)]}, "missing_capture"),
        ({"evaluation_frames": [(5, 50), (6, 60)], "captures": [_capture(50), _capture(50), _capture(60)]}, "duplicate_capture_row"),
        ({"evaluation_frames": [(5, 50), (6, 60)], "captures": [_capture(50), _capture(60), _capture(70)]}, "unexpected_capture"),
        ({"evaluation_frames": [(5, 50)], "captures": [_capture(50), _capture(60)]}, "evaluation_frames_differ_from_requested"),
        ({"evaluation_frames": None, "captures": []}, "evaluation_not_observed"),
    ],
)
def test_assemble_fails_closed(state, expected):
    arrays, failures = capture_module.assemble_unit_capture(state, _PAYLOAD)
    assert arrays is None and expected in failures


# ---------------------------------------------------------------------- storage


def test_store_writes_a_deterministic_npz_and_drops_the_arrays(tmp_path):
    state = {"evaluation_frames": [(5, 50), (6, 60)], "captures": [_capture(50), _capture(60)]}
    arrays, _ = capture_module.assemble_unit_capture(state, _PAYLOAD)
    first = {"candidate_id": "anchor_center", "member_identity": "20260730:part_1", "capture": arrays}
    capture_module.store_unit_fields(tmp_path / "a", first)
    second = {"candidate_id": "anchor_center", "member_identity": "20260730:part_1", "capture": dict(arrays)}
    capture_module.store_unit_fields(tmp_path / "b", second)
    assert "capture" not in first and first["capture_file"]["frames"] == 2
    assert first["capture_file"]["sha256"] == second["capture_file"]["sha256"]
    with np.load(tmp_path / "a" / first["capture_file"]["path"]) as data:
        for name in arrays:
            assert np.array_equal(data[name], arrays[name])
    empty = {"candidate_id": "anchor_center", "member_identity": "20260730:part_1", "capture": None}
    capture_module.store_unit_fields(tmp_path / "c", empty)
    assert empty["capture_file"] is None


# ---------------------------------------------------------------------- round trip and references


def _selected_arrays(field: np.ndarray, frame: int = 7):
    labels, _ = _label_liquid_components(field >= LIQUIDUS)
    label = int(labels[49, 49])
    hw = interpolated_component_contour_hw_diagnostic(field, labels == label, liquidus_temperature_K=LIQUIDUS, cell_size_um=16.0, experimental_pixel_size_um=8.0)
    arrays = {
        "frame_index": np.array([frame]),
        "top_surface_temperature_K": field[None, :, :],
        "production_status": np.array(["SELECTED"]),
        "selected_label": np.array([label]),
        "liquid_cells": np.array([int(np.count_nonzero(field >= LIQUIDUS))]),
        "liquidus_temperature_K": np.array(LIQUIDUS),
        "cell_size_um": np.array(16.0),
        "experimental_pixel_size_um": np.array(8.0),
    }
    record = {"production_status": "SELECTED", "simulated_H_pixels": hw["H_pixels"], "simulated_W_pixels": hw["W_pixels"]}
    return arrays, {frame: record}


def test_round_trip_reproduces_selected_hw_bit_for_bit_and_detects_drift():
    arrays, records = _selected_arrays(_field())
    result = capture_module.verify_round_trip(arrays, records)
    assert result["pass"] and result["selected_hw_bit_identical"] == 1
    records[7]["simulated_H_pixels"] += 1e-9
    drifted = capture_module.verify_round_trip(arrays, records)
    assert not drifted["pass"] and drifted["mismatches"][0]["problem"] == "selected_hw_differs"
    bad_label = dict(arrays, selected_label=np.array([99]))
    assert capture_module.verify_round_trip(bad_label, _selected_arrays(_field())[1])["mismatches"][0]["problem"] == "selected_label_not_in_saved_field"


def test_round_trip_checks_zero_scored_and_fail_closed_frames():
    arrays, _ = _selected_arrays(_field())
    zero = dict(arrays, production_status=np.array(["NO_LASER_ASSOCIATED_MELT"]))
    ok = {7: {"production_status": "NO_LASER_ASSOCIATED_MELT", "simulated_H_pixels": 0.0, "simulated_W_pixels": 0.0}}
    assert capture_module.verify_round_trip(zero, ok)["pass"]
    wrong = {7: {"production_status": "NO_LASER_ASSOCIATED_MELT", "simulated_H_pixels": 1.0, "simulated_W_pixels": 0.0}}
    assert not capture_module.verify_round_trip(zero, wrong)["pass"]
    tied = dict(arrays, production_status=np.array(["FAIL_CLOSED_TIED_SHARE"]))
    undefined = {7: {"production_status": "FAIL_CLOSED_TIED_SHARE", "simulated_H_pixels": None, "simulated_W_pixels": None}}
    assert capture_module.verify_round_trip(tied, undefined)["pass"]
    status_differs = {7: {"production_status": "SELECTED", "simulated_H_pixels": None, "simulated_W_pixels": None}}
    assert capture_module.verify_round_trip(tied, status_differs)["mismatches"][0]["problem"] == "status_differs"


def test_stage_a_comparison_is_exact_on_repr_strings():
    record = {
        "status": "PASS", "exclusion_reason": None, "undefined_reason": None, "simulated_H_pixels": 22.70067596435547,
        "simulated_W_pixels": 8.404678344726562, "production_status": "SELECTED", "production_mode": "largest_beam_share",
        "production_selected_label": 1, "production_beam_share": 0.42105723619708396, "production_contains_beam_cell": True,
        "melt_classification": "FINITE_MELT",
    }
    reference = {12370: {column: str(stage_a_module._csv_value(record[column])) for column in capture_module.STAGE_A_COMPARE_COLUMNS}}
    assert capture_module.compare_with_stage_a({12370: record}, reference)["pass"]
    changed = dict(record, simulated_H_pixels=22.700675964355472)
    result = capture_module.compare_with_stage_a({12370: changed}, reference)
    assert not result["pass"] and result["mismatches"][0]["column"] == "simulated_H_pixels"
    assert not capture_module.compare_with_stage_a({12370: record, 12371: record}, reference)["pass"]


def test_census_comparison_is_exact():
    arrays = {
        "frame_index": np.array([12370]),
        "mapped_process_row": np.array([427]),
        "source_center_x_mm": np.array([0.7795267498561246]),
        "source_center_y_mm": np.array([0.7920812254335543]),
        "heating_center_x_mm": np.array([0.7863776631728757]),
        "heating_center_y_mm": np.array([0.79]),
    }
    reference = {
        12370: {
            "mapped_process_row": "427",
            "census_source_center_x_mm": "0.7795267498561246",
            "census_source_center_y_mm": "0.7920812254335543",
            "census_heating_center_x_mm": "0.7863776631728757",
            "census_heating_center_y_mm": "0.79",
        }
    }
    assert capture_module.compare_with_census(arrays, reference)["pass"]
    reference[12370]["census_source_center_x_mm"] = "0.7795267498561247"
    assert not capture_module.compare_with_census(arrays, reference)["pass"]


# ---------------------------------------------------------------------- runner


def _member(position: int) -> DatasetMember:
    return DatasetMember(
        set_id=1, dataset_member_id=position, coupon_position=position, path=Path(f"part_{position}_20260730.h5").resolve(),
        sha256=f"{position:064d}", power_W=140.0, nominal_speed_mm_s=850.0, spot_diameter_mm=0.08, acquisition_set_id="20260730",
    )


MEMBERS = {"20260730:part_1": _member(1), "20260730:part_3": _member(3)}


def _rows(member_identity: str, frames: dict[str, list[int]]) -> list[dict]:
    return [
        {"member_identity": member_identity, "scan_track_id": track, "frame_index": frame, "experimental_H_pixels": 9.0, "experimental_W_pixels": 8.0, "observation_eligible": True}
        for track, indices in frames.items()
        for frame in indices
    ]


ROWS = {
    "20260730:part_1": _rows("20260730:part_1", {"1": [10, 11, 12, 13], "2": [20, 21, 22]}),
    "20260730:part_3": _rows("20260730:part_3", {"1": [30, 31, 32]}),
}


def _fake_stage_a_unit(job):
    """Drives the seams the way a real unit does, then calls the (fake) evaluator."""

    context = job.experiment_context_dict
    rows = json.loads(context["frame_rows_json"])
    records, pairs = [], []
    for row in rows:
        record = dict(row)
        if not row["scored_frame"]:
            record["status"] = "EXCLUDED"
            records.append(record)
            continue
        process_row = 100 + 10 * int(row["frame_index"])
        diagnostics, _ = _observe(_field(length=4.0 + int(row["frame_index"]) % 3), row=process_row)
        pairs.append((int(row["frame_index"]), process_row))
        record.update(
            {
                "status": "PASS",
                "simulated_H_pixels": diagnostics["production_hw_simulated_H_pixels"],
                "simulated_W_pixels": diagnostics["production_hw_simulated_W_pixels"],
                "production_status": diagnostics["production_hw_association_status"],
            }
        )
        records.append(record)
    stage_a_module.evaluate_calibration_trial(pairs)
    scored = sum(1 for row in rows if row["scored_frame"])
    return {
        "candidate_id": context["candidate_id"],
        "member_identity": job.member_identity,
        "frame_records": records,
        "gate_failures": [],
        "evaluation_status": "PASS",
        "requested_frame_count": scored,
        "returned_frame_count": scored,
    }


@pytest.fixture
def fake_runner(monkeypatch, fake_sources):
    monkeypatch.setattr(capture_module, "_member_map", lambda data_directory: dict(MEMBERS))
    monkeypatch.setattr(capture_module, "_find_frame_file", lambda root, member: Path(root) / f"{member.coupon_position}.csv")
    monkeypatch.setattr(capture_module, "_portable_frame_rows", lambda path, member: list(ROWS[f"20260730:part_{member.coupon_position}"]))
    monkeypatch.setattr(stage_a_module, "_stage_a_unit_job", _fake_stage_a_unit)
    monkeypatch.setattr(stage_a_module, "evaluate_calibration_trial", lambda pairs: _Evaluation(pairs))

    def fake_pool(jobs, worker, *, workers, on_result=None):
        results = []
        for job in reversed(tuple(jobs)):
            result = SimulationResult(job=job, payload=worker(job))
            if on_result is not None:
                on_result(result)
            results.append(result)
        return tuple(results)

    monkeypatch.setattr(capture_module, "execute_parallel_jobs", fake_pool)


UNITS = (("anchor_center", "20260730:part_1"), ("anchor_t_min", "20260730:part_3"))


def test_runner_parallel_equals_serial_and_gate_passes(tmp_path, fake_runner):
    common = dict(data_directory=tmp_path, characterization_directory=tmp_path, units=UNITS)
    serial = capture_module.run_field_capture(output_directory=tmp_path / "serial", workers=1, **common)
    parallel = capture_module.run_field_capture(output_directory=tmp_path / "parallel", workers=4, **common)
    assert serial["execution"]["start_method"] == "serial" and parallel["execution"]["workers"] == 2
    assert serial["units"] == parallel["units"]
    for unit in serial["units"]:
        for folder in ("serial", "parallel"):
            assert unit["capture_gate_failures"] == [] and unit["captured_frame_count"] == unit["requested_frame_count"] > 0
        for name in (unit["unit_file"], unit["capture_file"]["path"]):
            assert (tmp_path / "serial" / name).read_bytes() == (tmp_path / "parallel" / name).read_bytes()
    gate = capture_module.evaluate_capture_gate(tmp_path / "serial", stage_a_frames_csv=tmp_path / "none.csv", census_frames_csv=tmp_path / "none.csv")
    assert gate["status"] == capture_module.GATE_PASS
    assert all(unit["G3_round_trip"]["selected_hw_bit_identical"] == unit["G1_counts"]["captured"] for unit in gate["units"])
    assert gate["G5_global"]["frozen_core"]["pass"] and gate["G5_global"]["dispatch_lock"]["pass"]
    strict = capture_module.evaluate_capture_gate(
        tmp_path / "serial", stage_a_frames_csv=tmp_path / "none.csv", census_frames_csv=tmp_path / "none.csv", require_references=True
    )
    assert strict["status"] == capture_module.GATE_FAIL  # Step 1 requires the Stage-A and census references


def test_gate_fails_when_a_field_file_is_altered(tmp_path, fake_runner):
    manifest = capture_module.run_field_capture(data_directory=tmp_path, characterization_directory=tmp_path, output_directory=tmp_path / "out", units=UNITS[:1], workers=1)
    path = tmp_path / "out" / manifest["units"][0]["capture_file"]["path"]
    with np.load(path) as data:
        arrays = {name: data[name] for name in data.files}
    arrays["top_surface_temperature_K"] = arrays["top_surface_temperature_K"] + 1e-6
    capture_module.write_npz_deterministic(path, arrays)
    gate = capture_module.evaluate_capture_gate(tmp_path / "out", stage_a_frames_csv=tmp_path / "none.csv", census_frames_csv=tmp_path / "none.csv")
    assert gate["status"] == capture_module.GATE_FAIL and "hash differs" in gate["units"][0]["G3_round_trip"]["reason"]


def test_runner_refuses_held_out_members_before_touching_data(tmp_path):
    with pytest.raises(Step0Error, match="held-out"):
        capture_module.run_field_capture(
            data_directory=tmp_path / "missing", characterization_directory=tmp_path, output_directory=tmp_path / "out", units=[("anchor_center", "20260730:part_2")]
        )
    assert not (tmp_path / "out").exists()


def test_step2_units_are_predeclared_and_calibration_only():
    units = capture_module.step2_units()
    calibration = set(calibration_member_identities())
    assert len(units) == 24 and {member for _, member in units} <= calibration
    assert sum(1 for candidate, _ in units if candidate == "anchor_center") == 16
    assert {member for candidate, member in units if candidate != "anchor_center"} == set(capture_module.CORNER_MEMBERS)
    assert capture_module.STEP1_UNITS == (("anchor_center", "20260730:part_1"),)


def test_step4_units_cover_the_rest_of_the_frozen_design_on_the_corners():
    units = capture_module.step4_units()
    candidates = {candidate for candidate, _ in units}
    design = set(stage_a_module._candidate_coordinates())
    assert len(design) == 17 and candidates == design - set(capture_module.STEP2_CANDIDATES) and len(candidates) == 14
    assert len(units) == 56 and {member for _, member in units} == set(capture_module.CORNER_MEMBERS)
    assert not set(units) & set(capture_module.step2_units())


def test_unit_parser_and_no_dispatch_path():
    assert capture_module._parse_unit("anchor_center@20260730:part_1") == ("anchor_center", "20260730:part_1")
    with pytest.raises(Exception):
        capture_module._parse_unit("anchor_center")
    source = inspect.getsource(capture_module)
    assert "run_search" not in source and "_thermal_worker" not in source
