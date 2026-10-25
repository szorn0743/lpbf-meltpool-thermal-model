"""Patch 22.3.8 Step 0: camera-side characterization of the coaxial melt-pool camera (ledger O13).

Diagnostic only.  Reads the raw camera frames of the 16 calibration members,
measures the thresholded blob the way the experimental H/W are measured, and
evaluates the predeclared Step-0 reading in
``docs/patches/22.3.8/PATCH_22_3_8_PLAN.md``.  No thermal model is run, no
parameter is fitted or selected, no held-out member is opened for image data,
and no production rule, constant or version changes.

Every coupon file's ``gige_image`` holds the whole layer (all six parts), so
frames are reached only through the member's own
``sync/gige_image_to_data_index``; frames of other coupons are never read.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

import cv2
import h5py
import numpy as np

from lpbf.calibration_contract import member_identity
from lpbf.hierarchical_objective import PIXEL_SIZE_UM
from lpbf.observational_characterization import CharacterizationContract, _load_required_member_arrays
from lpbf.patch22_3_5_1_frozen_revalidation import _member_map
from lpbf.patch22_4_3_parallel_coarse_calibration_execution import _find_frame_file, _portable_frame_rows
from lpbf.scored_frame_rule import SCORED_FRAME_RULE_VERSION, apply_scored_frame_rule

PATCH_VERSION = "22.3.8"
STEP_ID = "step0_camera_characterization"
SCHEMA = "lpbf_patch22_3_8_step0_camera_characterization"
CONTRACT_PATH = Path(__file__).with_name("data") / "patch21_0_calibration_contract.json"
DEFAULT_OUTPUT_DIRECTORY = "patch22_3_8_step0_output"
PLAN_PATH = Path(__file__).resolve().parents[2] / "docs" / "patches" / "22.3.8" / "PATCH_22_3_8_PLAN.md"

PRODUCTION_LAYER = "layer53"
DIRECTION_LAYER = "layer52"
LAYERS = (PRODUCTION_LAYER, DIRECTION_LAYER)
PRODUCTION_THRESHOLD = 150
SATURATION_LEVEL = 255
THRESHOLDS = (30, 45, 60, 80, 100, 125, 150, 175, 200, 225, 250)
SCAN_HALF_WINDOW_ROWS = 4
PROFILE_OFFSETS_PX = np.arange(-20, 21, dtype=np.float64)
WING_RANGE_PX = (10.0, 16.0)
WING_MIN_SAMPLES = 4
INNER_RADII_PX = (5.0, 6.0, 7.0, 8.0)
OUTER_RADII_PX = (9.0, 10.0, 11.0, 12.0)
RADIAL_DIRECTIONS = 24
BOOTSTRAP_REPLICATES = 2000
BOOTSTRAP_SEED = 22038

# Predeclared Step-0 reading (PATCH_22_3_8_PLAN.md, fixed 2026-10-14 before the 16-member run).
COAXIAL_CENTROID_IQR_MAX_PX = 1.5
SATURATED_FRAME_FRACTION_MIN = 0.90
SATURATED_BLOB_FRACTION_MIN = 0.30
SHAPE_THRESHOLDS = (60, 100, 150, 200, 250)
SHAPE_HW_RANGE = (1.0, 1.5)
SHAPE_HW_RISE_MAX = 0.25
SPEED_SLOPE_SUPPORT_MAX = 0.25
POOL_SPEED_SLOPE = 0.5
WING_STRENGTH_MAX = 0.15
C1_MIN_COAXIAL_FAILURES = 2
C2_UNSATURATED_FRACTION = 0.50
C2_MIN_UNSATURATED_MEMBERS = 3
C3_TAIL_HW = 1.8
C3_THRESHOLDS = (60, 100)
# C5 amended 2026-10-14 before the 16-member run: a pooled resultant-length comparison
# cannot separate the hypotheses when the hatch rotates only ~45 deg between layers, so
# each member's layer52 -> layer53 rotation of the asymmetry direction is compared with
# the mapped scan rotation ("follows") and with zero ("fixed").
C5_FIXED_PREFERRED_MIN_DEG = 15.0
DIRECTION_DISCRIMINATING_MIN_ROTATION_DEG = 30.0


class Step0Error(RuntimeError):
    """Fail-closed error for the Patch 22.3.8 Step-0 camera characterization."""


# ---------------------------------------------------------------------- members


def _partition() -> Mapping[str, Any]:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))["data_partition"]


def calibration_member_identities() -> tuple[str, ...]:
    members = _partition()["calibration_members"]
    return tuple(sorted(member_identity(item["acquisition_set_id"], item["part_number"]) for item in members))


def held_out_member_identities() -> tuple[str, ...]:
    members = _partition()["validation_members"]
    return tuple(sorted(member_identity(item["acquisition_set_id"], item["part_number"]) for item in members))


def require_calibration_members(identities: Sequence[str]) -> tuple[str, ...]:
    """Return the requested identities, refusing held-out and unknown members."""

    calibration = set(calibration_member_identities())
    held_out = set(held_out_member_identities())
    for identity in identities:
        if identity in held_out:
            raise Step0Error(f"held-out member refused by Patch 22.3.8 Step 0: {identity}")
        if identity not in calibration:
            raise Step0Error(f"not a calibration member: {identity}")
    return tuple(sorted(set(str(identity) for identity in identities)))


def _condition_records() -> dict[str, dict[str, Any]]:
    return {
        member_identity(item["acquisition_set_id"], item["part_number"]): {
            "condition_id": str(item["condition_id"]),
            "power_W": float(item["power_W"]),
            "speed_mm_s": float(item["speed_mm_s"]),
            "acquisition_set_id": str(item["acquisition_set_id"]),
        }
        for item in _partition()["calibration_members"]
    }


# ---------------------------------------------------------------------- frames


def scored_frame_rows(
    mapping: np.ndarray,
    laser_on: np.ndarray,
    track_ids: np.ndarray,
    h_pixels: np.ndarray,
    w_pixels: np.ndarray,
) -> list[dict[str, Any]]:
    """Scored frames of one member-layer: Patch 21.3 eligibility, then the A22 rule.

    Only frames whose ``gige_image_to_data_index`` maps into this member's
    process rows are considered, so other coupons' frames never enter.
    """

    mapping = np.asarray(mapping, dtype=np.int64)
    n_rows = int(np.asarray(laser_on).size)
    rows: list[dict[str, Any]] = []
    for frame_index, mapped in enumerate(mapping):
        mapped = int(mapped)
        if not 0 <= mapped < n_rows or not bool(laser_on[mapped]):
            continue
        h_value, w_value = float(h_pixels[mapped]), float(w_pixels[mapped])
        track = int(track_ids[mapped])
        eligible = bool(math.isfinite(h_value) and math.isfinite(w_value) and h_value >= 0.0 and w_value >= 0.0 and track > 0)
        rows.append(
            {
                "frame_index": int(frame_index),
                "mapped_process_row": mapped,
                "scan_track_id": str(track),
                "observation_eligible": eligible,
                "experimental_H_pixels": h_value,
                "experimental_W_pixels": w_value,
            }
        )
    return [row for row in apply_scored_frame_rule(rows) if row["scored_frame"]]


def _frame_key_set(rows: Sequence[Mapping[str, Any]]) -> set[tuple[int, str]]:
    return {(int(row["frame_index"]), str(row["scan_track_id"])) for row in rows}


# ---------------------------------------------------------------------- blob geometry


def principal_axis_deg(xs: np.ndarray, ys: np.ndarray) -> float:
    """Major-axis angle in image coordinates (x right, y down), in [0, 180); NaN if isotropic."""

    if xs.size < 3:
        return float("nan")
    cov = np.cov(np.vstack([xs, ys]).astype(np.float64))
    values, vectors = np.linalg.eigh(cov)
    if not np.all(np.isfinite(values)) or values[1] <= values[0] * (1.0 + 1e-9):
        return float("nan")
    vx, vy = vectors[:, 1]
    return float(np.degrees(np.arctan2(vy, vx)) % 180.0)


def measure_blob(image: np.ndarray, threshold: int) -> dict[str, Any] | None:
    """Camera convention: ``>= threshold``, largest 8-connected component, external contour, minAreaRect."""

    image = np.asarray(image)
    mask = (image >= int(threshold)).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if count < 2:
        return None
    index = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    component = labels == index
    contours, _ = cv2.findContours(component.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    points = np.vstack([contour.reshape(-1, 2) for contour in contours]).astype(np.float32)
    (_, _), (side_a, side_b), _ = cv2.minAreaRect(points)
    ys, xs = np.nonzero(component)
    n_rows, n_cols = image.shape
    return {
        "H_px": float(max(side_a, side_b)),
        "W_px": float(min(side_a, side_b)),
        "area_px": int(xs.size),
        "component_count": int(count - 1),
        "touches_edge": bool(xs.min() == 0 or ys.min() == 0 or xs.max() == n_cols - 1 or ys.max() == n_rows - 1),
        "centroid_x": float(xs.mean()),
        "centroid_y": float(ys.mean()),
        "axis_deg": principal_axis_deg(xs, ys),
        "saturated_px": int(np.count_nonzero(image[component] >= SATURATION_LEVEL)),
    }


# ---------------------------------------------------------------------- circular statistics


def axial_mean_deg(angles: Sequence[float]) -> tuple[float, float]:
    """Mean and resultant length of 180-periodic angles."""

    values = np.radians(np.asarray(angles, dtype=np.float64))
    values = values[np.isfinite(values)]
    if values.size == 0:
        return float("nan"), float("nan")
    z = np.mean(np.exp(2j * values))
    return float(np.degrees(np.angle(z)) / 2.0 % 180.0), float(abs(z))


def circular_mean_deg(angles: Sequence[float]) -> tuple[float, float]:
    """Mean and resultant length of 360-periodic angles."""

    values = np.radians(np.asarray(angles, dtype=np.float64))
    values = values[np.isfinite(values)]
    if values.size == 0:
        return float("nan"), float("nan")
    z = np.mean(np.exp(1j * values))
    return float(np.degrees(np.angle(z)) % 360.0), float(abs(z))


def scan_direction_deg(x_mm: np.ndarray, y_mm: np.ndarray, rows: Sequence[int]) -> np.ndarray:
    """Machine-frame scan direction (full circle) around each mapped process row."""

    x_mm, y_mm = np.asarray(x_mm, dtype=np.float64), np.asarray(y_mm, dtype=np.float64)
    rows = np.asarray(rows, dtype=np.int64)
    lo = np.clip(rows - SCAN_HALF_WINDOW_ROWS, 0, x_mm.size - 1)
    hi = np.clip(rows + SCAN_HALF_WINDOW_ROWS, 0, x_mm.size - 1)
    dx, dy = x_mm[hi] - x_mm[lo], y_mm[hi] - y_mm[lo]
    angles = np.degrees(np.arctan2(dy, dx)) % 360.0
    angles[np.hypot(dx, dy) <= 0.0] = np.nan
    return angles


# ---------------------------------------------------------------------- profiles


def bilinear_sample(image: np.ndarray, xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
    """Bilinear samples; NaN outside the represented pixel centres."""

    image = np.asarray(image, dtype=np.float64)
    n_rows, n_cols = image.shape
    xs, ys = np.asarray(xs, dtype=np.float64), np.asarray(ys, dtype=np.float64)
    inside = (xs >= 0.0) & (xs <= n_cols - 1) & (ys >= 0.0) & (ys <= n_rows - 1)
    out = np.full(xs.shape, np.nan)
    x, y = xs[inside], ys[inside]
    x0 = np.minimum(np.floor(x).astype(int), n_cols - 2)
    y0 = np.minimum(np.floor(y).astype(int), n_rows - 2)
    fx, fy = x - x0, y - y0
    out[inside] = (
        image[y0, x0] * (1 - fx) * (1 - fy)
        + image[y0, x0 + 1] * fx * (1 - fy)
        + image[y0 + 1, x0] * (1 - fx) * fy
        + image[y0 + 1, x0 + 1] * fx * fy
    )
    return out


def line_profile(image: np.ndarray, cx: float, cy: float, angle_deg: float, offsets: np.ndarray = PROFILE_OFFSETS_PX) -> np.ndarray:
    theta = math.radians(angle_deg)
    return bilinear_sample(image, cx + offsets * math.cos(theta), cy + offsets * math.sin(theta))


def edge_width_px(profile: np.ndarray, offsets: np.ndarray, *, side: int) -> float:
    """10-90 % (of full scale) edge width moving outward from the core on one side (+1 or -1)."""

    order = np.argsort(side * offsets)
    s = (side * offsets)[order]
    v = np.asarray(profile, dtype=np.float64)[order]
    keep = s >= 0
    s, v = s[keep], v[keep]

    def crossing(level: float) -> float:
        for k in range(1, s.size):
            if not (np.isfinite(v[k - 1]) and np.isfinite(v[k])):
                return float("nan")
            if v[k - 1] > level >= v[k]:
                return float(s[k - 1] + (v[k - 1] - level) / (v[k - 1] - v[k]) * (s[k] - s[k - 1]))
        return float("nan")

    high, low = crossing(0.9 * SATURATION_LEVEL), crossing(0.1 * SATURATION_LEVEL)
    return float(low - high) if math.isfinite(high) and math.isfinite(low) else float("nan")


def wing_levels(profile: np.ndarray, offsets: np.ndarray) -> tuple[float, float]:
    """Mean level (fraction of full scale) at 10-16 px on the + and - side; NaN if under-sampled."""

    def side_mean(mask: np.ndarray) -> float:
        values = np.asarray(profile, dtype=np.float64)[mask]
        values = values[np.isfinite(values)]
        return float(values.mean() / SATURATION_LEVEL) if values.size >= WING_MIN_SAMPLES else float("nan")

    lo, hi = WING_RANGE_PX
    return side_mean((offsets >= lo) & (offsets <= hi)), side_mean((offsets <= -lo) & (offsets >= -hi))


def radial_asymmetry(image: np.ndarray, cx: float, cy: float, radii: Sequence[float]) -> dict[str, Any]:
    """Pairwise radial asymmetry: only directions whose opposite is also inside the crop contribute."""

    phis = np.arange(RADIAL_DIRECTIONS) * 360.0 / RADIAL_DIRECTIONS
    radii = np.asarray(radii, dtype=np.float64)
    levels = np.full(phis.size, np.nan)
    for k, phi in enumerate(phis):
        t = math.radians(phi)
        samples = bilinear_sample(image, cx + radii * math.cos(t), cy + radii * math.sin(t))
        if np.all(np.isfinite(samples)):
            levels[k] = float(samples.mean())
    half = RADIAL_DIRECTIONS // 2
    vector = np.zeros(2)
    pairs = 0
    for k in range(half):
        a, b = levels[k], levels[k + half]
        if math.isfinite(a) and math.isfinite(b):
            t = math.radians(phis[k])
            vector += (a - b) * np.array([math.cos(t), math.sin(t)])
            pairs += 1
    if pairs == 0:
        return {"pairs": 0, "angle_deg": float("nan"), "magnitude_fraction": float("nan"), "levels": levels.tolist()}
    vector /= pairs
    return {
        "pairs": int(pairs),
        "angle_deg": float(np.degrees(np.arctan2(vector[1], vector[0])) % 360.0),
        "magnitude_fraction": float(np.hypot(*vector) / SATURATION_LEVEL),
        "levels": [None if not math.isfinite(value) else float(value) for value in levels],
    }


# ---------------------------------------------------------------------- statistics


def _iqr(values: Sequence[float]) -> float:
    values = np.asarray(values, dtype=np.float64)
    values = values[np.isfinite(values)]
    return float(np.subtract(*np.percentile(values, [75, 25]))) if values.size else float("nan")


def _median(values: Sequence[float]) -> float:
    values = np.asarray(values, dtype=np.float64)
    values = values[np.isfinite(values)]
    return float(np.median(values)) if values.size else float("nan")


def track_bootstrap_median_ci(values: Sequence[float], tracks: Sequence[str], *, rng: np.random.Generator) -> tuple[float, float]:
    """95 % percentile CI of the median, resampling whole scan tracks."""

    values = np.asarray(values, dtype=np.float64)
    tracks = np.asarray(tracks)
    keep = np.isfinite(values)
    values, tracks = values[keep], tracks[keep]
    groups = [values[tracks == track] for track in np.unique(tracks)]
    if len(groups) < 2:
        return float("nan"), float("nan")
    medians = np.empty(BOOTSTRAP_REPLICATES)
    for r in range(BOOTSTRAP_REPLICATES):
        picks = rng.integers(0, len(groups), size=len(groups))
        medians[r] = np.median(np.concatenate([groups[p] for p in picks]))
    lo, hi = np.percentile(medians, [2.5, 97.5])
    return float(lo), float(hi)


def member_trend(log_power: Sequence[float], log_speed: Sequence[float], response: Sequence[float], *, rng: np.random.Generator) -> dict[str, Any]:
    """OLS of ``response`` on [1, log P, log v] with a member-resampling bootstrap."""

    lp, lv, y = (np.asarray(item, dtype=np.float64) for item in (log_power, log_speed, response))
    keep = np.isfinite(lp) & np.isfinite(lv) & np.isfinite(y)
    lp, lv, y = lp[keep], lv[keep], y[keep]
    design = np.column_stack([np.ones_like(lp), lp, lv])
    if y.size < 4 or np.linalg.matrix_rank(design) < 3:
        raise Step0Error("trend regression is not identifiable on the supplied members")
    beta = np.linalg.lstsq(design, y, rcond=None)[0]
    draws: list[np.ndarray] = []
    for _ in range(BOOTSTRAP_REPLICATES):
        picks = rng.integers(0, y.size, size=y.size)
        sample = design[picks]
        if np.linalg.matrix_rank(sample) < 3:
            continue
        draws.append(np.linalg.lstsq(sample, y[picks], rcond=None)[0])
    boot = np.asarray(draws)
    ci = np.percentile(boot, [2.5, 97.5], axis=0)
    return {
        "members": int(y.size),
        "bootstrap_replicates_used": int(boot.shape[0]),
        "slope_log_power": float(beta[1]),
        "slope_log_power_ci95": [float(ci[0, 1]), float(ci[1, 1])],
        "slope_log_speed": float(beta[2]),
        "slope_log_speed_ci95": [float(ci[0, 2]), float(ci[1, 2])],
    }


# ---------------------------------------------------------------------- one member-layer


def _read_member_frames(path: Path, layer: str, frame_indices: Sequence[int]) -> dict[str, Any]:
    """Read only the listed frames (strictly increasing) plus machine XY and the data->frame map."""

    indices = np.asarray(frame_indices, dtype=np.int64)
    if indices.size == 0 or np.any(np.diff(indices) <= 0):
        raise Step0Error("frame indices must be non-empty and strictly increasing")
    with h5py.File(path, "r") as h5_file:
        group = h5_file[layer]
        names = [item.decode() if isinstance(item, bytes) else str(item) for item in group["names"][()]]
        data = group["data"]
        return {
            "images": np.asarray(group["gige_image"][indices.tolist()]),
            "x_mm": np.asarray(data[names.index("X-Machine"), :], dtype=np.float64),
            "y_mm": np.asarray(data[names.index("Y-Machine"), :], dtype=np.float64),
            "data_to_frame": np.asarray(group["sync/data_to_gige_image_index"][()], dtype=np.int64),
        }


def analyse_member_layer(
    images: np.ndarray,
    rows: Sequence[Mapping[str, Any]],
    *,
    x_mm: np.ndarray,
    y_mm: np.ndarray,
    data_to_frame: np.ndarray,
    rng: np.random.Generator,
) -> dict[str, Any]:
    """Per-frame blob family and per-member-layer summary for one member-layer."""

    images = np.asarray(images)
    if images.shape[0] != len(rows):
        raise Step0Error("image count does not match scored frame rows")
    frames: list[dict[str, Any]] = []
    for image, row in zip(images, rows):
        record: dict[str, Any] = {
            "frame_index": int(row["frame_index"]),
            "mapped_process_row": int(row["mapped_process_row"]),
            "scan_track_id": str(row["scan_track_id"]),
            "stored_H_px": float(row["experimental_H_pixels"]),
            "stored_W_px": float(row["experimental_W_pixels"]),
            "peak": int(image.max()),
            "saturated_px": int(np.count_nonzero(image >= SATURATION_LEVEL)),
            "background_p05": float(np.percentile(image, 5)),
            "row_maps_back_to_frame": bool(data_to_frame[int(row["mapped_process_row"])] == int(row["frame_index"])),
        }
        for threshold in THRESHOLDS:
            blob = measure_blob(image, threshold)
            record[f"H_{threshold}"] = blob["H_px"] if blob else float("nan")
            record[f"W_{threshold}"] = blob["W_px"] if blob else float("nan")
            record[f"area_{threshold}"] = blob["area_px"] if blob else 0
            record[f"edge_{threshold}"] = bool(blob["touches_edge"]) if blob else False
            if threshold == PRODUCTION_THRESHOLD:
                record["has_blob_150"] = blob is not None
                record["centroid_x"] = blob["centroid_x"] if blob else float("nan")
                record["centroid_y"] = blob["centroid_y"] if blob else float("nan")
                record["axis_deg"] = blob["axis_deg"] if blob else float("nan")
                record["saturated_fraction_150"] = blob["saturated_px"] / blob["area_px"] if blob else float("nan")
        frames.append(record)

    scan = scan_direction_deg(x_mm, y_mm, [record["mapped_process_row"] for record in frames])
    for record, angle in zip(frames, scan):
        record["scan_deg"] = float(angle)

    bearing = [record for record in frames if record["has_blob_150"]]
    if not bearing:
        raise Step0Error("no scored frame carries a threshold-150 blob")
    tracks = [record["scan_track_id"] for record in bearing]

    family: list[dict[str, Any]] = []
    for threshold in THRESHOLDS:
        nested = min(threshold, PRODUCTION_THRESHOLD)
        h = np.array([record[f"H_{threshold}"] for record in bearing])
        w = np.array([record[f"W_{threshold}"] for record in bearing])
        ratio = np.where(w > 0, h / np.where(w > 0, w, 1.0), np.nan)
        non_edge = np.array([not record[f"edge_{nested}"] for record in bearing])
        entry = {
            "threshold": int(threshold),
            "frames": int(np.count_nonzero(np.isfinite(h))),
            "median_H_px": _median(h),
            "median_W_px": _median(w),
            "median_HW": _median(ratio),
            "edge_touch_fraction": float(np.mean([record[f"edge_{threshold}"] for record in bearing])),
            "non_edge_frames": int(np.count_nonzero(non_edge & np.isfinite(ratio))),
            "median_HW_non_edge": _median(ratio[non_edge]),
            "median_area_px": _median([record[f"area_{threshold}"] for record in bearing]),
        }
        if threshold in (60, PRODUCTION_THRESHOLD):
            lo, hi = track_bootstrap_median_ci(ratio[non_edge], np.asarray(tracks)[non_edge], rng=rng)
            entry["median_HW_non_edge_ci95"] = [lo, hi]
        family.append(entry)

    centroid_x = np.median([record["centroid_x"] for record in bearing])
    centroid_y = np.median([record["centroid_y"] for record in bearing])
    axis, axis_r = axial_mean_deg([record["axis_deg"] for record in bearing])
    scan_mean, scan_r = circular_mean_deg([record["scan_deg"] for record in bearing])
    bearing_images = images[[k for k, record in enumerate(frames) if record["has_blob_150"]]]
    mean_image = bearing_images.astype(np.float64).mean(axis=0)
    along = line_profile(mean_image, centroid_x, centroid_y, axis)
    across = line_profile(mean_image, centroid_x, centroid_y, axis + 90.0)
    wing_plus, wing_minus = wing_levels(along, PROFILE_OFFSETS_PX)
    wings = [value for value in (wing_plus, wing_minus) if math.isfinite(value)]
    stored_h = np.array([record["stored_H_px"] for record in bearing])
    stored_w = np.array([record["stored_W_px"] for record in bearing])
    h150 = np.array([record["H_150"] for record in bearing])
    w150 = np.array([record["W_150"] for record in bearing])
    positive = (stored_h > 0) & (stored_w > 0)

    summary = {
        "scored_frames": int(len(frames)),
        "blob_bearing_frames": int(len(bearing)),
        "scored_frames_without_blob_150": int(len(frames) - len(bearing)),
        "stored_zero_footprint_frames": int(sum(1 for record in frames if record["stored_H_px"] == 0.0 or record["stored_W_px"] == 0.0)),
        "tracks": int(len(set(tracks))),
        "saturated_frame_fraction": float(np.mean([record["saturated_px"] > 0 for record in bearing])),
        "median_saturated_px": _median([record["saturated_px"] for record in bearing]),
        "median_saturated_fraction_150": _median([record["saturated_fraction_150"] for record in bearing]),
        "median_peak": _median([record["peak"] for record in bearing]),
        "median_background_p05": _median([record["background_p05"] for record in bearing]),
        "centroid_x_median": float(centroid_x),
        "centroid_y_median": float(centroid_y),
        "centroid_x_iqr": _iqr([record["centroid_x"] for record in bearing]),
        "centroid_y_iqr": _iqr([record["centroid_y"] for record in bearing]),
        "blob_axis_deg": axis,
        "blob_axis_resultant": axis_r,
        "scan_direction_deg": scan_mean,
        "scan_direction_resultant": scan_r,
        "median_H_150_um": _median(h150) * PIXEL_SIZE_UM,
        "median_W_150_um": _median(w150) * PIXEL_SIZE_UM,
        "median_HW_150": _median(np.where(w150 > 0, h150 / np.where(w150 > 0, w150, 1.0), np.nan)),
        "edge_width_along_plus_px": edge_width_px(along, PROFILE_OFFSETS_PX, side=+1),
        "edge_width_along_minus_px": edge_width_px(along, PROFILE_OFFSETS_PX, side=-1),
        "edge_width_across_plus_px": edge_width_px(across, PROFILE_OFFSETS_PX, side=+1),
        "edge_width_across_minus_px": edge_width_px(across, PROFILE_OFFSETS_PX, side=-1),
        "wing_plus_fraction": wing_plus,
        "wing_minus_fraction": wing_minus,
        "wing_max_fraction": float(max(wings)) if wings else float("nan"),
        "convention_H_median_diff_px": _median(h150[positive] - stored_h[positive]),
        "convention_W_median_diff_px": _median(w150[positive] - stored_w[positive]),
        "convention_H_within_half_px": float(np.mean(np.abs(h150[positive] - stored_h[positive]) <= 0.5)) if positive.any() else float("nan"),
        "convention_W_within_half_px": float(np.mean(np.abs(w150[positive] - stored_w[positive]) <= 0.5)) if positive.any() else float("nan"),
        "row_maps_back_to_frame_fraction": float(np.mean([record["row_maps_back_to_frame"] for record in bearing])),
    }
    inner = radial_asymmetry(mean_image, centroid_x, centroid_y, INNER_RADII_PX)
    outer = radial_asymmetry(mean_image, centroid_x, centroid_y, OUTER_RADII_PX)
    summary.update(
        {
            "asymmetry_inner_angle_deg": inner["angle_deg"],
            "asymmetry_inner_fraction": inner["magnitude_fraction"],
            "asymmetry_inner_pairs": inner["pairs"],
            "asymmetry_outer_angle_deg": outer["angle_deg"],
            "asymmetry_outer_fraction": outer["magnitude_fraction"],
            "asymmetry_outer_pairs": outer["pairs"],
        }
    )
    profiles = {
        "offsets_px": PROFILE_OFFSETS_PX.tolist(),
        "along_axis": [None if not math.isfinite(v) else float(v) for v in along],
        "across_axis": [None if not math.isfinite(v) else float(v) for v in across],
        "radial_inner_levels": inner["levels"],
        "radial_outer_levels": outer["levels"],
        "mean_image": np.round(mean_image, 2).tolist(),
    }
    return {"summary": summary, "family": family, "profiles": profiles, "frames": frames}


# ---------------------------------------------------------------------- across members


def wrap180(angle_deg: float) -> float:
    """Wrap an angle difference into (-180, 180]."""

    value = (float(angle_deg) + 180.0) % 360.0 - 180.0
    return 180.0 if value == -180.0 else value


def direction_test(entries: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Does the low-level asymmetry follow the scan direction or stay fixed in the image?

    The machine-to-image mapping (mirrored or direct) is fitted on the blob axes of
    all member-layers.  Then, per member, the observed layer52 -> layer53 rotation of
    the asymmetry direction is compared with the mapped scan rotation ("follows") and
    with zero ("fixed").
    """

    scan = np.array([float(entry["scan_direction_deg"]) for entry in entries])
    axis = np.array([float(entry["blob_axis_deg"]) for entry in entries])
    wing = np.array([float(entry["asymmetry_inner_angle_deg"]) for entry in entries])
    _, scan_r = circular_mean_deg(scan)
    mirrored_c, mirrored_r = axial_mean_deg((axis + scan) % 180.0)
    direct_c, direct_r = axial_mean_deg((axis - scan) % 180.0)
    mirrored = mirrored_r >= direct_r
    c = mirrored_c if mirrored else direct_c
    predicted_axis = (c - scan) % 360.0 if mirrored else (c + scan) % 360.0
    delta = (wing - predicted_axis) % 360.0
    delta_mean, follow_r = circular_mean_deg(delta)
    _, fixed_r = circular_mean_deg(wing)

    by_member: dict[str, dict[str, Mapping[str, Any]]] = {}
    for entry in entries:
        by_member.setdefault(str(entry["member_identity"]), {})[str(entry["layer"])] = entry
    pairs: list[dict[str, Any]] = []
    for identity, layers in sorted(by_member.items()):
        if PRODUCTION_LAYER not in layers or DIRECTION_LAYER not in layers:
            continue
        first, second = layers[DIRECTION_LAYER], layers[PRODUCTION_LAYER]
        values = [float(first[key]) for key in ("scan_direction_deg", "asymmetry_inner_angle_deg")]
        values += [float(second[key]) for key in ("scan_direction_deg", "asymmetry_inner_angle_deg")]
        if not all(math.isfinite(value) for value in values):
            continue
        scan_rotation = wrap180(values[2] - values[0])
        predicted = -scan_rotation if mirrored else scan_rotation
        observed = wrap180(values[3] - values[1])
        pairs.append(
            {
                "member_identity": identity,
                "scan_rotation_deg": scan_rotation,
                "predicted_image_rotation_if_follows_deg": predicted,
                "observed_asymmetry_rotation_deg": observed,
                "residual_follows_deg": abs(wrap180(observed - predicted)),
                "residual_fixed_deg": abs(observed),
            }
        )
    median_rotation = _median([abs(p["scan_rotation_deg"]) for p in pairs])
    median_follow = _median([p["residual_follows_deg"] for p in pairs])
    median_fixed = _median([p["residual_fixed_deg"] for p in pairs])
    return {
        "member_layers": int(len(entries)),
        "paired_members": int(len(pairs)),
        "mapping": "mirrored" if mirrored else "direct",
        "axis_mapping_constant_deg": c,
        "axis_mapping_resultant_mirrored": mirrored_r,
        "axis_mapping_resultant_direct": direct_r,
        "median_abs_scan_rotation_deg": median_rotation,
        "discriminating": bool(math.isfinite(median_rotation) and median_rotation >= DIRECTION_DISCRIMINATING_MIN_ROTATION_DEG),
        "median_residual_follows_deg": median_follow,
        "median_residual_fixed_deg": median_fixed,
        "fixed_preferred_by_deg": float(median_follow - median_fixed) if pairs else float("nan"),
        "members_closer_to_follows": int(sum(p["residual_follows_deg"] < p["residual_fixed_deg"] for p in pairs)),
        "pooled_scan_direction_resultant": scan_r,
        "pooled_wing_follow_resultant": follow_r,
        "pooled_wing_follow_mean_offset_deg": delta_mean,
        "pooled_wing_fixed_resultant": fixed_r,
        "pairs": pairs,
        "per_member_layer": [
            {
                "member_identity": entry["member_identity"],
                "layer": entry["layer"],
                "scan_direction_deg": float(s),
                "blob_axis_deg": float(a),
                "wing_angle_deg": float(g),
                "wing_offset_from_scan_axis_deg": float(d),
            }
            for entry, s, a, g, d in zip(entries, scan, axis, wing, delta)
        ],
    }


