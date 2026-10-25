"""Patch 22.3.8 Step 3: synthetic camera, criteria and runner (synthetic data only)."""

from __future__ import annotations

import csv
import gzip
import json
import math
from pathlib import Path

import numpy as np
import pytest

import lpbf.camera_observations as step0
import lpbf.synthetic_camera as cam
from lpbf.execution.work_units import SimulationResult

LIQUIDUS = 1673.15
CELL_UM = 16.0
CONSTANT = 29.677858774859413  # Step-0 mirrored mapping constant
MOTION_DEG = 45.0  # machine scan direction on layer 53


def _hot_field(*, peak=2500.0, tail_um=200.0, width_um=50.0, angle_deg=MOTION_DEG, center_um=(792.0, 792.0), n=99):
    """A beam-centred hot zone with a slow-decaying tail behind the motion direction (machine axes, x along i)."""

    x = (np.arange(n) + 0.5) * CELL_UM
    X, Y = np.meshgrid(x, x, indexing="ij")
    a = math.radians(angle_deg)
    dx, dy = X - center_um[0], Y - center_um[1]
    along = dx * math.cos(a) + dy * math.sin(a)
    across = -dx * math.sin(a) + dy * math.cos(a)
    scale = np.where(along < 0.0, tail_um, width_um)
    return 298.0 + (peak - 298.0) * np.exp(-0.5 * ((along / scale) ** 2 + (across / width_um) ** 2))


def _render(field, constant=CONSTANT):
    offsets = cam.subsample_offsets_um(constant)
    return cam.render_temperature_subsamples(field, source_x_mm=0.792, source_y_mm=0.792, cell_um=CELL_UM, offsets=offsets)


# ---------------------------------------------------------------------- radiometry and geometry


def _wrap180(angle_deg: float) -> float:
    return (float(angle_deg) + 180.0) % 360.0 - 180.0


def test_uniform_surface_at_t150_reads_150_counts_and_planck_follows_wien():
    for model in cam.EMISSIVITY_MODELS:
        for t150 in (1500.0, 2000.0, 2600.0):
            unit = cam.count_level_unit(t150, wavelength_nm=850.0, emissivity_model=model, liquidus_K=LIQUIDUS)
            radiance = cam.emissivity(t150, model, LIQUIDUS) * cam.planck_relative(t150, 850.0)
            assert float(radiance / unit) == pytest.approx(150.0, rel=1e-12)
    ratio = cam.planck_relative(2000.0, 850.0) / cam.planck_relative(1500.0, 850.0)
    wien = math.exp(cam.SECOND_RADIATION_CONSTANT_UM_K / 0.85 * (1 / 1500.0 - 1 / 2000.0))
    assert float(ratio) == pytest.approx(wien, rel=1e-3)
    assert cam.emissivity(1700.0, "liquid_half", LIQUIDUS) == 0.5 and cam.emissivity(1600.0, "liquid_half", LIQUIDUS) == 1.0


def test_cases_are_the_24_predeclared_ones_in_computation_order():
    cases = cam.synthetic_cases()
    assert len(cases) == 24 and len({c["case_id"] for c in cases}) == 24
    assert [c["sigma_px"] for c in cases[:4]] == [0.0, 1.0, 2.0, 2.6]
    assert cam.T150_GRID_K[0] == 1400.0 and cam.T150_GRID_K[-1] == 3200.0 and len(cam.T150_GRID_K) == 73


def test_mirrored_mapping_puts_the_scan_axis_where_step0_found_it():
    field = _hot_field(tail_um=120.0, width_um=40.0)
    t_sub, inside = _render(field)
    image = cam.pixel_mean(t_sub)
    blob = cam.measure_component(image >= 1200.0)
    ys, xs = np.nonzero(blob["component"])
    axis = step0.principal_axis_deg(xs, ys)
    expected = (CONSTANT - MOTION_DEG) % 180.0
    assert abs(_wrap180(2.0 * (axis - expected)) / 2.0) < 2.0
    assert bool(cam.pixel_all(inside)[blob["component"]].all())  # the hot zone is sampled inside the model window


def test_tail_points_opposite_the_mapped_motion():
    field = _hot_field(tail_um=250.0, width_um=40.0)
    t_sub, _ = _render(field)
    blob = cam.measure_component(cam.pixel_mean(t_sub) >= 1000.0)
    direction = math.degrees(math.atan2(blob["centroid_y"] - cam.RENDER_HALF_PX, blob["centroid_x"] - cam.RENDER_HALF_PX)) % 360.0
    expected = (CONSTANT - MOTION_DEG + 180.0) % 360.0
    assert abs(_wrap180(direction - expected)) < 10.0


