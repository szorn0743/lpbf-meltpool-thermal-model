"""Schematic figures for the thesis: F3 (scoring and aggregation), F4 (numerical model) and F5 (calibration workflow).

Every count on the schematics is read from the committee data (T04 data accounting, D3, D4, D6); the model
quantities on F4 are the fixed controls of committee T05. F4(b) draws a recorded confirm_c1 frame from the
presentation package sources (the scored liquidus component and its production box).
"""
from __future__ import annotations

import numpy as np
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Polygon

import data as D
import style as S

FS = 7.4


def _box(ax, x, y, w, h, text, *, face=S.WHITE, edge=S.INK_2, lw=0.8, fs=FS, weight="normal", color=S.INK,
         ha="center", pad=0.6, ls="-"):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0,rounding_size={pad}", facecolor=face,
                                edgecolor=edge, lw=lw, ls=ls, zorder=2))
    tx = x + w / 2 if ha == "center" else x + 1.2
    ax.text(tx, y + h / 2, text, ha=ha, va="center", fontsize=fs, color=color, fontweight=weight, zorder=3,
            linespacing=1.15)


def _arrow(ax, p, q, *, color=S.INK_2, lw=0.8, style="-|>", ms=6, ls="-", connection="arc3"):
    ax.add_patch(FancyArrowPatch(p, q, arrowstyle=style, mutation_scale=ms, color=color, lw=lw, ls=ls, zorder=1,
                                 shrinkA=0, shrinkB=0, connectionstyle=connection))


def _canvas(plt, w, h):
    fig = plt.figure(figsize=(w, h))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100 * h / w)
    ax.set_aspect("equal")
    ax.axis("off")
    return fig, ax


def _fmt(n) -> str:
    return f"{int(n):,}"


# ---------------------------------------------------------------------- F3


def f3_scoring_hierarchy(plt):
    """Qualitative schematic (owner, 2026-10-23): descriptive labels only, no counts, values or formulas."""

    fig, ax = _canvas(plt, S.FULL_W, 3.3)
    ax.set_ylim(0, 51.5)
    ax.text(0.5, 51.2, "(a) Observation and scoring", fontsize=9.5, va="top", color=S.INK)
    ax.text(46.5, 51.2, "(b) Hierarchical aggregation", fontsize=9.5, va="top", color=S.INK)
    steps = [
        ("Camera frames synchronized\nto the process record", S.WHITE),
        ("Frames on laser-on rows\nwithin a scan track", S.WHITE),
        ("Eligible frames: finite, non-negative\ncamera H and W", S.WHITE),
        ("Track-edge rule: first and last eligible\nframe of each track excluded", S.NEUTRAL),
        ("Frames with undefined model geometry\nexcluded and counted against coverage", S.NEUTRAL),
        ("Scored Frames", S.BAND),
    ]
    y = 47.0
    h = 6.0
    src = []
    for i, (text, face) in enumerate(steps):
        _box(ax, 1.0, y - h, 41.0, h, text, face=face, fs=7.0, weight="bold" if i == len(steps) - 1 else "normal")
        if i < len(steps) - 1:
            _arrow(ax, (21.5, y - h), (21.5, y - h - 1.6))
        y -= h + 1.6
        src.append(["a", i + 1, text.replace("\n", " ")])
    levels = [
        ("Scored frame", "log ratio of model to camera,\nfor H and for W"),
        ("Scan track", "mean squared log ratio\nover the track's frames"),
        ("Coupon", "mean over the coupon's tracks"),
        ("Process condition", "mean over replicate coupons\nof the same condition"),
        ("Analysis group", "mean over the group's\nunique conditions"),
    ]
    y = 47.0
    for i, (name, rule) in enumerate(levels):
        _box(ax, 47.0, y - h, 22.0, h, name, face=S.WHITE if i < len(levels) - 1 else S.BAND, fs=7.0)
        ax.text(70.5, y - h / 2, rule, fontsize=6.8, va="center", ha="left", color=S.INK_2, linespacing=1.15)
        if i < len(levels) - 1:
            _arrow(ax, (58.0, y - h), (58.0, y - h - 1.6))
        y -= h + 1.6
        src.append(["b", i + 1, f"{name}: {rule.replace(chr(10), ' ')}"])
    ax.text(47.0, y - 0.6, "The group H and W errors are combined with\nequal weight into the objective J.\n"
            "Every level is an unweighted mean.", fontsize=7.2, va="top", ha="left", color=S.INK, linespacing=1.3)
    S.write_csv(S.SOURCE_DIR / "F3_scoring_hierarchy.csv", ["panel", "step", "label"], src)
    S.save(fig, "F3_scoring_hierarchy")
    plt.close(fig)
    return {"labels": [r[2] for r in src]}


