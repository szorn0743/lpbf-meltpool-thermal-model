"""Patch 22.3.8 Step 3: synthetic camera, camera-free physics and a level-free check on the captured fields.

Offline analysis of the Step-2 field files (``patch22_3_8_field_capture``) against the Step-0 per-frame camera
measurements of the same frames. It runs no thermal model, changes no production code or semantics, never opens a
held-out member and adopts no parameter: the brightness scale ``T150`` is scanned over a predeclared grid and never
selected. The predeclared reading (P, S with M1-M5, L) is in ``docs/patches/22.3.8/PATCH_22_3_8_PLAN.md``; it was
approved by the owner before any Step-2 data was opened.

Synthetic camera, per frame and case:
1. bilinear interpolation of the 99 x 99 top-surface field to 4 um sub-samples laid out on the camera's pixel grid
   (mirrored machine-to-image mapping fitted in Step 0, beam at a pixel centre);
2. in-band radiance ``eps(T) * B_lambda(T)`` and the 2 x 2 sub-sample mean (8 um pixels);
3. a Gaussian PSF of ``sigma`` pixels on the radiance image;
4. counts ``150 * R / (eps(T150) * B_lambda(T150))``, i.e. threshold ``t`` is the radiance level
   ``t * eps(T150) * B_lambda(T150) / 150`` and saturation is the ``255`` level;
5. the camera's 64 x 24 crop placed so that the synthetic threshold-150 centroid sits at that frame's camera
   centroid, then the camera convention (``>=`` level, largest 8-connected component, external contour,
   ``minAreaRect``; H the long side, W the short side).
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import math
import platform
import subprocess
import sys
import warnings
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import cv2
import numpy as np

from lpbf.execution.parallel import execute_parallel_jobs
from lpbf.execution.work_units import SimulationJob, SimulationResult, execute_serial_jobs
from lpbf.hierarchical_objective import PIXEL_SIZE_UM
from lpbf.patch22_3_8_camera_step0 import (
    BOOTSTRAP_REPLICATES,
    BOOTSTRAP_SEED,
    PRODUCTION_LAYER,
    SATURATION_LEVEL,
    _condition_records,
    calibration_member_identities,
    member_trend,
    require_calibration_members,
)

PATCH_VERSION = "22.3.8"
STEP_ID = "step3_synthetic_camera"
SCHEMA = "lpbf_patch22_3_8_step3_synthetic_camera"
REPO_ROOT = Path(__file__).resolve().parents[2]
PLAN_PATH = REPO_ROOT / "docs" / "patches" / "22.3.8" / "PATCH_22_3_8_PLAN.md"
STEP0_EVIDENCE = REPO_ROOT / "docs" / "patches" / "22.3.8" / "evidence" / "step0"
DIRECTION_TEST_JSON = STEP0_EVIDENCE / "step0_direction_test.json"
STEP0_TRENDS_JSON = STEP0_EVIDENCE / "step0_trends.json"
STEP0_SUMMARY_CSV = STEP0_EVIDENCE / "step0_member_layer_summary.csv"
CAPTURE_MANIFEST_NAME = "field_capture_manifest.json"
CAPTURE_GATE_NAME = "field_capture_gate.json"
CAPTURE_GATE_PASS = "PASS_PATCH_22_3_8_FIELD_CAPTURE_GATE"
DEFAULT_CAPTURE_DIRECTORY = "patch22_3_8_capture_output/step2"
DEFAULT_CAMERA_FRAMES = "patch22_3_8_step0_output/step0_frames.csv.gz"
DEFAULT_OUTPUT_DIRECTORY = "patch22_3_8_step3_output"
DEFAULT_WORKERS = 4

PRIMARY_CANDIDATE = "anchor_center"
CORNER_CANDIDATES = ("anchor_t_min", "anchor_center", "anchor_t_max")
CORNER_MEMBERS = ("20260904:part_1", "20260904:part_3", "20260904:part_4", "20260904:part_6")

# Predeclared scan and sensitivity cases.
T150_GRID_K = tuple(float(value) for value in range(1400, 3201, 25))
WAVELENGTHS_NM = (750.0, 850.0, 950.0)
EMISSIVITY_MODELS = ("uniform", "liquid_half")
PSF_SIGMAS_PX = (0.0, 1.0, 2.0, 2.6)
LIQUID_TO_SOLID_EMISSIVITY = 0.5

# Predeclared match criteria.
MATCH_THRESHOLDS = (60, 100, 150, 200, 250)
REFERENCE_THRESHOLD = 150
M1_RANGE = (0.87, 1.15)
M2_RANGE = (0.8, 1.25)
M2_MEMBER_FRACTION = 0.75  # 12 of 16 members; 3 of 4 on the corners
M3_THRESHOLDS = (60, 250)
M3_RANGE = (0.8, 1.25)
M4_TOLERANCE = 0.15
COVERAGE_FLOOR = 0.95  # implementation clarification: A23's floor applied to the synthetic observable
BOILING_K = 3133.0

# Rendering and measurement.
CAMERA_ROWS, CAMERA_COLS = 24, 64
RENDER_HALF_PX = 96  # 192 x 192 px: the crop fits for hot-zone centroids up to ~400 um behind the beam
SUBSAMPLES = 2
PSF_TRUNCATE = 4.0
SECOND_RADIATION_CONSTANT_UM_K = 14387.768775
LEVEL_FREE_FLOOR_K = 800.0
LEVEL_FREE_ITERATIONS = 30

READING_A = "R_A_SYNTHETIC_CAMERA_REPRODUCES_CAMERA"
READING_B = "R_B_MODEL_HOT_ZONE_TOO_ELONGATED_STOP_AND_RECONSIDER"
READING_C = "R_C_PARTIAL_MATCH"


class Step3Error(RuntimeError):
    """Fail-closed error for the Step-3 analysis."""


def synthetic_cases() -> tuple[dict[str, Any], ...]:
    """The 24 predeclared cases, ordered wavelength -> emissivity -> PSF (the order they are computed in)."""

    return tuple(
        {
            "case_id": f"lam{int(wavelength)}_{emissivity}_sig{sigma:.1f}",
            "wavelength_nm": float(wavelength),
            "emissivity": emissivity,
            "sigma_px": float(sigma),
        }
        for wavelength in WAVELENGTHS_NM
        for emissivity in EMISSIVITY_MODELS
        for sigma in PSF_SIGMAS_PX
    )


def select_cases(case_ids: Sequence[str] | None = None) -> tuple[dict[str, Any], ...]:
    """The predeclared cases, or the listed subset, always in the canonical computation order."""

    cases = synthetic_cases()
    if case_ids is None:
        return cases
    wanted = [str(case_id) for case_id in case_ids]
    known = {case["case_id"] for case in cases}
    unknown = sorted(set(wanted) - known)
    if unknown or len(set(wanted)) != len(wanted) or not wanted:
        raise Step3Error(f"invalid case subset {wanted!r} (unknown: {unknown})")
    return tuple(case for case in cases if case["case_id"] in set(wanted))


# ---------------------------------------------------------------------- radiometry


def planck_relative(temperature_K: Any, wavelength_nm: float) -> np.ndarray:
    """Planck spectral radiance up to a wavelength-only factor: ``1 / (exp(c2 / (lambda T)) - 1)``."""

    temperature = np.asarray(temperature_K, dtype=np.float64)
    x = SECOND_RADIATION_CONSTANT_UM_K / (float(wavelength_nm) * 1.0e-3 * temperature)
    with np.errstate(over="ignore"):
        return 1.0 / np.expm1(x)


def emissivity(temperature_K: Any, model: str, liquidus_K: float) -> np.ndarray:
    temperature = np.asarray(temperature_K, dtype=np.float64)
    if model == "uniform":
        return np.ones_like(temperature)
    if model == "liquid_half":
        return np.where(temperature >= float(liquidus_K), LIQUID_TO_SOLID_EMISSIVITY, 1.0)
    raise Step3Error(f"unknown emissivity model {model!r}")


def count_level_unit(t150_K: Any, *, wavelength_nm: float, emissivity_model: str, liquidus_K: float) -> np.ndarray:
    """Radiance per camera count: the radiance of a uniform surface at ``T150`` reads 150 counts."""

    t150 = np.asarray(t150_K, dtype=np.float64)
    return emissivity(t150, emissivity_model, liquidus_K) * planck_relative(t150, wavelength_nm) / REFERENCE_THRESHOLD


# ---------------------------------------------------------------------- geometry


def load_image_mapping(path: Path | None = None) -> dict[str, Any]:
    """Step-0 machine-to-image mapping, with its full-circle sign fixed by the wake.

    Step 0 fitted an axial (mod 180) mirrored mapping ``image angle = c - machine angle`` on the blob axes. The
    trailing wake lies opposite the motion, so the sign of ``c`` is the one that puts the wake at about 180 deg from
    the mapped motion direction.
    """

    path = Path(path or DIRECTION_TEST_JSON)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("mapping") != "mirrored":
        raise Step3Error(f"Step-0 mapping is {payload.get('mapping')!r}, expected 'mirrored'")
    constant = float(payload["axis_mapping_constant_deg"])
    wake_offset = float(payload["pooled_wing_follow_mean_offset_deg"])
    flipped = math.cos(math.radians(wake_offset)) > 0.0
    return {
        "mapping": "mirrored",
        "axial_constant_deg": constant,
        "wake_offset_from_mapped_motion_deg": wake_offset,
        "full_circle_constant_deg": (constant + 180.0) % 360.0 if flipped else constant,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def image_to_machine_matrix(constant_deg: float) -> np.ndarray:
    """Mirrored mapping: an image direction at angle ``a`` (x right, y down) is the machine direction ``c - a``."""

    c = math.radians(float(constant_deg))
    return np.array([[math.cos(c), math.sin(c)], [math.sin(c), -math.cos(c)]], dtype=np.float64)


def subsample_offsets_um(
    constant_deg: float, *, half_px: int = RENDER_HALF_PX, subsamples: int = SUBSAMPLES, pixel_um: float = PIXEL_SIZE_UM
) -> tuple[np.ndarray, np.ndarray]:
    """Machine-frame offsets (um) from the beam of the sub-samples of a ``2*half_px`` square image.

    Pixel ``(row v, col u)`` is centred ``(u - half_px, v - half_px)`` pixels from the beam; its sub-samples sit at
    ``+-1/(2*subsamples)`` pixel around that centre.
    """

    n = 2 * int(half_px) * int(subsamples)
    steps = ((np.arange(n, dtype=np.float64) + 0.5) / subsamples - 0.5 - half_px) * float(pixel_um)
    du, dv = np.meshgrid(steps, steps)
    matrix = image_to_machine_matrix(constant_deg)
    return matrix[0, 0] * du + matrix[0, 1] * dv, matrix[1, 0] * du + matrix[1, 1] * dv


def bilinear_field(field: np.ndarray, fi: np.ndarray, fj: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Bilinear samples of ``field[i, j]`` at fractional indices, clamped at the border, plus an inside mask."""

    field = np.asarray(field, dtype=np.float64)
    n_i, n_j = field.shape
    inside = (fi >= 0.0) & (fi <= n_i - 1.0) & (fj >= 0.0) & (fj <= n_j - 1.0)
    fi = np.clip(fi, 0.0, n_i - 1.0)
    fj = np.clip(fj, 0.0, n_j - 1.0)
    i0 = np.minimum(np.floor(fi).astype(np.int64), n_i - 2)
    j0 = np.minimum(np.floor(fj).astype(np.int64), n_j - 2)
    ti, tj = fi - i0, fj - j0
    value = (
        (1.0 - ti) * (1.0 - tj) * field[i0, j0]
        + ti * (1.0 - tj) * field[i0 + 1, j0]
        + (1.0 - ti) * tj * field[i0, j0 + 1]
        + ti * tj * field[i0 + 1, j0 + 1]
    )
    return value, inside