def test_mapping_sign_is_fixed_by_the_wake(tmp_path):
    for offset, expected in ((212.0, 30.0), (20.0, 210.0)):
        path = tmp_path / f"d{int(offset)}.json"
        path.write_text(json.dumps({"mapping": "mirrored", "axis_mapping_constant_deg": 30.0, "pooled_wing_follow_mean_offset_deg": offset}))
        assert cam.load_image_mapping(path)["full_circle_constant_deg"] == pytest.approx(expected)
    path = tmp_path / "direct.json"
    path.write_text(json.dumps({"mapping": "direct", "axis_mapping_constant_deg": 30.0, "pooled_wing_follow_mean_offset_deg": 180.0}))
    with pytest.raises(cam.Step3Error):
        cam.load_image_mapping(path)
    real = cam.load_image_mapping()
    assert real["full_circle_constant_deg"] == pytest.approx(CONSTANT)


def test_render_marks_samples_outside_the_model_window():
    field = _hot_field()
    offsets = cam.subsample_offsets_um(CONSTANT, half_px=120)
    _, inside = cam.render_temperature_subsamples(field, source_x_mm=0.792, source_y_mm=0.792, cell_um=CELL_UM, offsets=offsets)
    assert not bool(inside.all()) and bool(inside[inside.shape[0] // 2, inside.shape[1] // 2])


def test_gaussian_psf_conserves_interior_flux_and_identity_at_zero():
    image = np.zeros((40, 40))
    image[20, 20] = 1.0
    assert cam.gaussian_psf(image, 0.0) is not None and np.array_equal(cam.gaussian_psf(image, 0.0), image)
    blurred = cam.gaussian_psf(image, 2.0)
    assert blurred.sum() == pytest.approx(1.0, rel=1e-9) and blurred[20, 20] < 0.1


# ---------------------------------------------------------------------- measurement


def test_measure_component_matches_the_step0_camera_convention():
    rng = np.random.default_rng(7)
    for _ in range(40):
        image = np.zeros((24, 64))
        for _ in range(rng.integers(1, 4)):
            cy, cx = rng.uniform(0, 24), rng.uniform(0, 64)
            sy, sx = rng.uniform(1.5, 5.0), rng.uniform(1.5, 9.0)
            yy, xx = np.mgrid[0:24, 0:64]
            image += rng.uniform(100, 400) * np.exp(-0.5 * (((yy - cy) / sy) ** 2 + ((xx - cx) / sx) ** 2))
        image = np.clip(image + rng.uniform(0, 5, size=image.shape), 0, 255).astype(np.uint8)
        for threshold in (30, 60, 150, 250):
            expected = step0.measure_blob(image, threshold)
            got = cam.measure_component(image >= threshold)
            if expected is None:
                assert got is None
                continue
            assert (got["H_px"], got["W_px"], got["area_px"], got["touches_edge"]) == (
                expected["H_px"], expected["W_px"], expected["area_px"], expected["touches_edge"]
            )
            assert got["centroid_x"] == pytest.approx(expected["centroid_x"], abs=1e-9)
            assert got["centroid_y"] == pytest.approx(expected["centroid_y"], abs=1e-9)


def _radiance_image(field, wavelength=850.0):
    t_sub, inside = _render(field)
    return cam.pixel_mean(cam.planck_relative(t_sub, wavelength)), cam.pixel_all(inside)


def test_measure_levels_places_the_camera_crop_at_the_camera_centroid():
    image, inside = _radiance_image(_hot_field())
    units = cam.count_level_unit(np.array([2000.0, 2200.0, 9000.0]), wavelength_nm=850.0, emissivity_model="uniform", liquidus_K=LIQUIDUS)
    shape = (3, len(cam.MATCH_THRESHOLDS))
    h, w, edge, sat = np.full(shape, np.nan), np.full(shape, np.nan), np.zeros(shape, bool), np.full(3, np.nan)
    centroid = (46.4, 9.3)
    cam.measure_levels(image, inside, units, centroid, h, w, edge, sat)
    assert np.all(np.isnan(h[2])) and np.isnan(sat[2])  # T150 above the peak: nothing seen
    for k in (0, 1):
        reference = cam.measure_component(image >= 150 * units[k])
        ox = int(math.floor(reference["centroid_x"] - centroid[0] + 0.5))
        oy = int(math.floor(reference["centroid_y"] - centroid[1] + 0.5))
        crop = image[oy : oy + 24, ox : ox + 64]
        inner = cam.measure_component(crop >= 150 * units[k])
        assert abs(inner["centroid_x"] - centroid[0]) <= 0.5 + 1e-9 and abs(inner["centroid_y"] - centroid[1]) <= 0.5 + 1e-9
        for t, threshold in enumerate(cam.MATCH_THRESHOLDS):
            blob = cam.measure_component(crop >= threshold * units[k])
            assert (h[k, t], w[k, t], edge[k, t]) == (blob["H_px"], blob["W_px"], blob["touches_edge"])
        blob = cam.measure_component(crop >= 150 * units[k])
        assert sat[k] == np.count_nonzero(crop[blob["component"]] >= 255 * units[k]) / blob["area_px"]
    assert h[0, 0] > h[1, 0]  # a hotter T150 shrinks every blob


def test_long_tail_is_flagged_at_the_crop_edge():
    image, inside = _radiance_image(_hot_field(tail_um=900.0, width_um=50.0))
    units = cam.count_level_unit(np.array([1900.0]), wavelength_nm=850.0, emissivity_model="uniform", liquidus_K=LIQUIDUS)
    shape = (1, len(cam.MATCH_THRESHOLDS))
    h, w, edge, sat = np.full(shape, np.nan), np.full(shape, np.nan), np.zeros(shape, bool), np.full(1, np.nan)
    cam.measure_levels(image, inside, units, (46.4, 9.3), h, w, edge, sat)
    assert bool(edge[0, 0]) and math.isfinite(h[0, 0])  # threshold 60: the tail leaves the 64 x 24 crop


def test_blob_whose_crop_cannot_be_placed_counts_as_edge_not_absent():
    image = np.zeros((40, 70))
    image[18:22, 2:30] = 10.0  # centroid near x = 15.5 < 46.4: the crop would start left of the image
    shape = (1, len(cam.MATCH_THRESHOLDS))
    h, w, edge, sat = np.full(shape, np.nan), np.full(shape, np.nan), np.zeros(shape, bool), np.full(1, np.nan)
    cam.measure_levels(image, np.ones_like(image, bool), np.array([0.01]), (46.4, 9.3), h, w, edge, sat)
    assert bool(np.all(edge[0])) and np.all(np.isfinite(h[0])) and math.isnan(sat[0])


def test_level_free_crossing_finds_the_isotherm_matching_the_camera_width():
    t_sub, inside = _render(_hot_field())
    image, inside_px = cam.pixel_mean(t_sub), cam.pixel_all(inside)
    result = cam.level_free_crossing(image, inside_px, 9.0)
    assert result["status"] == "DEFINED" and result["W_px"] >= 9.0 and result["H_px"] > result["W_px"]
    above = cam.measure_component(image >= result["level_K"] + 0.01)
    assert above is None or above["W_px"] < 9.0
    assert cam.level_free_crossing(image, inside_px, 500.0)["status"] == "CAMERA_WIDER_THAN_MODEL_AT_FLOOR"


# ---------------------------------------------------------------------- criteria


def test_bootstrap_slopes_reproduce_member_trend():
    records = step0._condition_records()
    members = step0.calibration_member_identities()
    lp = [math.log(records[m]["power_W"]) for m in members]
    lv = [math.log(records[m]["speed_mm_s"]) for m in members]
    y = np.random.default_rng(3).normal(size=len(members))
    expected = step0.member_trend(lp, lv, y, rng=np.random.default_rng(cam.BOOTSTRAP_SEED))
    got = cam.bootstrap_slopes(cam.bootstrap_design(lp, lv), y[:, None])
    assert got["P"][0] == pytest.approx(expected["slope_log_power"], abs=1e-10)
    assert got["v"][0] == pytest.approx(expected["slope_log_speed"], abs=1e-10)
    assert [got["P_lo"][0], got["P_hi"][0]] == pytest.approx(expected["slope_log_power_ci95"], abs=1e-10)
    assert [got["v_lo"][0], got["v_hi"][0]] == pytest.approx(expected["slope_log_speed_ci95"], abs=1e-10)
    nan_column = cam.bootstrap_slopes(cam.bootstrap_design(lp, lv), np.column_stack([y, np.full_like(y, np.nan)]))
    assert math.isfinite(nan_column["P"][0]) and math.isnan(nan_column["P"][1]) and math.isnan(nan_column["v_hi"][1])


def _orthogonal_noise(members, scale=0.05, seed=11):
    records = step0._condition_records()
    design = np.column_stack(
        [np.ones(len(members)), [math.log(records[m]["power_W"]) for m in members], [math.log(records[m]["speed_mm_s"]) for m in members]]
    )
    noise = np.random.default_rng(seed).normal(size=len(members))
    noise -= design @ np.linalg.lstsq(design, noise, rcond=None)[0]
    return scale * noise / np.abs(noise).max()


def _fake_aggregates(members, *, hw_factor, size_factor=1.0, sat_model=0.5, paired_150=100, grid=3):
    """Per-member aggregates over (24 cases, ``grid`` T150, 5 thresholds); grid point 0 carries the given factors."""

    noise = _orthogonal_noise(members)
    shape = (24, grid, len(cam.MATCH_THRESHOLDS))
    results = {}
    for m, member in enumerate(members):
        camera_h, camera_w = 10.0, 8.0
        factor = np.full(shape, 3.0)
        factor[:, 0, :] = hw_factor
        size = np.full(shape, 2.0)
        size[:, 0, :] = size_factor * math.exp(noise[m])
        model_w = camera_w * size
        model_h = model_w * (camera_h / camera_w) * factor
        paired = np.full(shape, 100.0)
        paired[..., cam.MATCH_THRESHOLDS.index(150)] = paired_150
        results[member] = {
            "aggregate": {
                "camera_valid": np.full(len(cam.MATCH_THRESHOLDS), 100),
                "paired": paired,
                "model_H": model_h,
                "model_W": model_w,
                "model_HW": model_h / model_w,
                "camera_H": np.full(shape, camera_h),
                "camera_W": np.full(shape, camera_w),
                "camera_HW": np.full(shape, camera_h / camera_w),
                "model_sat": np.full(shape[:2], sat_model),
                "camera_sat": np.full(shape[:2], 0.5),
                "w_ratio_m3": np.broadcast_to(size[None, ..., [0, 4]], (4,) + shape[:2] + (2,)).astype(np.float32),
            }
        }
    return results


def test_size_off_by_a_factor_fails_m2_and_m3():
    members = list(step0.calibration_member_identities())
    scope = cam.evaluate_scope(members, _fake_aggregates(members, hw_factor=1.0, size_factor=1.5), with_trends=True)
    assert bool(scope["M1_150_pass"][0, 0]) and not bool(scope["M2_pass"][0, 0]) and not bool(scope["M3_pass"][0, 0])


def test_corner_scope_needs_three_of_four_members():
    members = list(cam.CORNER_MEMBERS)
    scope = cam.evaluate_scope(members, _fake_aggregates(members, hw_factor=1.0), with_trends=False)
    assert int(scope["M2_required"]) == 3 and bool(scope["core_pass"][0, 0]) and "M5_pass" not in scope


# ---------------------------------------------------------------------- unit analysis and runner


def _camera_entry(frames, *, centroid=(46.4, 9.3)):
    n = len(frames)
    entry = {
        "frame_index": list(frames),
        "centroid_x": [centroid[0]] * n,
        "centroid_y": [centroid[1]] * n,
        "sat": [0.5] * n,
        "has_blob_150": [True] * n,
    }
    for t, (h, w) in zip(cam.MATCH_THRESHOLDS, ((16.0, 12.0), (13.0, 10.0), (11.0, 8.5), (9.0, 7.0), (7.0, 5.5))):
        entry[f"H_{t}"] = [h] * n
        entry[f"W_{t}"] = [w] * n
        entry[f"edge_{t}"] = [False] * n
    return entry


def _unit_arrays(frames, *, peak=2500.0):
    n = len(frames)
    fields = np.stack([_hot_field(peak=peak + 20.0 * k) for k in range(n)])
    return {
        "frame_index": np.asarray(frames, dtype=np.int64),
        "top_surface_temperature_K": fields,
        "source_center_x_mm": np.full(n, 0.792),
        "source_center_y_mm": np.full(n, 0.792),
        "production_status": np.asarray(["SELECTED"] * n),
        "liquidus_temperature_K": np.asarray(LIQUIDUS),
        "cell_size_um": np.asarray(CELL_UM),
    }


def _production(frames):
    return {f: {"frame_index": f, "scored_frame": True, "production_status": "SELECTED", "simulated_H_pixels": 22.0, "simulated_W_pixels": 7.0} for f in frames}


def _write_camera_table(path: Path, summary: Path, units):
    frames_by_member = {}
    for k, (_, member) in enumerate(units):
        frames_by_member.setdefault(member, [100 + k, 101 + k])
    fields = ["member_identity", "layer", "frame_index", "centroid_x", "centroid_y", "saturated_fraction_150", "has_blob_150"]
    fields += [f"{key}_{t}" for t in cam.MATCH_THRESHOLDS for key in ("H", "W", "edge")]
    with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for member, frames in frames_by_member.items():
            entry = _camera_entry(frames)
            for i, frame in enumerate(frames):
                row = {"member_identity": member, "layer": "layer53", "frame_index": frame}
                row.update({key: entry[source][i] for key, source in (("centroid_x", "centroid_x"), ("centroid_y", "centroid_y"), ("saturated_fraction_150", "sat"), ("has_blob_150", "has_blob_150"))})
                row.update({f"{key}_{t}": entry[f"{key}_{t}"][i] for t in cam.MATCH_THRESHOLDS for key in ("H", "W", "edge")})
                writer.writerow(row)
            writer.writerow({"member_identity": member, "layer": "layer52", "frame_index": 5})
    with summary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["member_identity", "layer", "scored_frames", "median_H_150_um", "median_W_150_um"])
        writer.writeheader()
        for member in frames_by_member:
            writer.writerow({"member_identity": member, "layer": "layer53", "scored_frames": 2, "median_H_150_um": 11.0 * 8.0, "median_W_150_um": 8.5 * 8.0})


STEP2_UNITS = tuple(("anchor_center", m) for m in step0.calibration_member_identities()) + tuple(
    (c, m) for c in ("anchor_t_min", "anchor_t_max") for m in cam.CORNER_MEMBERS
)


@pytest.fixture
def fake_step2(tmp_path, monkeypatch):
    # The corner units of t_min / t_max reuse the anchor_center camera frames of the same member.
    units = list(STEP2_UNITS)
    index = {member: k for k, (candidate, member) in enumerate(units) if candidate == "anchor_center"}
    capture = tmp_path / "capture"
    (capture / "fields").mkdir(parents=True)
    (capture / "units").mkdir()
    manifest_units = []
    for k, (candidate, member) in enumerate(units):
        stem = f"{candidate}__{member.replace(':', '_')}"
        base = index[member]
        frames = [100 + base, 101 + base]
        shift = {"anchor_t_min": -150.0, "anchor_center": 0.0, "anchor_t_max": 150.0}[candidate]
        np.savez_compressed(capture / "fields" / f"{stem}.npz", **_unit_arrays(frames, peak=2400.0 + 10.0 * base + shift))
        records = [dict(record, member_identity=member) for record in _production(frames).values()]
        (capture / "units" / f"{stem}.json").write_text(json.dumps({"frame_records": records}))
        manifest_units.append(
            {
                "candidate_id": candidate,
                "member_identity": member,
                "unit_file": f"units/{stem}.json",
                "capture_file": {"path": f"fields/{stem}.npz", "sha256": cam._sha256(capture / "fields" / f"{stem}.npz"), "frames": 2},
            }
        )
    (capture / cam.CAPTURE_MANIFEST_NAME).write_text(json.dumps({"units": manifest_units}))
    (capture / cam.CAPTURE_GATE_NAME).write_text(json.dumps({"status": cam.CAPTURE_GATE_PASS}))
    camera_path, summary = tmp_path / "frames.csv.gz", tmp_path / "summary.csv"
    _write_camera_table(camera_path, summary, [(c, m) for c, m in units if c == "anchor_center"])
    monkeypatch.setattr(cam, "STEP0_SUMMARY_CSV", summary)
    monkeypatch.setattr(cam, "T150_GRID_K", (1800.0, 2000.0, 2200.0))

    def fake_pool(jobs, worker, *, workers, on_result=None):
        results = []
        for job in reversed(tuple(jobs)):
            result = SimulationResult(job=job, payload=worker(job))
            if on_result is not None:
                on_result(result)
            results.append(result)
        return tuple(results)

    monkeypatch.setattr(cam, "execute_parallel_jobs", fake_pool)
    return capture, camera_path


OUTPUT_FILES = ("step3_grid.csv.gz", "step3_level_free_frames.csv.gz", "step3_verdict.json", "step3_physics.json", "step3_level_free.json")


