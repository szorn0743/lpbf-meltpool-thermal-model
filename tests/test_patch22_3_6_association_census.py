"""Patch 22.3.6 association census: per-component telemetry, offline rule evaluation, sync audit.

Diagnostic only.  Nothing here changes association policy or H/W semantics; the
census records enough per-frame geometry that any candidate rule can be
evaluated offline on identical thermal fields.
"""
from __future__ import annotations

import json
import math
import pickle
from pathlib import Path

import numpy as np
import pytest

import lpbf.model.current_execution as current_execution
import lpbf.patch22_3_6_association_census as census_module
from lpbf.execution.work_units import SimulationResult
from lpbf.experiments.dataset import DatasetMember
from lpbf.model._accepted_core import comparison as accepted_comparison
from lpbf.model._accepted_core.parameters import HeatSourceParameters
from lpbf.model.observation_diagnostics import interpolated_component_contour_hw_diagnostic
from lpbf.model.production_hw import PRODUCTION_HW_SEMANTICS_VERSION, laser_associated_observation_instrumentation
from lpbf.patch22_3_6_association_census import (
    BEAM_SHARE_FLOORS,
    CENSUS_STATUS_FAIL,
    CENSUS_STATUS_PASS,
    CONTOUR_RADII_CELLS,
    DEFAULT_CENSUS_WORKERS,
    STAGE_A_CANDIDATES,
    STAGE_A_MEMBERS,
    AssociationCensusError,
    association_census_instrumentation,
    audit_member_tracks,
    build_census_jobs,
    component_contour_points_mm,
    evaluate_beam_share_rule,
    evaluate_census,
    evaluate_contour_distance_rule,
    label_track_positions,
    per_component_telemetry,
    run_association_census,
    surface_beam_profile,
)
from lpbf.patch22_4_3_parallel_coarse_calibration_execution import _dataset_member_from_context

SPACING = 0.016
RADIUS = 0.040
LIQUIDUS = 1673.15


def _member(position: int) -> DatasetMember:
    return DatasetMember(
        set_id=1,
        dataset_member_id=position,
        coupon_position=position,
        path=Path(f"part_{position}_20260730.h5").resolve(),
        sha256=f"{position:064d}",
        power_W=140.0,
        nominal_speed_mm_s=850.0,
        spot_diameter_mm=0.08,
        acquisition_set_id="20260730",
    )


MEMBERS = {"20260730:part_1": _member(1), "20260730:part_3": _member(3)}


def _frame_rows(member_identity: str, frames: dict[str, list[int]]) -> list[dict]:
    rows = []
    for track, indices in frames.items():
        for frame in indices:
            rows.append(
                {
                    "member_identity": member_identity,
                    "scan_track_id": track,
                    "frame_index": frame,
                    "experimental_H_pixels": 9.0,
                    "experimental_W_pixels": 8.0,
                    "observation_eligible": True,
                }
            )
    return rows


def _blob(nx: int, ny: int, *, ci: float, cj: float, a: float, b: float, peak: float = 2400.0) -> np.ndarray:
    i, j = np.meshgrid(np.arange(nx), np.arange(ny), indexing="ij")
    return 1000.0 + (peak - 1000.0) * np.exp(-(((i - ci) / a) ** 2 + ((j - cj) / b) ** 2))


# ---------------------------------------------------------------- geometry


def test_surface_beam_profile_is_normalized_and_peaks_under_the_source():
    profile = surface_beam_profile(99, 99, spacing_mm=SPACING, center_x_mm=0.805, center_y_mm=0.792, gaussian_radius_mm=RADIUS)
    assert profile.shape == (99, 99)
    assert profile.sum() == pytest.approx(1.0, abs=1e-12)
    peak = np.unravel_index(int(np.argmax(profile)), profile.shape)
    assert peak == (50, 49)  # 0.805 mm lies in cell 50 (0.800-0.816); 0.792 mm is the center of cell 49
    # 1/e^2 definition: a cell one beam radius away carries exp(-2) of the peak density
    i0, j0 = peak
    ratio = profile[i0, j0 + 3] / profile[i0, j0]  # 3 cells = 0.048 mm from the center's cell
    expected = math.exp(-2.0 * ((j0 + 3 + 0.5) * SPACING - 0.792) ** 2 / RADIUS**2) / math.exp(
        -2.0 * ((j0 + 0.5) * SPACING - 0.792) ** 2 / RADIUS**2
    )
    assert ratio == pytest.approx(expected, rel=1e-12)


