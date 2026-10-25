"""Data charts for the thesis: F1 and F6-F11 (thesis list numbering).

Every plotted value is written to source/<figure>.csv. Numbers quoted in captions are computed here and returned
to the build, which writes them into the caption text.
"""
from __future__ import annotations


import numpy as np

import data as D
import style as S

HATCH_LAYER_MM2 = S.C.HATCH_MM * S.C.LAYER_MM


def _ved_power(ved: float, speed):
    return ved * HATCH_LAYER_MM2 * np.asarray(speed, dtype=float)


def _pv_background(ax, *, v_lim=(540, 1460), p_lim=(128, 200), isolines=(50, 100, 125), labels=True,
                   band_label=True):
    v = np.linspace(*v_lim, 200)
    ax.fill_between(v, _ved_power(S.WINDOW[0], v), _ved_power(S.WINDOW[1], v), color=S.BAND, lw=0, zorder=0)
    for ved in isolines:
        ax.plot(v, _ved_power(ved, v), color=S.GRID, lw=0.8, zorder=1)
        if labels:
            # label where the isoline leaves the top of the axes, or at the right edge
            v_top = p_lim[1] / (ved * HATCH_LAYER_MM2)
            if v_lim[0] < v_top < v_lim[1]:
                ax.text(v_top, p_lim[1] - 1.2, f"{ved:g}", ha="right", va="top", fontsize=6.5, color=S.MUTED)
            else:
                p_r = float(_ved_power(ved, v_lim[1]))
                ax.text(v_lim[1] - 8, p_r + 0.8, f"{ved:g}", ha="right", va="bottom", fontsize=6.5, color=S.MUTED)
    if band_label:
        p_txt = p_lim[1] - 1.5
        ax.text(p_txt / (75 * HATCH_LAYER_MM2), p_txt, "65–85\nJ/mm³", ha="center", va="top", fontsize=6.5,
                color=S.MUTED, linespacing=1.0)
    ax.set_xlim(*v_lim)
    ax.set_ylim(*p_lim)
    ax.set_xlabel("Scan speed $v$ (mm/s)")
    ax.set_ylabel("Laser power $P$ (W)")


def _conditions_by_ved():
    return sorted(D.conditions(), key=lambda r: r["ved_J_mm3"])


# ---------------------------------------------------------------------- F1


def f1_process_space(plt):
    rows = _conditions_by_ved()
    fig, ax = plt.subplots(figsize=(S.FULL_W, 3.5))
    _pv_background(ax, band_label=False)
    # campaign design lines
    lc = dict(color=S.MUTED, lw=0.7, ls=(0, (1.5, 1.5)), zorder=1)
    ax.plot([850, 1100], [140, 190], **lc)
    for p in (140, 180):
        ax.plot([600, 1400], [p, p], **lc)
    for v in (700, 1200):
        ax.plot([v, v], [140, 180], **lc)
    ax.annotate("Jul 30 and Jul 31\n(same six conditions)", xy=(1100, 190), xytext=(1185, 193.5), fontsize=7,
                color=S.INK_2, ha="left", va="center", arrowprops=dict(arrowstyle="-", color=S.MUTED, lw=0.6))
    ax.text(1405, 141.2, "Sep 4: speed sweep", fontsize=7, color=S.INK_2, ha="right", va="bottom")
    ax.text(1405, 181.2, "Sep 4: speed sweep", fontsize=7, color=S.INK_2, ha="right", va="bottom")
    ax.text(700, 182.0, "Sep 10:\npower\nsweep", fontsize=7, color=S.INK_2, ha="center", va="bottom", linespacing=1.0)
    ax.text(1200, 182.0, "Sep 10:\npower\nsweep", fontsize=7, color=S.INK_2, ha="center", va="bottom", linespacing=1.0)
    src = []
    for r in rows:
        S.role_scatter(ax, r["speed_mm_s"], r["power_W"], r["role"], size=34, label="_")
        if r["coupons"] == 2:
            ax.text(r["speed_mm_s"] + 14, r["power_W"] - 1.6, "×2", fontsize=6.5, color=S.INK_2, ha="left", va="top")
        src.append([r["name"], r["role"], r["power_W"], r["speed_mm_s"], r["ved_J_mm3"], r["coupons"], r["members"]])
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch

    extra = [Patch(facecolor=S.BAND, edgecolor="none", label="Calibration window,\n65–85 J/mm³"),
             Line2D([], [], color=S.GRID, lw=0.8, label="VED isoline (J/mm³)"),
             Line2D([], [], color=S.MUTED, lw=0.7, ls=(0, (1.5, 1.5)), label="Campaign design"),
             Line2D([], [], ls="none", marker="$×2$", ms=7, color=S.INK_2, label="Two coupons\n(Jul 30, Jul 31)")]
    ax.legend(handles=S.role_handles() + extra, loc="upper left", bbox_to_anchor=(1.0, 1.0), fontsize=7.5,
              handlelength=1.4, borderaxespad=0.2, labelspacing=0.7)
    S.write_csv(S.SOURCE_DIR / "F1_process_space_map.csv",
                ["condition", "role", "power_W", "speed_mm_s", "ved_J_mm3", "coupons", "members"], src)
    S.save(fig, "F1_process_space_map")
    plt.close(fig)
    return {
        "conditions": len(rows),
        "coupons": sum(r["coupons"] for r in rows),
        "ved_min": min(r["ved_J_mm3"] for r in rows),
        "ved_max": max(r["ved_J_mm3"] for r in rows),
    }


