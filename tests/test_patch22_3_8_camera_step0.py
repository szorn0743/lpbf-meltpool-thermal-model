"""Patch 22.3.8 Step 0: camera-side characterization (diagnostic only)."""
from __future__ import annotations

import math

import cv2
import numpy as np
import pytest

from lpbf import patch22_3_8_camera_step0 as step0


def _axial_distance(a: float, b: float) -> float:
    d = abs(a - b) % 180.0
    return min(d, 180.0 - d)


def _gaussian_blob(cx: float, cy: float, sigma_x: float, sigma_y: float, peak: float, shape=(24, 64)) -> np.ndarray:
    yy, xx = np.mgrid[0 : shape[0], 0 : shape[1]]
    field = peak * np.exp(-0.5 * (((xx - cx) / sigma_x) ** 2 + ((yy - cy) / sigma_y) ** 2))
    return np.clip(np.rint(field), 0, 255).astype(np.uint8)


# ---------------------------------------------------------------------- members


def test_calibration_members_are_the_contract_sixteen_and_exclude_held_out():
    calibration = step0.calibration_member_identities()
    held_out = step0.held_out_member_identities()
    assert len(calibration) == 16
    assert len(held_out) == 8
    assert not set(calibration) & set(held_out)
    assert {"20260730:part_2", "20260730:part_4", "20260904:part_2", "20260910:part_5"} <= set(held_out)


def test_held_out_and_unknown_members_are_refused():
    with pytest.raises(step0.Step0Error, match="held-out"):
        step0.require_calibration_members(["20260730:part_1", "20260730:part_2"])
    with pytest.raises(step0.Step0Error, match="not a calibration member"):
        step0.require_calibration_members(["20260730:part_9"])


def test_run_refuses_held_out_before_touching_data_or_output(tmp_path):
    with pytest.raises(step0.Step0Error, match="held-out"):
        step0.run_step0(
            data_directory=tmp_path / "missing",
            characterization_directory=tmp_path,
            output_directory=tmp_path / "out",
            members=["20260904:part_2"],
        )
    assert not (tmp_path / "out").exists()


# ---------------------------------------------------------------------- frames


def _toy_process():
    laser_on = np.array([0, 1, 1, 1, 1, 1, 0, 1, 1, 1, 1, 0], dtype=bool)
    track_ids = np.array([0, 1, 1, 1, 1, 1, 0, 2, 2, 2, 2, 0])
    h = np.full(12, 10.0)
    w = np.full(12, 8.0)
    # -1 marks frames of other coupons in the same layer; 12 and 13 map to laser-off rows.
    mapping = np.array([-1, 1, 2, -1, 3, 4, 5, -1, 7, 8, 9, 10, 0, 6])
    return mapping, laser_on, track_ids, h, w


def test_scored_frames_use_only_member_mapped_frames_and_drop_track_edges():
    rows = step0.scored_frame_rows(*_toy_process())
    assert [row["frame_index"] for row in rows] == [2, 4, 5, 9, 10]
    assert {row["scan_track_id"] for row in rows} == {"1", "2"}


def test_ineligible_rows_do_not_count_as_track_edges():
    mapping, laser_on, track_ids, h, w = _toy_process()
    h[3] = np.nan  # frame 4 becomes ineligible
    rows = step0.scored_frame_rows(mapping, laser_on, track_ids, h, w)
    assert [row["frame_index"] for row in rows] == [2, 5, 9, 10]


def test_frame_reader_rejects_unsorted_indices(tmp_path):
    with pytest.raises(step0.Step0Error, match="strictly increasing"):
        step0._read_member_frames(tmp_path / "x.h5", "layer53", [5, 3])


# ---------------------------------------------------------------------- blob geometry


def test_measure_blob_pixel_centre_minarearect_and_largest_component():
    image = np.zeros((24, 64), dtype=np.uint8)
    image[5:11, 20:30] = 200  # 6 rows x 10 columns
    image[15:17, 50:52] = 255  # smaller second component
    blob = step0.measure_blob(image, 150)
    assert blob["H_px"] == pytest.approx(9.0)
    assert blob["W_px"] == pytest.approx(5.0)
    assert blob["area_px"] == 60
    assert blob["component_count"] == 2
    assert blob["saturated_px"] == 0
    assert not blob["touches_edge"]
    assert _axial_distance(blob["axis_deg"], 0.0) < 1e-6