def test_beam_share_separates_a_trailing_pool_from_a_remnant_one_hatch_over():
    nx = ny = 99
    source_x = (49 + 0.5) * SPACING
    source_y = (49 + 0.5) * SPACING
    mask = np.zeros((nx, ny), dtype=bool)
    mask[42:48, 47:52] = True  # trailing pool: nearest cell center 1.5 cells behind the source along x
    mask[41:58, 53:56] = True  # previous-line remnant: one hatch (5 cells) over in y, 3 cells wide
    top = np.where(mask, LIQUIDUS + 100.0, 1000.0)
    components, summary = per_component_telemetry(
        mask,
        top,
        spacing_mm=SPACING,
        liquidus_temperature_K=LIQUIDUS,
        experimental_pixel_size_um=8.0,
        source_center_x_mm=source_x,
        source_center_y_mm=source_y,
        gaussian_radius_mm=RADIUS,
        beam_i=49,
        beam_j=49,
    )
    assert len(components) == 2
    by_count = sorted(components, key=lambda item: item["cell_count"])
    trailing, remnant = by_count[0], by_count[1]
    assert trailing["cell_count"] == 30 and remnant["cell_count"] == 51
    assert trailing["beam_share"] > 0.03
    assert remnant["beam_share"] < 0.01
    assert trailing["beam_share"] / remnant["beam_share"] > 5.0
    assert summary["beam_share_on_liquid_total"] == pytest.approx(trailing["beam_share"] + remnant["beam_share"])
    assert trailing["min_cell_center_distance_cells"] == pytest.approx(2.0)
    assert trailing["contains_beam_cell"] is False and remnant["contains_beam_cell"] is False


def test_contour_points_reproduce_the_official_component_hw():
    import cv2

    top = _blob(40, 40, ci=20.3, cj=18.7, a=5.0, b=3.0)
    mask = top >= LIQUIDUS
    official = interpolated_component_contour_hw_diagnostic(
        top, mask, liquidus_temperature_K=LIQUIDUS, cell_size_um=16.0, experimental_pixel_size_um=8.0
    )
    points_mm = component_contour_points_mm(top, mask, liquidus_temperature_K=LIQUIDUS, spacing_mm=SPACING)
    assert points_mm.shape[1] == 2 and len(points_mm) > 8
    rect = cv2.minAreaRect(np.asarray(points_mm / 0.008, dtype=np.float32))
    h, w = max(rect[1]), min(rect[1])
    assert h == pytest.approx(official["H_pixels"], rel=1e-5, abs=1e-5)
    assert w == pytest.approx(official["W_pixels"], rel=1e-5, abs=1e-5)
    # the contour lies between the last liquid cell center and the first solid one
    source = ((20 + 0.5) * SPACING, (26 + 0.5) * SPACING)  # just outside the blob in +y
    centre_distance = np.min(np.hypot((np.argwhere(mask)[:, 0] + 0.5) * SPACING - source[0], (np.argwhere(mask)[:, 1] + 0.5) * SPACING - source[1]))
    contour_distance = np.min(np.hypot(points_mm[:, 0] - source[0], points_mm[:, 1] - source[1]))
    assert contour_distance < centre_distance


def test_per_component_telemetry_reports_boundary_contact_and_heating_position():
    nx = ny = 30
    mask = np.zeros((nx, ny), dtype=bool)
    mask[14:17, 14:18] = True  # enclosed pool containing the beam cell
    mask[0:3, 25:29] = True  # touches x_min boundary
    top = np.where(mask, LIQUIDUS + 50.0, 1200.0)
    source_x, source_y = (15 + 0.5) * SPACING, (15 + 0.5) * SPACING
    components, summary = per_component_telemetry(
        mask,
        top,
        spacing_mm=SPACING,
        liquidus_temperature_K=LIQUIDUS,
        experimental_pixel_size_um=8.0,
        source_center_x_mm=source_x,
        source_center_y_mm=source_y,
        gaussian_radius_mm=RADIUS,
        beam_i=15,
        beam_j=15,
        heating_center_x_mm=source_x - 0.004,
        heating_center_y_mm=source_y,
    )
    pool = next(item for item in components if item["contains_beam_cell"])
    edge = next(item for item in components if not item["contains_beam_cell"])
    assert pool["cell_count"] == 12 and pool["touches_boundary"] is False
    assert pool["min_cell_center_distance_cells"] == 0.0
    assert pool["min_contour_distance_cells"] > 0.0
    assert pool["contour_status"] == "FINITE_BEAM_COMPONENT" and pool["H_pixels"] > pool["W_pixels"] > 0.0
    assert pool["min_cell_center_distance_from_heating_center_cells"] == pytest.approx(0.25)
    assert edge["touches_boundary"] is True and edge["boundary_sides"] == ["x_min"]
    assert edge["contour_status"] == "UNENCLOSED_BEAM_COMPONENT" and edge["H_pixels"] is None
    assert summary["component_count"] == 2 and summary["beam_cell_label"] == pool["label"]
    assert 0.0 < summary["beam_share_on_liquid_total"] <= 1.0
    for item in components:
        assert all(isinstance(item[key], (float, int, bool, str, list, type(None))) for key in item)


