"""Figure sources that need the external inputs: coupon HDF5 frames, c1 field files and the candidate unit files.

Read only. No thermal run, no fitting, no selection. Everything describes the frozen Patch 22.4.3.2 candidate
``confirm_c1`` as recorded (and, for the candidate figure, the recorded calibrate and confirm units).

What is extracted
- One representative frame per coupon, by a fixed rule (not a search for agreement): among the scored frames that
  have a predicted pool and whose stored camera image re-measures to the scored camera H and W within 0.5 px, the
  frame whose camera and model H and W are jointly closest (sum of squared log distances) to the coupon's medians.
- For each such frame: the camera image and its threshold-150 blob (largest 8-connected component, external
  contour, ``minAreaRect``; H the long side, W the short side), and the model's top-surface field rendered in the
  camera's orientation and scale (the Step-0 mirrored mapping that reading S used) with the production liquidus box
  (the beam-share-selected component's interpolated liquidus crossings, ``minAreaRect``). The model box is checked
  bit for bit against the recorded H/W, the camera box against the scored camera H/W (within 0.5 px, by the rule).
- Display alignment: the model render is shifted so that its box centre sits on the camera box centre (rounded to
  the 4 um sub-sample). Position is not compared anywhere; only sizes and shapes are.
- For one in-window frame: the reading-S synthetic camera (850 nm, uniform emissivity, PSF 0 and 2 px, T150 1950 K
  and 1825 K), placed as reading S placed it, and checked against the reading-S frame record.
- For one scan track of that coupon: every scored frame (film strip and animation), at one fixed track alignment.
- For three coupons: machine X/Y of every scored frame (scan-path maps).
- From the calibrate and confirm unit files: per candidate and calibration coupon, the median model H/W over frames
  with a pool, and the camera medians.

Camera frames are taken only from the member's own scored frames (``frame_index`` of its unit records, which come
from ``sync/data_to_gige_image_index``); frames of the other parts of the layer are never read.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from statistics import median
from typing import Any, Mapping, Sequence

import cv2
import numpy as np

from style import C, SOURCE_DIR

from lpbf.model.observation_diagnostics import _label_liquid_components, interpolated_component_contour_hw_diagnostic
from lpbf.camera_observations import PRODUCTION_LAYER, _read_member_frames, measure_blob, scan_direction_deg
import lpbf.synthetic_camera as cam

THRESHOLD = 150
HALF = cam.RENDER_HALF_PX
SUB = cam.SUBSAMPLES
ROWS, COLS = cam.CAMERA_ROWS, cam.CAMERA_COLS
# Stored model window, in camera-aligned pixel coordinates (pixel centres are integers).
WIN_X = (-8, 72)  # 80 px
WIN_Y = (-8, 32)  # 40 px
CASES = {
    "sigma0": {"case_id": "lam850_uniform_sig0.0", "sigma_px": 0.0, "T150_K": 1950.0},
    "sigma2": {"case_id": "lam850_uniform_sig2.0", "sigma_px": 2.0, "T150_K": 1825.0},
}
FEATURE_MEMBER = "20260730:part_3"  # in-window calibration coupon used by the explainer, film strip and pipeline
MAP_MEMBERS = ("20260904:part_6", "20260730:part_3", "20260904:part_4")
LEVELS_CAMERA = (30, 60, 100, 150, 200, 250)
# Animations.
ANIM_X = (-44, 20)  # beam-centred window, px: the laser spot sits where the camera's pool usually does (64 x 24 px)
ANIM_Y = (-12, 12)
LAYER_STEP = 6  # every 6th scored frame for the whole-layer animation (keeps the GIF under 10 MB)
PATH_STEP = 25  # every 25th laser-on data row for the drawn scan path
LANDSCAPE_MEMBERS = ("20260904:part_6", "20260730:part_3", "20260904:part_4")  # 54, 70 and 125 J/mm3
LANDSCAPE_U = (-720.0, 200.0)  # um along the travel (negative = behind the laser)
LANDSCAPE_V = (-240.0, 240.0)
LANDSCAPE_STEP_UM = 8.0
LEVELS_MODEL_K = (900.0, 1100.0, 1300.0, 1500.0, 1673.15, 1900.0)  # the in-window frame peaks near 2,000 K


class ExtractError(RuntimeError):
    pass


def available() -> bool:
    fields = all((C.FIELDS_DIR / f"{C.CANDIDATE}__{m.replace(':', '_')}.npz").is_file() for m in C.ROLE)
    return C.COUPON_DATA_DIR.is_dir() and fields and C.CALIBRATE_UNITS_DIR.is_dir() and C.CHARACTERIZATION.is_dir()


# ---------------------------------------------------------------------- measurement helpers


def blob(image: np.ndarray, threshold: float) -> dict[str, Any] | None:
    """The camera convention, also returning the rectangle and the outline (same arithmetic as ``measure_blob``)."""

    return blob_mask(np.asarray(image) >= threshold)


def blob_mask(mask: np.ndarray) -> dict[str, Any] | None:
    mask = np.asarray(mask).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if count < 2:
        return None
    index = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    component = labels == index
    contours, _ = cv2.findContours(component.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    points = np.vstack([c.reshape(-1, 2) for c in contours]).astype(np.float32)
    rect = cv2.minAreaRect(points)
    ys, xs = np.nonzero(component)
    n_rows, n_cols = mask.shape
    return {
        "H_px": float(max(rect[1])), "W_px": float(min(rect[1])), "corners": cv2.boxPoints(rect).astype(float),
        "outline": max(contours, key=len).reshape(-1, 2).astype(float), "centroid": (float(xs.mean()), float(ys.mean())),
        "touches_edge": bool(xs.min() == 0 or ys.min() == 0 or xs.max() == n_cols - 1 or ys.max() == n_rows - 1),
        "area_px": int(xs.size),
    }


def crossing_points(field: np.ndarray, component: np.ndarray, level: float, cell_um: float, pixel_um: float) -> np.ndarray:
    """Interpolated liquidus crossings of one component, in the production order and units (8 um pixels)."""

    scale = cell_um / pixel_um
    nx, ny = field.shape
    xc = (np.arange(nx, dtype=np.float64) + 0.5) * scale
    yc = (np.arange(ny, dtype=np.float64) + 0.5) * scale
    pts: list[tuple[float, float]] = []
    for i in range(nx - 1):
        for j in range(ny):
            if bool(component[i, j]) == bool(component[i + 1, j]):
                continue
            t0, t1 = float(field[i, j]), float(field[i + 1, j])
            fraction = (level - t0) / (t1 - t0)
            pts.append((float(xc[i] + fraction * (xc[i + 1] - xc[i])), float(yc[j])))
    for i in range(nx):
        for j in range(ny - 1):
            if bool(component[i, j]) == bool(component[i, j + 1]):
                continue
            t0, t1 = float(field[i, j]), float(field[i, j + 1])
            fraction = (level - t0) / (t1 - t0)
            pts.append((float(xc[i]), float(yc[j] + fraction * (yc[j + 1] - yc[j]))))
    return np.asarray(pts, dtype=np.float32)


class Member:
    """One coupon: its scored frames, camera images, field arrays and image mapping."""

    def __init__(self, member: str, frames: Sequence[Mapping[str, str]], mapping: Mapping[str, Any]):
        self.member = member
        self.frames = sorted(frames, key=lambda r: int(r["frame_index"]))
        acquisition_set, part = C.member_key(member)
        self.h5 = C.COUPON_DATA_DIR / f"part_{part}_{acquisition_set}.h5"
        if C.sha256_file(self.h5) != C.characterization_audit(member)["input_file_sha256"]:
            raise ExtractError(f"{self.h5.name}: sha256 differs from the characterization record")
        unit = json.loads(C.unit_path(member).read_text(encoding="utf-8"))
        npz = C.FIELDS_DIR / f"{C.CANDIDATE}__{member.replace(':', '_')}.npz"
        if C.sha256_file(npz) != unit["capture_file"]["sha256"]:
            raise ExtractError(f"{npz.name}: sha256 differs from its unit record")
        with np.load(npz, allow_pickle=False) as z:
            self.arrays = {k: z[k] for k in z.files}
        self.position = {int(f): k for k, f in enumerate(self.arrays["frame_index"])}
        indices = [int(r["frame_index"]) for r in self.frames]
        got = _read_member_frames(self.h5, PRODUCTION_LAYER, indices)
        self.images = dict(zip(indices, got["images"]))
        self.x_mm, self.y_mm = got["x_mm"], got["y_mm"]
        self.constant = float(mapping["full_circle_constant_deg"])
        self.offsets = cam.subsample_offsets_um(self.constant)
        self.matrix = cam.image_to_machine_matrix(self.constant)
        if not np.allclose(self.matrix @ self.matrix, np.eye(2), atol=1e-12):
            raise ExtractError("image mapping is not an involution")
        self.liquidus = float(self.arrays["liquidus_temperature_K"])
        self.cell = float(self.arrays["cell_size_um"])
        self.pixel = float(self.arrays["experimental_pixel_size_um"])
        with __import__("h5py").File(self.h5, "r") as h5:
            self.gige_time = np.asarray(h5[PRODUCTION_LAYER]["gige_time"][indices], dtype=np.float64)
        self.time_of = dict(zip(indices, self.gige_time.tolist()))

    # -- camera
    def camera(self, frame: int, threshold: float = THRESHOLD) -> dict[str, Any] | None:
        return blob(self.images[frame], threshold)

    # -- model
    def model(self, frame: int, record: Mapping[str, str]) -> dict[str, Any]:
        k = self.position[frame]
        field = self.arrays["top_surface_temperature_K"][k]
        if str(self.arrays["production_status"][k]) != "SELECTED":
            raise ExtractError(f"{self.member} frame {frame}: no selected component")
        labels, _ = _label_liquid_components(field >= self.liquidus)
        component = labels == int(self.arrays["selected_label"][k])
        pristine = interpolated_component_contour_hw_diagnostic(
            field, component, liquidus_temperature_K=self.liquidus, cell_size_um=self.cell, experimental_pixel_size_um=self.pixel
        )
        pts = crossing_points(field, component, self.liquidus, self.cell, self.pixel)
        rect = cv2.minAreaRect(pts)
        h, w = float(max(rect[1])), float(min(rect[1]))
        if not (h == pristine["H_pixels"] == float(record["sim_H_px"]) and w == pristine["W_pixels"] == float(record["sim_W_px"])):
            raise ExtractError(f"{self.member} frame {frame}: model box does not reproduce the recorded H/W")
        sx = float(self.arrays["source_center_x_mm"][k]) * 1000.0
        sy = float(self.arrays["source_center_y_mm"][k]) * 1000.0
        dx = pts[:, 0].astype(np.float64) * self.pixel - sx
        dy = pts[:, 1].astype(np.float64) * self.pixel - sy
        m = self.matrix
        u = (m[0, 0] * dx + m[0, 1] * dy) / self.pixel + HALF
        v = (m[1, 0] * dx + m[1, 1] * dy) / self.pixel + HALF
        rect_i = cv2.minAreaRect(np.stack([u, v], axis=1).astype(np.float32))
        if abs(max(rect_i[1]) - h) > 1e-3 or abs(min(rect_i[1]) - w) > 1e-3:
            raise ExtractError(f"{self.member} frame {frame}: box changed under the image mapping")
        t_sub, inside = cam.render_temperature_subsamples(field, source_x_mm=sx / 1000.0, source_y_mm=sy / 1000.0, cell_um=self.cell, offsets=self.offsets)
        # Other liquid components (not associated with the laser, not scored) are capped 1 K below the liquidus in a
        # second render, whose liquidus contour is then the scored component's alone.
        t_sel = None
        if int(labels.max()) > 1:
            capped = np.where((labels > 0) & ~component, np.minimum(field, self.liquidus - 1.0), field)
            t_sel, _ = cam.render_temperature_subsamples(capped, source_x_mm=sx / 1000.0, source_y_mm=sy / 1000.0, cell_um=self.cell, offsets=self.offsets)
        return {
            "k": k, "field": field, "t_sub": t_sub, "t_sel": t_sel, "inside": inside, "rect": rect_i, "corners": cv2.boxPoints(rect_i).astype(float),
            "H_px": h, "W_px": w, "peak_K": float(field.max()), "beam_uv": (float(HALF), float(HALF)), "components": int(labels.max()),
        }

    def motion_uv(self, record: Mapping[str, str]) -> tuple[float, float]:
        """Laser travel direction in image coordinates (unit vector), from machine X/Y around the frame's data row."""

        angle = float(scan_direction_deg(self.x_mm, self.y_mm, [int(record["process_row"])])[0])
        dx, dy = math.cos(math.radians(angle)), math.sin(math.radians(angle))
        m = self.matrix
        du, dv = m[0, 0] * dx + m[0, 1] * dy, m[1, 0] * dx + m[1, 1] * dy
        n = math.hypot(du, dv)
        return du / n, dv / n