def _hw_non_edge(entry: Mapping[str, Any], threshold: int) -> float:
    for item in entry["family"]:
        if int(item["threshold"]) == int(threshold):
            return float(item["median_HW_non_edge"])
    raise Step0Error(f"threshold {threshold} missing from family")


def evaluate_step0_reading(
    production: Sequence[Mapping[str, Any]],
    *,
    speed_slope_ci95: Sequence[float],
    direction: Mapping[str, Any],
    all_wings: Sequence[float],
) -> dict[str, Any]:
    """Apply the predeclared Step-0 reading.  ``production`` holds layer53 entries (summary + family)."""

    def coaxial_ok(entry: Mapping[str, Any]) -> bool:
        s = entry["summary"]
        return bool(s["centroid_x_iqr"] <= COAXIAL_CENTROID_IQR_MAX_PX and s["centroid_y_iqr"] <= COAXIAL_CENTROID_IQR_MAX_PX)

    def shape_ok(entry: Mapping[str, Any]) -> bool:
        lo, hi = SHAPE_HW_RANGE
        values = [_hw_non_edge(entry, t) for t in SHAPE_THRESHOLDS]
        rise = _hw_non_edge(entry, 60) - _hw_non_edge(entry, PRODUCTION_THRESHOLD)
        return bool(all(lo <= v <= hi for v in values) and rise < SHAPE_HW_RISE_MAX)

    ci_lo, ci_hi = float(speed_slope_ci95[0]), float(speed_slope_ci95[1])
    coaxial_failures = [entry["member_identity"] for entry in production if not coaxial_ok(entry)]
    unsaturated = [entry["member_identity"] for entry in production if entry["summary"]["saturated_frame_fraction"] < C2_UNSATURATED_FRACTION]
    tails = [
        entry["member_identity"]
        for entry in production
        if any(_hw_non_edge(entry, t) >= C3_TAIL_HW for t in C3_THRESHOLDS)
    ]
    wings = [entry["summary"]["wing_max_fraction"] for entry in production]
    evaluable_wings = [w for w in wings if math.isfinite(w)]
    strong_any = [w for w in all_wings if math.isfinite(w) and w > WING_STRENGTH_MAX]
    supports = {
        "S0_coaxial": not coaxial_failures,
        "S1_saturated": all(
            entry["summary"]["saturated_frame_fraction"] >= SATURATED_FRAME_FRACTION_MIN
            and entry["summary"]["median_saturated_fraction_150"] >= SATURATED_BLOB_FRACTION_MIN
            for entry in production
        ),
        "S2_shape_invariant": all(shape_ok(entry) for entry in production),
        "S3_no_pool_speed_scaling": bool(ci_hi < SPEED_SLOPE_SUPPORT_MAX),
        "S4_faint_wake": bool(evaluable_wings and all(w <= WING_STRENGTH_MAX for w in evaluable_wings)),
    }
    contradicts = {
        "C1_not_beam_locked": len(coaxial_failures) >= C1_MIN_COAXIAL_FAILURES,
        "C2_unsaturated": len(unsaturated) >= C2_MIN_UNSATURATED_MEMBERS,
        "C3_resolved_tail": bool(tails),
        "C4_pool_speed_scaling": bool(ci_lo <= POOL_SPEED_SLOPE <= ci_hi),
        "C5_image_fixed_strong_asymmetry": bool(
            direction["discriminating"]
            and float(direction["fixed_preferred_by_deg"]) > C5_FIXED_PREFERRED_MIN_DEG
            and bool(strong_any)
        ),
    }
    if any(contradicts.values()):
        verdict = "CONTRADICTS_H_CORE_STOP_AND_RECONSIDER"
    elif all(supports.values()):
        verdict = "SUPPORTS_H_CORE"
    else:
        verdict = "MIXED_DISCUSS_WITH_OWNER"
    return {
        "verdict": verdict,
        "supports": supports,
        "contradicts": contradicts,
        "detail": {
            "coaxial_failures": coaxial_failures,
            "unsaturated_members": unsaturated,
            "resolved_tail_members": tails,
            "wing_evaluable_members": len(evaluable_wings),
            "speed_slope_ci95": [ci_lo, ci_hi],
            "direction_discriminating": bool(direction["discriminating"]),
        },
    }