# ------------------------------------------------------------ rule evaluation


def _component(label, *, share, contour, centre, h=10.0, w=6.0, boundary=False, status="FINITE_BEAM_COMPONENT"):
    return {
        "label": label,
        "cell_count": 20,
        "contains_beam_cell": False,
        "touches_boundary": boundary,
        "boundary_sides": ["x_min"] if boundary else [],
        "beam_share": share,
        "min_cell_center_distance_cells": centre,
        "min_contour_distance_cells": contour,
        "min_cell_center_distance_from_heating_center_cells": centre,
        "min_contour_distance_from_heating_center_cells": contour,
        "contour_status": status,
        "H_pixels": None if boundary else h,
        "W_pixels": None if boundary else w,
    }


def test_beam_share_rule_statuses_and_scoring():
    pool = _component(1, share=0.30, contour=0.6, centre=1.2)
    remnant = _component(2, share=0.004, contour=2.6, centre=3.1, h=12.0, w=7.0)

    selected = evaluate_beam_share_rule([pool, remnant], floor=0.02)
    assert selected["status"] == "SELECTED" and selected["selected_label"] == 1
    assert selected["scored"] is True and (selected["scored_H_pixels"], selected["scored_W_pixels"]) == (10.0, 6.0)

    no_melt = evaluate_beam_share_rule([remnant], floor=0.02)
    assert no_melt["status"] == "NO_LASER_ASSOCIATED_MELT"
    assert no_melt["scored"] is True and (no_melt["scored_H_pixels"], no_melt["scored_W_pixels"]) == (0.0, 0.0)
    assert no_melt["selected_label"] is None

    zero = evaluate_beam_share_rule([], floor=0.02)
    assert zero["status"] == "ZERO_FOOTPRINT" and (zero["scored_H_pixels"], zero["scored_W_pixels"]) == (0.0, 0.0)

    tied = evaluate_beam_share_rule([pool, _component(3, share=0.30, contour=0.7, centre=1.3)], floor=0.02)
    assert tied["status"] == "AMBIGUOUS" and tied["scored"] is False
    assert tied["scored_H_pixels"] is None and tied["scored_W_pixels"] is None

    unenclosed = evaluate_beam_share_rule([_component(4, share=0.5, contour=0.2, centre=0.9, boundary=True, status="UNENCLOSED_BEAM_COMPONENT")], floor=0.02)
    assert unenclosed["status"] == "UNENCLOSED" and unenclosed["scored"] is False and unenclosed["scored_H_pixels"] is None

    with pytest.raises(AssociationCensusError, match="floor"):
        evaluate_beam_share_rule([pool], floor=-0.1)


def test_contour_distance_rule_statuses():
    near = _component(1, share=0.1, contour=0.8, centre=1.4)
    far = _component(2, share=0.001, contour=3.0, centre=3.6)
    assert evaluate_contour_distance_rule([near, far], radius_cells=1.0)["selected_label"] == 1
    outside = evaluate_contour_distance_rule([far], radius_cells=1.0)
    assert outside["status"] == "NO_LASER_ASSOCIATED_MELT" and outside["distance_cells"] == 3.0
    assert outside["scored_H_pixels"] == 0.0
    assert evaluate_contour_distance_rule([far], radius_cells=3.0)["status"] == "SELECTED"  # radius is inclusive
    tied = evaluate_contour_distance_rule([near, _component(3, share=0.1, contour=0.8, centre=1.5)], radius_cells=1.0)
    assert tied["status"] == "AMBIGUOUS" and tied["scored_H_pixels"] is None
    assert evaluate_contour_distance_rule([], radius_cells=1.0)["status"] == "ZERO_FOOTPRINT"
    # a source inside a pool is at distance 0, not at the distance to the pool's far edge
    inside = {**_component(5, share=0.6, contour=2.4, centre=0.0), "contains_beam_cell": True}
    containing = evaluate_contour_distance_rule([inside, far], radius_cells=1.0)
    assert containing["status"] == "SELECTED" and containing["selected_label"] == 5 and containing["distance_cells"] == 0.0


