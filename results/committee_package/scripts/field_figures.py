"""F13: one camera frame per representative condition with four boundaries drawn on it.

On the camera's own 64 x 24 crop:
- the camera's threshold-150 blob (the supplied H/W convention);
- the model liquidus (c1 field, bilinear on 4 µm sub-samples);
- the reading-S synthetic camera at threshold 150 (850 nm, uniform emissivity, PSF 0, T150 = 1950 K);
- the width-matched isotherm: the highest model isotherm whose W reaches the camera's W (Patch 22.3.8 operator).
The model field is placed exactly as the reading-S stage placed it (``lpbf.synthetic_camera``: Step-0 image
mapping, crop chosen so that the synthetic threshold-150 centroid sits at the camera centroid). Each outline is the
boundary of the largest connected component of its mask, the convention every H/W in the package uses.

The source step reads the external coupon HDF5 files (sha256-checked against the characterization) and the
gitignored c1 field files; it is skipped, and the committed sources are kept, when they are absent. The render needs
only ``figures/source/F13_*``.

Frame choice (fixed rule, not a search): in each coupon, the scan track at the median track number among tracks
with at least 10 scored frames; in it, the middle scored frame; if that frame has no predicted pool, no synthetic
blob or no width-matched isotherm, the nearest frame in the track that has all three.
"""
from __future__ import annotations

import math
from typing import Any, Mapping

import numpy as np

import common as C
from figures import AXIS, INK, INK_2, MODEL_HUE, SOURCE_DIR, SURFACE, _save

COUPONS = (("20260904:part_6", "Low VED"), ("20260730:part_3", "In window"), ("20260904:part_4", "High VED"))
CASE = {"wavelength_nm": 850.0, "emissivity": "uniform", "sigma_px": 0.0, "T150_K": 1950.0}
OPERATOR_STYLE = {
    "camera_150": (INK, "Camera, threshold 150"),
    "liquidus": (MODEL_HUE, "Model liquidus (c1)"),
    "synthetic_150": ("#eb6834", "Synthetic camera, threshold 150"),
    "width_matched": ("#1baf7a", "Width-matched isotherm"),
}


def sources_available() -> bool:
    return C.COUPON_DATA_DIR.is_dir() and all((C.FIELDS_DIR / f"{C.CANDIDATE}__{m.replace(':', '_')}.npz").is_file() for m, _ in COUPONS)