# ---------------------------------------------------------------------- runner


def _json_default(value: Any) -> Any:
    if isinstance(value, (np.floating,)):
        return None if not math.isfinite(float(value)) else float(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    raise TypeError(f"not JSON serializable: {type(value)!r}")


def _clean(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    return value


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(_clean(payload), indent=2, default=_json_default, allow_nan=False) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]], *, compress: bool = False) -> None:
    if not rows:
        raise Step0Error(f"no rows to write for {path.name}")
    fields = list(rows[0].keys())
    opener = (lambda p: gzip.open(p, "wt", encoding="utf-8", newline="")) if compress else (lambda p: p.open("w", encoding="utf-8", newline=""))
    with opener(path) as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _clean(row.get(key)) for key in fields})


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], capture_output=True, text=True, check=True, cwd=Path(__file__).resolve().parents[2]).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def run_step0(
    *,
    data_directory: str | Path,
    characterization_directory: str | Path,
    output_directory: str | Path,
    members: Sequence[str] | None = None,
) -> dict[str, Any]:
    identities = require_calibration_members(members if members is not None else calibration_member_identities())
    output = Path(output_directory).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    characterization = Path(characterization_directory).expanduser().resolve()
    member_map = _member_map(data_directory)
    conditions = _condition_records()
    rng = np.random.default_rng(BOOTSTRAP_SEED)

    entries: list[dict[str, Any]] = []
    frame_rows_out: list[dict[str, Any]] = []
    cross_checks: list[dict[str, Any]] = []
    for identity in identities:
        member = member_map.get(identity)
        if member is None:
            raise Step0Error(f"dataset member is missing: {identity}")
        for layer in LAYERS:
            arrays = _load_required_member_arrays(Path(member.path), contract=CharacterizationContract(layer_name=layer))
            rows = scored_frame_rows(arrays["mapping"], arrays["laser_on"], arrays["scan_track_id"], arrays["h_pixels"], arrays["w_pixels"])
            if layer == PRODUCTION_LAYER:
                reference = [
                    row for row in apply_scored_frame_rule(_portable_frame_rows(_find_frame_file(characterization, member), member)) if row["scored_frame"]
                ]
                if _frame_key_set(reference) != _frame_key_set(rows):
                    raise Step0Error(f"{identity} {layer}: scored frames differ from the Patch 21.3 characterization rows")
                cross_checks.append({"member_identity": identity, "layer": layer, "scored_frames": len(rows), "matches_patch21_3_rows": True})
            frames = _read_member_frames(Path(member.path), layer, [int(row["frame_index"]) for row in rows])
            result = analyse_member_layer(
                frames["images"], rows, x_mm=frames["x_mm"], y_mm=frames["y_mm"], data_to_frame=frames["data_to_frame"], rng=rng
            )
            condition = conditions[identity]
            entry = {"member_identity": identity, "layer": layer, **condition, **result["summary"], "family": result["family"], "profiles": result["profiles"]}
            entries.append(entry)
            for record in result["frames"]:
                frame_rows_out.append({"member_identity": identity, "layer": layer, **record})

    production = [entry for entry in entries if entry["layer"] == PRODUCTION_LAYER]
    log_p = [math.log(entry["power_W"]) for entry in production]
    log_v = [math.log(entry["speed_mm_s"]) for entry in production]
    trends = {
        "basis": "layer53 member medians at threshold 150; regressors [1, log P, log v]; member bootstrap",
        "log_H": member_trend(log_p, log_v, [math.log(entry["median_H_150_um"]) for entry in production], rng=rng),
        "log_W": member_trend(log_p, log_v, [math.log(entry["median_W_150_um"]) for entry in production], rng=rng),
        "log_HW": member_trend(log_p, log_v, [math.log(entry["median_HW_150"]) for entry in production], rng=rng),
        "rosenthal_liquid_pool_reference": {"log_H": {"P": 1.0, "v": 0.0}, "log_W": {"P": 0.5, "v": -0.5}, "log_HW": {"P": 0.5, "v": 0.5}},
    }
    direction = direction_test(entries)
    verdict = evaluate_step0_reading(
        [{"member_identity": e["member_identity"], "summary": e, "family": e["family"]} for e in production],
        speed_slope_ci95=trends["log_HW"]["slope_log_speed_ci95"],
        direction=direction,
        all_wings=[entry["wing_max_fraction"] for entry in entries],
    )

    summary_rows = [{key: value for key, value in entry.items() if key not in ("family", "profiles")} for entry in entries]
    family_rows = [
        {"member_identity": entry["member_identity"], "layer": entry["layer"], "condition_id": entry["condition_id"], **item}
        for entry in entries
        for item in entry["family"]
    ]
    for row in family_rows:
        ci = row.pop("median_HW_non_edge_ci95", None)
        row["median_HW_non_edge_ci95_lo"] = ci[0] if ci else None
        row["median_HW_non_edge_ci95_hi"] = ci[1] if ci else None
    _write_csv(output / "step0_member_layer_summary.csv", summary_rows)
    _write_csv(output / "step0_threshold_family.csv", family_rows)
    _write_csv(output / "step0_frames.csv.gz", frame_rows_out, compress=True)
    _write_json(output / "step0_profiles.json", {f"{e['member_identity']}|{e['layer']}": e["profiles"] for e in entries})
    _write_json(output / "step0_trends.json", trends)
    _write_json(output / "step0_direction_test.json", direction)
    _write_json(output / "step0_verdict.json", verdict)
    manifest = {
        "schema": SCHEMA,
        "patch_version": PATCH_VERSION,
        "step": STEP_ID,
        "git_commit": _git("rev-parse", "HEAD"),
        "git_worktree_dirty": bool(_git("status", "--porcelain")),
        "plan_sha256": _sha256(PLAN_PATH) if PLAN_PATH.is_file() else "unavailable",
        "module_sha256": _sha256(Path(__file__)),
        "members": list(identities),
        "member_sha256": {identity: member_map[identity].sha256 for identity in identities},
        "layers": list(LAYERS),
        "scored_frame_rule_version": SCORED_FRAME_RULE_VERSION,
        "frame_cross_checks": cross_checks,
        "thresholds": list(THRESHOLDS),
        "pixel_size_um": PIXEL_SIZE_UM,
        "bootstrap": {"replicates": BOOTSTRAP_REPLICATES, "seed": BOOTSTRAP_SEED},
        "runtime": {"python": sys.version.split()[0], "numpy": np.__version__, "opencv": cv2.__version__, "h5py": h5py.__version__, "platform": platform.platform()},
        "guardrails": {
            "held_out_members_opened_for_images": False,
            "other_coupon_frames_read": False,
            "thermal_simulation_performed": False,
            "parameter_fitting_performed": False,
            "parameter_selection_performed": False,
            "full_campaign_dispatched": False,
            "production_semantics_changed": False,
        },
        "verdict": verdict["verdict"],
    }
    _write_json(output / "step0_manifest.json", manifest)
    return {"manifest": manifest, "verdict": verdict, "trends": trends, "direction": direction, "entries": summary_rows}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Patch 22.3.8 Step 0: camera-side characterization (calibration members only)")
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--characterization-dir", required=True)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIRECTORY)
    parser.add_argument("--members", nargs="*", default=None, help="calibration member identities, e.g. 20260730:part_1")
    args = parser.parse_args(argv)
    result = run_step0(
        data_directory=args.data_dir,
        characterization_directory=args.characterization_dir,
        output_directory=args.output_dir,
        members=args.members,
    )
    print(json.dumps(_clean(result["verdict"]), indent=2, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