def test_default_floors_and_radii_are_predeclared_grids():
    assert BEAM_SHARE_FLOORS == (0.005, 0.01, 0.02, 0.05, 0.10, 0.135, 0.25)
    assert CONTOUR_RADII_CELLS == (1.0, 1.5, 2.0, 2.5)
    assert DEFAULT_CENSUS_WORKERS == 4
    assert STAGE_A_CANDIDATES == ("anchor_center", "anchor_t_min", "anchor_t_max", "halton_04", "halton_11")
    assert STAGE_A_MEMBERS == ("20260730:part_1", "20260730:part_3")


def test_track_positions_label_first_last_single_and_interior_frames():
    rows = _frame_rows("20260730:part_1", {"7": [120, 131, 125], "8": [140], "9": [150, 160]})
    rows.append({**rows[0], "frame_index": 118, "observation_eligible": False})
    positions = label_track_positions(rows)
    assert 118 not in positions
    assert positions[120] == {"scan_track_id": "7", "position": 0, "track_frame_count": 3, "is_first": True, "is_last": False, "edge_class": "first"}
    assert positions[125]["edge_class"] == "interior" and positions[131]["edge_class"] == "last"
    assert positions[140] == {"scan_track_id": "8", "position": 0, "track_frame_count": 1, "is_first": True, "is_last": True, "edge_class": "single"}
    assert positions[150]["is_first"] and positions[160]["is_last"]


# ----------------------------------------------------------- instrumentation


class _Geometry:
    Lx_mm = 1.584
    Ly_mm = 1.584


class _Grid:
    Nx = 99
    Ny = 99


class _Params:
    geometry = _Geometry()
    grid = _Grid()


def test_census_instrumentation_nests_outside_production_and_records_source_builds(monkeypatch):
    original_top = accepted_comparison.top_surface_liquid_component_diagnostics
    original_component_hw = accepted_comparison.interpolated_component_contour_hw_diagnostic

    def fake_builder(**kwargs):
        source = HeatSourceParameters(
            incident_power_W=140.0,
            absorptivity=0.5 if kwargs["laser_on"] else 0.0,
            gaussian_radius_mm=RADIUS,
            depth_mm=0.075,
            center_x_mm=0.792 + float(kwargs.get("accumulated_subcell_x_mm", 0.0)),
            center_y_mm=0.792 + float(kwargs.get("accumulated_subcell_y_mm", 0.0)),
        )
        return np.zeros((2, 2, 2)), source, {"row": kwargs.get("row_index")}

    def fake_accepted_builder(*args, **kwargs):
        _, source, _ = fake_builder(laser_on=True, **{k: v for k, v in kwargs.items() if k != "params"})
        return np.zeros((2, 2, 2)), source

    monkeypatch.setattr(current_execution, "build_centered_heat_source_for_row_with_deposition_depth", fake_builder)
    monkeypatch.setattr(accepted_comparison, "build_centered_heat_source_for_row", fake_accepted_builder)

    mask = np.zeros((99, 99), dtype=bool)
    mask[48:51, 47:50] = True  # pool containing the beam cell (49, 49)
    mask[48:52, 55:58] = True  # second component one hatch over
    top = np.where(mask, LIQUIDUS + 80.0, 1100.0)

    with association_census_instrumentation() as census_state:
        current_execution.build_centered_heat_source_for_row_with_deposition_depth(
            params=_Params(), laser_on=False, row_index=10, accumulated_subcell_x_mm=0.0, accumulated_subcell_y_mm=0.0
        )
        current_execution.build_centered_heat_source_for_row_with_deposition_depth(
            params=_Params(), laser_on=True, row_index=11, accumulated_subcell_x_mm=0.004, accumulated_subcell_y_mm=0.0
        )
        assert [build["row_index"] for build in census_state["builds"]] == [10, 11]
        with laser_associated_observation_instrumentation() as interfaces:
            interfaces.heat_source_for_row(params=_Params(), accumulated_subcell_x_mm=0.004, accumulated_subcell_y_mm=0.0)
            diagnostics = accepted_comparison.top_surface_liquid_component_diagnostics(mask, beam_i=49, beam_j=49)
            beam_result = accepted_comparison.interpolated_component_contour_hw_diagnostic(
                top, mask & (np.arange(99)[:, None] < 52) & (np.arange(99)[None, :] < 52),
                liquidus_temperature_K=LIQUIDUS, cell_size_um=16.0, experimental_pixel_size_um=8.0,
            )
    # production outcome is untouched and present
    assert diagnostics["production_hw_association_status"] == "SELECTED"
    assert diagnostics["production_hw_association_mode"] == "largest_beam_share"  # Patch 22.3.7 production
    assert diagnostics["production_hw_association_contains_beam_cell"] is True
    assert diagnostics["production_hw_simulated_H_pixels"] == pytest.approx(beam_result["H_pixels"])
    # census telemetry rides on the same diagnostics record
    assert diagnostics["census_patch"] == "22.3.6"
    assert diagnostics["census_component_count"] == 2 and len(diagnostics["census_components"]) == 2
    assert diagnostics["census_source_row_index"] == 11 and diagnostics["census_source_laser_on"] is True
    assert diagnostics["census_source_center_x_mm"] == pytest.approx(0.796)
    assert diagnostics["census_heating_row_index"] == 10 and diagnostics["census_heating_laser_on"] is False
    assert diagnostics["census_gaussian_radius_mm"] == RADIUS
    assert diagnostics["census_spacing_mm"] == pytest.approx(SPACING)
    pool = next(item for item in diagnostics["census_components"] if item["contains_beam_cell"])
    assert pool["H_pixels"] == pytest.approx(beam_result["H_pixels"]) and pool["beam_share"] > 0.3
    assert diagnostics["census_production_selected_label"] == pool["label"]
    # both seams are restored on exit
    assert accepted_comparison.top_surface_liquid_component_diagnostics is original_top
    assert accepted_comparison.interpolated_component_contour_hw_diagnostic is original_component_hw
    assert current_execution.build_centered_heat_source_for_row_with_deposition_depth is fake_builder