def aligned_window(t_sub: np.ndarray, offset: tuple[float, float]) -> np.ndarray:
    """Model sub-samples on the stored window, in camera-aligned coordinates ``render - offset``."""

    ox, oy = offset
    # Sub-sample s of the render sits at (s + 0.5) / SUB - 0.5 px; the window starts at WIN - 0.5 px.
    s0x = int(round((WIN_X[0] - 0.5 + ox + 0.5) * SUB))
    s0y = int(round((WIN_Y[0] - 0.5 + oy + 0.5) * SUB))
    nx, ny = (WIN_X[1] - WIN_X[0]) * SUB, (WIN_Y[1] - WIN_Y[0]) * SUB
    if s0x < 0 or s0y < 0 or s0x + nx > t_sub.shape[1] or s0y + ny > t_sub.shape[0]:
        raise ExtractError("stored window leaves the render")
    return np.asarray(t_sub[s0y : s0y + ny, s0x : s0x + nx], dtype=np.float32)


def wide_window(t_sub: np.ndarray, offset: tuple[float, float], half_rows_px: int = 36) -> tuple[np.ndarray, np.ndarray]:
    """The full render width, +-``half_rows_px`` rows around the beam, and its extent in aligned coordinates."""

    r0, r1 = (HALF - half_rows_px) * SUB, (HALF + half_rows_px) * SUB
    ox, oy = offset
    extent = np.array([-0.5 - ox, t_sub.shape[1] / SUB - 0.5 - ox, (HALF + half_rows_px) - 0.5 - oy, (HALF - half_rows_px) - 0.5 - oy])
    return np.asarray(t_sub[r0:r1, :], dtype=np.float32), extent