# ---------------------------------------------------------------------- F6


def f6_footprints(plt):
    """Camera and model H × W boxes at their process conditions, as the presentation figure 'Melt pool footprints over
    process space' (owner, 2026-10-23). Sizes are the committee condition medians; the presentation source is checked
    against them."""

    from matplotlib.lines import Line2D
    from matplotlib.offsetbox import AnchoredOffsetbox, AnnotationBbox, DrawingArea, TextArea, VPacker
    from matplotlib.patches import Patch, Rectangle

    rows = _conditions_by_ved()
    pres = {r["condition"]: r for r in D.read_csv(D.PRESENTATION_SOURCE / "condition_sizes.csv")}
    sizes = []
    for r in rows:
        s = {"camera_H": r["cam_H_px_median"] * S.UM_PER_PX, "camera_W": r["cam_W_px_median"] * S.UM_PER_PX,
             "model_H": r["sim_H_px_median_pool"] * S.UM_PER_PX, "model_W": r["sim_W_px_median_pool"] * S.UM_PER_PX}
        for k, v in s.items():
            assert abs(v - pres[r["name"]][f"{k}_um"]) < 1e-6, (r["name"], k)
        sizes.append(s)
    fig = plt.figure(figsize=(S.FULL_W, 4.1))
    ax = fig.add_axes([0.085, 0.10, 0.85, 0.72])
    xlim, ylim = (555, 1445), (130, 200)
    k = HATCH_LAYER_MM2
    v = np.linspace(500, 1500, 200)
    ax.fill_between(v, S.WINDOW[0] * v * k, S.WINDOW[1] * v * k, color=S.BAND, lw=0, zorder=0)
    for e in (40, 50, 60, 65, 85, 100, 125):
        ax.plot(v, e * v * k, color=S.AXIS if e in S.WINDOW else S.GRID, lw=0.8, zorder=0)
        top_v = ylim[1] / (e * k)
        if top_v <= xlim[1]:
            ax.text(top_v, ylim[1] + 0.6, f"{e}", fontsize=7, color=S.INK_2, ha="center", va="bottom", clip_on=False)
        else:
            ax.text(xlim[1] + 8, e * xlim[1] * k, f"{e}", fontsize=7, color=S.INK_2, ha="left", va="center",
                    clip_on=False)
    ax.text(xlim[1] + 8, ylim[1] + 0.6, "J/mm³", fontsize=7, color=S.INK_2, ha="left", va="bottom", clip_on=False)
    ax.set_xlim(*xlim)
    ax.set_ylim(*ylim)
    # Box scale (points per µm): the largest at which every pair of neighbouring conditions still clears by 10 %.
    pt_per_v = ax.get_position().width * S.FULL_W * 72 / (xlim[1] - xlim[0])
    pt_per_p = ax.get_position().height * 4.1 * 72 / (ylim[1] - ylim[0])
    half_h = [max(s["camera_H"], s["model_H"]) / 2 for s in sizes]
    half_w = [max(s["camera_W"], s["model_W"]) / 2 for s in sizes]
    limits = []
    for i, a in enumerate(rows):
        for j, b in enumerate(rows):
            if j <= i:
                continue
            gap_x = abs(a["speed_mm_s"] - b["speed_mm_s"]) * pt_per_v
            gap_y = abs(a["power_W"] - b["power_W"]) * pt_per_p
            # boxes overlap only if they overlap in both directions; the binding direction is the easier one to clear
            limits.append(max(gap_x / (half_h[i] + half_h[j]), gap_y / (half_w[i] + half_w[j])))
    scale = 0.9 * min(limits)
    src = []
    for r, s in zip(rows, sizes):
        ch, cw, mh, mw = (s[q] * scale for q in ("camera_H", "camera_W", "model_H", "model_W"))
        width, height = max(ch, mh) + 3, max(cw, mw) + 3
        da = DrawingArea(width, height, 0, 0)
        da.add_artist(Rectangle(((width - mh) / 2, (height - mw) / 2), mh, mw, facecolor=S.MODEL, alpha=0.30,
                                edgecolor="none"))
        da.add_artist(Rectangle(((width - mh) / 2, (height - mw) / 2), mh, mw, facecolor="none", edgecolor=S.MODEL,
                                lw=0.9))
        da.add_artist(Rectangle(((width - ch) / 2, (height - cw) / 2), ch, cw, facecolor="none", edgecolor=S.CAMERA,
                                lw=1.1))
        ax.add_artist(AnnotationBbox(da, (r["speed_mm_s"], r["power_W"]), frameon=False, pad=0, zorder=3))
        src.append([r["name"], r["role"], r["power_W"], r["speed_mm_s"], r["ved_J_mm3"], r["coupons"],
                    s["camera_H"], s["camera_W"], s["model_H"], s["model_W"]])
    bar = DrawingArea(100 * scale, 3, 0, 0)
    bar.add_artist(Rectangle((0, 0.8), 100 * scale, 1.5, facecolor=S.INK, edgecolor="none"))
    key = VPacker(children=[bar, TextArea("100 µm at box scale", textprops=dict(fontsize=7, color=S.INK))],
                  align="left", pad=0, sep=3)
    ax.add_artist(AnchoredOffsetbox(loc="upper left", child=key, pad=0.3, borderpad=0.5, frameon=False))
    ax.set_xlabel("Scan speed (mm/s)")
    ax.set_ylabel("Laser power (W)")
    handles = [Line2D([], [], color=S.CAMERA, lw=1.4, label="Experiment: camera H × W"),
               Patch(facecolor=S.MODEL, alpha=0.4, edgecolor=S.MODEL, label="Simulation: model H × W"),
               Patch(facecolor=S.BAND, edgecolor="none", label="Calibration window, 65–85 J/mm³"),
               Line2D([], [], color=S.GRID, lw=0.8, label="Lines of constant energy density")]
    fig.legend(handles=handles, loc="lower left", bbox_to_anchor=(0.075, 0.89), ncol=2, fontsize=7.5,
               columnspacing=2.0, handlelength=1.6)
    S.write_csv(S.SOURCE_DIR / "F6_footprints_over_process_space.csv",
                ["condition", "role", "power_W", "speed_mm_s", "ved_J_mm3", "coupons", "camera_H_um", "camera_W_um",
                 "model_H_um", "model_W_um"], src)
    S.save(fig, "F6_footprints_over_process_space")
    plt.close(fig)
    return {"scale_pt_per_um": scale}


