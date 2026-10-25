"""Patch 22.3.8 Step 0: camera-side characterization (diagnostic only)."""
from __future__ import annotations

import math

import cv2
import numpy as np
import pytest

from lpbf import camera_observations as step0


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


# ---------------------------------------------------------------------- one member-layer


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