def box_offset(model: Mapping[str, Any], camera: Mapping[str, Any]) -> tuple[float, float]:
    """Render-to-camera shift that puts the model box centre on the camera box centre (rounded to a sub-sample)."""

    mc = np.asarray(model["corners"]).mean(axis=0)
    cc = np.asarray(camera["corners"]).mean(axis=0)
    return float(round((mc[0] - cc[0]) * SUB) / SUB), float(round((mc[1] - cc[1]) * SUB) / SUB)


def representative(m: Member) -> tuple[Mapping[str, str], dict[str, Any]]:
    scored = m.frames
    pool = [r for r in scored if r["no_pool"] == "false"]
    med = {}
    for key in ("cam_H_px", "cam_W_px"):
        med[key] = math.log(median(float(r[key]) for r in scored))
    for key in ("sim_H_px", "sim_W_px"):
        med[key] = math.log(median(float(r[key]) for r in pool))
    eligible = []
    for r in pool:
        b = m.camera(int(r["frame_index"]))
        if b is None or b["touches_edge"]:
            continue
        if abs(b["H_px"] - float(r["cam_H_px"])) > 0.5 or abs(b["W_px"] - float(r["cam_W_px"])) > 0.5:
            continue
        d = sum((math.log(float(r[key])) - med[key]) ** 2 for key in med)
        eligible.append((d, int(r["frame_index"]), r, b))
    if not eligible:
        raise ExtractError(f"{m.member}: no eligible representative frame")
    eligible.sort(key=lambda item: (item[0], item[1]))
    d, _, r, b = eligible[0]
    return r, {"distance": d, "eligible": len(eligible), "medians_px": {k: math.exp(v) for k, v in med.items()}, "camera": b}