# ---------------------------------------------------------------------- F7

ORIGIN_LABEL = {"frozen_design": "design", "confirmation": "confirmation"}


def _origin(c: dict) -> str:
    if c["candidate"].startswith("anchor"):
        return "anchor"
    if c["candidate"].startswith("halton"):
        return "Halton"
    return "confirmation"


display_name = D.display_name
COLS = (1.06, 1.13, 1.19, 1.215)


def f7_candidate_ranking(plt):
    cands = sorted(D.candidates(), key=lambda c: c["J"])
    j_min = cands[0]["J"]
    fig, ax = plt.subplots(figsize=(S.FULL_W, 4.0))
    y = np.arange(len(cands))[::-1]
    h_part = [0.5 * c["H_component"] for c in cands]
    w_part = [0.5 * c["W_component"] for c in cands]
    ax.barh(y, h_part, height=0.66, color=S.INK_2, lw=0, label="H term, ½ $Q_H$")
    ax.barh(y, w_part, left=h_part, height=0.66, color="#bdbcb6", lw=0, label="W term, ½ $Q_W$")
    ax.axvline(1.10 * j_min, color=S.MODEL, lw=0.8, ls=(0, (3, 2)))
    ax.text(1.10 * j_min, len(cands) - 0.45, "near-best limit, 1.10 $J_{min}$", fontsize=6.5, color=S.MODEL,
            va="bottom", ha="center")
    labels = []
    src = []
    for yi, c in zip(y, cands):
        name = c["candidate"]
        tag = ""
        if c["selected"]:
            tag = "  (selected)"
        elif c["rank_by_J"] == 2:
            tag = "  (second best)"
        labels.append(display_name(name) + tag)
        ax.text(c["J"] + 0.008, yi, f"{c['J']:.3f}", va="center", ha="left", fontsize=6.8, color=S.INK)
        for xc, text in zip(COLS, (f"{c['t']:+.2f}".replace("-", "−"), f"{c['ck']:.3f}", f"{c['eta']:.2f}",
                                   _origin(c))):
            ax.text(xc, yi, text, transform=ax.get_yaxis_transform(), va="center",
                    ha="left" if text == _origin(c) else "right", fontsize=6.8, color=S.INK_2)
        src.append([c["rank_by_J"], name, display_name(name), _origin(c), c["t"], c["ck"], c["eta"], c["absorptivity"],
                    c["deposition_depth_mm"], c["J"], c["e_H"], c["e_W"], c["H_component"], c["W_component"],
                    c["near_best"], c["selected"]])
    for xc, text in zip(COLS, ("$t$", "$c_k$", "$η$", "origin")):
        ax.text(xc, len(cands) - 0.45, text, transform=ax.get_yaxis_transform(), va="bottom",
                ha="left" if text == "origin" else "right", fontsize=7, color=S.MUTED)
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=7.2)
    for tick, c in zip(ax.get_yticklabels(), cands):
        if c["selected"]:
            tick.set_fontweight("bold")
            tick.set_color(S.MODEL)
    ax.set_ylim(-0.6, len(cands) + 0.3)
    ax.set_xlim(0, max(c["J"] for c in cands) * 1.12)
    ax.set_xlabel("Calibration objective $J$ = ½ $Q_H$ + ½ $Q_W$ (9 calibration coupons)")
    ax.grid(axis="y", visible=False)
    ax.legend(loc="upper right", fontsize=7, handlelength=1.2, bbox_to_anchor=(1.0, 0.94))
    S.write_csv(S.SOURCE_DIR / "F7_candidate_ranking.csv",
                ["rank", "candidate", "label", "origin", "t", "ck", "eta", "absorptivity", "deposition_depth_mm", "J", "e_H",
                 "e_W", "Q_H", "Q_W", "near_best", "selected"], src)
    S.save(fig, "F7_candidate_ranking")
    plt.close(fig)
    second = cands[1]
    return {"n": len(cands), "j_min": j_min, "second": second["candidate"], "second_J": second["J"],
            "near_best": [c["candidate"] for c in cands if c["near_best"]],
            "h_share_selected": cands[0]["H_component"] / (cands[0]["H_component"] + cands[0]["W_component"])}


