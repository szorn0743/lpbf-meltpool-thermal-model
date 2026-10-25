"""Image figures for the thesis: F2 (camera H/W extraction) and F12 (observation operators).

F2 re-measures one stored camera frame with the documented camera convention (lpbf.patch22_3_8_camera_step0.
measure_blob: pixels >= 150, largest 8-connected component, external contour, minimum-area rectangle). The canonical
camera H/W used everywhere else are the values stored with the dataset; the frame was chosen by the presentation
package's fixed rule, so its re-measurement agrees with the stored value within half a pixel.
F12 draws the committee package's recorded outlines (F13 sources) and its operator group table (T14).
"""
from __future__ import annotations

import cv2
import numpy as np

from lpbf.patch22_3_8_camera_step0 import measure_blob

import data as D
import style as S

THRESHOLD = 150


def _camera_steps(image: np.ndarray):
    mask = (image >= THRESHOLD).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    index = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    component = labels == index
    contours, _ = cv2.findContours(component.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    points = np.vstack([c.reshape(-1, 2) for c in contours]).astype(np.float32)
    rect = cv2.minAreaRect(points)
    box = cv2.boxPoints(rect).astype(float)
    return mask.astype(bool), component, contours[0].reshape(-1, 2).astype(float), box


def _sides(box: np.ndarray):
    """The rectangle's long side (H) and short side (W) as point pairs."""

    e0 = (box[0], box[1])
    e1 = (box[1], box[2])
    l0 = float(np.hypot(*(box[1] - box[0])))
    l1 = float(np.hypot(*(box[2] - box[1])))
    return (e0, l0, e1, l1) if l0 >= l1 else (e1, l1, e0, l0)


def _dimension(ax, p, q, box_center, text, color, *, offset=1.6, fontsize=7.5):
    p, q = np.asarray(p), np.asarray(q)
    mid = 0.5 * (p + q)
    normal = mid - box_center
    normal = normal / np.hypot(*normal)
    a, b = p + offset * normal, q + offset * normal
    ax.annotate("", xy=a, xytext=b, arrowprops=dict(arrowstyle="<->", color=color, lw=1.0, shrinkA=0, shrinkB=0))
    for end, base in ((a, p), (b, q)):
        ax.plot([base[0], end[0] + 0.3 * normal[0]], [base[1], end[1] + 0.3 * normal[1]], color=color, lw=0.6)
    t = mid + (offset + 0.7) * normal
    ha = "right" if normal[0] < -0.5 else ("left" if normal[0] > 0.5 else "center")
    va = "top" if normal[1] > 0.5 else ("bottom" if normal[1] < -0.5 else "center")
    ax.text(t[0], t[1], text, color="white", fontsize=fontsize, ha=ha, va=va, path_effects=S.text_halo())


def f2_extraction(plt):
    rows, arr = D.pipeline_frame()
    meta = rows[0]
    image = arr["camera_image"].astype(float)
    mask, component, contour, box = _camera_steps(arr["camera_image"])
    blob = measure_blob(arr["camera_image"], THRESHOLD)
    (h_side, h_len, w_side, w_len) = _sides(box)
    assert abs(h_len - blob["H_px"]) < 1e-4 and abs(w_len - blob["W_px"]) < 1e-4
    assert abs(blob["H_px"] - meta["camera_H_px"]) <= 0.5 and abs(blob["W_px"] - meta["camera_W_px"]) <= 0.5
    cy, cx = np.argwhere(component).mean(axis=0)
    half_w = 17
    x0 = int(round(cx)) - half_w
    xlim = (x0 - 0.5, x0 + 2 * half_w + 0.5)
    ylim = (23.5, -0.5)
    fig, axes = plt.subplots(2, 2, figsize=(S.FULL_W, 3.75))
    axes = axes.ravel()
    extent = (-0.5, 63.5, 23.5, -0.5)

    def base(ax, dim=1.0):
        ax.imshow(image * dim, cmap="gray", vmin=0, vmax=255, extent=extent, interpolation="nearest")
        ax.set_xlim(*xlim)
        ax.set_ylim(*ylim)
        ax.set_xticks([])
        ax.set_yticks([])
        ax.grid(False)
        for sp in ax.spines.values():
            sp.set_visible(True)
            sp.set_color(S.AXIS)
            sp.set_linewidth(0.6)

    ax = axes[0]
    base(ax)
    bar_px = 50 / S.UM_PER_PX
    bx = xlim[1] - 2.0 - bar_px
    ax.plot([bx, bx + bar_px], [22.0, 22.0], color="white", lw=2.0)
    ax.text(bx + bar_px / 2, 21.2, "50 µm", color="white", fontsize=7, ha="center", va="bottom")
    sm = plt.cm.ScalarMappable(cmap="gray", norm=plt.Normalize(0, 255))
    cax = ax.inset_axes([1.02, 0.0, 0.03, 1.0])
    cb = fig.colorbar(sm, cax=cax, ticks=[0, 150, 255])
    cb.ax.tick_params(labelsize=6.5, length=2)
    cb.outline.set_linewidth(0.5)
    S.panel(ax, "a", "Coaxial frame (counts)")
    ax = axes[1]
    base(ax, dim=0.35)
    rgba = np.zeros((24, 64, 4))
    other = mask & ~component
    rgba[component] = (*plt.matplotlib.colors.to_rgb(S.CAMERA), 0.85)
    rgba[other] = (0.75, 0.75, 0.75, 0.85)
    ax.imshow(rgba, extent=extent, interpolation="nearest")
    for x in np.arange(xlim[0], xlim[1] + 1):
        ax.axvline(x, color="white", lw=0.25, alpha=0.25)
    for y in np.arange(-0.5, 24):
        ax.axhline(y, color="white", lw=0.25, alpha=0.25)
    S.panel(ax, "b", f"Pixels ≥ {THRESHOLD}, largest component")
    ax = axes[2]
    base(ax, dim=0.35)
    closed = np.vstack([contour, contour[:1]])
    ax.plot(closed[:, 0], closed[:, 1], color="white", lw=0.9, marker="o", ms=1.6, label="external contour")
    rect = np.vstack([box, box[:1]])
    ax.plot(rect[:, 0], rect[:, 1], color=S.CAMERA_ON_DARK, lw=1.6, path_effects=S.halo())
    S.panel(ax, "c", "Contour and minimum-area rectangle")
    ax = axes[3]
    base(ax, dim=0.35)
    ax.plot(rect[:, 0], rect[:, 1], color=S.CAMERA_ON_DARK, lw=1.6, path_effects=S.halo())
    center = box.mean(axis=0)
    _dimension(ax, *h_side, center, f"H = {h_len:.1f} px ({h_len * S.UM_PER_PX:.0f} µm)", "white", offset=1.5)
    _dimension(ax, *w_side, center, f"W = {w_len:.1f} px\n({w_len * S.UM_PER_PX:.0f} µm)", "white", offset=1.5)
    S.panel(ax, "d", "H = long side, W = short side")
    fig.subplots_adjust(wspace=0.16, hspace=0.28)
    S.write_csv(S.SOURCE_DIR / "F2_extraction.csv",
                ["member", "frame_index", "scan_track_id", "threshold", "H_px_remeasured", "W_px_remeasured",
                 "H_px_stored", "W_px_stored", "component_count", "area_px", "box_x", "box_y"],
                [[meta["member"], meta["frame_index"], meta["scan_track_id"], THRESHOLD, blob["H_px"], blob["W_px"],
                  meta["camera_H_px"], meta["camera_W_px"], blob["component_count"], blob["area_px"],
                  " ".join(f"{v:.3f}" for v in box[:, 0]), " ".join(f"{v:.3f}" for v in box[:, 1])]])
    S.save(fig, "F2_extraction")
    plt.close(fig)
    return {"member": meta["member"], "frame": meta["frame_index"], "track": meta["scan_track_id"],
            "power": meta["power_W"] if "power_W" in meta else None, "condition": meta["condition"],
            "ved": meta["ved_J_mm3"], "H": blob["H_px"], "W": blob["W_px"], "H_stored": meta["camera_H_px"],
            "W_stored": meta["camera_W_px"], "components": blob["component_count"]}


# ---------------------------------------------------------------------- F12

OPS = (("liquidus", "Model liquidus", S.MODEL, "o", S.MODEL),
       ("lam850_uniform_sig0.0", "Simulated camera, PSF 0 px", S.SYNTH, "s", S.SYNTH),
       ("lam850_uniform_sig2.0", "Simulated camera, PSF 2 px", S.SYNTH, "s", S.WHITE))
GROUPS = (("calibration", "Calibration"), ("in_window_held_out", "Held out,\nin window"),
          ("out_of_window_all", "Out of\nwindow"))


def f12_operators(plt):
    frames = sorted(D.operator_frames(), key=lambda r: r["ved_J_mm3"])
    outlines = D.operator_outlines()
    pixels = D.operator_camera_pixels()
    groups = D.operator_groups()
    fig = plt.figure(figsize=(S.FULL_W, 3.75))
    gs = fig.add_gridspec(2, 3, height_ratios=[0.62, 1.35], hspace=0.78, wspace=0.42)
    src = []
    for i, fr in enumerate(frames):
        ax = fig.add_subplot(gs[0, i])
        m = fr["member"]
        ax.imshow(pixels[m], cmap="gray", vmin=0, vmax=255, extent=(-0.5, 63.5, 23.5, -0.5),
                  interpolation="nearest")
        xmin = -0.5
        for op, color, lw in (("liquidus", S.MODEL_ON_DARK, 1.2), ("synthetic_150", S.SYNTH_ON_DARK, 1.3),
                              ("camera_150", S.CAMERA_ON_DARK, 1.3)):
            pts = outlines.get((m, op))
            if pts is None or len(pts) == 0:
                continue
            closed = np.vstack([pts, pts[:1]])
            ax.plot(closed[:, 0], closed[:, 1], color=color, lw=lw, path_effects=S.halo(width=2.2))
            xmin = min(xmin, float(pts[:, 0].min()) - 1)
            for v, (x, y) in enumerate(pts):
                src.append(["outline", m, op, v, float(x), float(y)])
        ax.set_xlim(xmin, 63.5)
        ax.set_ylim(23.5, -0.5)
        ax.set_xticks([])
        ax.set_yticks([])
        ax.grid(False)
        for sp in ax.spines.values():
            sp.set_visible(True)
            sp.set_color(S.AXIS)
            sp.set_linewidth(0.6)
        letter = "abc"[i]
        S.panel(ax, letter, f"{fr['ved_J_mm3']:.1f} J/mm³")
        ax.text(0.0, -0.06,
                f"camera {fr['camera_H_px_remeasured']:.1f} × {fr['camera_W_px_remeasured']:.1f} px\n"
                f"liquidus {fr['model_H_px']:.1f} × {fr['model_W_px']:.1f} px\n"
                f"simulated camera {fr['synthetic_H_px']:.1f} × {fr['synthetic_W_px']:.1f} px",
                transform=ax.transAxes, ha="left", va="top", fontsize=6.6, color=S.INK, linespacing=1.15)
        src.append(["frame", m, fr["condition"], fr["frame_index"], fr["camera_H_px_remeasured"],
                    fr["camera_W_px_remeasured"], fr["model_H_px"], fr["model_W_px"], fr["synthetic_H_px"],
                    fr["synthetic_W_px"], fr["T150_K"]])
    metrics = (("median_H_ratio", "H ratio to camera"), ("median_W_ratio", "W ratio to camera"),
               ("shape_ratio", "H/W ratio to camera"))
    out = {}
    for j, (key, label) in enumerate(metrics):
        ax = fig.add_subplot(gs[1, j])
        ax.axhline(1.0, color=S.INK_2, lw=0.8)
        for gi, (g, glabel) in enumerate(GROUPS):
            for oi, (op, oplabel, color, marker, face) in enumerate(OPS):
                row = next(r for r in groups if r["group"] == g and r["operator"] == op)
                ax.scatter(gi + (oi - 1) * 0.22, row[key], s=22, marker=marker, facecolor=face, edgecolor=color,
                           lw=1.0, zorder=3, label=oplabel if (gi == 0 and j == 0) else "_")
                src.append(["group", g, op, key, row[key], row["coverage"], row["frames"]])
                out[(g, op, key)] = row[key]
                out[(g, op, "coverage")] = row["coverage"]
        ax.set_yscale("log")
        ax.set_yticks([0.25, 0.5, 1, 2, 3])
        ax.set_yticklabels(["0.25", "0.5", "1", "2", "3"])
        ax.minorticks_off()
        ax.set_ylim(0.2, 3.6)
        ax.set_xticks(range(len(GROUPS)))
        ax.set_xticklabels([g[1] for g in GROUPS], fontsize=7)
        ax.set_xlim(-0.5, len(GROUPS) - 0.5)
        ax.grid(axis="x", visible=False)
        S.panel(ax, "def"[j], label)
    from matplotlib.lines import Line2D

    handles = [Line2D([], [], color=S.CAMERA, lw=1.3, label="Camera, threshold 150"),
               Line2D([], [], color=S.MODEL, lw=1.2, marker="o", ms=4, label="Model liquidus"),
               Line2D([], [], color=S.SYNTH, lw=1.2, marker="s", ms=4, label="Simulated camera, PSF 0 px"),
               Line2D([], [], ls="none", marker="s", ms=4, mfc=S.WHITE, mec=S.SYNTH,
                      label="Simulated camera, PSF 2 px")]
    fig.legend(handles=handles, loc="lower center", ncol=4, bbox_to_anchor=(0.5, -0.05), fontsize=7.2,
               columnspacing=1.0, handlelength=1.8)
    S.write_csv(S.SOURCE_DIR / "F12_operators.csv",
                ["kind", "a", "b", "c", "d", "e", "f", "g", "h", "i", "j"], src)
    S.save(fig, "F12_operators")
    plt.close(fig)
    out["frames"] = [(f["member"], f["ved_J_mm3"], f["frame_index"]) for f in frames]
    out["T150"] = sorted({f["T150_K"] for f in frames})
    return out


# ---------------------------------------------------------------------- F13

LEVELS_MEMBER = "20260730:part_3"


def f13_thresholds_and_isotherms(plt):
    """The presentation figure 'Camera thresholds and model isotherms' in thesis style (owner, 2026-10-23): one frame,
    camera outlines at six thresholds and model outlines at the isotherms that stay inside the model window, with the
    size at each level. Sources are the presentation package's levels_feature_frame.csv / _outlines.npz."""

    from matplotlib.patches import Rectangle

    rows = {r["member"]: r for r in D.representative_frames()}
    row = rows[LEVELS_MEMBER]
    camera_image = D.representative_arrays()[LEVELS_MEMBER.replace(":", "_") + "__camera_image"]
    levels = D.read_csv(D.PRESENTATION_SOURCE / "levels_feature_frame.csv")
    outlines = np.load(D.PRESENTATION_SOURCE / "levels_feature_outlines.npz")
    cam = [r for r in levels if r["source"] == "camera"]
    mod = [r for r in levels if r["source"] == "model" and not r["touches_edge"]]
    dropped = [r for r in levels if r["source"] == "model" and r["touches_edge"]]
    cam_hw = [r["H_px"] / r["W_px"] for r in cam]
    mod_hw = [r["H_px"] / r["W_px"] for r in mod]
    # Guards for the caption: the camera stays near round, every drawn model isotherm is more elongated than any
    # camera threshold, and the scored levels (150 counts, the liquidus) are among the drawn ones.
    assert max(cam_hw) < min(mod_hw) and max(cam_hw) < 1.6
    assert any(r["level"] == 150 for r in cam)
    assert any(abs(r["level"] - row["liquidus_K"]) < 1e-6 for r in mod)
    cam_colors = [S.ORANGE_RAMP[i] for i in (3, 4, 6, 7, 9, 11)]
    mod_colors = [S.BLUE_RAMP[i] for i in (3, 5, 7, 9, 11)][-len(mod):]
    xlim, ylim = (-18.5, 66.5), (-5.5, 29.5)
    fig = plt.figure(figsize=(S.FULL_W, 3.7))
    gs = fig.add_gridspec(2, 2, width_ratios=[1.6, 1], hspace=0.55, wspace=0.22, left=0.0, right=1.0, top=0.93,
                          bottom=0.1)
    ax_c, ax_m = fig.add_subplot(gs[0, 0]), fig.add_subplot(gs[1, 0])

    def frame(ax):
        ax.set_xlim(*xlim)
        ax.set_ylim(ylim[1], ylim[0])
        ax.set_aspect("equal")
        ax.set_xticks([])
        ax.set_yticks([])
        ax.grid(False)
        for sp in ax.spines.values():
            sp.set_visible(False)

    frame(ax_c)
    rows_px, cols_px = camera_image.shape
    ax_c.imshow(camera_image, cmap="gray", vmin=0, vmax=255, interpolation="nearest",
                extent=(-0.5, cols_px - 0.5, rows_px - 0.5, -0.5), zorder=1)
    ax_c.add_patch(Rectangle((-0.5, -0.5), cols_px, rows_px, fill=False, edgecolor=S.AXIS, lw=0.7, zorder=2))
    ax_c.text(-0.5, rows_px + 0.3, "camera field of view", fontsize=6.6, color=S.INK_2, va="top")
    src = []
    for r, color in zip(cam, cam_colors):
        pts = outlines[f"camera_{r['level']}"]
        closed = np.vstack([pts, pts[:1]])
        ax_c.plot(closed[:, 0], closed[:, 1], color=color, lw=1.6 if r["level"] == 150 else 0.9, zorder=5)
        src.append(["camera", r["level"], "counts", r["H_px"] * S.UM_PER_PX, r["W_px"] * S.UM_PER_PX,
                    r["H_px"] / r["W_px"], True])
    frame(ax_m)
    wide, extent = outlines["model_wide_K"], tuple(outlines["model_wide_extent"])
    ax_m.imshow(wide, cmap="gray", vmin=300.0, vmax=2200.0, interpolation="bilinear", extent=extent, zorder=1)
    ny, nx = wide.shape
    gx = extent[0] + (np.arange(nx) + 0.5) * (extent[1] - extent[0]) / nx
    gy = extent[3] + (np.arange(ny) + 0.5) * (extent[2] - extent[3]) / ny
    for r, color in zip(mod, mod_colors):
        is_liq = abs(r["level"] - row["liquidus_K"]) < 1e-6
        ax_m.contour(*np.meshgrid(gx, gy), wide, levels=[r["level"]], colors=[color], linewidths=1.6 if is_liq else 0.9,
                     zorder=5)
        src.append(["model", r["level"], "K", r["H_px"] * S.UM_PER_PX, r["W_px"] * S.UM_PER_PX,
                    r["H_px"] / r["W_px"], True])
    for r in dropped:
        src.append(["model", r["level"], "K", r["H_px"] * S.UM_PER_PX, r["W_px"] * S.UM_PER_PX,
                    r["H_px"] / r["W_px"], False])
    ax_m.add_patch(Rectangle((-0.5, -0.5), cols_px, rows_px, fill=False, edgecolor="#ffffff", lw=0.7,
                             ls=(0, (3, 2)), zorder=6, alpha=0.85))
    ax_m.text(cols_px - 1.0, -1.0, "camera field of view", fontsize=6.6, color="#ffffff", va="bottom", ha="right",
              path_effects=S.text_halo())
    bar = 100 / S.UM_PER_PX
    bx, by = xlim[1] - 2.5 - bar, ylim[1] - 2.0
    ax_m.plot([bx, bx + bar], [by, by], color="#ffffff", lw=1.6, solid_capstyle="butt", zorder=8,
              path_effects=S.halo())
    ax_m.text(bx + bar / 2, by - 0.8, "100 µm", color="#ffffff", ha="center", va="bottom", fontsize=6.6, zorder=8,
              path_effects=S.text_halo())
    S.panel(ax_c, "a", "Camera outlines at six brightness thresholds")
    S.panel(ax_m, "c", "Model outlines at isotherms")
    for ax, data, colors, hue, xlabel, letter, title in (
            (fig.add_subplot(gs[0, 1]), cam, cam_colors, S.CAMERA, "Threshold (counts)", "b", "Camera size"),
            (fig.add_subplot(gs[1, 1]), mod, mod_colors, S.MODEL, "Isotherm (K)", "d", "Model size")):
        x = [float(r["level"]) for r in data]
        h = [r["H_px"] * S.UM_PER_PX for r in data]
        w = [r["W_px"] * S.UM_PER_PX for r in data]
        ax.plot(x, h, color=hue, lw=1.2, zorder=2)
        ax.plot(x, w, color=hue, lw=1.2, ls=(0, (1, 1.5)), zorder=2)
        ax.scatter(x, h, c=colors, s=18, edgecolors=S.WHITE, linewidths=0.6, zorder=3)
        ax.scatter(x, w, c=colors, s=18, edgecolors=S.WHITE, linewidths=0.6, zorder=3, marker="s")
        span = x[-1] - x[0]
        ax.text(x[0] - 0.06 * span, h[0], "H", color=S.INK, fontsize=8, ha="right", va="center", fontweight="bold")
        ax.text(x[0] - 0.06 * span, w[0], "W", color=S.INK, fontsize=8, ha="right", va="center", fontweight="bold")
        top = max(h) * 1.12
        ax.set_ylim(-0.24 * top, top)
        ax.set_xlim(x[0] - 0.16 * span, x[-1] + 0.07 * span)
        ax.axhline(0, color=S.AXIS, lw=0.6, zorder=1)
        ax.text(x[0] - 0.06 * span, -0.13 * top, "H/W", color=S.INK_2, fontsize=6.6, ha="right", va="center")
        for xi, hi_, wi in zip(x, h, w):
            ax.text(xi, -0.13 * top, f"{hi_ / wi:.1f}", fontsize=6.6, color=S.INK, ha="center", va="center")
        ax.set_yticks([v for v in ax.get_yticks() if 0 <= v <= top])
        ax.set_xlabel(xlabel)
        ax.set_ylabel("Size (µm)")
        S.panel(ax, letter, title)
    S.write_csv(S.SOURCE_DIR / "F13_thresholds_and_isotherms.csv",
                ["source", "level", "unit", "H_um", "W_um", "HW", "drawn"], src)
    S.save(fig, "F13_thresholds_and_isotherms")
    plt.close(fig)
    return {"member": LEVELS_MEMBER, "frame": row["frame_index"], "dropped": [r["level"] for r in dropped]}


ALL = {"F2": f2_extraction, "F12": f12_operators, "F13": f13_thresholds_and_isotherms}