def test_measure_blob_threshold_is_inclusive_and_edges_are_flagged():
    image = np.zeros((24, 64), dtype=np.uint8)
    image[0:3, 10:14] = 150
    blob = step0.measure_blob(image, 150)
    assert blob is not None and blob["area_px"] == 12
    assert blob["touches_edge"]
    assert step0.measure_blob(image, 151) is None


def test_principal_axis_follows_image_coordinates():
    image = np.zeros((24, 64), dtype=np.uint8)
    cv2.ellipse(image, (32, 12), (10, 4), 30, 0, 360, 255, -1)
    blob = step0.measure_blob(image, 150)
    assert _axial_distance(blob["axis_deg"], 30.0) < 2.0
    assert blob["H_px"] > 2.0 * blob["W_px"]


# ---------------------------------------------------------------------- circular statistics and scan direction


def test_circular_means():
    mean, r = step0.axial_mean_deg([10.0, 170.0])
    assert _axial_distance(mean, 0.0) < 1e-9 and r == pytest.approx(math.cos(math.radians(20.0)))
    mean, r = step0.circular_mean_deg([350.0, 10.0, float("nan")])
    assert min(mean, 360.0 - mean) < 1e-9 and r == pytest.approx(math.cos(math.radians(10.0)))


def test_scan_direction_full_circle():
    t = np.arange(40, dtype=float)
    forward = step0.scan_direction_deg(t, t, [10, 20])
    backward = step0.scan_direction_deg(-t, -t, [10, 20])
    assert forward == pytest.approx([45.0, 45.0])
    assert backward == pytest.approx([225.0, 225.0])
    still = step0.scan_direction_deg(np.zeros(40), np.zeros(40), [10])
    assert np.isnan(still[0])


# ---------------------------------------------------------------------- profiles


def test_bilinear_sample_is_exact_on_a_ramp_and_nan_outside():
    yy, xx = np.mgrid[0:24, 0:64]
    ramp = 2.0 * xx + 3.0 * yy
    values = step0.bilinear_sample(ramp, np.array([1.5, 10.25, -0.5, 63.5]), np.array([2.5, 4.0, 1.0, 1.0]))
    assert values[:2] == pytest.approx([2 * 1.5 + 3 * 2.5, 2 * 10.25 + 3 * 4.0])
    assert np.isnan(values[2]) and np.isnan(values[3])


def test_edge_width_on_a_linear_ramp():
    offsets = np.arange(-20, 21, dtype=float)
    profile = np.clip(255.0 * (1.0 - np.abs(offsets) / 10.0), 0.0, None)
    assert step0.edge_width_px(profile, offsets, side=+1) == pytest.approx(8.0)
    assert step0.edge_width_px(profile, offsets, side=-1) == pytest.approx(8.0)


def test_symmetric_blob_has_no_asymmetry_and_equal_wings():
    image = _gaussian_blob(32.0, 12.0, 4.0, 4.0, 600.0).astype(float)
    asym = step0.radial_asymmetry(image, 32.0, 12.0, step0.INNER_RADII_PX)
    assert asym["pairs"] > 0 and asym["magnitude_fraction"] < 1e-3
    plus, minus = step0.wing_levels(step0.line_profile(image, 32.0, 12.0, 0.0), step0.PROFILE_OFFSETS_PX)
    assert plus == pytest.approx(minus)


def test_one_sided_tail_sets_asymmetry_direction_and_brighter_wing():
    image = _gaussian_blob(30.0, 12.0, 4.0, 4.0, 600.0).astype(float)
    xx = np.arange(64)
    tail = np.where(xx > 30, 60.0 * np.exp(-(xx - 30) / 12.0), 0.0)
    image = np.clip(image + tail[None, :] * np.exp(-0.5 * ((np.arange(24)[:, None] - 12.0) / 3.0) ** 2), 0, 255)
    asym = step0.radial_asymmetry(image, 30.0, 12.0, step0.INNER_RADII_PX)
    assert min(asym["angle_deg"], 360.0 - asym["angle_deg"]) < 5.0
    plus, minus = step0.wing_levels(step0.line_profile(image, 30.0, 12.0, 0.0), step0.PROFILE_OFFSETS_PX)
    assert plus > minus


def test_radial_asymmetry_ignores_unpaired_directions():
    # Blob near the right crop edge: only pairs fully inside the crop may contribute.
    image = _gaussian_blob(58.0, 12.0, 4.0, 4.0, 600.0).astype(float)
    asym = step0.radial_asymmetry(image, 58.0, 12.0, step0.OUTER_RADII_PX)
    assert asym["pairs"] < step0.RADIAL_DIRECTIONS // 2
    assert asym["pairs"] == 0 or asym["magnitude_fraction"] < 1e-3