# ------------------------------------------------------------ jobs / execution


def _rows_by_member():
    return {
        "20260730:part_1": _frame_rows("20260730:part_1", {"1": [12369, 12380], "2": [12400]}),
        "20260730:part_3": _frame_rows("20260730:part_3", {"1": [2100, 2110, 2120]}),
    }


def _tracks_by_member():
    return {
        "20260730:part_1": {"1": {"process_row_start": 383, "process_row_end": 3237}, "2": {"process_row_start": 3533, "process_row_end": 3588}},
        "20260730:part_3": {"1": {"process_row_start": 100, "process_row_end": 900}},
    }


def test_census_jobs_are_one_per_unit_sorted_and_spawn_safe(tmp_path):
    units = [("anchor_t_min", "20260730:part_3"), ("anchor_center", "20260730:part_1"), ("anchor_center", "20260730:part_3")]
    jobs = build_census_jobs(units, MEMBERS, _rows_by_member(), _tracks_by_member(), characterization_directory=tmp_path)
    assert [(job.experiment_context_dict["candidate_id"], job.member_identity) for job in jobs] == [
        ("anchor_center", "20260730:part_1"),
        ("anchor_center", "20260730:part_3"),
        ("anchor_t_min", "20260730:part_3"),
    ]
    assert [job.case_index for job in jobs] == [0, 1, 2]
    assert jobs[0].frame_index == 12369 and jobs[1].frame_index == 2100
    assert len({job.identity_key for job in jobs}) == 3
    for job in jobs:
        assert pickle.loads(pickle.dumps(job)) == job
        context = job.experiment_context_dict
        assert _dataset_member_from_context(json.loads(context["dataset_member_json"])) == MEMBERS[job.member_identity]
        assert json.loads(context["frame_rows_json"]) == _rows_by_member()[job.member_identity]
        assert json.loads(context["track_rows_json"]) == _tracks_by_member()[job.member_identity]
        assert context["characterization_directory"] == str(tmp_path.resolve())
    with pytest.raises(AssociationCensusError, match="frozen coarse design"):
        build_census_jobs([("nope", "20260730:part_1")], MEMBERS, _rows_by_member(), _tracks_by_member(), characterization_directory=tmp_path)
    with pytest.raises(AssociationCensusError, match="dataset member is missing"):
        build_census_jobs([("anchor_center", "20260730:part_2")], MEMBERS, _rows_by_member(), _tracks_by_member(), characterization_directory=tmp_path)


@pytest.mark.parametrize("workers", [0, -1, True, 2.0, "4"])
def test_census_workers_must_be_a_positive_integer(tmp_path, workers):
    with pytest.raises(AssociationCensusError, match="workers must be a positive integer"):
        run_association_census(data_directory=tmp_path, characterization_directory=tmp_path, output_directory=tmp_path / "out", workers=workers)
    assert not (tmp_path / "out").exists()


