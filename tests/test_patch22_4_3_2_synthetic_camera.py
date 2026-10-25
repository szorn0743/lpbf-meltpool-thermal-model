"""Patch 22.4.3.2 reading S: synthetic camera on the evaluate stage's captured fields (synthetic inputs only)."""
from __future__ import annotations

import json
import math
import pickle
from pathlib import Path

import cv2
import h5py
import numpy as np
import pytest

import lpbf.patch22_3_8_camera_step0 as step0
import lpbf.patch22_3_8_synthetic_camera as cam
import lpbf.patch22_4_3_2_synthetic_camera as s
import lpbf.patch22_4_3_2_window_calibration as w

LIQUIDUS = 1673.15
CELL_UM = 16.0
CONSTANT = 29.677858774859413  # Step-0 mirrored mapping constant
MEMBER = "20260730:part_1"  # P140 V850
LN2, LN3 = math.log(2.0), math.log(3.0)


def _hot_field(*, peak=2500.0, tail_um=200.0, width_um=50.0, n=99):
    x = (np.arange(n) + 0.5) * CELL_UM
    X, Y = np.meshgrid(x, x, indexing="ij")
    a = math.radians(45.0)
    dx, dy = X - 792.0, Y - 792.0
    along = dx * math.cos(a) + dy * math.sin(a)
    across = -dx * math.sin(a) + dy * math.cos(a)
    scale = np.where(along < 0.0, tail_um, width_um)
    return 298.0 + (peak - 298.0) * np.exp(-0.5 * ((along / scale) ** 2 + (across / width_um) ** 2))


def _blob_image(*, center=(32, 12), axes=(7, 4), value=220):
    image = np.full((cam.CAMERA_ROWS, cam.CAMERA_COLS), 20, dtype=np.uint8)
    cv2.ellipse(image, center, axes, 0.0, 0.0, 360.0, int(value), thickness=-1)
    return image


# ---------------------------------------------------------------------- camera side


def test_camera_measurement_follows_the_step0_convention():
    images = [_blob_image(), np.full((cam.CAMERA_ROWS, cam.CAMERA_COLS), 20, dtype=np.uint8), _blob_image(value=255)]
    entry = s.measure_camera_frames(images, [5, 9, 12])
    assert entry["frame_index"] == [5, 9, 12] and entry["has_blob_150"] == [True, False, True]
    for t in cam.MATCH_THRESHOLDS:
        blob = step0.measure_blob(images[0], t)
        if blob is None:  # 250 lies above the blob's 220 counts
            assert t == 250 and math.isnan(entry[f"H_{t}"][0]) and entry[f"edge_{t}"][0] is False
        else:
            assert (entry[f"H_{t}"][0], entry[f"W_{t}"][0], entry[f"edge_{t}"][0]) == (blob["H_px"], blob["W_px"], blob["touches_edge"])
        assert math.isnan(entry[f"H_{t}"][1]) and entry[f"edge_{t}"][1] is False
    blob = step0.measure_blob(images[0], 150)
    assert (entry["centroid_x"][0], entry["centroid_y"][0]) == (blob["centroid_x"], blob["centroid_y"])
    assert math.isnan(entry["centroid_x"][1]) and entry["sat"][0] == 0.0 and entry["sat"][2] == 1.0
    with pytest.raises(s.SyntheticCameraError, match="expected"):
        s.measure_camera_frames([np.zeros((10, 10), dtype=np.uint8)], [1])


# ---------------------------------------------------------------------- frame records and scores