def _outline(mask: np.ndarray) -> np.ndarray | None:
    import cv2

    mask = np.ascontiguousarray(mask, dtype=np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if count < 2:
        return None
    index = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    contours, _ = cv2.findContours((labels == index).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    return max(contours, key=len).reshape(-1, 2).astype(float)


def _choose_frame(member: str, scored: list[Mapping[str, Any]], ok) -> Mapping[str, Any]:
    tracks: dict[int, list] = {}
    for f in scored:
        tracks.setdefault(f["scan_track_id"], []).append(f)
    long = sorted(t for t, fs in tracks.items() if len(fs) >= 10)
    track = long[len(long) // 2]
    frames = sorted(tracks[track], key=lambda f: f["frame_index"])
    middle = len(frames) // 2
    for offset in sorted(range(len(frames)), key=lambda k: (abs(k - middle), k)):
        if ok(frames[offset]):
            return frames[offset]
    raise RuntimeError(f"{member}: no frame in track {track} has all four boundaries")


def write_sources(analysis: Mapping[str, Any]) -> list:
    from lpbf.camera_observations import _read_member_frames, measure_blob
    import lpbf.synthetic_camera as cam

    mapping = cam.load_image_mapping()
    offsets = cam.subsample_offsets_um(mapping["full_circle_constant_deg"])
    synthetic = {}
    for r in C.read_csv(C.SYNTHETIC_FRAMES):
        if r["case_id"] == "lam850_uniform_sig0.0" and r["member_identity"] in dict(COUPONS):
            synthetic[(r["member_identity"], int(r["frame_index"]))] = r
    pixels, outlines, meta = [], [], []
    for member, label in COUPONS:
        acquisition_set, part = C.member_key(member)
        h5 = C.COUPON_DATA_DIR / f"part_{part}_{acquisition_set}.h5"
        if C.sha256_file(h5) != C.characterization_audit(member)["input_file_sha256"]:
            raise RuntimeError(f"{h5.name}: sha256 differs from the characterization record")
        with np.load(C.FIELDS_DIR / f"{C.CANDIDATE}__{member.replace(':', '_')}.npz", allow_pickle=False) as npz:
            arrays = {k: npz[k] for k in ("frame_index", "top_surface_temperature_K", "source_center_x_mm", "source_center_y_mm", "cell_size_um", "liquidus_temperature_K")}
        position = {int(f): k for k, f in enumerate(arrays["frame_index"])}
        liquidus = float(arrays["liquidus_temperature_K"])
        unit = float(cam.count_level_unit(CASE["T150_K"], wavelength_nm=CASE["wavelength_nm"], emissivity_model=CASE["emissivity"], liquidus_K=liquidus))
        cache: dict[int, dict[str, Any] | None] = {}

        def build(frame_row: Mapping[str, Any]) -> dict[str, Any] | None:
            frame = int(frame_row["frame_index"])
            if frame in cache:
                return cache[frame]
            cache[frame] = None
            s = synthetic.get((member, frame))
            if frame_row["no_pool"] or s is None or s["synthetic_status"] != "PAIRED":
                return None
            image = _read_member_frames(h5, "layer53", [frame])["images"][0]
            blob = measure_blob(image, 150)
            if blob is None:
                return None
            k = position[frame]
            t_sub, inside_sub = cam.render_temperature_subsamples(
                arrays["top_surface_temperature_K"][k], source_x_mm=float(arrays["source_center_x_mm"][k]), source_y_mm=float(arrays["source_center_y_mm"][k]),
                cell_um=float(arrays["cell_size_um"]), offsets=offsets,
            )
            radiance = cam.pixel_mean(cam.planck_relative(t_sub, CASE["wavelength_nm"]))  # uniform emissivity, PSF 0
            level = cam.REFERENCE_THRESHOLD * unit  # compared exactly as measure_levels does
            reference = cam.measure_component(radiance >= level)
            if reference is None:
                return None
            ox = cam._round_half_up(reference["centroid_x"] - blob["centroid_x"])
            oy = cam._round_half_up(reference["centroid_y"] - blob["centroid_y"])
            rows_, cols_ = cam.CAMERA_ROWS, cam.CAMERA_COLS
            if ox < 0 or oy < 0 or ox + cols_ > radiance.shape[1] or oy + rows_ > radiance.shape[0]:
                return None
            t_image = cam.pixel_mean(t_sub)
            matched = cam.level_free_crossing(t_image, cam.pixel_all(inside_sub), blob["W_px"])
            if matched["status"] != "DEFINED":
                return None
            sub = cam.SUBSAMPLES
            # Model boundaries on the full render (they can extend past the camera crop), in crop pixel coordinates.
            to_px = lambda xy: (xy + 0.5) / sub - 0.5 - np.array([ox, oy], dtype=float)
            synth_blob = cam.measure_component(radiance[oy : oy + rows_, ox : ox + cols_] >= level)
            shapes = {
                "camera_150": _outline(image >= 150),
                "liquidus": None if (o := _outline(t_sub >= liquidus)) is None else to_px(o),
                "synthetic_150": _outline(radiance[oy : oy + rows_, ox : ox + cols_] >= level),
                "width_matched": None if (o := _outline(t_sub >= matched["level_K"])) is None else to_px(o),
            }
            if any(v is None for v in shapes.values()):
                return None
            cache[frame] = {
                "image": np.asarray(image), "shapes": shapes, "level_K": matched["level_K"], "matched_H_px": matched["H_px"], "matched_W_px": matched["W_px"],
                "camera_H_px": blob["H_px"], "camera_W_px": blob["W_px"], "synthetic_H_px": synth_blob["H_px"] if synth_blob else None, "synthetic_W_px": synth_blob["W_px"] if synth_blob else None,
                "synthetic_record_H_px": float(s["simulated_H_pixels"]), "synthetic_record_W_px": float(s["simulated_W_pixels"]),
            }
            return cache[frame]

        chosen = _choose_frame(member, analysis["frames_by_member"][member], lambda f: build(f) is not None)
        got = cache[int(chosen["frame_index"])]
        if got["synthetic_H_px"] is None or not (math.isclose(got["synthetic_H_px"], got["synthetic_record_H_px"], rel_tol=1e-5) and math.isclose(got["synthetic_W_px"], got["synthetic_record_W_px"], rel_tol=1e-5)):
            raise RuntimeError(f"{member}: re-rendered synthetic H/W differs from the reading-S record")
        image = got["image"]
        for (i, j), value in np.ndenumerate(image):
            pixels.append({"member": member, "row": i, "col": j, "counts": int(value)})
        for name, xy in got["shapes"].items():
            for k, (x, y) in enumerate(xy):
                outlines.append({"member": member, "operator": name, "vertex": k, "x_px": float(x), "y_px": float(y)})
        meta.append(
            {
                "member": member, "panel": label, "condition": analysis["record"][member]["condition"], "ved_J_mm3": analysis["record"][member]["ved_J_mm3"],
                "scan_track_id": chosen["scan_track_id"], "frame_index": chosen["frame_index"], "track_position": chosen["track_position"],
                "camera_H_px_supplied": float(chosen["cam_H_px"]), "camera_W_px_supplied": float(chosen["cam_W_px"]),
                "camera_H_px_remeasured": got["camera_H_px"], "camera_W_px_remeasured": got["camera_W_px"],
                "model_H_px": float(chosen["sim_H_px"]), "model_W_px": float(chosen["sim_W_px"]), "liquidus_K": liquidus,
                "synthetic_H_px": got["synthetic_H_px"], "synthetic_W_px": got["synthetic_W_px"], "T150_K": CASE["T150_K"],
                "width_matched_level_K": got["level_K"], "width_matched_H_px": got["matched_H_px"], "width_matched_W_px": got["matched_W_px"],
                "image_mapping_constant_deg": mapping["full_circle_constant_deg"],
            }
        )
    return [
        C.write_csv(SOURCE_DIR / "F13_camera_pixels.csv", pixels),
        C.write_csv(SOURCE_DIR / "F13_outlines.csv", outlines),
        C.write_csv(SOURCE_DIR / "F13_frames.csv", meta),
    ]


def render(plt) -> list:
    from matplotlib.colors import LinearSegmentedColormap
    from matplotlib.lines import Line2D

    pixels = C.read_csv(SOURCE_DIR / "F13_camera_pixels.csv")
    outlines = C.read_csv(SOURCE_DIR / "F13_outlines.csv")
    meta = C.read_csv(SOURCE_DIR / "F13_frames.csv")
    from matplotlib.patches import Rectangle

    gray = LinearSegmentedColormap.from_list("camera", (SURFACE, "#c3c2b7", INK_2))
    fig, axes = plt.subplots(len(meta), 1, figsize=(6.5, 2.1 * len(meta)))
    for ax, m in zip(np.atleast_1d(axes), meta):
        member = m["member"]
        px = [r for r in pixels if r["member"] == member]
        rows = max(int(r["row"]) for r in px) + 1
        cols = max(int(r["col"]) for r in px) + 1
        img = np.zeros((rows, cols))
        for r in px:
            img[int(r["row"]), int(r["col"])] = float(r["counts"])
        ax.imshow(img, cmap=gray, vmin=0, vmax=255, interpolation="nearest", extent=(-0.5, cols - 0.5, rows - 0.5, -0.5), zorder=1)
        ax.add_patch(Rectangle((-0.5, -0.5), cols, rows, fill=False, edgecolor=AXIS, linewidth=1.0, zorder=2))
        xmin, xmax, ymin, ymax = -0.5, cols - 0.5, -0.5, rows - 0.5
        for name, (color, _) in OPERATOR_STYLE.items():
            pts = sorted((r for r in outlines if r["member"] == member and r["operator"] == name), key=lambda r: int(r["vertex"]))
            xs = [float(r["x_px"]) for r in pts] + [float(pts[0]["x_px"])]
            ys = [float(r["y_px"]) for r in pts] + [float(pts[0]["y_px"])]
            ax.plot(xs, ys, color=color, linewidth=1.3 if name != "camera_150" else 1.6, zorder=3)
            xmin, xmax, ymin, ymax = min(xmin, min(xs) - 1), max(xmax, max(xs) + 1), min(ymin, min(ys) - 1), max(ymax, max(ys) + 1)
        ax.set_xlim(xmin, xmax)
        ax.set_ylim(ymax, ymin)
        ax.set_aspect("equal")
        ax.set_xticks([])
        ax.set_yticks([])
        ax.grid(False)
        for s in ax.spines.values():
            s.set_visible(False)
        ax.set_title(f"{m['panel']}: {member}, {m['condition']} ({float(m['ved_J_mm3']):.1f} J/mm³), track {m['scan_track_id']}, frame {m['frame_index']}", loc="left", fontsize=8)
        text = (
            f"H × W (px)\ncamera {float(m['camera_H_px_supplied']):.1f} × {float(m['camera_W_px_supplied']):.1f}\nliquidus {float(m['model_H_px']):.1f} × {float(m['model_W_px']):.1f}\n"
            f"synthetic {float(m['synthetic_H_px']):.1f} × {float(m['synthetic_W_px']):.1f}\nwidth-matched {float(m['width_matched_H_px']):.1f} × {float(m['width_matched_W_px']):.1f}\n({float(m['width_matched_level_K']):.0f} K)"
        )
        ax.text(1.01, 0.98, text, transform=ax.transAxes, fontsize=6.5, color=INK_2, va="top", ha="left", linespacing=1.3)
    handles = [Line2D([], [], color=color, linewidth=1.6, label=label) for color, label in OPERATOR_STYLE.values()]
    fig.legend(handles=handles, loc="lower center", bbox_to_anchor=(0.45, -0.04), ncol=4, fontsize=7, handletextpad=0.4, columnspacing=1.2)
    fig.suptitle("Melt pool boundaries on one camera frame", x=0.0, ha="left", fontsize=10, fontweight="bold", color=INK)
    fig.text(0.0, -0.09, "Framed: the camera image (counts 0–255; darker = brighter pixel), its 64 × 24 px crop at 8 µm/px nominal. The model field is placed as in reading S; the liquidus and width-matched\noutlines are drawn on the full model render and may leave the crop. Outlines: largest connected component of each mask. The liquidus and the camera's threshold-150 blob are\ndifferent physical boundaries (A12, A24); agreement under one operator is not agreement under another.", fontsize=6.5, color=INK_2)
    fig.subplots_adjust(right=0.8, hspace=0.35)
    out = _save(fig, "F13_measurement_operators")
    plt.close(fig)
    return out