def _fake_unit_payload(job, *, drop_last_frame=False):
    context = job.experiment_context_dict
    rows = json.loads(context["frame_rows_json"])
    if drop_last_frame:
        rows = rows[:-1]
    frames = []
    for row in rows:
        undefined = row["frame_index"] % 2 == 0
        frames.append(
            {
                "frame_index": row["frame_index"],
                "mapped_process_row": row["frame_index"] * 3,
                "scan_track_id": row["scan_track_id"],
                "experimental_H_pixels": row["experimental_H_pixels"],
                "experimental_W_pixels": row["experimental_W_pixels"],
                "production_status": "FAIL_CLOSED_DISTANCE_EXCEEDED" if undefined else "SELECTED",
                "production_mode": "fail_closed" if undefined else "strict_center",
                "production_H_pixels": None if undefined else 11.0,
                "production_W_pixels": None if undefined else 5.5,
                "census_components": [_component(1, share=0.2, contour=0.5, centre=1.1)],
            }
        )
    return {
        "candidate_id": context["candidate_id"],
        "member_identity": job.member_identity,
        "requested_frame_count": len(json.loads(context["frame_rows_json"])),
        "returned_frame_count": len(frames),
        "evaluation_status": "FAILURE",
        "evaluation_stage": "observation_validation",
        "evaluation_failure": {"code": "PRIMARY_OBSERVATION_REJECTED"},
        "frames": frames,
        "thermal_execution_performed": True,
    }


def _patch_inputs(monkeypatch):
    monkeypatch.setattr(census_module, "_member_map", lambda data_directory: dict(MEMBERS))
    monkeypatch.setattr(census_module, "_find_frame_file", lambda root, member: Path(root) / f"{member.coupon_position}.csv")
    monkeypatch.setattr(census_module, "_portable_frame_rows", lambda path, member: list(_rows_by_member()[f"20260730:part_{member.coupon_position}"]))
    monkeypatch.setattr(census_module, "_read_scan_tracks", lambda path: dict(_tracks_by_member()[f"20260730:part_{path.stem}"]))


def test_census_parallel_output_is_identical_to_serial(tmp_path, monkeypatch):
    _patch_inputs(monkeypatch)
    monkeypatch.setattr(census_module, "_census_unit_job", _fake_unit_payload)
    dispatched = {}

    def fake_pool(jobs, worker, *, workers, on_result=None):
        dispatched["workers"] = workers
        results = []
        for job in reversed(tuple(jobs)):
            result = SimulationResult(job=job, payload=worker(job))
            if on_result is not None:
                on_result(result)
            results.append(result)
        return tuple(results)

    monkeypatch.setattr(census_module, "execute_parallel_jobs", fake_pool)
    progress = []
    common = dict(data_directory=tmp_path, characterization_directory=tmp_path, candidates=("anchor_center", "anchor_t_min"))
    serial = run_association_census(output_directory=tmp_path / "serial", workers=1, **common)
    parallel = run_association_census(
        output_directory=tmp_path / "parallel",
        workers=4,
        progress_callback=lambda done, total, unit: progress.append((done, total, unit["candidate_id"], unit["member_identity"])),
        **common,
    )
    assert dispatched["workers"] == 4
    assert serial["status"] == parallel["status"] == CENSUS_STATUS_PASS
    assert serial["units"] == parallel["units"]
    assert [unit["candidate_id"] for unit in serial["units"]] == ["anchor_center", "anchor_center", "anchor_t_min", "anchor_t_min"]
    assert serial["frame_count"] == parallel["frame_count"] == 12
    for name in ("PATCH_22_3_6_ASSOCIATION_CENSUS_FRAMES.csv", "PATCH_22_3_6_ASSOCIATION_CENSUS_COMPONENTS.csv"):
        assert (tmp_path / "parallel" / name).read_bytes() == (tmp_path / "serial" / name).read_bytes()
    for unit in serial["units"]:
        assert (tmp_path / "parallel" / "units" / unit["unit_file"]).read_bytes() == (tmp_path / "serial" / "units" / unit["unit_file"]).read_bytes()
    assert serial["census_execution"]["start_method"] == "serial" and serial["census_execution"]["workers"] == 1
    assert parallel["census_execution"]["start_method"] == "spawn" and parallel["census_execution"]["workers"] == 4
    assert [(done, total) for done, total, *_ in progress] == [(1, 4), (2, 4), (3, 4), (4, 4)]
    assert parallel["full_campaign_dispatched"] is False and parallel["validation_partition_used"] is False
    assert parallel["parameter_fitting_performed"] is False and parallel["parameter_selection_performed"] is False
    assert parallel["production_hw_semantics_version"] == PRODUCTION_HW_SEMANTICS_VERSION and parallel["semantics_changed"] is False
    report = json.loads((tmp_path / "parallel" / "PATCH_22_3_6_ASSOCIATION_CENSUS_REPORT.json").read_text(encoding="utf-8"))
    assert report["status"] == CENSUS_STATUS_PASS
    # undefined production H/W is written as null, never as zero
    unit = json.loads((tmp_path / "parallel" / "units" / serial["units"][0]["unit_file"]).read_text(encoding="utf-8"))
    undefined = [frame for frame in unit["frames"] if frame["production_status"] != "SELECTED"]
    assert undefined and all(frame["production_H_pixels"] is None for frame in undefined)