# ---------------------------------------------------------------------- F4

ISO = (0.55, 0.30)  # oblique projection of the y axis
DEPTH_X = 2.0  # depth drawn exaggerated for legibility


def _p(x, y, z):
    return (x + ISO[0] * y, DEPTH_X * z + ISO[1] * y)


def f4_model_schematic(plt):
    rows = {r["member"]: r for r in D.representative_frames()}
    member = "20260730:part_3"
    row = rows[member]
    arr = D.representative_arrays()
    prefix = member.replace(":", "_") + "__"
    field = arr[prefix + "model_window_K"]
    scored = arr[prefix + "model_window_selected_K"] if prefix + "model_window_selected_K" in arr.files else field
    corners = arr[prefix + "model_corners"]
    fig = plt.figure(figsize=(S.FULL_W, 3.05))
    ax = fig.add_axes([0.0, 0.0, 0.57, 0.95])
    L, Wd, Dp = 1.584, 1.584, 0.336
    ax.set_aspect("equal")
    ax.axis("off")
    top = [_p(0, 0, 0), _p(L, 0, 0), _p(L, Wd, 0), _p(0, Wd, 0)]
    front = [_p(0, 0, 0), _p(L, 0, 0), _p(L, 0, -Dp), _p(0, 0, -Dp)]
    side = [_p(L, 0, 0), _p(L, Wd, 0), _p(L, Wd, -Dp), _p(L, 0, -Dp)]
    ax.add_patch(Polygon(front, closed=True, facecolor="#f4f3ef", edgecolor=S.INK_2, lw=0.8, zorder=1))
    ax.add_patch(Polygon(side, closed=True, facecolor="#e9e8e3", edgecolor=S.INK_2, lw=0.8, zorder=1))
    ax.add_patch(Polygon(top, closed=True, facecolor="#fbfaf7", edgecolor=S.INK_2, lw=0.8, zorder=1))
    # sparse grid on the top face (every 11 cells)
    for k in np.linspace(0, L, 10):
        ax.plot(*zip(_p(k, 0, 0), _p(k, Wd, 0)), color=S.GRID, lw=0.4, zorder=1)
        ax.plot(*zip(_p(0, k, 0), _p(L, k, 0)), color=S.GRID, lw=0.4, zorder=1)
    xc, yc = L / 2, Wd / 2
    # previous hatch tracks (solidified) and the current track
    for dy in (-0.16, -0.08):
        ax.plot(*zip(_p(0, yc + dy, 0), _p(L, yc + dy, 0)), color="#c9c8c2", lw=1.6, zorder=2,
                solid_capstyle="butt")
    ax.plot(*zip(_p(0, yc, 0), _p(xc, yc, 0)), color="#b5b4ae", lw=1.6, zorder=2, solid_capstyle="butt")
    # melt pool teardrop behind the laser (travel along +x)
    s = np.linspace(0, 2 * np.pi, 120)
    a_front, a_back, b = 0.06, 0.26, 0.055
    px = np.where(np.cos(s) >= 0, a_front * np.cos(s), a_back * np.cos(s))
    py = b * np.sin(s) * (1 - 0.25 * (np.cos(s) < 0) * np.abs(np.cos(s)))
    pool = [_p(xc + u, yc + v, 0) for u, v in zip(px, py)]
    ax.add_patch(Polygon(pool, closed=True, facecolor="#f2b098", edgecolor=S.MODEL, lw=1.1, zorder=4))
    # volumetric source below the spot (exponential depth profile, drawn as fading lobes)
    for depth, alpha in ((0.03, 0.55), (0.07, 0.35), (0.12, 0.2), (0.18, 0.1)):
        t = np.linspace(np.pi, 2 * np.pi, 40)
        lobe = [_p(xc + 0.05 * np.cos(tt), yc, depth * np.sin(tt)) for tt in t]
        ax.add_patch(Polygon(lobe, closed=True, facecolor=S.CAMERA, alpha=alpha, edgecolor="none", zorder=3))
    # beam
    tip = _p(xc, yc, 0)
    ax.add_patch(Polygon([(tip[0] - 0.03, tip[1]), (tip[0] + 0.03, tip[1]), (tip[0] + 0.07, tip[1] + 0.75),
                          (tip[0] - 0.07, tip[1] + 0.75)], closed=True, facecolor=S.CAMERA, alpha=0.35,
                         edgecolor="none", zorder=5))
    ax.text(tip[0] + 0.12, tip[1] + 0.72, "laser: Gaussian, $R$ = 40 µm,\n$P_{abs} = αP$, exponential\n"
            "deposition depth $δ$", fontsize=6.8, ha="left", va="top", color=S.INK, linespacing=1.1)
    # travel arrow on the track
    ax.annotate("", xy=_p(L - 0.08, yc, 0), xytext=_p(xc + 0.22, yc, 0),
                arrowprops=dict(arrowstyle="-|>", color=S.INK_2, lw=0.8, mutation_scale=7))
    ax.text(*_p(L - 0.1, yc + 0.07, 0), "scan", fontsize=6.6, ha="right", va="bottom", color=S.INK_2)
    # top boundary
    for xx in (0.05, 0.3):
        b0 = _p(xx, Wd * 0.8, 0)
        ax.annotate("", xy=(b0[0], b0[1] + 0.26), xytext=b0,
                    arrowprops=dict(arrowstyle="-|>", color=S.MODEL, lw=0.8, mutation_scale=6))
    ax.text(tip[0] - 0.12, tip[1] + 0.72, "top: convection,\n$h$ = 10 W/(m²·K), and\nboiling loss above 3133 K",
            fontsize=6.8, ha="right", va="top", color=S.MODEL, linespacing=1.1)
    # side and bottom boundaries
    s0 = _p(L, Wd * 0.85, -Dp * 0.55)
    ax.annotate("", xy=(s0[0] + 0.25, s0[1]), xytext=s0,
                arrowprops=dict(arrowstyle="-|>", color=S.INK_2, lw=0.8, mutation_scale=6))
    b0 = _p(L * 0.85, 0.0, -Dp)
    ax.annotate("", xy=(b0[0], b0[1] - 0.2), xytext=b0,
                arrowprops=dict(arrowstyle="-|>", color=S.INK_2, lw=0.8, mutation_scale=6))
    ax.text(s0[0] + 0.3, s0[1], "sides and bottom:\nsolid-absorbing,\n$h$ = 1000 W/(m²·K)\nto 298 K",
            fontsize=6.8, ha="left", va="center", color=S.INK_2, linespacing=1.1)
    # dimensions
    d0, d1 = _p(0, 0, -Dp), _p(L, 0, -Dp)
    ax.annotate("", xy=(d1[0], d1[1] - 0.12), xytext=(d0[0], d0[1] - 0.12),
                arrowprops=dict(arrowstyle="<->", color=S.MUTED, lw=0.6, mutation_scale=6))
    ax.text((d0[0] + d1[0]) / 2 - 0.2, d0[1] - 0.17, "1.584 mm (99 cells)", fontsize=6.6, ha="center", va="top",
            color=S.MUTED)
    z0, z1 = _p(0, 0, 0), _p(0, 0, -Dp)
    ax.annotate("", xy=(z1[0] - 0.08, z1[1]), xytext=(z0[0] - 0.08, z0[1]),
                arrowprops=dict(arrowstyle="<->", color=S.MUTED, lw=0.6, mutation_scale=6))
    ax.text(z0[0] - 0.12, (z0[1] + z1[1]) / 2, "0.336 mm\n(21 cells)", fontsize=6.6, ha="right", va="center",
            color=S.MUTED, linespacing=1.0)
    ax.text(*_p(L * 0.5, 0.0, -Dp * 0.5), "16 µm cubic cells;\nexplicit, Δt = 2.5 µs", fontsize=6.6, ha="center",
            va="center", color=S.INK_2, linespacing=1.1)
    # window motion
    m0 = _p(L * 0.55, Wd + 0.1, 0)
    m1 = _p(L * 0.95, Wd + 0.1, 0)
    ax.annotate("", xy=m1, xytext=m0, arrowprops=dict(arrowstyle="-|>", color=S.INK, lw=1.2, mutation_scale=8))
    ax.text(m1[0] + 0.04, m1[1], "window moves\nwith the laser", fontsize=6.8, ha="left", va="center",
            color=S.INK, linespacing=1.1)
    lp = _p(xc - 0.2, yc - 0.42, 0)
    ax.annotate("liquidus footprint", xy=_p(xc - 0.12, yc - 0.03, 0), xytext=lp, fontsize=6.6, color=S.MODEL,
                ha="center", va="top", arrowprops=dict(arrowstyle="-", color=S.MODEL, lw=0.5))
    allpts = np.array(top + front + side)
    ax.set_xlim(allpts[:, 0].min() - 0.5, allpts[:, 0].max() + 1.0)
    ax.set_ylim(allpts[:, 1].min() - 0.45, allpts[:, 1].max() + 0.95)
    ax.text(ax.get_xlim()[0], ax.get_ylim()[1], "(a) Moving computational window", fontsize=9.5, va="top",
            color=S.INK)
    # (b) a recorded top-surface field with the production H/W box
    axb = fig.add_axes([0.61, 0.36, 0.39, 0.46])
    win_x, win_y = (-8, 72), (-8, 32)
    extent = (win_x[0] - 0.5, win_x[1] - 0.5, win_y[1] - 0.5, win_y[0] - 0.5)
    im = axb.imshow(field, cmap="inferno", vmin=300, vmax=3000, extent=extent, interpolation="bilinear")
    ny, nx = scored.shape
    gx = extent[0] + (np.arange(nx) + 0.5) * (extent[1] - extent[0]) / nx
    gy = extent[3] + (np.arange(ny) + 0.5) * (extent[2] - extent[3]) / ny
    axb.contour(*np.meshgrid(gx, gy), scored, levels=[row["liquidus_K"]], colors=["white"], linewidths=0.9)
    box = np.vstack([corners, corners[:1]])
    axb.plot(box[:, 0], box[:, 1], color=S.MODEL_ON_DARK, lw=1.5, path_effects=S.halo())
    axb.plot([row["beam_x_px"]], [row["beam_y_px"]], marker="+", color="white", ms=7, mew=1.2)
    cx, cy = corners.mean(axis=0)
    xlim = (cx - 22, cx + 22)
    ylim = (cy - 11, cy + 11)
    axb.set_xlim(*xlim)
    axb.set_ylim(ylim[1], ylim[0])
    axb.set_xticks([])
    axb.set_yticks([])
    axb.grid(False)
    bar = 100 / S.UM_PER_PX
    axb.plot([xlim[1] - 2 - bar, xlim[1] - 2], [ylim[1] - 2, ylim[1] - 2], color="white", lw=1.6)
    axb.text(xlim[1] - 2 - bar / 2, ylim[1] - 2.8, "100 µm", color="white", fontsize=6.6, ha="center", va="bottom")
    axb.text(xlim[0] + 1, ylim[0] + 1.2,
             f"H = {row['model_H_px'] * S.UM_PER_PX:.0f} µm\nW = {row['model_W_px'] * S.UM_PER_PX:.0f} µm",
             color="white", fontsize=7, ha="left", va="top", path_effects=S.text_halo(), linespacing=1.1)
    axb.set_title("(b) Top surface and liquidus footprint", loc="left", fontsize=9.5, pad=4)
    cax = fig.add_axes([0.61, 0.29, 0.39, 0.025])
    cb = fig.colorbar(im, cax=cax, orientation="horizontal", ticks=[500, 1000, 1673, 2000, 2500, 3000])
    cb.ax.tick_params(labelsize=6.5, length=2)
    cb.outline.set_linewidth(0.5)
    cb.set_label("Surface temperature (K); white line: 1673 K liquidus", fontsize=7)
    S.write_csv(S.SOURCE_DIR / "F4_model_schematic.csv",
                ["member", "frame_index", "condition", "model_H_px", "model_W_px", "peak_K", "liquidus_K",
                 "beam_x_px", "beam_y_px"],
                [[member, row["frame_index"], row["condition"], row["model_H_px"], row["model_W_px"], row["peak_K"],
                  row["liquidus_K"], row["beam_x_px"], row["beam_y_px"]]])
    S.save(fig, "F4_model_schematic")
    plt.close(fig)
    return {"member": member, "frame": row["frame_index"], "condition": row["condition"], "ved": row["ved_J_mm3"],
            "H_um": row["model_H_px"] * S.UM_PER_PX, "W_um": row["model_W_px"] * S.UM_PER_PX}