# ---------------------------------------------------------------------- one member-layer


def test_analyse_member_layer_on_synthetic_beam_locked_frames():
    rng = np.random.default_rng(0)
    images, rows = [], []
    n_rows = 400
    for k in range(40):
        image = _gaussian_blob(46.0, 9.5, 3.0, 2.6, 900.0)
        images.append(image)
        blob = step0.measure_blob(image, 150)
        rows.append(
            {
                "frame_index": 100 + k,
                "mapped_process_row": 20 + 8 * k,
                "scan_track_id": str(1 + k // 10),
                "experimental_H_pixels": blob["H_px"],
                "experimental_W_pixels": blob["W_px"],
            }
        )
    data_to_frame = np.full(n_rows, -1)
    for row in rows:
        data_to_frame[row["mapped_process_row"]] = row["frame_index"]
    t = np.arange(n_rows, dtype=float)
    result = step0.analyse_member_layer(
        np.asarray(images), rows, x_mm=0.004 * t, y_mm=np.zeros(n_rows), data_to_frame=data_to_frame, rng=rng
    )
    summary = result["summary"]
    assert summary["blob_bearing_frames"] == 40 and summary["tracks"] == 4
    assert summary["saturated_frame_fraction"] == 1.0
    assert summary["centroid_x_iqr"] == 0.0 and summary["centroid_y_iqr"] == 0.0
    assert summary["convention_H_median_diff_px"] == 0.0 and summary["convention_H_within_half_px"] == 1.0
    assert summary["row_maps_back_to_frame_fraction"] == 1.0
    assert summary["scan_direction_deg"] == pytest.approx(0.0, abs=1e-9)
    assert [item["threshold"] for item in result["family"]] == list(step0.THRESHOLDS)
    family = {item["threshold"]: item for item in result["family"]}
    assert family[30]["median_area_px"] > family[250]["median_area_px"]
    assert 1.0 <= family[150]["median_HW_non_edge"] <= 1.5


# ---------------------------------------------------------------------- across members


def test_member_trend_recovers_known_slopes():
    rng = np.random.default_rng(1)
    log_p = np.log([140, 140, 160, 180, 180, 190, 140, 180, 160, 190])
    log_v = np.log([600, 1400, 950, 600, 1400, 1100, 850, 1050, 700, 1200])
    y = 1.0 + 0.3 * log_p + 0.5 * log_v
    trend = step0.member_trend(log_p, log_v, y, rng=rng)
    assert trend["slope_log_power"] == pytest.approx(0.3)
    assert trend["slope_log_speed"] == pytest.approx(0.5)
    lo, hi = trend["slope_log_speed_ci95"]
    assert lo == pytest.approx(0.5) and hi == pytest.approx(0.5)


def _direction_entries(pairs, wing_of, c=200.0):
    """``pairs``: (layer52 scan, layer53 scan) per member; ``wing_of(scan)`` gives the asymmetry angle."""

    entries = []
    for k, scans in enumerate(pairs):
        for layer, s in zip(("layer52", "layer53"), scans):
            entries.append(
                {
                    "member_identity": f"m{k}",
                    "layer": layer,
                    "scan_direction_deg": s,
                    "blob_axis_deg": (c - s) % 180.0,
                    "asymmetry_inner_angle_deg": wing_of(s),
                }
            )
    return entries


_LAYER_PAIRS = [(90.0, 45.0)] * 4 + [(0.0, 315.0)] * 4


def test_wrap180():
    assert step0.wrap180(-45.0) == -45.0
    assert step0.wrap180(315.0) == -45.0
    assert step0.wrap180(-180.0) == 180.0


def test_direction_test_detects_a_wake_that_follows_the_scan():
    result = step0.direction_test(_direction_entries(_LAYER_PAIRS, lambda s: (200.0 - s + 180.0) % 360.0))
    assert result["mapping"] == "mirrored" and result["paired_members"] == 8
    assert result["discriminating"] and result["median_abs_scan_rotation_deg"] == pytest.approx(45.0)
    assert result["median_residual_follows_deg"] == pytest.approx(0.0, abs=1e-9)
    assert result["median_residual_fixed_deg"] == pytest.approx(45.0)
    assert result["fixed_preferred_by_deg"] < 0 and result["members_closer_to_follows"] == 8


def test_direction_test_detects_an_image_fixed_asymmetry():
    result = step0.direction_test(_direction_entries(_LAYER_PAIRS, lambda s: 90.0))
    assert result["median_residual_fixed_deg"] == pytest.approx(0.0)
    assert result["fixed_preferred_by_deg"] == pytest.approx(45.0)
    assert result["fixed_preferred_by_deg"] > step0.C5_FIXED_PREFERRED_MIN_DEG


def test_direction_test_is_not_discriminating_without_hatch_rotation():
    result = step0.direction_test(_direction_entries([(45.0, 50.0)] * 4, lambda s: 90.0))
    assert not result["discriminating"]


# ---------------------------------------------------------------------- predeclared reading


def _production_entry(name, *, hw=None, saturated=0.99, sat_blob=0.55, iqr=0.3, wing=0.08):
    hw = hw or {t: 1.15 for t in step0.THRESHOLDS}
    return {
        "member_identity": name,
        "summary": {
            "centroid_x_iqr": iqr,
            "centroid_y_iqr": iqr,
            "saturated_frame_fraction": saturated,
            "median_saturated_fraction_150": sat_blob,
            "wing_max_fraction": wing,
        },
        "family": [{"threshold": t, "median_HW_non_edge": hw[t]} for t in step0.THRESHOLDS],
    }


_FOLLOWING = {"discriminating": True, "fixed_preferred_by_deg": -40.0}


def test_reading_supports_h_core_when_all_supports_hold():
    production = [_production_entry(f"m{k}") for k in range(16)]
    reading = step0.evaluate_step0_reading(production, speed_slope_ci95=[-0.1, 0.1], direction=_FOLLOWING, all_wings=[0.08] * 32)
    assert reading["verdict"] == "SUPPORTS_H_CORE"
    assert all(reading["supports"].values()) and not any(reading["contradicts"].values())


def test_reading_stops_on_a_resolved_tail():
    hw = {t: 1.15 for t in step0.THRESHOLDS}
    hw[60] = 1.9
    production = [_production_entry(f"m{k}") for k in range(15)] + [_production_entry("tail", hw=hw)]
    reading = step0.evaluate_step0_reading(production, speed_slope_ci95=[-0.1, 0.1], direction=_FOLLOWING, all_wings=[0.08] * 32)
    assert reading["contradicts"]["C3_resolved_tail"]
    assert reading["verdict"] == "CONTRADICTS_H_CORE_STOP_AND_RECONSIDER"
    assert reading["detail"]["resolved_tail_members"] == ["tail"]


def test_reading_stops_on_pool_like_speed_scaling_and_on_unsaturated_members():
    production = [_production_entry(f"m{k}") for k in range(16)]
    reading = step0.evaluate_step0_reading(production, speed_slope_ci95=[0.3, 0.7], direction=_FOLLOWING, all_wings=[0.08] * 32)
    assert reading["contradicts"]["C4_pool_speed_scaling"] and not reading["supports"]["S3_no_pool_speed_scaling"]
    unsaturated = [_production_entry(f"u{k}", saturated=0.3) for k in range(3)] + production[3:]
    reading = step0.evaluate_step0_reading(unsaturated, speed_slope_ci95=[-0.1, 0.1], direction=_FOLLOWING, all_wings=[0.08] * 32)
    assert reading["contradicts"]["C2_unsaturated"]


def test_reading_is_mixed_when_a_support_fails_without_a_contradiction():
    production = [_production_entry(f"m{k}") for k in range(15)] + [_production_entry("loose", iqr=2.0)]
    reading = step0.evaluate_step0_reading(production, speed_slope_ci95=[-0.1, 0.3], direction=_FOLLOWING, all_wings=[0.08] * 32)
    assert not reading["supports"]["S0_coaxial"] and not reading["contradicts"]["C1_not_beam_locked"]
    assert reading["verdict"] == "MIXED_DISCUSS_WITH_OWNER"


def test_reading_stops_on_an_image_fixed_strong_asymmetry():
    production = [_production_entry(f"m{k}") for k in range(16)]
    fixed = {"discriminating": True, "fixed_preferred_by_deg": 40.0}
    reading = step0.evaluate_step0_reading(production, speed_slope_ci95=[-0.1, 0.1], direction=fixed, all_wings=[0.2] + [0.08] * 31)
    assert reading["contradicts"]["C5_image_fixed_strong_asymmetry"]
    weak = step0.evaluate_step0_reading(production, speed_slope_ci95=[-0.1, 0.1], direction=fixed, all_wings=[0.08] * 32)
    assert not weak["contradicts"]["C5_image_fixed_strong_asymmetry"]