def _unit_records():
    rows = []
    for track, frames in (("1", range(0, 6)), ("2", range(10, 14))):
        frames = list(frames)
        for k, frame in enumerate(frames):
            scored = 0 < k < len(frames) - 1
            rows.append(
                {
                    "member_identity": MEMBER,
                    "acquisition_set_id": "20260730",
                    "part_number": 1,
                    "exact_condition_id": "P140_V850",
                    "power_W": 140.0,
                    "speed_mm_s": 850.0,
                    "scan_track_id": track,
                    "frame_index": frame,
                    "observation_eligible": True,
                    "observation_status": "ELIGIBLE_FINITE_HW",
                    "experimental_H_pixels": 9.5,
                    "experimental_W_pixels": 7.5,
                    "scored_frame": scored,
                    "status": ("UNDEFINED" if frame == 12 else "PASS") if scored else "EXCLUDED",
                    "production_status": "SELECTED",
                    "simulated_H_pixels": 17.0,
                    "simulated_W_pixels": 6.0,
                }
            )
    return rows


def _synthetic():
    # scored frames 1, 2, 3, 4 (track 1) and 11, 12 (track 2); case 0 at grid index 0
    frames = [1, 2, 3, 4, 11, 12]
    h = np.array([20.0, 10.0, 12.0, np.nan, 11.0, 30.0])
    wv = np.array([8.0, 4.0, 8.0, np.nan, 8.0, 8.0])
    edge = np.array([False, False, False, False, True, False])
    return {
        "frame_index": frames,
        "H150": np.stack([h, h * 2.0], axis=1)[:, :, None],
        "W150": np.stack([wv, wv], axis=1)[:, :, None],
        "edge150": np.stack([edge, edge], axis=1)[:, :, None],
        "camera_H150": np.array([10.0, 10.0, 10.0, 10.0, 10.0, 10.0]),
        "camera_W150": np.array([8.0, 8.0, 8.0, 8.0, 8.0, 8.0]),
        "camera_valid150": np.array([True, True, False, True, True, True]),
    }


def test_synthetic_records_classify_frames_and_score_through_the_log_ratio_hierarchy():
    records = s.synthetic_frame_records(_unit_records(), _synthetic(), case_index=0, grid_index=0)
    by_frame = {row["frame_index"]: row for row in records}
    assert [by_frame[f]["status"] for f in (0, 5, 10, 13)] == ["EXCLUDED"] * 4 and "synthetic_status" not in by_frame[0]
    assert {f: by_frame[f]["synthetic_status"] for f in (1, 2, 3, 4, 11, 12)} == {
        1: s.PAIRED, 2: s.PAIRED, 3: s.CAMERA_INVALID, 4: s.SYNTHETIC_ABSENT, 11: s.SYNTHETIC_EDGE, 12: s.PAIRED
    }
    assert by_frame[3]["observation_eligible"] is False and by_frame[3]["experimental_H_pixels"] == 9.5
    assert by_frame[1]["experimental_H_pixels"] == 10.0 and by_frame[1]["stored_experimental_H_pixels"] == 9.5
    assert by_frame[1]["simulated_H_pixels"] == 20.0 and "simulated_H_pixels" not in by_frame[4]
    assert all("production_status" not in row for row in records)

    score = s.score_records(records, [MEMBER], "test")
    assert score["status"] == "PASS"
    h_component = 0.5 * (0.5 * (LN2**2 + 0.0) + LN3**2)
    w_component = 0.5 * (0.5 * (0.0 + LN2**2) + 0.0)
    assert score["e_H"] == pytest.approx(math.sqrt(h_component), rel=1e-12)
    assert score["e_W"] == pytest.approx(math.sqrt(w_component), rel=1e-12)
    assert score["coverage"] == pytest.approx(3 / 5) and score["coverage_flag"] is not None
    assert score["synthetic_status_counts"] == {s.CAMERA_INVALID: 1, s.PAIRED: 3, s.SYNTHETIC_ABSENT: 1, s.SYNTHETIC_EDGE: 1}

    doubled = s.score_records(s.synthetic_frame_records(_unit_records(), _synthetic(), case_index=1, grid_index=0), [MEMBER], "test")
    assert doubled["e_H"] > score["e_H"] and doubled["e_W"] == pytest.approx(score["e_W"], rel=1e-12)