def check_measure_blob(image: np.ndarray, b: Mapping[str, Any]) -> None:
    ref = measure_blob(image, THRESHOLD)
    if ref is None or ref["H_px"] != b["H_px"] or ref["W_px"] != b["W_px"]:
        raise ExtractError("camera box differs from measure_blob")


# ---------------------------------------------------------------------- synthetic camera (reading S)


def synthetic(m: Member, frame: int, model: Mapping[str, Any], camera: Mapping[str, Any], records: Mapping[tuple[str, str, int], Mapping[str, str]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    inside_px = cam.pixel_all(model["inside"])
    for key, case in CASES.items():
        rec = records[(case["case_id"], m.member, frame)]
        if rec["synthetic_status"] != "PAIRED":
            raise ExtractError(f"{m.member} frame {frame}: {case['case_id']} is {rec['synthetic_status']}")
        unit = float(cam.count_level_unit(case["T150_K"], wavelength_nm=850.0, emissivity_model="uniform", liquidus_K=m.liquidus))
        radiance = cam.gaussian_psf(cam.pixel_mean(cam.planck_relative(model["t_sub"], 850.0)), case["sigma_px"])
        level = cam.REFERENCE_THRESHOLD * unit
        reference = cam.measure_component(radiance >= level)
        cx, cy = camera["centroid"]
        ox = cam._round_half_up(reference["centroid_x"] - cx)
        oy = cam._round_half_up(reference["centroid_y"] - cy)
        crop = radiance[oy : oy + ROWS, ox : ox + COLS]
        got = cam.measure_component(crop >= level)
        if got is None or not (math.isclose(got["H_px"], float(rec["simulated_H_pixels"]), rel_tol=1e-6) and math.isclose(got["W_px"], float(rec["simulated_W_pixels"]), rel_tol=1e-6)):
            raise ExtractError(f"{m.member} frame {frame}: synthetic {key} differs from the reading-S record")
        if not bool(inside_px[oy : oy + ROWS, ox : ox + COLS][got["component"]].all()):
            raise ExtractError("synthetic blob reaches outside the model window")
        counts = crop / unit
        b = blob_mask(crop >= level)
        if b is None or not (b["H_px"] == got["H_px"] and b["W_px"] == got["W_px"]):
            raise ExtractError("synthetic outline does not reproduce the synthetic box")
        out[key] = {
            "offset_px": (ox, oy), "counts": np.asarray(counts, dtype=np.float32), "corners": b["corners"], "outline": b["outline"],
            "H_px": got["H_px"], "W_px": got["W_px"], "T150_K": case["T150_K"], "sigma_px": case["sigma_px"],
            "t_sub_crop": np.asarray(model["t_sub"][oy * SUB : (oy + ROWS) * SUB, ox * SUB : (ox + COLS) * SUB], dtype=np.float32),
            "camera_H_px_reading_S": float(rec["experimental_H_pixels"]), "camera_W_px_reading_S": float(rec["experimental_W_pixels"]),
        }
    return out


# ---------------------------------------------------------------------- the extraction


def _pack_frame(prefix: str, m: Member, record: Mapping[str, str], camera: Mapping[str, Any], model: Mapping[str, Any], offset: tuple[float, float], store: dict[str, np.ndarray]) -> dict[str, Any]:
    frame = int(record["frame_index"])
    store[f"{prefix}camera_image"] = np.asarray(m.images[frame], dtype=np.uint8)
    store[f"{prefix}camera_outline"] = np.asarray(camera["outline"], dtype=np.float32)
    store[f"{prefix}camera_corners"] = np.asarray(camera["corners"], dtype=np.float64)
    store[f"{prefix}model_window_K"] = aligned_window(model["t_sub"], offset)
    if model["t_sel"] is not None:
        store[f"{prefix}model_window_selected_K"] = aligned_window(model["t_sel"], offset)
    store[f"{prefix}model_corners"] = np.asarray(model["corners"], dtype=np.float64) - np.asarray(offset)
    beam = np.asarray(model["beam_uv"]) - np.asarray(offset)
    mu, mv = m.motion_uv(record)
    return {
        "member": m.member, "frame_index": frame, "scan_track_id": int(record["scan_track_id"]), "track_position": int(record["track_position"]),
        "condition": record["condition"], "power_W": float(record["power_W"]), "speed_mm_s": float(record["speed_mm_s"]), "ved_J_mm3": float(record["ved_J_mm3"]),
        "role": record["role"], "camera_H_px": float(record["cam_H_px"]), "camera_W_px": float(record["cam_W_px"]),
        "camera_H_px_remeasured": camera["H_px"], "camera_W_px_remeasured": camera["W_px"],
        "model_H_px": model["H_px"], "model_W_px": model["W_px"], "peak_K": model["peak_K"], "liquidus_K": m.liquidus, "liquid_components": model["components"],
        "offset_x_px": offset[0], "offset_y_px": offset[1], "beam_x_px": float(beam[0]), "beam_y_px": float(beam[1]),
        "travel_u": mu, "travel_v": mv, "gige_time_s": m.time_of[frame],
    }


def write_sources() -> list[Path]:
    SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    mapping = cam.load_image_mapping()
    d1 = C.read_csv(C.DATA_DIR / "D1_frames.csv.gz")
    by_member: dict[str, list[dict[str, str]]] = {}
    for r in d1:
        by_member.setdefault(r["member"], []).append(r)
    synth_records = {}
    for r in C.read_csv(C.SYNTHETIC_FRAMES):
        if r["member_identity"] == FEATURE_MEMBER:
            synth_records[(r["case_id"], r["member_identity"], int(r["frame_index"]))] = r

    files: list[Path] = []
    rep_rows, rep_store = [], {}
    feature: dict[str, Any] = {}
    landscapes: dict[str, dict[str, Any]] = {}
    for member in sorted(by_member, key=lambda mm: (float(by_member[mm][0]["ved_J_mm3"]), mm)):
        m = Member(member, by_member[member], mapping)
        record, info = representative(m)
        frame = int(record["frame_index"])
        camera = info["camera"]
        check_measure_blob(m.images[frame], camera)
        model = m.model(frame, record)
        offset = box_offset(model, camera)
        key = member.replace(":", "_")
        row = _pack_frame(f"{key}__", m, record, camera, model, offset, rep_store)
        row.update({"eligible_frames": info["eligible"], "distance": info["distance"], **{f"median_{k}": v for k, v in info["medians_px"].items()}})
        rep_rows.append(row)
        if member == FEATURE_MEMBER:
            feature = {"member": m, "record": record, "camera": camera, "model": model, "offset": offset}
        if member in MAP_MEMBERS:
            files.append(_scan_map(m))
        if member in LANDSCAPE_MEMBERS:
            landscapes[member] = _landscape(m, record)
        print(f"  {member}: frame {frame} (track {record['scan_track_id']}), {info['eligible']} eligible", flush=True)
    files.append(C.write_csv(SOURCE_DIR / "representative_frames.csv", rep_rows))
    path = SOURCE_DIR / "representative_frames.npz"
    np.savez_compressed(path, **rep_store)
    files.append(path)
    files.extend(_feature_sources(feature, synth_records))
    files.extend(_animation_sources(feature["member"], landscapes))
    files.append(_candidate_sizes())
    return files


def _travel_vector(m: Member, record: Mapping[str, str]) -> tuple[float, float]:
    angle = math.radians(float(scan_direction_deg(m.x_mm, m.y_mm, [int(record["process_row"])])[0]))
    return math.cos(angle), math.sin(angle)


def _landscape(m: Member, record: Mapping[str, str]) -> dict[str, Any]:
    """The frame's top-surface field resampled in the laser's frame: u along the travel (negative = behind), v across."""

    k = m.position[int(record["frame_index"])]
    field = m.arrays["top_surface_temperature_K"][k]
    dx, dy = _travel_vector(m, record)
    u = np.arange(LANDSCAPE_U[0], LANDSCAPE_U[1] + 1e-9, LANDSCAPE_STEP_UM)
    v = np.arange(LANDSCAPE_V[0], LANDSCAPE_V[1] + 1e-9, LANDSCAPE_STEP_UM)
    uu, vv = np.meshgrid(u, v)
    ox, oy = uu * dx - vv * dy, uu * dy + vv * dx  # machine offsets (um); v points to the left of the travel
    sx = float(m.arrays["source_center_x_mm"][k]) * 1000.0
    sy = float(m.arrays["source_center_y_mm"][k]) * 1000.0
    values, inside = cam.bilinear_field(field, (sx + ox) / m.cell - 0.5, (sy + oy) / m.cell - 0.5)
    if not bool(inside.all()):
        raise ExtractError(f"{m.member}: landscape grid leaves the model window")
    return {"T": np.asarray(values, dtype=np.float32), "u_um": u, "v_um": v, "row": dict(record), "liquidus_K": m.liquidus, "peak_K": float(field.max())}


def _beam_window(t_sub: np.ndarray) -> np.ndarray:
    """Sub-samples of a beam-centred window (ANIM_X by ANIM_Y px around the laser spot), as float16 for storage."""

    x0, y0 = (HALF + ANIM_X[0]) * SUB, (HALF + ANIM_Y[0]) * SUB
    nx, ny = (ANIM_X[1] - ANIM_X[0]) * SUB, (ANIM_Y[1] - ANIM_Y[0]) * SUB
    return np.asarray(t_sub[y0 : y0 + ny, x0 : x0 + nx], dtype=np.float16)


def _animation_sources(m: Member, landscapes: Mapping[str, Mapping[str, Any]]) -> list[Path]:
    """Sources of the animations: consecutive tracks frame by frame, the whole layer, and three temperature landscapes."""

    import h5py

    files: list[Path] = []
    # 1. The three consecutive infill (hatch) tracks with the most scored frames, every scored frame, in the camera view,
    #    beam fixed. Hatch tracks run along the layer's common scan direction; the border pass does not.
    by_track: dict[int, list[Mapping[str, str]]] = {}
    for r in m.frames:
        by_track.setdefault(int(r["scan_track_id"]), []).append(r)

    def direction(t: int) -> float:
        a, b = (int(by_track[t][i]["process_row"]) for i in (0, -1))
        return math.degrees(math.atan2(m.y_mm[b] - m.y_mm[a], m.x_mm[b] - m.x_mm[a]))

    long_tracks = [t for t in by_track if len(by_track[t]) >= 5]
    common = float(np.median([direction(t) for t in long_tracks]))
    hatch = sorted(t for t in long_tracks if abs((direction(t) - common + 180.0) % 360.0 - 180.0) <= 10.0)
    runs = [hatch[i : i + 3] for i in range(len(hatch) - 2) if hatch[i + 2] - hatch[i] == 2]
    tracks = max(runs, key=lambda run: (sum(len(by_track[t]) for t in run), -run[0]))
    rows, store = [], {}
    for t in tracks:
        for r in sorted(by_track[t], key=lambda r: int(r["frame_index"])):
            f = int(r["frame_index"])
            b = m.camera(f)
            store[f"{f}__camera_image"] = np.asarray(m.images[f], dtype=np.uint8)
            if b is not None:
                store[f"{f}__camera_corners"] = b["corners"]
                store[f"{f}__camera_outline"] = np.asarray(b["outline"], dtype=np.float32)
            row = {"frame_index": f, "scan_track_id": t, "track_position": int(r["track_position"]), "gige_time_s": m.time_of[f], "no_pool": r["no_pool"],
                   "camera_H_px": float(r["cam_H_px"]), "camera_W_px": float(r["cam_W_px"]), "model_H_px": float(r["sim_H_px"]), "model_W_px": float(r["sim_W_px"]),
                   "camera_H_px_remeasured": b["H_px"] if b else "", "camera_W_px_remeasured": b["W_px"] if b else ""}
            if r["no_pool"] == "false":
                mod = m.model(f, r)
                store[f"{f}__model_window_K"] = _beam_window(mod["t_sub"])
                if mod["t_sel"] is not None:
                    store[f"{f}__model_window_selected_K"] = _beam_window(mod["t_sel"])
                store[f"{f}__model_corners"] = mod["corners"] - np.array([HALF + ANIM_X[0], HALF + ANIM_Y[0]], dtype=float)
            rows.append(row)
    meta = {"member": m.member, "window_x_px": f"{ANIM_X[0]}:{ANIM_X[1]}", "window_y_px": f"{ANIM_Y[0]}:{ANIM_Y[1]}", "liquidus_K": m.liquidus}
    files.append(C.write_csv(SOURCE_DIR / "animation_tracks.csv", [{**meta, **r} for r in rows]))
    path = SOURCE_DIR / "animation_tracks.npz"
    np.savez_compressed(path, **store)
    files.append(path)

    # 2. The whole layer: every LAYER_STEP-th scored frame's field, placed at its machine position, and the laser-on path.
    with h5py.File(m.h5, "r") as h5:
        laser_on = np.asarray(h5[PRODUCTION_LAYER]["sync/data_on_grouped"][()], dtype=bool)
    on_rows = np.flatnonzero(laser_on)
    path_rows = on_rows[:: PATH_STEP]
    frames = m.frames[:: LAYER_STEP]
    store, rows = {}, []
    for r in frames:
        f = int(r["frame_index"])
        k = m.position[f]
        row = int(r["process_row"])
        sx, sy = float(m.arrays["source_center_x_mm"][k]), float(m.arrays["source_center_y_mm"][k])
        store[f"{f}__field_K"] = np.asarray(m.arrays["top_surface_temperature_K"][k], dtype=np.float16)
        rows.append({"frame_index": f, "scan_track_id": int(r["scan_track_id"]), "process_row": row, "gige_time_s": m.time_of[f], "beam_x_mm": float(m.x_mm[row]),
                     "beam_y_mm": float(m.y_mm[row]), "window_x0_mm": float(m.x_mm[row]) - sx, "window_y0_mm": float(m.y_mm[row]) - sy,
                     "model_H_px": float(r["sim_H_px"]), "model_W_px": float(r["sim_W_px"]), "no_pool": r["no_pool"]})
    store["path_rows"] = path_rows.astype(np.int64)
    store["path_x_mm"] = m.x_mm[path_rows].astype(np.float32)
    store["path_y_mm"] = m.y_mm[path_rows].astype(np.float32)
    meta = {"member": m.member, "cell_um": m.cell, "cells": int(m.arrays["top_surface_temperature_K"].shape[1]), "liquidus_K": m.liquidus, "frame_step": LAYER_STEP}
    files.append(C.write_csv(SOURCE_DIR / "animation_layer.csv", [{**meta, **r} for r in rows]))
    path = SOURCE_DIR / "animation_layer.npz"
    np.savez_compressed(path, **store)
    files.append(path)

    # 3. Temperature landscapes of three representative frames, in the laser's frame.
    store, rows = {}, []
    for member, item in landscapes.items():
        key = member.replace(":", "_")
        store[f"{key}__T_K"] = item["T"]
        store[f"{key}__u_um"] = item["u_um"]
        store[f"{key}__v_um"] = item["v_um"]
        r = item["row"]
        rows.append({"member": member, "frame_index": int(r["frame_index"]), "condition": r["condition"], "power_W": float(r["power_W"]), "speed_mm_s": float(r["speed_mm_s"]),
                     "ved_J_mm3": float(r["ved_J_mm3"]), "role": r["role"], "liquidus_K": item["liquidus_K"], "peak_K": item["peak_K"],
                     "model_H_px": float(r["sim_H_px"]), "model_W_px": float(r["sim_W_px"]), "camera_H_px": float(r["cam_H_px"]), "camera_W_px": float(r["cam_W_px"])})
    files.append(C.write_csv(SOURCE_DIR / "animation_landscapes.csv", rows))
    path = SOURCE_DIR / "animation_landscapes.npz"
    np.savez_compressed(path, **store)
    files.append(path)
    return files


def _scan_map(m: Member) -> Path:
    rows = []
    for r in m.frames:
        row = int(r["process_row"])
        rows.append(
            {
                "member": m.member, "frame_index": int(r["frame_index"]), "scan_track_id": int(r["scan_track_id"]), "x_mm": float(m.x_mm[row]), "y_mm": float(m.y_mm[row]),
                "camera_H_px": float(r["cam_H_px"]), "camera_W_px": float(r["cam_W_px"]), "model_H_px": float(r["sim_H_px"]), "model_W_px": float(r["sim_W_px"]),
                "no_pool": r["no_pool"], "gige_time_s": m.time_of[int(r["frame_index"])],
            }
        )
    return C.write_csv(SOURCE_DIR / f"scan_map__{m.member.replace(':', '_')}.csv", rows)


def _feature_sources(feature: Mapping[str, Any], synth_records: Mapping[tuple[str, str, int], Mapping[str, str]]) -> list[Path]:
    m: Member = feature["member"]
    files: list[Path] = []
    # Thresholds and isotherms on the representative frame.
    record, camera, model, offset = feature["record"], feature["camera"], feature["model"], feature["offset"]
    frame = int(record["frame_index"])
    level_rows, store = [], {}
    for t in LEVELS_CAMERA:
        b = blob(m.images[frame], t)
        store[f"camera_{t}"] = np.asarray(b["outline"], dtype=np.float32)
        level_rows.append({"source": "camera", "level": t, "unit": "counts", "H_px": b["H_px"], "W_px": b["W_px"], "touches_edge": b["touches_edge"]})
    t_image = cam.pixel_mean(model["t_sub"])
    inside_px = cam.pixel_all(model["inside"])
    for level in LEVELS_MODEL_K:
        comp = cam.measure_component(t_image >= level)
        if comp is None:
            raise ExtractError(f"isotherm {level} K is above the feature frame's peak")
        level_rows.append(
            {"source": "model", "level": level, "unit": "K", "H_px": comp["H_px"], "W_px": comp["W_px"],
             "touches_edge": bool(comp["touches_edge"] or not bool(inside_px[comp["component"]].all()))}
        )
    store["model_wide_K"], store["model_wide_extent"] = wide_window(model["t_sub"], offset)
    files.append(C.write_csv(SOURCE_DIR / "levels_feature_frame.csv", level_rows))
    path = SOURCE_DIR / "levels_feature_outlines.npz"
    np.savez_compressed(path, **store)
    files.append(path)

    # The synthetic camera on the first frame of the ranking that reading S paired in both cases.
    record_s, info_s = record, None
    ranked = []
    scored = [r for r in m.frames if r["no_pool"] == "false"]
    med = {k: math.log(median(float(r[k]) for r in (m.frames if k.startswith("cam") else scored))) for k in ("cam_H_px", "cam_W_px", "sim_H_px", "sim_W_px")}
    for r in scored:
        f = int(r["frame_index"])
        if any(synth_records.get((c["case_id"], m.member, f), {}).get("synthetic_status") != "PAIRED" for c in CASES.values()):
            continue
        b = m.camera(f)
        if b is None or b["touches_edge"] or abs(b["H_px"] - float(r["cam_H_px"])) > 0.5 or abs(b["W_px"] - float(r["cam_W_px"])) > 0.5:
            continue
        ranked.append((sum((math.log(float(r[k])) - med[k]) ** 2 for k in med), f, r, b))
    ranked.sort(key=lambda item: (item[0], item[1]))
    _, _, record_s, camera_s = ranked[0]
    frame_s = int(record_s["frame_index"])
    model_s = m.model(frame_s, record_s)
    synth = synthetic(m, frame_s, model_s, camera_s, synth_records)
    store = {"camera_image": np.asarray(m.images[frame_s], dtype=np.uint8), "camera_corners": camera_s["corners"], "camera_outline": camera_s["outline"]}
    rows = []
    for key, s in synth.items():
        store[f"{key}_counts"] = s["counts"]
        store[f"{key}_corners"] = s["corners"]
        store[f"{key}_outline"] = s["outline"]
        store[f"{key}_t_sub"] = s["t_sub_crop"]
        # The liquidus box in this case's crop coordinates.
        store[f"{key}_model_corners"] = model_s["corners"] - np.asarray(s["offset_px"], dtype=float)
        rows.append({"case": key, "T150_K": s["T150_K"], "sigma_px": s["sigma_px"], "offset_x_px": s["offset_px"][0], "offset_y_px": s["offset_px"][1], "H_px": s["H_px"], "W_px": s["W_px"]})
    path = SOURCE_DIR / "pipeline_frame.npz"
    np.savez_compressed(path, **store)
    files.append(path)
    meta = {
        "member": m.member, "frame_index": frame_s, "scan_track_id": int(record_s["scan_track_id"]), "condition": record_s["condition"], "ved_J_mm3": float(record_s["ved_J_mm3"]),
        "camera_H_px": float(record_s["cam_H_px"]), "camera_W_px": float(record_s["cam_W_px"]), "camera_H_px_remeasured": camera_s["H_px"], "camera_W_px_remeasured": camera_s["W_px"],
        "model_H_px": model_s["H_px"], "model_W_px": model_s["W_px"], "liquidus_K": m.liquidus, "wavelength_nm": 850.0, "emissivity": "uniform",
    }
    files.append(C.write_csv(SOURCE_DIR / "pipeline_frame.csv", [{**meta, **r} for r in rows]))

    # Every scored frame of the representative frame's track, at the representative frame's alignment.
    track = int(record["scan_track_id"])
    strip_rows, store = [], {}
    for r in m.frames:
        if int(r["scan_track_id"]) != track:
            continue
        f = int(r["frame_index"])
        b = m.camera(f)
        row = {"frame_index": f, "track_position": int(r["track_position"]), "gige_time_s": m.time_of[f], "camera_H_px": float(r["cam_H_px"]), "camera_W_px": float(r["cam_W_px"]),
               "model_H_px": float(r["sim_H_px"]), "model_W_px": float(r["sim_W_px"]), "no_pool": r["no_pool"],
               "camera_H_px_remeasured": b["H_px"] if b else "", "camera_W_px_remeasured": b["W_px"] if b else ""}
        store[f"{f}__camera_image"] = np.asarray(m.images[f], dtype=np.uint8)
        if b is not None:
            store[f"{f}__camera_corners"] = b["corners"]
            store[f"{f}__camera_outline"] = np.asarray(b["outline"], dtype=np.float32)
        if r["no_pool"] == "false":
            mod = m.model(f, r)
            store[f"{f}__model_window_K"] = aligned_window(mod["t_sub"], offset)
            if mod["t_sel"] is not None:
                store[f"{f}__model_window_selected_K"] = aligned_window(mod["t_sel"], offset)
            store[f"{f}__model_corners"] = mod["corners"] - np.asarray(offset)
        strip_rows.append(row)
    files.append(C.write_csv(SOURCE_DIR / "track_frames.csv", [{"member": m.member, "scan_track_id": track, "offset_x_px": offset[0], "offset_y_px": offset[1], **r} for r in strip_rows]))
    path = SOURCE_DIR / "track_frames.npz"
    np.savez_compressed(path, **store)
    files.append(path)
    return files


def _candidate_sizes() -> Path:
    """Median model H/W (frames with a pool) and camera H/W per candidate and calibration coupon, from the unit files."""

    rows = []
    for directory in (C.CALIBRATE_UNITS_DIR, C.CONFIRM_UNITS_DIR):
        for path in sorted(directory.glob("*.json")):
            unit = json.loads(path.read_text(encoding="utf-8"))
            scored = [f for f in unit["frame_records"] if f.get("scored_frame") and f.get("status") == "PASS"]
            pool = [f for f in scored if f.get("production_status") == "SELECTED"]
            rows.append(
                {
                    "candidate": unit["candidate_id"], "member": unit["member_identity"], "stage": unit["stage"], "scored_frames": len(scored), "pool_frames": len(pool),
                    "model_H_px_median_pool": median(float(f["simulated_H_pixels"]) for f in pool), "model_W_px_median_pool": median(float(f["simulated_W_pixels"]) for f in pool),
                    "camera_H_px_median": median(float(f["experimental_H_pixels"]) for f in scored), "camera_W_px_median": median(float(f["experimental_W_pixels"]) for f in scored),
                }
            )
    rows.sort(key=lambda r: (r["candidate"], r["member"]))
    return C.write_csv(SOURCE_DIR / "candidate_coupon_sizes.csv", rows)