def render_temperature_subsamples(
    field: np.ndarray,
    *,
    source_x_mm: float,
    source_y_mm: float,
    cell_um: float,
    offsets: tuple[np.ndarray, np.ndarray],
) -> tuple[np.ndarray, np.ndarray]:
    """Sub-sample temperatures on the camera grid (beam at the central pixel) and the inside-window mask.

    ``field[i, j]`` is the cell centred at ``((i + 0.5) * cell, (j + 0.5) * cell)`` in the window, x along ``i``.
    """

    dx, dy = offsets
    fi = (float(source_x_mm) * 1000.0 + dx) / float(cell_um) - 0.5
    fj = (float(source_y_mm) * 1000.0 + dy) / float(cell_um) - 0.5
    return bilinear_field(field, fi, fj)


def pixel_mean(values: np.ndarray, subsamples: int = SUBSAMPLES) -> np.ndarray:
    n = values.shape[0] // subsamples
    return values.reshape(n, subsamples, n, subsamples).mean(axis=(1, 3))


def pixel_all(mask: np.ndarray, subsamples: int = SUBSAMPLES) -> np.ndarray:
    n = mask.shape[0] // subsamples
    return mask.reshape(n, subsamples, n, subsamples).all(axis=(1, 3))


def gaussian_psf(image: np.ndarray, sigma_px: float) -> np.ndarray:
    """Separable Gaussian blur (truncated at 4 sigma, zero outside the image); identity for ``sigma <= 0``."""

    image = np.asarray(image, dtype=np.float64)
    if sigma_px <= 0.0:
        return image
    radius = int(math.ceil(PSF_TRUNCATE * float(sigma_px)))
    x = np.arange(-radius, radius + 1, dtype=np.float64)
    kernel = np.exp(-0.5 * (x / float(sigma_px)) ** 2)
    kernel /= kernel.sum()
    return cv2.sepFilter2D(image, cv2.CV_64F, kernel, kernel, borderType=cv2.BORDER_CONSTANT)


# ---------------------------------------------------------------------- camera-convention measurement