def test_census_fails_closed_when_a_unit_returns_fewer_frames(tmp_path, monkeypatch):
    _patch_inputs(monkeypatch)
    monkeypatch.setattr(census_module, "_census_unit_job", lambda job: _fake_unit_payload(job, drop_last_frame=True))
    report = run_association_census(data_directory=tmp_path, characterization_directory=tmp_path, output_directory=tmp_path / "out", workers=1, candidates=("anchor_center",))
    assert report["status"] == CENSUS_STATUS_FAIL
    assert len(report["failures"]) == 2
    assert all("frames" in failure for failure in report["failures"])


# ------------------------------------------------------------ offline evaluation


def _write_fake_census(root: Path) -> None:
    (root / "units").mkdir(parents=True)
    members = {"20260730:part_1": {"1": [10, 11, 12, 13], "2": [20, 21]}}
    units = []
    for candidate, undefined_frames in (("anchor_center", {13}), ("anchor_t_min", {11, 13, 21})):
        frames = []
        for member_identity, tracks in members.items():
            positions = label_track_positions(_frame_rows(member_identity, tracks))
            for frame, position in sorted(positions.items()):
                undefined = frame in undefined_frames
                frames.append(
                    {
                        "frame_index": frame,
                        "mapped_process_row": frame * 10,
                        "scan_track_id": position["scan_track_id"],
                        "track_position": position,
                        "experimental_H_pixels": 9.0,
                        "experimental_W_pixels": 8.0,
                        "production_status": "FAIL_CLOSED_DISTANCE_EXCEEDED" if undefined else "SELECTED",
                        "production_mode": "fail_closed" if undefined else ("strict_center" if frame % 2 == 0 else "unique_nearest_fallback"),
                        "production_min_distance_cells": 1.3 if undefined else (0.0 if frame % 2 == 0 else 0.9),
                        "production_H_pixels": None if undefined else 10.0 + frame,
                        "production_W_pixels": None if undefined else 5.0,
                        "census_components": [
                            _component(1, share=0.004 if undefined else 0.3, contour=1.2 if undefined else 0.4, centre=1.3 if undefined else 0.9, h=10.0 + frame, w=5.0)
                        ],
                    }
                )
        unit_file = f"{candidate}__20260730_part_1.json"
        (root / "units" / unit_file).write_text(
            json.dumps({"candidate_id": candidate, "member_identity": "20260730:part_1", "candidate_coordinates": {"abs_depth_identifiable_coordinate": 0.0 if candidate == "anchor_center" else -3.0}, "frames": frames, "requested_frame_count": len(frames), "returned_frame_count": len(frames)}),
            encoding="utf-8",
        )
        units.append({"candidate_id": candidate, "member_identity": "20260730:part_1", "unit_file": unit_file})
    (root / "PATCH_22_3_6_ASSOCIATION_CENSUS_REPORT.json").write_text(json.dumps({"status": CENSUS_STATUS_PASS, "units": units}), encoding="utf-8")


def _write_fake_old_run(root: Path) -> None:
    for candidate in ("anchor_center", "anchor_t_min"):
        observations = []
        for frame in (10, 11, 12, 13, 20, 21):
            old_strict = frame % 2 == 0
            observations.append(
                {
                    "frame_index": frame,
                    "mapped_process_row": frame * 10,
                    "simulated_H_pixels": 10.0 + frame if frame != 13 else float("nan"),
                    "simulated_W_pixels": 5.0 if frame != 13 else float("nan"),
                    "observation_diagnostics": {
                        "production_hw_association_mode": "strict_center" if old_strict else ("fail_closed" if frame == 13 else "unique_nearest_fallback"),
                        "production_hw_association_status": "FAIL_CLOSED_DISTANCE_EXCEEDED" if frame == 13 else "SELECTED",
                        "production_hw_association_min_distance_cells": 0.0 if old_strict else (2.0**0.5 if frame == 13 else 1.0),
                    },
                }
            )
        path = root / "work_units" / "set_01_20260730" / "coupon_01" / "x" / candidate / "result.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"payload": {"member_identity": "20260730:part_1", "candidate_id": candidate, "atomic_failure_evaluation": {"observations": observations}}}), encoding="utf-8")