# ---------------------------------------------------------------------- F8


def f8_observed_vs_predicted(plt):
    conds = [r for r in _conditions_by_ved() if r["role"] == "calibration"]
    cps = [c for c in D.coupons() if c["role"] == "calibration"]
    grp = D.group("calibration")
    fig, axes = plt.subplots(1, 2, figsize=(S.FULL_W, 3.05))
    src = []
    out = {}
    for ax, q, letter, lim in ((axes[0], "H", "a", (40, 210)), (axes[1], "W", "b", (20, 120))):
        xs = np.linspace(*lim, 10)
        ax.plot(xs, xs, color=S.INK_2, lw=0.8, zorder=1)
        ax.text(lim[1] * 0.97, lim[1] * 0.97, "1:1", ha="right", va="top", fontsize=7, color=S.INK_2, rotation=45,
                rotation_mode="anchor")
        ratio = grp[f"median_{q}_ratio"]
        ax.plot(xs, ratio * xs, color=S.MODEL, lw=0.7, ls=(0, (3, 2)), zorder=1)
        span = lim[1] - lim[0]
        x_txt = lim[0] + (0.12 if q == "H" else 0.62) * span
        ax.text(x_txt + 0.02 * span, ratio * x_txt - 0.04 * span, f"model = {ratio:.2f} × camera\n(pooled median ratio)",
                fontsize=6.8, color=S.MODEL, ha="left", va="top", linespacing=1.0)
        ax.scatter([r[f"cam_{q}_px_median"] * S.UM_PER_PX for r in conds],
                   [r[f"sim_{q}_px_median_pool"] * S.UM_PER_PX for r in conds], s=30, color=S.INK, zorder=3,
                   label="calibration condition (5)")
        ax.set_xlim(*lim)
        ax.set_ylim(*lim)
        ax.set_aspect("equal")
        ax.set_xlabel(f"Camera {q} (µm)")
        ax.set_ylabel(f"Model {q} (µm)")
        S.panel(ax, letter, q)
        out[f"{q}_ratio"] = ratio
        out[f"{q}_cond_ratio_min"] = min(r[f"median_{q}_ratio"] for r in conds)
        out[f"{q}_cond_ratio_max"] = max(r[f"median_{q}_ratio"] for r in conds)
        out[f"cam_{q}_um"] = grp[f"cam_{q}_px_median"] * S.UM_PER_PX
        out[f"sim_{q}_um"] = grp[f"sim_{q}_px_median_pool"] * S.UM_PER_PX
    axes[1].legend(loc="upper left", fontsize=7)
    for r in conds:
        src.append(["condition", r["name"], r["ved_J_mm3"], r["cam_H_px_median"] * S.UM_PER_PX,
                    r["sim_H_px_median_pool"] * S.UM_PER_PX, r["cam_W_px_median"] * S.UM_PER_PX,
                    r["sim_W_px_median_pool"] * S.UM_PER_PX, r["median_H_ratio"], r["median_W_ratio"]])
    for c in cps:
        src.append(["coupon", c["member"], c["ved_J_mm3"], c["cam_H_um_median"], c["sim_H_um_median_pool"],
                    c["cam_W_um_median"], c["sim_W_um_median_pool"], c["median_H_ratio"], c["median_W_ratio"]])
    S.write_csv(S.SOURCE_DIR / "F8_observed_vs_predicted.csv",
                ["level", "name", "ved_J_mm3", "camera_H_um", "model_H_um", "camera_W_um", "model_W_um",
                 "median_H_ratio", "median_W_ratio"], src)
    fig.subplots_adjust(wspace=0.32)
    S.save(fig, "F8_observed_vs_predicted")
    plt.close(fig)
    out["no_pool"] = grp["no_pool_frames"]
    out["scored"] = grp["scored_frames"]
    return out