def test_synthetic_records_fail_closed():
    rows = _unit_records()
    rows[1]["status"] = "FAIL"
    with pytest.raises(s.SyntheticCameraError, match="status"):
        s.synthetic_frame_records(rows, _synthetic(), case_index=0, grid_index=0)
    synthetic = _synthetic()
    synthetic["frame_index"] = [1, 2, 3, 4, 11, 99]
    with pytest.raises(s.SyntheticCameraError, match="no synthetic measurement"):
        s.synthetic_frame_records(_unit_records(), synthetic, case_index=0, grid_index=0)


# ---------------------------------------------------------------------- T150 rule


def _aggregate(hw_ratio_case0, paired_case0, paired_case1, frames=100):
    n_cases, n_grid, n_thr = 2, len(hw_ratio_case0), len(cam.MATCH_THRESHOLDS)
    camera_hw = 1.2
    model_hw = np.full((n_cases, n_grid, n_thr), camera_hw)
    model_hw[0] = camera_hw * np.asarray(hw_ratio_case0, dtype=np.float64)[:, None]
    paired = np.empty((n_cases, n_grid, n_thr))
    paired[0] = np.asarray(paired_case0, dtype=np.float64)[:, None]
    paired[1] = float(paired_case1)
    ones = np.ones((n_cases, n_grid, n_thr))
    return {
        "aggregate": {
            "model_H": 12.0 * ones,
            "model_W": 10.0 * ones,
            "model_HW": model_hw,
            "camera_H": 12.0 * ones,
            "camera_W": 10.0 * ones,
            "camera_HW": camera_hw * ones,
            "model_sat": 0.5 * np.ones((n_cases, n_grid)),
            "camera_sat": 0.5 * np.ones((n_cases, n_grid)),
            "paired": paired,
            "camera_valid": np.full(n_thr, float(frames)),
            "w_ratio_m3": np.ones((frames, n_cases, n_grid, 2)),
        }
    }


def test_t150_is_the_closest_approach_among_covered_grid_points_and_uncovered_cases_are_unavailable():
    grid = (1800.0, 2000.0, 2200.0)
    # grid point 0 is closest (1.01) but has 94 % coverage; of the covered points 0.9 beats 1.5
    members = ("m1", "m2", "m3")
    results = {m: _aggregate((1.01, 1.5, 0.9), (94, 100, 100), 90) for m in members}
    fixed = s.fix_t150(results, members, grid)
    first, second = (fixed[case_id] for case_id in s.S_CASE_IDS)
    assert first["available"] and first["T150_K"] == 2200.0 and first["grid_index"] == 2
    assert first["M1_HW_ratio_150"] == pytest.approx(0.9) and first["coverage_150"] == pytest.approx(1.0)
    assert not second["available"] and second["T150_K"] is None and second["max_coverage_150"] == pytest.approx(0.9)
    tie = s.fix_t150({m: _aggregate((2.0, 0.5, 3.0), (100, 100, 100), 100) for m in members}, members, grid)
    assert tie[s.S_CASE_IDS[0]]["T150_K"] == 1800.0  # a tie keeps the first (lowest) grid point, as 22.3.8 does


def test_s_cases_are_the_predeclared_two():
    cases = cam.select_cases(s.S_CASE_IDS)
    assert [(c["wavelength_nm"], c["emissivity"], c["sigma_px"]) for c in cases] == [(850.0, "uniform", 0.0), (850.0, "uniform", 2.0)]
    assert [name for name, _ in s.GROUPS] == ["calibration", "in_window_held_out", "cross_campaign_20260904_part_5", "out_of_window_examined", "out_of_window_blind"]
    assert sum(len(group) for name, group in s.GROUPS if name != "cross_campaign_20260904_part_5") == 24


# ---------------------------------------------------------------------- worker