def measure_component(mask: np.ndarray) -> dict[str, Any] | None:
    """Camera convention on a binary mask: largest 8-connected component, external contour, ``minAreaRect``.

    Same convention as ``patch22_3_8_camera_step0.measure_blob`` (H the long side, W the short side).
    """

    mask = np.ascontiguousarray(mask, dtype=np.uint8)
    count, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if count < 2:
        return None
    index = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    component = labels == index
    contours, _ = cv2.findContours(component.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    points = np.vstack([contour.reshape(-1, 2) for contour in contours]).astype(np.float32)
    (_, _), (side_a, side_b), _ = cv2.minAreaRect(points)
    x0, y0, width, height, area = (int(value) for value in stats[index][:5])
    n_rows, n_cols = mask.shape
    return {
        "H_px": float(max(side_a, side_b)),
        "W_px": float(min(side_a, side_b)),
        "area_px": area,
        "touches_edge": bool(x0 == 0 or y0 == 0 or x0 + width == n_cols or y0 + height == n_rows),
        "centroid_x": float(centroids[index][0]),
        "centroid_y": float(centroids[index][1]),
        "component": component,
    }


def _round_half_up(value: float) -> int:
    return int(math.floor(float(value) + 0.5))


def measure_levels(
    image: np.ndarray,
    inside_px: np.ndarray,
    units: np.ndarray,
    camera_centroid: tuple[float, float],
    out_h: np.ndarray,
    out_w: np.ndarray,
    out_edge: np.ndarray,
    out_sat: np.ndarray,
) -> None:
    """Fill ``(T150, threshold)`` measurements for one radiance image (NaN where the synthetic camera sees nothing).

    For each ``T150`` the camera crop is placed so that the threshold-150 centroid of the full render sits at the
    frame's camera centroid; all thresholds are then measured inside that crop. A blob touching the crop edge or
    containing a pixel sampled outside the model window is flagged as edge (excluded, as camera edge frames are).
    """

    peak = float(image.max())
    n_rows, n_cols = image.shape
    cam_x, cam_y = camera_centroid
    for k, unit in enumerate(np.asarray(units, dtype=np.float64)):
        if peak < REFERENCE_THRESHOLD * unit:
            continue
        reference = measure_component(image >= REFERENCE_THRESHOLD * unit)
        if reference is None:
            continue
        ox = _round_half_up(reference["centroid_x"] - cam_x)
        oy = _round_half_up(reference["centroid_y"] - cam_y)
        if ox < 0 or oy < 0 or ox + CAMERA_COLS > n_cols or oy + CAMERA_ROWS > n_rows:
            # The crop cannot be placed inside the render: the blob exists but would be truncated (edge).
            for t, threshold in enumerate(MATCH_THRESHOLDS):
                blob = measure_component(image >= threshold * unit)
                if blob is not None:
                    out_h[k, t], out_w[k, t], out_edge[k, t] = blob["H_px"], blob["W_px"], True
            continue
        crop = image[oy : oy + CAMERA_ROWS, ox : ox + CAMERA_COLS]
        crop_inside = inside_px[oy : oy + CAMERA_ROWS, ox : ox + CAMERA_COLS]
        crop_peak = float(crop.max())
        for t, threshold in enumerate(MATCH_THRESHOLDS):
            level = threshold * unit
            if crop_peak < level:
                continue
            blob = measure_component(crop >= level)
            if blob is None:
                continue
            out_h[k, t] = blob["H_px"]
            out_w[k, t] = blob["W_px"]
            out_edge[k, t] = bool(blob["touches_edge"] or not bool(crop_inside[blob["component"]].all()))
            if threshold == REFERENCE_THRESHOLD:
                saturated = np.count_nonzero(crop[blob["component"]] >= SATURATION_LEVEL * unit)
                out_sat[k] = saturated / blob["area_px"]


def synthesize_frame(
    t_sub: np.ndarray,
    inside_sub: np.ndarray,
    *,
    liquidus_K: float,
    camera_centroid: tuple[float, float],
    t150_grid: Sequence[float] = T150_GRID_K,
    case_ids: Sequence[str] | None = None,
) -> dict[str, np.ndarray]:
    """Predeclared cases (all, or a subset) for one frame: arrays ``(case, T150, threshold)`` of H, W and edge flags."""

    cases = select_cases(case_ids)
    wanted = {(case["wavelength_nm"], case["emissivity"], case["sigma_px"]) for case in cases}
    grid = np.asarray(t150_grid, dtype=np.float64)
    shape = (len(cases), grid.size, len(MATCH_THRESHOLDS))
    out = {
        "H": np.full(shape, np.nan, dtype=np.float32),
        "W": np.full(shape, np.nan, dtype=np.float32),
        "edge": np.zeros(shape, dtype=bool),
        "sat": np.full(shape[:2], np.nan, dtype=np.float32),
    }
    inside_px = pixel_all(inside_sub)
    index = 0
    for wavelength in WAVELENGTHS_NM:
        if not any(key[0] == wavelength for key in wanted):
            continue
        radiance_sub = planck_relative(t_sub, wavelength)
        for model in EMISSIVITY_MODELS:
            if not any(key[:2] == (wavelength, model) for key in wanted):
                continue
            radiance = pixel_mean(radiance_sub * emissivity(t_sub, model, liquidus_K))
            units = count_level_unit(grid, wavelength_nm=wavelength, emissivity_model=model, liquidus_K=liquidus_K)
            for sigma in PSF_SIGMAS_PX:
                if (wavelength, model, sigma) not in wanted:
                    continue
                case = cases[index]
                if (case["wavelength_nm"], case["emissivity"], case["sigma_px"]) != (wavelength, model, sigma):
                    raise Step3Error("case order does not match the computation order")
                measure_levels(
                    gaussian_psf(radiance, sigma),
                    inside_px,
                    units,
                    camera_centroid,
                    out["H"][index],
                    out["W"][index],
                    out["edge"][index],
                    out["sat"][index],
                )
                index += 1
    return out


def level_free_crossing(
    t_image: np.ndarray,
    inside_px: np.ndarray,
    target_w_px: float,
    *,
    floor_K: float = LEVEL_FREE_FLOOR_K,
    iterations: int = LEVEL_FREE_ITERATIONS,
) -> dict[str, Any]:
    """Highest isotherm whose camera-convention W reaches ``target_w_px`` (bisection; no free scalar)."""

    def at(level: float) -> dict[str, Any] | None:
        return measure_component(t_image >= level)

    low = at(floor_K)
    if low is None or low["W_px"] < target_w_px:
        return {"status": "CAMERA_WIDER_THAN_MODEL_AT_FLOOR"}
    lo, hi = float(floor_K), float(t_image.max())
    top = at(hi)
    if top is not None and top["W_px"] >= target_w_px:
        return {"status": "MODEL_PEAK_WIDER_THAN_CAMERA"}
    for _ in range(int(iterations)):
        mid = 0.5 * (lo + hi)
        blob = at(mid)
        if blob is not None and blob["W_px"] >= target_w_px:
            lo = mid
        else:
            hi = mid
    blob = at(lo)
    if blob["touches_edge"] or not bool(inside_px[blob["component"]].all()):
        return {"status": "ISOTHERM_TOUCHES_RENDER_EDGE"}
    return {"status": "DEFINED", "level_K": lo, "H_px": blob["H_px"], "W_px": blob["W_px"]}


# ---------------------------------------------------------------------- per-member aggregation


def _quiet_nanmedian(values: np.ndarray, axis: int = 0) -> np.ndarray:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        return np.nanmedian(values, axis=axis)


def _ratio(numerator: Any, denominator: Any) -> np.ndarray:
    numerator = np.asarray(numerator, dtype=np.float64)
    denominator = np.asarray(denominator, dtype=np.float64)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(denominator > 0.0, numerator / np.where(denominator > 0.0, denominator, 1.0), np.nan)


def aggregate_member(synthetic: Mapping[str, np.ndarray], camera: Mapping[str, np.ndarray]) -> dict[str, np.ndarray]:
    """Member-level medians over paired frames.

    ``synthetic``: frame-stacked ``H``, ``W``, ``edge`` (frame, case, T150, threshold) and ``sat`` (frame, case,
    T150). ``camera``: ``H``, ``W``, ``valid`` (frame, threshold) and ``sat`` (frame,). A frame is paired at a
    threshold when the camera blob exists without touching the crop edge and the synthetic blob exists without
    touching an edge. Member ratios are later formed as ratios of these member medians. Thresholds are processed
    one at a time to bound memory.
    """

    h_all, w_all, edge_all = synthetic["H"], synthetic["W"], synthetic["edge"]
    n_frames, n_cases, n_grid, n_thresholds = h_all.shape
    cam_valid_all = np.asarray(camera["valid"], dtype=bool)
    keys = ("paired", "synthetic_edge", "synthetic_absent", "model_H", "model_W", "model_HW", "camera_H", "camera_W", "camera_HW")
    out: dict[str, np.ndarray] = {key: np.empty((n_cases, n_grid, n_thresholds)) for key in keys}
    w_ratio = np.full((n_frames, n_cases, n_grid, len(M3_THRESHOLDS)), np.nan, dtype=np.float32)
    nan = np.nan
    for t, threshold in enumerate(MATCH_THRESHOLDS):
        h = np.asarray(h_all[..., t], dtype=np.float64)
        w = np.asarray(w_all[..., t], dtype=np.float64)
        edge = np.asarray(edge_all[..., t], dtype=bool)
        cam_h = np.asarray(camera["H"], dtype=np.float64)[:, t][:, None, None]
        cam_w = np.asarray(camera["W"], dtype=np.float64)[:, t][:, None, None]
        cam_valid = cam_valid_all[:, t][:, None, None]
        exists = np.isfinite(h) & np.isfinite(w)
        paired = cam_valid & exists & ~edge
        out["paired"][..., t] = paired.sum(axis=0)
        out["synthetic_edge"][..., t] = (cam_valid & exists & edge).sum(axis=0)
        out["synthetic_absent"][..., t] = (cam_valid & ~exists).sum(axis=0)
        out["model_H"][..., t] = _quiet_nanmedian(np.where(paired, h, nan))
        out["model_W"][..., t] = _quiet_nanmedian(np.where(paired, w, nan))
        out["model_HW"][..., t] = _quiet_nanmedian(np.where(paired, _ratio(h, w), nan))
        out["camera_H"][..., t] = _quiet_nanmedian(np.where(paired, cam_h, nan))
        out["camera_W"][..., t] = _quiet_nanmedian(np.where(paired, cam_w, nan))
        out["camera_HW"][..., t] = _quiet_nanmedian(np.where(paired, _ratio(cam_h, cam_w), nan))
        if threshold in M3_THRESHOLDS:
            ratio = _ratio(w, np.broadcast_to(cam_w, w.shape))
            w_ratio[..., M3_THRESHOLDS.index(threshold)] = np.where(paired, ratio, nan)
        if threshold == REFERENCE_THRESHOLD:
            sat = np.asarray(synthetic["sat"], dtype=np.float64)
            cam_sat = np.asarray(camera["sat"], dtype=np.float64)[:, None, None]
            out["model_sat"] = _quiet_nanmedian(np.where(paired, sat, nan))
            out["camera_sat"] = _quiet_nanmedian(np.where(paired, np.broadcast_to(cam_sat, sat.shape), nan))
    out["frames"] = np.asarray(n_frames)
    out["camera_valid"] = cam_valid_all.sum(axis=0)
    out["w_ratio_m3"] = w_ratio
    return out


# ---------------------------------------------------------------------- camera table


def _as_bool(text: str) -> bool:
    if text in ("True", "true", "1"):
        return True
    if text in ("False", "false", "0", ""):
        return False
    raise Step3Error(f"not a boolean: {text!r}")


def _as_float(text: str) -> float:
    return float("nan") if text in ("", "nan", "None") else float(text)


def load_camera_frames(path: str | Path, members: Sequence[str]) -> dict[str, dict[str, list[Any]]]:
    """Per-member layer-53 camera measurements from the Step-0 frame table (flat lists, frame order)."""

    wanted = set(members)
    table: dict[str, dict[str, list[Any]]] = {}
    with gzip.open(Path(path), "rt", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row["layer"] != PRODUCTION_LAYER or row["member_identity"] not in wanted:
                continue
            entry = table.get(row["member_identity"])
            if entry is None:
                entry = {"frame_index": [], "centroid_x": [], "centroid_y": [], "sat": [], "has_blob_150": []}
                entry.update({f"{key}_{t}": [] for t in MATCH_THRESHOLDS for key in ("H", "W", "edge")})
                table[row["member_identity"]] = entry
            entry["frame_index"].append(int(row["frame_index"]))
            entry["centroid_x"].append(_as_float(row["centroid_x"]))
            entry["centroid_y"].append(_as_float(row["centroid_y"]))
            entry["sat"].append(_as_float(row["saturated_fraction_150"]))
            entry["has_blob_150"].append(_as_bool(row["has_blob_150"]))
            for t in MATCH_THRESHOLDS:
                entry[f"H_{t}"].append(_as_float(row[f"H_{t}"]))
                entry[f"W_{t}"].append(_as_float(row[f"W_{t}"]))
                entry[f"edge_{t}"].append(_as_bool(row[f"edge_{t}"]))
    missing = sorted(wanted - set(table))
    if missing:
        raise Step3Error(f"camera frame table has no layer-53 rows for {missing}")
    return table


def check_camera_against_step0_evidence(
    table: Mapping[str, Mapping[str, list[Any]]], summary_csv: Path | None = None
) -> list[dict[str, Any]]:
    """The frame table must reproduce the committed Step-0 member summaries (frames, median H/W at 150)."""

    with Path(summary_csv or STEP0_SUMMARY_CSV).open(encoding="utf-8", newline="") as handle:
        rows = {r["member_identity"]: r for r in csv.DictReader(handle) if r["layer"] == PRODUCTION_LAYER}
    checks = []
    for member, entry in sorted(table.items()):
        reference = rows.get(member)
        if reference is None:
            raise Step3Error(f"Step-0 evidence has no layer-53 summary for {member}")
        bearing = np.asarray(entry["has_blob_150"], dtype=bool)
        h = np.asarray(entry["H_150"], dtype=np.float64)[bearing]
        w = np.asarray(entry["W_150"], dtype=np.float64)[bearing]
        values = {
            "scored_frames": (len(entry["frame_index"]), int(reference["scored_frames"])),
            "median_H_150_um": (float(np.median(h)) * PIXEL_SIZE_UM, float(reference["median_H_150_um"])),
            "median_W_150_um": (float(np.median(w)) * PIXEL_SIZE_UM, float(reference["median_W_150_um"])),
        }
        ok = values["scored_frames"][0] == values["scored_frames"][1] and all(
            math.isclose(a, b, rel_tol=0.0, abs_tol=1e-9) for key, (a, b) in values.items() if key != "scored_frames"
        )
        if not ok:
            raise Step3Error(f"camera frame table disagrees with the committed Step-0 summary for {member}: {values}")
        checks.append({"member_identity": member, "pass": True, **{key: list(pair) for key, pair in values.items()}})
    return checks


def camera_arrays(entry: Mapping[str, Sequence[Any]], order: Sequence[int]) -> dict[str, np.ndarray]:
    idx = np.asarray(order, dtype=np.int64)
    h = np.column_stack([np.asarray(entry[f"H_{t}"], dtype=np.float64)[idx] for t in MATCH_THRESHOLDS])
    w = np.column_stack([np.asarray(entry[f"W_{t}"], dtype=np.float64)[idx] for t in MATCH_THRESHOLDS])
    edge = np.column_stack([np.asarray(entry[f"edge_{t}"], dtype=bool)[idx] for t in MATCH_THRESHOLDS])
    return {
        "H": h,
        "W": w,
        "valid": np.isfinite(h) & np.isfinite(w) & ~edge,
        "sat": np.asarray(entry["sat"], dtype=np.float64)[idx],
        "centroid_x": np.asarray(entry["centroid_x"], dtype=np.float64)[idx],
        "centroid_y": np.asarray(entry["centroid_y"], dtype=np.float64)[idx],
    }


# ---------------------------------------------------------------------- worker


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _production_records(unit_file: Path) -> dict[int, dict[str, Any]]:
    payload = json.loads(Path(unit_file).read_text(encoding="utf-8"))
    return {int(record["frame_index"]): record for record in payload["frame_records"] if record.get("scored_frame")}


def analyse_unit(
    arrays: Mapping[str, np.ndarray],
    camera_entry: Mapping[str, Sequence[Any]],
    production: Mapping[int, Mapping[str, Any]],
    *,
    mapping_constant_deg: float,
    t150_grid: Sequence[float] = T150_GRID_K,
    case_ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Synthetic camera, physics and level-free measures for one unit (pure; no file access)."""

    frames = np.asarray(arrays["frame_index"], dtype=np.int64)
    camera_position = {int(frame): k for k, frame in enumerate(camera_entry["frame_index"])}
    if len(camera_position) != len(camera_entry["frame_index"]):
        raise Step3Error("camera frame table has duplicate frames")
    captured = [int(f) for f in frames]
    if len(set(captured)) != len(captured) or set(captured) != set(camera_position):
        raise Step3Error("captured frames differ from the camera's scored frames")
    if set(captured) != set(production):
        raise Step3Error("captured frames differ from the unit's scored frame records")
    camera = camera_arrays(camera_entry, [camera_position[f] for f in captured])
    fields = np.asarray(arrays["top_surface_temperature_K"], dtype=np.float64)
    status = [str(value) for value in np.asarray(arrays["production_status"])]
    for frame, value in zip(captured, status):
        if str(production[frame].get("production_status")) != value:
            raise Step3Error(f"frame {frame}: captured production status {value!r} differs from the unit record")
    liquidus = float(arrays["liquidus_temperature_K"])
    cell_um = float(arrays["cell_size_um"])
    offsets = subsample_offsets_um(mapping_constant_deg)
    default_centroid = (float(np.nanmedian(camera["centroid_x"])), float(np.nanmedian(camera["centroid_y"])))
    ref = MATCH_THRESHOLDS.index(REFERENCE_THRESHOLD)

    stacked: dict[str, list[np.ndarray]] = {"H": [], "W": [], "edge": [], "sat": []}
    level_free: list[dict[str, Any]] = []
    peaks = np.empty(frames.size, dtype=np.float64)
    for f, frame in enumerate(captured):
        t_sub, inside_sub = render_temperature_subsamples(
            fields[f],
            source_x_mm=float(arrays["source_center_x_mm"][f]),
            source_y_mm=float(arrays["source_center_y_mm"][f]),
            cell_um=cell_um,
            offsets=offsets,
        )
        cx, cy = float(camera["centroid_x"][f]), float(camera["centroid_y"][f])
        centroid = (cx, cy) if math.isfinite(cx) and math.isfinite(cy) else default_centroid
        frame_out = synthesize_frame(
            t_sub, inside_sub, liquidus_K=liquidus, camera_centroid=centroid, t150_grid=t150_grid, case_ids=case_ids
        )
        for key in stacked:
            stacked[key].append(frame_out[key])
        peaks[f] = float(fields[f].max())
        if bool(camera["valid"][f, ref]):
            crossing = level_free_crossing(pixel_mean(t_sub), pixel_all(inside_sub), float(camera["W"][f, ref]))
            crossing["frame_index"] = frame
            if crossing["status"] == "DEFINED":
                crossing["camera_H_px"] = float(camera["H"][f, ref])
                crossing["camera_W_px"] = float(camera["W"][f, ref])
                crossing["H_ratio"] = crossing["H_px"] / crossing["camera_H_px"]
            level_free.append(crossing)

    synthetic = {key: np.stack(values) for key, values in stacked.items()}
    aggregate = aggregate_member(synthetic, camera)

    selected = [production[f] for f in captured if str(production[f].get("production_status")) == "SELECTED"]
    sim_h = np.array([float(r["simulated_H_pixels"]) for r in selected], dtype=np.float64)
    sim_w = np.array([float(r["simulated_W_pixels"]) for r in selected], dtype=np.float64)
    status_counts: dict[str, int] = {}
    for value in status:
        status_counts[value] = status_counts.get(value, 0) + 1
    physics = {
        "scored_frames": int(frames.size),
        "production_status_counts": dict(sorted(status_counts.items())),
        "selected_frames": int(sim_h.size),
        "median_liquidus_H_px": float(np.median(sim_h)) if sim_h.size else float("nan"),
        "median_liquidus_W_px": float(np.median(sim_w)) if sim_w.size else float("nan"),
        "median_liquidus_HW": float(np.median(_ratio(sim_h, sim_w))) if sim_h.size else float("nan"),
        "median_peak_K": float(np.median(peaks)),
        "p95_peak_K": float(np.percentile(peaks, 95)),
        "fraction_peak_above_boiling": float(np.mean(peaks > BOILING_K)),
        "liquidus_K": liquidus,
    }
    return {"aggregate": aggregate, "physics": physics, "level_free": level_free}


def _step3_unit_job(job: SimulationJob) -> dict[str, Any]:
    """Spawn-safe worker: reads one unit's field file and unit record, writes nothing."""

    context = job.experiment_context_dict
    field_file = Path(context["field_file"])
    if _sha256(field_file) != context["field_sha256"]:
        raise Step3Error(f"field file hash differs from the Step-2 manifest: {field_file}")
    with np.load(field_file, allow_pickle=False) as handle:
        arrays = {key: handle[key] for key in handle.files}
    result = analyse_unit(
        arrays,
        context["camera"],
        _production_records(Path(context["unit_file"])),
        mapping_constant_deg=float(context["mapping_constant_deg"]),
        t150_grid=tuple(float(v) for v in context["t150_grid"]),
        case_ids=context.get("case_ids"),
    )
    result.update({"candidate_id": context["candidate_id"], "member_identity": job.member_identity})
    return result


# ---------------------------------------------------------------------- criteria across members


def bootstrap_design(log_power: Sequence[float], log_speed: Sequence[float], *, seed: int = BOOTSTRAP_SEED) -> dict[str, np.ndarray]:
    """Member-resampling bootstrap of OLS on ``[1, log P, log v]`` with the draws of ``member_trend``."""

    lp, lv = np.asarray(log_power, dtype=np.float64), np.asarray(log_speed, dtype=np.float64)
    design = np.column_stack([np.ones_like(lp), lp, lv])
    rng = np.random.default_rng(seed)
    pinvs, picks = [], []
    for _ in range(BOOTSTRAP_REPLICATES):
        pick = rng.integers(0, lp.size, size=lp.size)
        sample = design[pick]
        if np.linalg.matrix_rank(sample) < 3:
            continue
        pinvs.append(np.linalg.pinv(sample))
        picks.append(pick)
    return {"point": np.linalg.pinv(design), "pinvs": np.stack(pinvs), "picks": np.stack(picks)}


def bootstrap_slopes(design: Mapping[str, np.ndarray], response: np.ndarray) -> dict[str, np.ndarray]:
    """Slopes (log P, log v) and 95 % percentile CIs for responses ``(members, K)``; a non-finite column gives NaN."""

    y = np.asarray(response, dtype=np.float64)
    finite = np.all(np.isfinite(y), axis=0)
    safe = np.where(finite[None, :], y, 0.0)
    point = design["point"] @ safe
    boot = np.einsum("rpn,rnk->rpk", design["pinvs"], safe[design["picks"]])
    lo, hi = np.percentile(boot, [2.5, 97.5], axis=0)
    nan = np.full(point.shape[1], np.nan)
    return {
        "P": np.where(finite, point[1], nan),
        "P_lo": np.where(finite, lo[1], nan),
        "P_hi": np.where(finite, hi[1], nan),
        "v": np.where(finite, point[2], nan),
        "v_lo": np.where(finite, lo[2], nan),
        "v_hi": np.where(finite, hi[2], nan),
    }


def _in(values: Any, bounds: tuple[float, float]) -> np.ndarray:
    values = np.asarray(values, dtype=np.float64)
    with np.errstate(invalid="ignore"):
        return np.isfinite(values) & (values >= bounds[0]) & (values <= bounds[1])


def evaluate_scope(members: Sequence[str], results: Mapping[str, Mapping[str, Any]], *, with_trends: bool) -> dict[str, np.ndarray]:
    """Criteria M1-M5 on every (case, T150) for one set of members of one candidate."""

    aggregates = [results[member]["aggregate"] for member in members]
    keys = ("model_H", "model_W", "model_HW", "camera_H", "camera_W", "camera_HW", "model_sat", "camera_sat", "paired")
    stack = {key: np.stack([np.asarray(a[key], dtype=np.float64) for a in aggregates]) for key in keys}
    camera_valid = np.sum([np.asarray(a["camera_valid"], dtype=np.float64) for a in aggregates], axis=0)
    with np.errstate(divide="ignore", invalid="ignore"):
        coverage = stack["paired"].sum(axis=0) / camera_valid
    coverage_ok = np.isfinite(coverage) & (coverage >= COVERAGE_FLOOR)
    ref = MATCH_THRESHOLDS.index(REFERENCE_THRESHOLD)

    m1_value = np.median(_ratio(stack["model_HW"], stack["camera_HW"]), axis=0)
    m1_pass_t = _in(m1_value, M1_RANGE) & coverage_ok
    ratio_h = _ratio(stack["model_H"][..., ref], stack["camera_H"][..., ref])
    ratio_w = _ratio(stack["model_W"][..., ref], stack["camera_W"][..., ref])
    m2_members = (_in(ratio_h, M2_RANGE) & _in(ratio_w, M2_RANGE)).sum(axis=0)
    m2_required = int(math.ceil(M2_MEMBER_FRACTION * len(members) - 1e-9))
    m2_pass = (m2_members >= m2_required) & coverage_ok[..., ref]
    pooled = np.concatenate([np.asarray(a["w_ratio_m3"], dtype=np.float64) for a in aggregates], axis=0)
    m3_value = _quiet_nanmedian(pooled, axis=0)
    m3_cov = coverage_ok[..., [MATCH_THRESHOLDS.index(t) for t in M3_THRESHOLDS]]
    m3_pass = np.all(_in(m3_value, M3_RANGE) & m3_cov, axis=-1)
    m4_model = np.median(stack["model_sat"], axis=0)
    m4_camera = np.median(stack["camera_sat"], axis=0)
    with np.errstate(invalid="ignore"):
        m4_close = np.abs(m4_model - m4_camera) <= M4_TOLERANCE
    m4_pass = np.isfinite(m4_model) & np.isfinite(m4_camera) & m4_close & coverage_ok[..., ref]
    out: dict[str, np.ndarray] = {
        "coverage": coverage,
        "M1_value": m1_value,
        "M1_pass_threshold": m1_pass_t,
        "M1_pass": np.all(m1_pass_t, axis=-1),
        "M1_150_pass": m1_pass_t[..., ref],
        "M2_members_ok": m2_members,
        "M2_required": np.asarray(m2_required),
        "M2_pass": m2_pass,
        "M3_value": m3_value,
        "M3_pass": m3_pass,
        "M4_model": m4_model,
        "M4_camera": m4_camera,
        "M4_pass": m4_pass,
    }
    out["core_pass"] = out["M1_150_pass"] & m2_pass
    if with_trends:
        records = _condition_records()
        design = bootstrap_design(
            [math.log(records[m]["power_W"]) for m in members], [math.log(records[m]["speed_mm_s"]) for m in members]
        )
        n_cases, n_grid = m1_value.shape[:2]
        m5_pass = np.ones((n_cases, n_grid), dtype=bool)
        for name, model_key, camera_key in (("H", "model_H", "camera_H"), ("W", "model_W", "camera_W")):
            with np.errstate(divide="ignore", invalid="ignore"):
                diff = np.log(stack[model_key][..., ref]) - np.log(stack[camera_key][..., ref])
            slopes = bootstrap_slopes(design, diff.reshape(len(members), -1))
            for key, value in slopes.items():
                out[f"M5_{name}_{key}"] = value.reshape(n_cases, n_grid)
            for regressor in ("P", "v"):
                lo, hi = out[f"M5_{name}_{regressor}_lo"], out[f"M5_{name}_{regressor}_hi"]
                with np.errstate(invalid="ignore"):
                    m5_pass &= np.isfinite(lo) & np.isfinite(hi) & (lo <= 0.0) & (hi >= 0.0)
        out["M5_pass"] = m5_pass & coverage_ok[..., ref]
        out["all_pass"] = out["M1_pass"] & m2_pass & m3_pass & m4_pass & out["M5_pass"]
    return out


def grid_intervals(grid: Sequence[float], passed: np.ndarray, step: float = 25.0) -> list[list[float]]:
    """Contiguous runs of passing grid values as ``[low, high]`` pairs."""

    runs: list[list[float]] = []
    for value, ok in zip(grid, np.asarray(passed, dtype=bool)):
        if not ok:
            continue
        if runs and math.isclose(float(value) - runs[-1][1], step):
            runs[-1][1] = float(value)
        else:
            runs.append([float(value), float(value)])
    return runs


def evaluate_reading(primary: Mapping[str, np.ndarray]) -> str:
    if bool(np.any(primary["all_pass"])):
        return READING_A
    if not bool(np.any(primary["core_pass"])):
        return READING_B
    return READING_C


# ---------------------------------------------------------------------- outputs


def _json_default(value: Any) -> Any:
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.bool_):
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
    plain = json.loads(json.dumps(payload, default=_json_default))
    path.write_text(json.dumps(_clean(plain), indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _csv_cell(value: Any) -> Any:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (float, np.floating)):
        return "" if not math.isfinite(float(value)) else repr(float(value))
    if isinstance(value, np.integer):
        return int(value)
    return "" if value is None else value


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]], *, compress: bool = False) -> None:
    """CSV whose bytes depend only on the rows (gzip header without a timestamp)."""

    if not rows:
        raise Step3Error(f"no rows to write for {path.name}")
    fields = list(rows[0].keys())
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: _csv_cell(row.get(key)) for key in fields})
    data = buffer.getvalue().encode("utf-8")
    if compress:
        with path.open("wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as handle:
            handle.write(data)
    else:
        path.write_bytes(data)


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], capture_output=True, text=True, check=True, cwd=REPO_ROOT).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def _grid_rows(
    scope: str,
    candidate: str,
    members: Sequence[str],
    result: Mapping[str, np.ndarray],
    liquidus: float,
    cases: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    rows = []
    for c, case in enumerate(cases if cases is not None else synthetic_cases()):
        for k, t150 in enumerate(T150_GRID_K):
            row: dict[str, Any] = {
                "scope": scope,
                "candidate_id": candidate,
                "members": len(members),
                "case_id": case["case_id"],
                "wavelength_nm": case["wavelength_nm"],
                "emissivity": case["emissivity"],
                "sigma_px": case["sigma_px"],
                "T150_K": t150,
                "T150_below_liquidus": bool(t150 < liquidus),
            }
            for t, threshold in enumerate(MATCH_THRESHOLDS):
                row[f"coverage_{threshold}"] = float(result["coverage"][c, k, t])
            for t, threshold in enumerate(MATCH_THRESHOLDS):
                row[f"M1_HW_ratio_{threshold}"] = float(result["M1_value"][c, k, t])
            row["M1_pass"] = bool(result["M1_pass"][c, k])
            row["M1_150_pass"] = bool(result["M1_150_pass"][c, k])
            row["M2_members_ok"] = int(result["M2_members_ok"][c, k])
            row["M2_required"] = int(result["M2_required"])
            row["M2_pass"] = bool(result["M2_pass"][c, k])
            for t, threshold in enumerate(M3_THRESHOLDS):
                row[f"M3_W_ratio_{threshold}"] = float(result["M3_value"][c, k, t])
            row["M3_pass"] = bool(result["M3_pass"][c, k])
            row["M4_model_sat"] = float(result["M4_model"][c, k])
            row["M4_camera_sat"] = float(result["M4_camera"][c, k])
            row["M4_pass"] = bool(result["M4_pass"][c, k])
            for name in ("H", "W"):
                for regressor in ("P", "v"):
                    for suffix in ("", "_lo", "_hi"):
                        key = f"M5_{name}_{regressor}{suffix}"
                        row[key] = float(result[key][c, k]) if key in result else None
            row["M5_pass"] = bool(result["M5_pass"][c, k]) if "M5_pass" in result else None
            row["all_pass"] = bool(result["all_pass"][c, k]) if "all_pass" in result else None
            row["core_pass"] = bool(result["core_pass"][c, k])
            rows.append(row)
    return rows


def _closest_approach(result: Mapping[str, np.ndarray], cases: Sequence[Mapping[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Descriptive only: per case, the grid T150 where median model/camera H/W at 150 is closest to 1."""

    ref = MATCH_THRESHOLDS.index(REFERENCE_THRESHOLD)
    checks = ("M1_pass", "M1_150_pass", "M2_pass", "M3_pass", "M4_pass") + (("M5_pass",) if "M5_pass" in result else ())
    out = []
    for c, case in enumerate(cases if cases is not None else synthetic_cases()):
        value = np.asarray(result["M1_value"][c, :, ref], dtype=np.float64)
        ok = np.isfinite(value) & (np.nan_to_num(result["coverage"][c, :, ref], nan=0.0) >= COVERAGE_FLOOR)
        if not ok.any():
            out.append({"case_id": case["case_id"], "available": False})
            continue
        distance = np.where(ok, np.abs(np.log(np.where(ok, value, 1.0))), np.inf)
        k = int(np.argmin(distance))
        out.append(
            {
                "case_id": case["case_id"],
                "available": True,
                "T150_K": T150_GRID_K[k],
                "M1_HW_ratio": {str(t): float(result["M1_value"][c, k, i]) for i, t in enumerate(MATCH_THRESHOLDS)},
                "coverage": {str(t): float(result["coverage"][c, k, i]) for i, t in enumerate(MATCH_THRESHOLDS)},
                "M2_members_ok": int(result["M2_members_ok"][c, k]),
                "M3_W_ratio": {str(t): float(result["M3_value"][c, k, i]) for i, t in enumerate(M3_THRESHOLDS)},
                "M4_model_sat": float(result["M4_model"][c, k]),
                "M4_camera_sat": float(result["M4_camera"][c, k]),
                "pass": {key: bool(result[key][c, k]) for key in checks},
            }
        )
    return out


def _physics_summary(members: Sequence[str], results: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    records = _condition_records()
    lp = [math.log(records[m]["power_W"]) for m in members]
    lv = [math.log(records[m]["speed_mm_s"]) for m in members]
    phys = [results[m]["physics"] for m in members]
    trends = {}
    for name, key in (("log_H", "median_liquidus_H_px"), ("log_W", "median_liquidus_W_px"), ("log_HW", "median_liquidus_HW")):
        trends[name] = member_trend(lp, lv, [math.log(p[key]) for p in phys], rng=np.random.default_rng(BOOTSTRAP_SEED))
    camera = json.loads(STEP0_TRENDS_JSON.read_text(encoding="utf-8"))
    total = sum(p["scored_frames"] for p in phys)
    return {
        "basis": "production liquidus H/W (SELECTED scored frames, member medians); regressors [1, log P, log v]; member bootstrap",
        "model_trends": trends,
        "camera_trends_step0": {key: camera[key] for key in ("log_H", "log_W", "log_HW")},
        "rosenthal_liquid_pool_reference": camera["rosenthal_liquid_pool_reference"],
        "members": [{"member_identity": m, **results[m]["physics"]} for m in members],
        "pooled": {
            "median_of_member_liquidus_HW": float(np.median([p["median_liquidus_HW"] for p in phys])),
            "fraction_peak_above_boiling": float(sum(p["fraction_peak_above_boiling"] * p["scored_frames"] for p in phys) / total),
        },
    }


def _level_free_summary(candidate: str, members: Sequence[str], results: Mapping[str, Mapping[str, Any]], liquidus: float) -> dict[str, Any]:
    per_member, pooled_ratio, pooled_level = [], [], []
    statuses: dict[str, int] = {}
    for member in members:
        entries = results[member]["level_free"]
        defined = [e for e in entries if e["status"] == "DEFINED"]
        for e in entries:
            statuses[e["status"]] = statuses.get(e["status"], 0) + 1
        ratio = [e["H_ratio"] for e in defined]
        level = [e["level_K"] for e in defined]
        pooled_ratio += ratio
        pooled_level += level
        per_member.append(
            {
                "member_identity": member,
                "frames": len(entries),
                "defined": len(defined),
                "median_H_ratio": float(np.median(ratio)) if ratio else float("nan"),
                "median_level_K": float(np.median(level)) if level else float("nan"),
            }
        )
    quantiles = (5, 25, 50, 75, 95)
    return {
        "candidate_id": candidate,
        "basis": (
            "per frame: highest isotherm of the 8-um temperature image (camera orientation, no PSF) whose "
            "camera-convention W reaches the camera's threshold-150 W; model H there / camera H"
        ),
        "status_counts": dict(sorted(statuses.items())),
        "pooled_H_ratio_quantiles": {str(q): float(np.percentile(pooled_ratio, q)) for q in quantiles} if pooled_ratio else {},
        "pooled_level_K_quantiles": {str(q): float(np.percentile(pooled_level, q)) for q in quantiles} if pooled_level else {},
        "median_of_member_H_ratio": float(np.median([m["median_H_ratio"] for m in per_member])),
        "liquidus_K": liquidus,
        "fraction_level_below_liquidus": float(np.mean(np.asarray(pooled_level) < liquidus)) if pooled_level else float("nan"),
        "members": per_member,
    }


def run_step3(
    *,
    capture_directory: str | Path,
    camera_frames: str | Path,
    output_directory: str | Path,
    workers: int = DEFAULT_WORKERS,
    progress: Callable[[int, int, str, str], None] | None = None,
) -> dict[str, Any]:
    if isinstance(workers, bool) or not isinstance(workers, int) or workers < 1:
        raise Step3Error(f"workers must be a positive integer, got {workers!r}")
    capture = Path(capture_directory)
    gate = json.loads((capture / CAPTURE_GATE_NAME).read_text(encoding="utf-8"))
    if gate.get("status") != CAPTURE_GATE_PASS:
        raise Step3Error(f"Step-2 capture gate is {gate.get('status')!r}; Step 3 needs {CAPTURE_GATE_PASS}")
    manifest = json.loads((capture / CAPTURE_MANIFEST_NAME).read_text(encoding="utf-8"))
    units = sorted(manifest["units"], key=lambda u: (str(u["candidate_id"]), str(u["member_identity"])))
    members = require_calibration_members(sorted({str(u["member_identity"]) for u in units}))
    by_candidate: dict[str, list[str]] = {}
    for unit in units:
        if unit.get("capture_file") is None:
            raise Step3Error(f"unit {unit['candidate_id']}@{unit['member_identity']} has no field file")
        by_candidate.setdefault(str(unit["candidate_id"]), []).append(str(unit["member_identity"]))
    if sorted(by_candidate.get(PRIMARY_CANDIDATE, [])) != sorted(calibration_member_identities()):
        raise Step3Error(f"{PRIMARY_CANDIDATE} must cover all calibration members")
    for candidate in CORNER_CANDIDATES:
        if not set(CORNER_MEMBERS) <= set(by_candidate.get(candidate, [])):
            raise Step3Error(f"{candidate} lacks corner members")
    camera_path = Path(camera_frames)
    table = load_camera_frames(camera_path, members)
    camera_checks = check_camera_against_step0_evidence(table)
    mapping = load_image_mapping()

    jobs = []
    for index, unit in enumerate(units):
        candidate, member = str(unit["candidate_id"]), str(unit["member_identity"])
        jobs.append(
            SimulationJob(
                case_index=index,
                member_identity=member,
                frame_index=0,
                window_cells=99,
                candidate_coordinates=(),
                experiment_context={
                    "candidate_id": candidate,
                    "field_file": str((capture / unit["capture_file"]["path"]).resolve()),
                    "field_sha256": str(unit["capture_file"]["sha256"]),
                    "unit_file": str((capture / unit["unit_file"]).resolve()),
                    "camera": table[member],
                    "mapping_constant_deg": float(mapping["full_circle_constant_deg"]),
                    "t150_grid": list(T150_GRID_K),
                },
                work_unit_id=f"{candidate}@{member}",
            )
        )
    done = {"count": 0}

    def on_result(result: SimulationResult) -> None:
        done["count"] += 1
        if progress is not None:
            progress(done["count"], len(jobs), str(result.payload["candidate_id"]), result.job.member_identity)

    if workers == 1:
        completed = execute_serial_jobs(jobs, _step3_unit_job, on_result=on_result)
    else:
        completed = execute_parallel_jobs(jobs, _step3_unit_job, workers=workers, on_result=on_result)
    results: dict[str, dict[str, Any]] = {}
    for result in completed:
        results.setdefault(str(result.payload["candidate_id"]), {})[result.job.member_identity] = result.payload

    liquidus_values = {float(r["physics"]["liquidus_K"]) for per in results.values() for r in per.values()}
    if len(liquidus_values) != 1:
        raise Step3Error(f"units disagree on the liquidus temperature: {sorted(liquidus_values)}")
    liquidus = liquidus_values.pop()
    cases = synthetic_cases()
    primary_members = sorted(results[PRIMARY_CANDIDATE])
    primary = evaluate_scope(primary_members, results[PRIMARY_CANDIDATE], with_trends=True)
    reading = evaluate_reading(primary)

    def feasible(result: Mapping[str, np.ndarray], key: str) -> dict[str, Any]:
        per_case = {}
        for c, case in enumerate(cases):
            runs = grid_intervals(T150_GRID_K, result[key][c])
            per_case[case["case_id"]] = {"intervals_K": runs, "any_below_liquidus": bool(runs and runs[0][0] < liquidus)}
        return per_case

    grid_rows = _grid_rows("all_members", PRIMARY_CANDIDATE, primary_members, primary, liquidus)
    corner_scopes = {}
    for candidate in CORNER_CANDIDATES:
        corner_members = list(CORNER_MEMBERS)
        scope = evaluate_scope(corner_members, results[candidate], with_trends=False)
        corner_scopes[candidate] = {
            "members": corner_members,
            "grid_points_core_pass": int(np.count_nonzero(scope["core_pass"])),
            "feasible_core": feasible(scope, "core_pass"),
            "closest_approach_descriptive": _closest_approach(scope),
        }
        grid_rows += _grid_rows("corners", candidate, corner_members, scope, liquidus)

    verdict = {
        "schema": SCHEMA,
        "patch_version": PATCH_VERSION,
        "reading": reading,
        "readings": {
            READING_A: "M1-M5 hold for some case and T150 (anchor_center, 16 members)",
            READING_B: "no case and T150 satisfies M1 at threshold 150 together with M2",
            READING_C: "M1 at 150 and M2 can be met together, but not all of M1-M5",
        },
        "primary": {
            "candidate_id": PRIMARY_CANDIDATE,
            "members": primary_members,
            "grid_points": int(primary["all_pass"].size),
            "grid_points_core_pass": int(np.count_nonzero(primary["core_pass"])),
            "grid_points_all_pass": int(np.count_nonzero(primary["all_pass"])),
            "grid_points_pass_by_criterion": {
                key: int(np.count_nonzero(primary[key])) for key in ("M1_pass", "M1_150_pass", "M2_pass", "M3_pass", "M4_pass", "M5_pass")
            },
            "feasible_core": feasible(primary, "core_pass"),
            "feasible_all": feasible(primary, "all_pass"),
            "closest_approach_descriptive": _closest_approach(primary),
        },
        "corners": corner_scopes,
        "liquidus_K": liquidus,
        "no_point_estimate_adopted": True,
    }
    physics = _physics_summary(primary_members, results[PRIMARY_CANDIDATE])
    level_free = {
        "primary": _level_free_summary(PRIMARY_CANDIDATE, primary_members, results[PRIMARY_CANDIDATE], liquidus),
        "corners": {c: _level_free_summary(c, list(CORNER_MEMBERS), results[c], liquidus) for c in CORNER_CANDIDATES},
    }
    level_free_rows = [
        {
            "candidate_id": candidate,
            "member_identity": member,
            **{k: e.get(k) for k in ("frame_index", "status", "level_K", "H_px", "W_px", "camera_H_px", "camera_W_px", "H_ratio")},
        }
        for candidate in sorted(results)
        for member in sorted(results[candidate])
        for e in results[candidate][member]["level_free"]
    ]

    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    _write_csv(output / "step3_grid.csv.gz", grid_rows, compress=True)
    _write_csv(output / "step3_level_free_frames.csv.gz", level_free_rows, compress=True)
    _write_json(output / "step3_verdict.json", verdict)
    _write_json(output / "step3_physics.json", physics)
    _write_json(output / "step3_level_free.json", level_free)
    run_manifest = {
        "schema": SCHEMA,
        "patch_version": PATCH_VERSION,
        "step": STEP_ID,
        "git_commit": _git("rev-parse", "HEAD"),
        "git_worktree_dirty": bool(_git("status", "--porcelain")),
        "module_sha256": _sha256(Path(__file__)),
        "plan_sha256": _sha256(PLAN_PATH) if PLAN_PATH.is_file() else "unavailable",
        "inputs": {
            "capture_manifest_sha256": _sha256(capture / CAPTURE_MANIFEST_NAME),
            "capture_gate_status": gate["status"],
            "field_files": {f"{u['candidate_id']}@{u['member_identity']}": u["capture_file"]["sha256"] for u in units},
            "camera_frames_sha256": _sha256(camera_path),
            "camera_checks_against_step0_evidence": camera_checks,
            "image_mapping": mapping,
        },
        "parameters": {
            "t150_grid_K": list(T150_GRID_K),
            "cases": list(cases),
            "match_thresholds": list(MATCH_THRESHOLDS),
            "M1_range": list(M1_RANGE),
            "M2_range": list(M2_RANGE),
            "M2_member_fraction": M2_MEMBER_FRACTION,
            "M3_thresholds": list(M3_THRESHOLDS),
            "M3_range": list(M3_RANGE),
            "M4_tolerance": M4_TOLERANCE,
            "coverage_floor": COVERAGE_FLOOR,
            "render": {
                "pixel_um": PIXEL_SIZE_UM,
                "subsamples": SUBSAMPLES,
                "render_px": 2 * RENDER_HALF_PX,
                "camera_crop_rows_cols": [CAMERA_ROWS, CAMERA_COLS],
                "psf_truncate_sigma": PSF_TRUNCATE,
            },
            "level_free": {"floor_K": LEVEL_FREE_FLOOR_K, "iterations": LEVEL_FREE_ITERATIONS},
            "bootstrap": {"replicates": BOOTSTRAP_REPLICATES, "seed": BOOTSTRAP_SEED},
            "boiling_K": BOILING_K,
        },
        "execution": {"workers": workers, "start_method": "serial" if workers == 1 else "spawn", "units": len(jobs)},
        "runtime": {"python": sys.version.split()[0], "numpy": np.__version__, "opencv": cv2.__version__, "platform": platform.platform()},
        "guardrails": {
            "held_out_members_used": False,
            "thermal_model_run": False,
            "parameter_fitting_performed": False,
            "parameter_selection_performed": False,
            "T150_point_estimate_adopted": False,
            "production_semantics_changed": False,
            "workers_wrote_files": False,
        },
        "reading": reading,
    }
    _write_json(output / "step3_manifest.json", run_manifest)
    return {"manifest": run_manifest, "verdict": verdict}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Patch 22.3.8 Step 3: synthetic camera on the captured fields")
    parser.add_argument("--capture-dir", default=DEFAULT_CAPTURE_DIRECTORY)
    parser.add_argument("--camera-frames", default=DEFAULT_CAMERA_FRAMES)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIRECTORY)
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    args = parser.parse_args(argv)

    def progress(done: int, total: int, candidate: str, member: str) -> None:
        print(f"unit {done}/{total} done: {candidate} {member}", flush=True)

    outcome = run_step3(
        capture_directory=args.capture_dir,
        camera_frames=args.camera_frames,
        output_directory=args.output_dir,
        workers=args.workers,
        progress=progress,
    )
    primary = outcome["verdict"]["primary"]
    summary = {"reading": outcome["verdict"]["reading"]}
    summary.update({k: primary[k] for k in ("grid_points", "grid_points_core_pass", "grid_points_all_pass", "grid_points_pass_by_criterion")})
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