# ---------------------------------------------------------------------- F9


def f9_calibration_vs_held_out(plt):
    """Two findings (owner asked for a clearer figure, 2026-10-23): (a) the model's size bias is the same in the
    calibration and the in-window held-out groups; (b) the held-out / calibration error ratio V lies inside the
    predefined pass region V <= 1.25 for H and W."""

    from matplotlib.lines import Line2D

    roles = ("calibration", "in_window_held_out")
    cps = [c for c in D.coupons() if c["role"] in roles]
    cc = next(c for c in cps if c["member"] == S.C.CROSS_CAMPAIGN)
    fig, axes = plt.subplots(1, 2, figsize=(S.FULL_W, 2.55), gridspec_kw={"width_ratios": [1.15, 1]})
    src = []
    rows = {"H": 1.0, "W": 0.0}
    off = {"calibration": 0.13, "in_window_held_out": -0.13}
    # (a) size ratios
    ax = axes[0]
    ax.axvline(1.0, color=S.INK_2, lw=0.9, zorder=1)
    for q, y0 in rows.items():
        for role in roles:
            y = y0 + off[role]
            for c in [c for c in cps if c["role"] == role]:
                if c["member"] == S.C.CROSS_CAMPAIGN:
                    ax.scatter(c[f"median_{q}_ratio"], y, s=14, marker="s", facecolor=S.GREY, edgecolor="#5c5b57",
                               lw=0.7, zorder=2)
                else:
                    ax.scatter(c[f"median_{q}_ratio"], y, s=10, marker="|", color=S.GREY, lw=1.0, zorder=2)
                src.append(["a_coupon", q, role, c["member"], c[f"median_{q}_ratio"], c[f"median_{q}_ratio_ci_lo"],
                            c[f"median_{q}_ratio_ci_hi"]])
            g = D.group(role)
            b = D.boot("group", role, f"median_{q}_ratio")
            marker, face, edge = S.ROLE_STYLE[role]
            ax.plot([b["ci_lo"], b["ci_hi"]], [y, y], color=S.INK, lw=1.2, zorder=3, solid_capstyle="butt")
            ax.scatter(g[f"median_{q}_ratio"], y, s=30, marker=marker, facecolor=face, edgecolor=edge, lw=0.9,
                       zorder=4)
            src.append(["a_group", q, role, "pooled", g[f"median_{q}_ratio"], b["ci_lo"], b["ci_hi"]])
        ratio = D.group("calibration")[f"median_{q}_ratio"]
        ax.text(ratio, y0 + 0.36, f"≈ {ratio:.2f} × camera", ha="center", va="bottom", fontsize=6.8, color=S.INK_2)
    ax.set_xscale("log")
    ax.set_xticks([0.5, 0.75, 1.0, 1.5, 2.0, 2.5])
    ax.set_xticklabels(["0.5", "0.75", "1", "1.5", "2", "2.5"])
    ax.minorticks_off()
    ax.set_xlim(0.5, 2.6)
    ax.set_ylim(-0.55, 1.75)
    ax.set_yticks([1.0, 0.0])
    ax.set_yticklabels(["H (length)", "W (width)"], fontsize=8)
    ax.grid(axis="y", visible=False)
    ax.text(0.98, 1.68, "← model smaller", ha="right", va="top", fontsize=6.8, color=S.MUTED)
    ax.text(1.02, 1.68, "model larger →", ha="left", va="top", fontsize=6.8, color=S.MUTED)
    ax.set_xlabel("Model / camera size ratio")
    S.panel(ax, "a", "Model size bias")
    # (b) transfer ratio V
    ax = axes[1]
    ax.axvspan(0.6, 1.25, color=S.BAND, lw=0, zorder=0)
    ax.axvline(1.25, color=S.INK_2, lw=0.9, ls=(0, (3, 2)), zorder=1)
    ax.axvline(1.0, color=S.GRID, lw=0.9, zorder=1)
    ax.text(1.24, 1.68, "pass\n(V ≤ 1.25)", ha="right", va="top", fontsize=6.8, color=S.INK_2, linespacing=1.0)
    ax.text(1.27, 1.68, "fail", ha="left", va="top", fontsize=6.8, color=S.INK_2)
    for q, y0 in rows.items():
        for name, y, style, label in (("held_out_over_calibration", y0 + 0.13, ("s", S.WHITE, S.INK), "group"),
                                      ("part_5_over_calibration", y0 - 0.13, ("s", S.GREY, "#5c5b57"), "coupon")):
            v = D.boot("v_ratio", name, f"e_{q} ratio")
            ax.plot([v["ci_lo"], v["ci_hi"]], [y, y], color=S.INK if label == "group" else S.MUTED, lw=1.2,
                    zorder=3, solid_capstyle="butt")
            ax.scatter(v["point_estimate"], y, s=30, marker=style[0], facecolor=style[1], edgecolor=style[2], lw=0.9,
                       zorder=4)
            ax.text(v["ci_hi"] + 0.015, y, f"{v['point_estimate']:.2f}", ha="left", va="center", fontsize=6.8,
                    color=S.INK if label == "group" else S.MUTED)
            src.append(["b_V", q, name, "", v["point_estimate"], v["ci_lo"], v["ci_hi"]])
    ax.set_xlim(0.6, 1.5)
    ax.set_ylim(-0.55, 1.75)
    ax.set_yticks([1.0, 0.0])
    ax.set_yticklabels(["$V_H$", "$V_W$"], fontsize=8.5)
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("V = held-out error / calibration error")
    S.panel(ax, "b", "Transfer to held-out coupons")
    handles = [Line2D([], [], ls="none", marker="o", ms=5, mfc=S.INK, mec=S.INK, label="Calibration (pooled)"),
               Line2D([], [], ls="none", marker="s", ms=5, mfc=S.WHITE, mec=S.INK, label="Held out, in window (pooled)"),
               Line2D([], [], ls="none", marker="s", ms=5, mfc=S.GREY, mec="#5c5b57",
                      label="Held-out coupon from Sep 4 (180 W, 1000 mm/s)"),
               Line2D([], [], ls="none", marker="|", ms=6, mew=1.0, color=S.GREY, label="Individual coupons")]
    fig.legend(handles=handles, loc="lower center", ncol=2, bbox_to_anchor=(0.5, -0.03), fontsize=7.2,
               columnspacing=1.6, handlelength=1.2)
    S.write_csv(S.SOURCE_DIR / "F9_calibration_vs_held_out.csv",
                ["kind", "quantity", "role", "name", "value", "ci_lo", "ci_hi"], src)
    fig.subplots_adjust(wspace=0.32, bottom=0.31)
    S.save(fig, "F9_calibration_vs_held_out")
    plt.close(fig)
    return {
        "V_H": D.group("in_window_held_out")["e_H"] / D.group("calibration")["e_H"],
        "V_W": D.group("in_window_held_out")["e_W"] / D.group("calibration")["e_W"],
        "cc_H_ratio": cc["median_H_ratio"],
        "cc_W_ratio": cc["median_W_ratio"],
    }