def _fake_member(path: Path, frames, rows, n_rows=100):
    with h5py.File(path, "w") as h5:
        group = h5.create_group(step0.PRODUCTION_LAYER)
        group["names"] = np.array([b"X-Machine", b"Y-Machine"])
        group["data"] = np.zeros((2, n_rows))
        images = np.full((max(frames) + 3, cam.CAMERA_ROWS, cam.CAMERA_COLS), 20, dtype=np.uint8)
        for k, frame in enumerate(frames):
            images[frame] = _blob_image(axes=(6 + k, 4))
        group["gige_image"] = images
        mapping = np.full(n_rows, -1, dtype=np.int64)
        mapping[list(rows)] = list(frames)
        group.create_group("sync")["data_to_gige_image_index"] = mapping


def _fake_unit(tmp_path: Path, member: str, frames, rows):
    evaluate = tmp_path / "evaluate"
    (evaluate / "fields").mkdir(parents=True, exist_ok=True)
    stem = member.replace(":", "_")
    n = len(frames)
    arrays = {
        "frame_index": np.asarray(frames, dtype=np.int64),
        "mapped_process_row": np.asarray(rows, dtype=np.int64),
        "top_surface_temperature_K": np.stack([_hot_field(peak=2500.0 + 30.0 * k) for k in range(n)]),
        "source_center_x_mm": np.full(n, 0.792),
        "source_center_y_mm": np.full(n, 0.792),
        "liquidus_temperature_K": np.asarray(LIQUIDUS),
        "cell_size_um": np.asarray(CELL_UM),
    }
    field = evaluate / "fields" / f"{stem}.npz"
    np.savez(field, **arrays)
    h5_path = tmp_path / f"{stem}.h5"
    _fake_member(h5_path, frames, rows)
    payload = {
        "candidate_id": "confirm_c1",
        "capture_file": {"path": f"fields/{stem}.npz", "sha256": s._sha256(field)},
        "frame_records": [{"frame_index": f, "scored_frame": True} for f in frames] + [{"frame_index": 0, "scored_frame": False}],
    }
    return evaluate, payload, str(h5_path)


def _jobs(tmp_path, grid=(1800.0, 2000.0)):
    payloads, paths = {}, {}
    for member, frames, rows in (("20260730:part_1", [3, 5, 8], [30, 50, 80]), ("20260731:part_1", [2, 4], [20, 40])):
        evaluate, payloads[member], paths[member] = _fake_unit(tmp_path, member, frames, rows)
    return s.build_jobs(list(payloads), payloads, paths, evaluate, t150_grid=grid, mapping_constant_deg=CONSTANT), payloads


def _same(a, b):
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    if isinstance(a, (list, tuple)) and not isinstance(a, np.ndarray):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    if isinstance(a, (np.ndarray, float, int, bool, np.generic)):
        return np.array_equal(np.asarray(a), np.asarray(b), equal_nan=np.asarray(a).dtype.kind == "f")
    return a == b


def test_unit_job_measures_its_own_frames_renders_only_the_given_grid_and_parallel_equals_serial(tmp_path):
    jobs, _ = _jobs(tmp_path)
    for job in jobs:
        pickle.loads(pickle.dumps(job))
    serial = s._execute(jobs, 1, None, "test")
    parallel = s._execute(jobs, 2, None, "test")
    assert serial.keys() == parallel.keys() == {"20260730:part_1", "20260731:part_1"}
    assert all(_same(serial[m], parallel[m]) for m in serial)
    result = serial["20260730:part_1"]
    assert result["frame_index"] == [3, 5, 8] and result["t150_grid"] == [1800.0, 2000.0]
    assert result["H150"].shape == (3, 2, 2) and result["aggregate"]["model_H"].shape == (2, 2, len(cam.MATCH_THRESHOLDS))
    assert result["row_maps_back_to_frame_fraction"] == 1.0
    assert result["camera"]["H_150"] == [step0.measure_blob(_blob_image(axes=(6 + k, 4)), 150)["H_px"] for k in range(3)]
    assert bool(np.all(result["camera_valid150"])) and bool(np.isfinite(result["H150"][:, 0, 0]).all())