def test_evaluate_census_tabulates_rules_track_positions_and_old_run_regression(tmp_path):
    _write_fake_census(tmp_path / "census")
    _write_fake_old_run(tmp_path / "old")
    evaluation = evaluate_census(tmp_path / "census", old_run_directory=tmp_path / "old", output_directory=tmp_path / "eval")

    assert evaluation["status"] == "PASS_PATCH_22_3_6_CENSUS_EVALUATION"
    current = evaluation["current_rule"]["by_candidate"]
    assert current["anchor_center"]["undefined"] == 1 and current["anchor_t_min"]["undefined"] == 3
    assert evaluation["current_rule"]["by_track_position"]["first"]["undefined"] == 0
    # beam-share rule at the 2% floor scores the former fail-closed frames as NO_LASER_ASSOCIATED_MELT (zero)
    beam = evaluation["beam_share_rule"]["by_floor"]["0.02"]
    assert beam["by_candidate"]["anchor_t_min"]["NO_LASER_ASSOCIATED_MELT"] == 3
    assert beam["by_candidate"]["anchor_t_min"]["SELECTED"] == 3 and beam["by_candidate"]["anchor_t_min"]["undefined"] == 0
    assert evaluation["beam_share_rule"]["floor_sensitivity"]["0.005->0.01"]["changed_frames"] == 0
    contour = evaluation["contour_distance_rule"]["by_radius"]["1.5"]
    assert contour["by_candidate"]["anchor_t_min"]["SELECTED"] == 6  # 1.2 cells to the contour is inside 1.5
    # old-run regression join
    regression = evaluation["old_run_regression"]
    assert regression["joined_frames"] == 12
    assert regression["strict_center_frames"] == 6 and regression["strict_center_hw_identical"] == 6
    assert regression["strict_center_max_abs_hw_difference_pixels"] == 0.0
    assert regression["old_orthogonal_fallback_frames"] == 4
    assert regression["old_orthogonal_fallback_now_undefined"] == 2  # anchor_t_min frames 11 and 21
    changed = evaluation["changed_outcomes_vs_current"]["beam_share_rule"]["0.02"]
    assert changed["undefined_to_scored"] == 4 and changed["scored_to_undefined"] == 0
    assert (tmp_path / "eval" / "PATCH_22_3_6_CENSUS_EVALUATION.json").is_file()
    assert (tmp_path / "eval" / "PATCH_22_3_6_CENSUS_RESIDUAL_CASES.csv").is_file()


# ----------------------------------------------------------------- sync audit


def test_audit_member_tracks_identifies_edge_anchors_and_dark_gaps():
    frame_rows = _frame_rows("20260730:part_1", {"1": [100, 101, 102], "2": [110, 111]})
    track_rows = {"1": {"process_row_start": 1000, "process_row_end": 1200}, "2": {"process_row_start": 1500, "process_row_end": 1600}}
    n = 120
    image_to_row = np.full(n, -1, dtype=np.int64)
    image_to_row[100:103] = [1000, 1100, 1200]
    image_to_row[110:112] = [1500, 1600]
    gige_on = np.zeros(n, dtype=np.int64)
    gige_on[100:103] = 1
    gige_on[110:112] = 1
    gige_time = np.arange(n, dtype=np.float64) * 1.3e-4
    audit = audit_member_tracks(
        frame_rows=frame_rows,
        track_rows=track_rows,
        matched_edge_frames=np.array([100, 102, 110]),
        matched_edge_signs=np.array([1, -1, 1]),
        anchor_rows=np.array([1000.0, 1200.0, 1500.0]),
        image_to_row=image_to_row,
        gige_on=gige_on,
        gige_time_s=gige_time,
    )
    first = audit["tracks"][0]
    assert first["scan_track_id"] == "1" and first["first_frame_index"] == 100
    assert first["first_is_rising_edge_anchor"] is True and first["first_maps_to_track_start_row"] is True
    assert first["dark_frames_before_first"] == 1 and first["dark_gap_before_first_s"] == pytest.approx(1.3e-4)
    assert first["last_is_falling_edge_anchor"] is True and first["last_maps_to_track_end_row"] is True
    second = audit["tracks"][1]
    assert second["last_is_falling_edge_anchor"] is False and second["eligible_frame_count"] == 2
    assert audit["summary"]["track_count"] == 2
    assert audit["summary"]["first_frame_rising_edge_anchor_fraction"] == 1.0
    assert audit["summary"]["last_frame_falling_edge_anchor_fraction"] == 0.5
    assert audit["summary"]["short_track_count_lt_4_frames"] == 2
