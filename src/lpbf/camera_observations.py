"""Camera-side observations: reading the coaxial camera's frames and measuring the thresholded blob.

``measure_blob`` applies the camera's documented H/W convention (``>= threshold``, largest 8-connected component,
external contour, ``minAreaRect``; H the long side, W the short side). ``scored_frame_rows`` selects a coupon's scored
frames on the camera side (synchronized, laser-on, eligible, then the scored-frame rule). No thermal model is run here.

Every coupon file's ``gige_image`` holds the whole layer (all six parts), so frames are reached only through the
member's own ``sync/gige_image_to_data_index``; frames of other coupons are never read.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import cv2
import h5py
import numpy as np

from lpbf.calibration_contract import load_patch21_0_contract, member_identity
from lpbf.configuration import CAMERA_LAYER, CAMERA_SATURATION_LEVEL, CAMERA_THRESHOLD
from lpbf.scored_frame_rule import apply_scored_frame_rule

PRODUCTION_LAYER = CAMERA_LAYER
PRODUCTION_THRESHOLD = CAMERA_THRESHOLD
SATURATION_LEVEL = CAMERA_SATURATION_LEVEL
SCAN_HALF_WINDOW_ROWS = 4
BOOTSTRAP_REPLICATES = 2000
BOOTSTRAP_SEED = 22038


class Step0Error(RuntimeError):
    """Fail-closed error of the camera-side observation code."""


# ---------------------------------------------------------------------- members


def _partition() -> Mapping[str, Any]:
    return load_patch21_0_contract()["data_partition"]


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


# ---------------------------------------------------------------------- statistics


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


# ---------------------------------------------------------------------- across members


# ---------------------------------------------------------------------- runner