# ---------------------------------------------------------------------- F10


def f10_ratio_vs_ved(plt):
    cps = sorted(D.coupons(), key=lambda c: c["ved_J_mm3"])
    fig, axes = plt.subplots(1, 2, figsize=(S.FULL_W, 3.0), sharey=True)
    src = []
    for ax, q, letter in ((axes[0], "H", "a"), (axes[1], "W", "b")):
        S.window_band(ax, y=0.985)
        ax.axhline(1.0, color=S.INK_2, lw=0.8, zorder=1)
        for role in S.ROLE_ORDER:
            sel = [c for c in cps if c["role"] == role]
            x = [c["ved_J_mm3"] for c in sel]
            yv = [c[f"median_{q}_ratio"] for c in sel]
            lo = [c[f"median_{q}_ratio"] - c[f"median_{q}_ratio_ci_lo"] for c in sel]
            hi = [c[f"median_{q}_ratio_ci_hi"] - c[f"median_{q}_ratio"] for c in sel]
            ax.errorbar(x, yv, yerr=[lo, hi], fmt="none", ecolor=S.MUTED, elinewidth=0.7, capsize=0, zorder=2)
            S.role_scatter(ax, x, yv, role, size=24, label="_")
        ax.set_yscale("log")
        ax.set_yticks([0.1, 0.2, 0.5, 1, 2, 3])
        ax.set_yticklabels(["0.1", "0.2", "0.5", "1", "2", "3"])
        ax.minorticks_off()
        ax.set_ylim(0.1, 4.0)
        ax.set_xlim(35, 132)
        ax.set_xlabel("Volumetric energy density (J/mm³)")
        S.panel(ax, letter, f"{q} ratio, model / camera")
    axes[0].set_ylabel("Coupon median ratio")
    low = cps[0]
    axes[0].annotate(f"{low['no_pool_fraction'] * 100:.1f}% of frames\nwithout a predicted pool",
                     xy=(low["ved_J_mm3"] + 1.2, low["median_H_ratio"]), xytext=(47, 0.16), fontsize=6.5,
                     color=S.INK_2, ha="left", va="center", arrowprops=dict(arrowstyle="-", color=S.MUTED, lw=0.5))
    for c in cps:
        src.append([c["member"], c["role"], c["power_W"], c["speed_mm_s"], c["ved_J_mm3"], c["median_H_ratio"],
                    c["median_H_ratio_ci_lo"], c["median_H_ratio_ci_hi"], c["median_W_ratio"],
                    c["median_W_ratio_ci_lo"], c["median_W_ratio_ci_hi"], c["no_pool_fraction"]])
    fig.legend(handles=S.role_handles(), loc="lower center", ncol=4, bbox_to_anchor=(0.5, -0.07), fontsize=7.5)
    S.write_csv(S.SOURCE_DIR / "F10_ratio_vs_ved.csv",
                ["coupon", "role", "power_W", "speed_mm_s", "ved_J_mm3", "median_H_ratio", "H_ci_lo", "H_ci_hi",
                 "median_W_ratio", "W_ci_lo", "W_ci_hi", "no_pool_fraction"], src)
    fig.subplots_adjust(wspace=0.08, bottom=0.2)
    S.save(fig, "F10_ratio_vs_ved")
    plt.close(fig)
    return {"low_member": low["member"], "low_ved": low["ved_J_mm3"], "low_no_pool": low["no_pool_fraction"],
            "low_H": low["median_H_ratio"], "low_W": low["median_W_ratio"]}