def test_unit_job_refuses_a_tampered_field_file_or_foreign_frames(tmp_path):
    jobs, payloads = _jobs(tmp_path)
    field = Path(jobs[0].experiment_context_dict["field_file"])
    data = dict(np.load(field))
    data["cell_size_um"] = np.asarray(8.0)
    np.savez(field, **data)
    with pytest.raises(s.SyntheticCameraError, match="hash"):
        s._synthetic_unit_job(jobs[0])
    payloads["20260731:part_1"]["frame_records"] = [{"frame_index": 2, "scored_frame": True}]
    evaluate = Path(jobs[1].experiment_context_dict["field_file"]).parents[1]
    paths = {m: jobs[k].experiment_context_dict["member_path"] for k, m in enumerate(sorted(payloads))}
    foreign = s.build_jobs(["20260731:part_1"], payloads, paths, evaluate, t150_grid=(1800.0,), mapping_constant_deg=CONSTANT)
    with pytest.raises(s.SyntheticCameraError, match="scored frames"):
        s._synthetic_unit_job(foreign[0])


# ---------------------------------------------------------------------- stage guards


def test_run_synthetic_refuses_without_a_verified_freeze_before_touching_data(tmp_path):
    out = tmp_path / "out"
    with pytest.raises(w.WindowCalibrationError, match="freeze file not found"):
        s.run_synthetic(data_directory=tmp_path / "missing", output_directory=out, freeze_file=tmp_path / "none.json", freeze_sha256="0" * 64, workers=1)
    assert not out.exists()


def test_run_synthetic_needs_a_complete_evaluate_stage_for_the_same_freeze(tmp_path, monkeypatch):
    freeze = {"selected": {"candidate_id": "confirm_c1"}, "content_sha256": "c" * 64}
    monkeypatch.setattr(w, "verify_committed_freeze", lambda path, sha: dict(freeze))
    kwargs = {"data_directory": tmp_path / "missing", "output_directory": tmp_path, "freeze_file": "x", "freeze_sha256": "a" * 64, "workers": 1}
    with pytest.raises(s.SyntheticCameraError, match="manifest not found"):
        s.run_synthetic(**kwargs)
    good = {"stage": "evaluate", "complete": True, "freeze_sha256": "a" * 64, "freeze_content_sha256": "c" * 64, "selected": "confirm_c1"}
    (tmp_path / "evaluate").mkdir()
    (tmp_path / "evaluate" / "stage_manifest.json").write_text(json.dumps({**good, "complete": False}), encoding="utf-8")
    with pytest.raises(s.SyntheticCameraError, match="not complete"):
        s.run_synthetic(**kwargs)
    assert s._check_evaluate_manifest(good, freeze, "A" * 64) == "confirm_c1"
    with pytest.raises(s.SyntheticCameraError, match="different freeze"):
        s._check_evaluate_manifest({**good, "freeze_sha256": "b" * 64}, freeze, "a" * 64)
    with pytest.raises(s.SyntheticCameraError, match="different freeze"):
        s._check_evaluate_manifest({**good, "freeze_content_sha256": "d" * 64}, freeze, "a" * 64)
    with pytest.raises(s.SyntheticCameraError, match="different candidate"):
        s._check_evaluate_manifest({**good, "selected": "confirm_c2"}, freeze, "a" * 64)
    assert not (tmp_path / s.STAGE).exists()


def test_module_runs_no_thermal_model_and_leaves_the_dispatch_lock_alone():
    source = Path(s.__file__).read_text(encoding="utf-8")
    for forbidden in ("evaluate_calibration_trial", "CAMPAIGN_DISPATCH_AUTHORIZED_BY", "run_search", "_thermal_worker"):
        assert forbidden not in source