# ---------------------------------------------------------------------- F5


def f5_workflow(plt):
    cps = D.coupons()
    cands = D.candidates()
    n_anchor = sum(1 for c in cands if c["candidate"].startswith("anchor"))
    n_halton = sum(1 for c in cands if c["candidate"].startswith("halton"))
    n_conf = sum(1 for c in cands if c["candidate"].startswith("confirm"))
    sel = next(c for c in cands if c["selected"])
    roles = {r: [c for c in cps if c["role"] == r] for r in S.ROLE_ORDER}
    n_cal_design = sum(1 for c in cps if c["a8_role"] == "calibration")
    n_held = sum(1 for c in cps if c["a8_role"] == "held_out")
    n_cal = len(roles["calibration"])
    fig, ax = _canvas(plt, S.FULL_W, 4.7)
    H = 100 * 4.7 / S.FULL_W
    LX, LW = 1.0, 60.0
    RX, RW = 66.0, 33.0
    y = H - 1.0

    def row(h):
        nonlocal y
        top = y
        y -= h
        return top - h

    b = row(6.0)
    _box(ax, LX, b, RX + RW - LX, 6.0, f"{len(cps)} coupons, {len({c['condition'] for c in cps})} process conditions\n"
         "Split by condition before any fitting",
         face=S.NEUTRAL, fs=7.4)
    top_mid = b
    y -= 3.0
    b = row(6.0)
    _box(ax, LX, b, LW, 6.0, f"{n_cal_design} calibration-design coupons", fs=7.4)
    _box(ax, RX, b, RW, 6.0, f"{n_held} held-out coupons", face="#e9e8e3", fs=7.4)
    _arrow(ax, (LX + LW / 2, top_mid), (LX + LW / 2, b + 6.0))
    _arrow(ax, (RX + RW / 2, top_mid), (RX + RW / 2, b + 6.0))
    r1 = b
    y -= 3.0
    b = row(6.0)
    _box(ax, LX, b, LW, 6.0, "Model development and diagnostics", fs=7.4)
    _arrow(ax, (LX + LW / 2, r1), (LX + LW / 2, b + 6.0))
    r2 = b
    y -= 3.0
    b = row(6.0)
    _box(ax, LX, b, LW, 6.0, "Calibration Window: 65–85 J/mm³", fs=7.4, weight="bold")
    _arrow(ax, (LX + LW / 2, r2), (LX + LW / 2, b + 6.0))
    r3 = b
    y -= 3.0
    b = row(6.0)
    cw = 34.0
    _box(ax, LX, b, cw, 6.0, f"{n_cal} calibration coupons",
         fs=7.2, face=S.WHITE)
    _box(ax, LX + cw + 2.0, b, LW - cw - 2.0, 6.0,
         f"{len(roles['out_of_window_examined'])} out-of-window coupons\n(examined)", fs=7.2,
         face=S.NEUTRAL)
    _arrow(ax, (LX + cw / 2, r3), (LX + cw / 2, b + 6.0))
    _arrow(ax, (LX + cw + 2.0 + (LW - cw - 2.0) / 2, r3), (LX + cw + 2.0 + (LW - cw - 2.0) / 2, b + 6.0))
    r4 = b
    y -= 3.0
    b = row(8.0)
    _box(ax, LX, b, cw, 8.0, f"Calibration search\n({n_anchor + n_halton + n_conf} candidates)", fs=7.4)
    _arrow(ax, (LX + cw / 2, r4), (LX + cw / 2, b + 8.0))
    r5 = b
    y -= 3.0
    b = row(6.0)
    _box(ax, LX, b, cw, 6.0, "Lowest J selected;\nparameters frozen",
         fs=7.2, edge=S.MODEL, lw=1.1)
    _arrow(ax, (LX + cw / 2, r5), (LX + cw / 2, b + 6.0))
    r6 = b
    ex_c = LX + cw + 2.0 + (LW - cw - 2.0) / 2
    # held-out column: locked until the freeze
    _box(ax, RX, r6, RW, r1 - r6 - 3.0,
         "Not used until\nthe freeze", face="#e9e8e3",
         edge=S.MUTED, ls=(0, (3, 2)), fs=7.2, color=S.INK_2)
    _arrow(ax, (RX + RW / 2, r1), (RX + RW / 2, r1 - 3.0))
    y -= 2.5
    fy = y
    ax.plot([0.5, 99.5], [fy, fy], color=S.MODEL, lw=1.0, ls=(0, (4, 2)))
    ax.text(0.5, fy - 0.5, "Selection freeze", fontsize=7.2, color=S.MODEL, ha="left", va="top")
    y -= 3.0
    b = row(8.0)
    ew = 30.6
    xs = (LX, LX + ew + 3.0, LX + 2 * (ew + 3.0))
    held_in = roles["in_window_held_out"]
    blind = roles["out_of_window_blind"]
    _box(ax, xs[0], b, ew, 8.0, f"Calibration performance\n({n_cal} coupons)", fs=7.2, face=S.BAND)
    _box(ax, xs[1], b, ew, 8.0, f"Out-of-window evaluation\n({len(roles['out_of_window_examined'])} examined + {len(blind)} blind)",
         fs=7.2, face=S.BAND)
    _box(ax, xs[2], b, ew, 8.0, f"Held-out evaluation\n({len(held_in)} coupons, $V$ ≤ 1.25)", fs=7.2, face=S.BAND)
    _arrow(ax, (LX + cw * 0.72, r6), (LX + cw * 0.72, b + 8.0))
    _arrow(ax, (ex_c, r4), (ex_c, b + 8.0), ls=(0, (2, 1.5)), color=S.MUTED)
    _arrow(ax, (RX + 4.0, r6), (xs[1] + ew * 0.85, b + 8.0))
    _arrow(ax, (xs[2] + ew / 2, r6), (xs[2] + ew / 2, b + 8.0))
    r7 = b
    y -= 3.0
    b = row(6.0)
    _box(ax, LX, b, 98.0, 6.0, "Secondary analyses: synthetic camera, width-matched isotherm,\ncamera thresholds, "
         "process-response slopes", fs=7.2, face=S.NEUTRAL)
    for x in xs:
        _arrow(ax, (x + ew / 2, r7), (x + ew / 2, b + 6.0))
    ax.set_ylim(b - 1.0, H)
    S.write_csv(S.SOURCE_DIR / "F5_workflow.csv", ["quantity", "count"],
                [["coupons", len(cps)], ["a8_calibration_design", n_cal_design], ["a8_held_out", n_held],
                 ["calibration", n_cal], ["in_window_held_out", len(held_in)],
                 ["out_of_window_examined", len(roles["out_of_window_examined"])],
                 ["out_of_window_blind", len(blind)], ["anchors", n_anchor], ["halton", n_halton],
                 ["confirmation", n_conf]])
    S.save(fig, "F5_workflow")
    plt.close(fig)
    return {"n_anchor": n_anchor, "n_halton": n_halton, "n_conf": n_conf, "selected": sel["candidate"],
            "J": sel["J"], "n_cal_design": n_cal_design, "n_held": n_held}


ALL = {"F3": f3_scoring_hierarchy, "F4": f4_model_schematic, "F5": f5_workflow}