# ---------------------------------------------------------------------- F11

QUANTITY_LABEL = {"H": "H", "W": "W", "HW": "H/W"}


def _slope(rows, subset, design, term, source, quantity):
    for r in rows:
        if (r["subset"], r["design"], r["term"], r["source"], r["quantity"]) == (subset, design, term, source, quantity):
            return r
    raise KeyError((subset, design, term, source, quantity))


def f11_process_slopes(plt):
    """Sensitivities as bars (owner asked for an easier figure, 2026-10-23): for each process variable, the fitted
    % change in H, W and H/W per 1 % increase (log-log coefficients over the 24 coupon medians), camera beside model,
    with coupon-bootstrap intervals. The fit without the 41.7 J/mm³ coupon is not drawn; the wording it supports in the
    caption is checked here."""

    from matplotlib.patches import Patch

    rows = D.process_slopes()
    panels = (("P_v", "ln_P", "a", "Laser power", "power", "larger at higher power →", "right"),
              ("P_v", "ln_v", "b", "Scan speed", "speed", "← smaller at higher speed", "left"),
              ("VED", "ln_VED", "c", "Energy density", "energy density", "larger at higher energy →", "right"))
    quantities = (("H", "H (length)"), ("W", "W (width)"), ("HW", "H/W (shape)"))
    fig, axes = plt.subplots(1, 3, figsize=(S.FULL_W, 2.55), sharey=True)
    src = []
    out = {}
    bar_h = 0.34
    for ax, (design, term, letter, title, word, direction, side) in zip(axes, panels):
        ax.axvline(0, color=S.INK_2, lw=0.8, zorder=1)
        for i, (q, _) in enumerate(quantities):
            y0 = len(quantities) - 1 - i
            for source, color, dy in (("camera", S.CAMERA, 0.19), ("model", S.MODEL, -0.19)):
                r = _slope(rows, "all_24", design, term, source, q)
                r2 = _slope(rows, "all_but_20260904_part_3", design, term, source, q)
                ax.barh(y0 + dy, r["estimate"], height=bar_h, color=color, alpha=0.85, lw=0, zorder=2)
                ax.plot([r["ci_lo"], r["ci_hi"]], [y0 + dy, y0 + dy], color=S.INK_2, lw=0.9, zorder=3,
                        solid_capstyle="butt")
                end = r["ci_hi"] if r["estimate"] >= 0 else r["ci_lo"]
                ax.text(end + (0.06 if r["estimate"] >= 0 else -0.06), y0 + dy, f"{r['estimate']:.2f}".replace("-", "−"),
                        ha="left" if r["estimate"] >= 0 else "right", va="center", fontsize=6.6, color=S.INK_2)
                out[(source, q, term)] = r
                out[(source, q, term, "excl")] = r2
                src.append(["all_24", design, term, source, q, r["estimate"], r["ci_lo"], r["ci_hi"],
                            "all_but_20260904_part_3", r2["estimate"]])
        lo = min(min(out[(s, q, term)]["ci_lo"] for s in ("camera", "model") for q, _ in quantities), 0)
        hi = max(max(out[(s, q, term)]["ci_hi"] for s in ("camera", "model") for q, _ in quantities), 0)
        pad = 0.28 * (hi - lo)
        ax.set_xlim(lo - (pad if lo < 0 else 0.15 * (hi - lo)), hi + (pad if hi > 0 else 0.15 * (hi - lo)))
        ax.text(0.98 if side == "right" else 0.02, 1.0, direction, transform=ax.transAxes,
                ha="right" if side == "right" else "left", va="top", fontsize=6.6, color=S.MUTED)
        ax.set_xlabel(f"% change per 1% increase\nin {word}", fontsize=8, linespacing=1.1)
        ax.grid(axis="y", visible=False)
        S.panel(ax, letter, title)
    axes[0].set_yticks([2, 1, 0])
    axes[0].set_yticklabels([label for _, label in quantities], fontsize=8)
    axes[0].set_ylim(-0.6, 2.75)
    handles = [Patch(facecolor=S.CAMERA, alpha=0.85, label="Experiment (camera)"),
               Patch(facecolor=S.MODEL, alpha=0.85, label="Simulation (calibrated model)")]
    fig.legend(handles=handles, loc="lower center", ncol=2, bbox_to_anchor=(0.5, -0.04), fontsize=7.5,
               handlelength=1.2, columnspacing=2.0)
    # Guards for the caption's wording: same direction for H and W, model at least twice as sensitive, also without
    # the lowest-energy coupon; camera shape nearly flat with energy density, model shape elongating.
    for key in ("", "excl"):
        for q in ("H", "W"):
            for term in ("ln_P", "ln_v", "ln_VED"):
                cam = out[("camera", q, term, key) if key else ("camera", q, term)]["estimate"]
                mod = out[("model", q, term, key) if key else ("model", q, term)]["estimate"]
                assert cam * mod > 0 and abs(mod) >= 2 * abs(cam), (q, term, key, cam, mod)
    assert abs(out[("camera", "HW", "ln_VED")]["estimate"]) < 0.1
    assert out[("model", "HW", "ln_VED")]["ci_lo"] > 0 and out[("model", "HW", "ln_P")]["ci_lo"] > 0
    S.write_csv(S.SOURCE_DIR / "F11_process_slopes.csv",
                ["subset", "design", "term", "source", "quantity", "estimate", "ci_lo", "ci_hi", "subset_2",
                 "estimate_2"], src)
    fig.subplots_adjust(wspace=0.12, bottom=0.3)
    S.save(fig, "F11_process_slopes")
    plt.close(fig)
    return {f"{s}_{q}_{t}": out[(s, q, t)]["estimate"] for s in ("camera", "model") for q, _ in quantities
            for t in ("ln_P", "ln_v", "ln_VED")}


ALL = {
    "F1": f1_process_space,
    "F6": f6_footprints,
    "F7": f7_candidate_ranking,
    "F8": f8_observed_vs_predicted,
    "F9": f9_calibration_vs_held_out,
    "F10": f10_ratio_vs_ved,
    "F11": f11_process_slopes,
}
