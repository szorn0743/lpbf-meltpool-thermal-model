"""Pass-2 figures F2, F4, F8, F9, F10, F12, F14, F15: source CSVs (numpy only) and PNG + SVG renders (matplotlib).

Same encoding as ``figures.py`` (window role = hue from the reference palette's first three categorical slots, data
status = marker shape). Magnitudes use the reference sequential blue ramp; model/camera ratios use the reference
blue-red diverging pair with a neutral gray midpoint at ratio 1. F13 (images and contours) is in
``field_figures.py``.
"""
from __future__ import annotations

import math
from typing import Mapping

import numpy as np

import common as C
from figures import AXIS, GRID, HUE, INK, INK_2, MARKER, MODEL_HUE, MUTED, SOURCE_DIR, SURFACE, WINDOW_FILL, _role_handles, _save, _scatter

FAMILY_BLAND_ALTMAN = 7
SEQUENTIAL = ("#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b")
DIVERGING = ("#184f95", "#3987e5", "#9ec5f4", "#f0efec", "#f2aaa9", "#e34948", "#a12f2e")
NEUTRAL_FILL = "#e1e0d9"
CAMERA_LINE = INK_2
REPRESENTATIVE = (("20260904:part_6", "Low VED"), ("20260730:part_3", "In window"), ("20260904:part_4", "High VED"))


def _f(row: Mapping[str, str], key: str) -> float:
    return float(row[key]) if row[key] != "" else float("nan")


# ---------------------------------------------------------------------- sources


def write_sources() -> list:
    d2 = C.read_csv(C.DATA_DIR / "D2_tracks.csv")
    d3 = C.read_csv(C.DATA_DIR / "D3_coupons.csv")
    d4 = C.read_csv(C.DATA_DIR / "D4_conditions_groups.csv")
    t4 = C.read_csv(C.TABLES_DIR / "T04_data_accounting.csv")
    pairs = C.read_csv(C.DATA_DIR / "T10_replicate_pairs.csv")
    cands = C.read_csv(C.DATA_DIR / "D6_candidate_search" / "D6_candidates.csv")
    cand_coupons = C.read_csv(C.DATA_DIR / "D6_candidate_search" / "D6_candidate_coupons.csv")
    files = []

    # F2: counts at every level of the hierarchy.
    total = next(r for r in t4 if r["member"] == "All 24 coupons")
    groups = {r["name"]: r for r in d4 if r["level"] == "group"}
    conditions = [r for r in d4 if r["level"] == "condition"]
    f2 = [
        {"level": "laser_on_mapped_frames", "count": int(total["laser_on_mapped_frames"]), "note": "sync-mapped camera frames on powered process rows"},
        {"level": "camera_invalid_frames", "count": int(total["camera_ineligible_frames"]), "note": "non-finite camera H/W; never in residuals"},
        {"level": "eligible_frames", "count": int(total["eligible_frames"]), "note": "A22 eligible"},
        {"level": "excluded_by_rule", "count": int(total["excluded_by_rule"]), "note": "first and last eligible frame of each track (A22)"},
        {"level": "undefined_frames", "count": int(total["undefined_frames"]), "note": "tied, unenclosed or no geometry; excluded and counted (A23)"},
        {"level": "scored_frames", "count": int(total["scored_frames"]), "note": "frame residual r = ln(max(model, 1) / max(camera, 1))"},
        {"level": "no_pool_frames", "count": int(total["no_pool_frames"]), "note": "scored as H = W = 0 (D1)"},
        {"level": "scan_tracks", "count": int(total["tracks_scored"]), "note": "track = mean of r² over its frames"},
        {"level": "coupons", "count": 24, "note": "coupon = mean over its tracks; coverage floor 95 % (A23)"},
        {"level": "conditions", "count": len(conditions), "note": "condition = mean over its replicate coupons"},
        {"level": "conditions_with_two_coupons", "count": sum(1 for r in conditions if int(r["coupons"]) == 2), "note": "July replicate pairs"},
        {"level": "calibration_conditions", "count": int(groups["calibration"]["conditions"]), "note": "group = mean over its conditions; e = sqrt, J = 0.5 e_H² + 0.5 e_W²"},
        {"level": "in_window_held_out_conditions", "count": int(groups["in_window_held_out"]["conditions"]), "note": ""},
        {"level": "out_of_window_conditions", "count": int(groups["out_of_window_all"]["conditions"]), "note": ""},
    ]
    files.append(C.write_csv(SOURCE_DIR / "F2_hierarchy.csv", f2))

    # F4: candidate points (the surface and guard slices are written by candidates.py).
    f4 = [{k: r[k] for k in ("candidate", "origin", "t", "ck", "eta", "coded_x1", "coded_x2", "coded_x3", "J", "guard_value", "near_best", "selected")} for r in cands]
    files.append(C.write_csv(SOURCE_DIR / "F4_candidates.csv", f4))

    # F8: Bland-Altman on coupon medians (log scale), bias and limits over the 14 in-window coupons.
    points, lines = [], []
    for k, q in enumerate(("H", "W")):
        for r in d3:
            cam, sim = _f(r, f"cam_{q}_um_median"), _f(r, f"sim_{q}_um_median_pool")
            points.append(
                {
                    "member": r["member"], "role": r["role"], "quantity": q, "ved_J_mm3": _f(r, "ved_J_mm3"),
                    "geometric_mean_size_um": math.sqrt(cam * sim), "median_log_ratio": _f(r, f"median_r_{q}"), "no_pool_fraction": _f(r, "no_pool_fraction"),
                }
            )
        sub = [p for p in points if p["quantity"] == q]
        inside = np.array([p["median_log_ratio"] for p in sub if p["role"] in ("calibration", "in_window_held_out")])
        bias, sd = float(inside.mean()), float(inside.std(ddof=1))
        picks = C.rng(FAMILY_BLAND_ALTMAN, k).integers(0, inside.size, size=(C.BOOTSTRAP_REPLICATES, inside.size))
        lo, hi = C.percentile_ci(inside[picks].mean(axis=1))
        x = np.log([p["geometric_mean_size_um"] for p in sub])
        y = np.array([p["median_log_ratio"] for p in sub])
        slope = float(np.polyfit(x, y, 1)[0])
        lines.append(
            {
                "quantity": q, "coupons_for_bias": int(inside.size), "bias": bias, "bias_ci_lo": float(lo), "bias_ci_hi": float(hi),
                "loa_lo": bias - 1.96 * sd, "loa_hi": bias + 1.96 * sd, "sd": sd, "bias_as_ratio": math.exp(bias),
                "proportional_slope_all_24": slope, "replicates": C.BOOTSTRAP_REPLICATES, "generator_keys": f"[{C.SEED}, {FAMILY_BLAND_ALTMAN}, {k}]",
            }
        )
    files.append(C.write_csv(SOURCE_DIR / "F8_bland_altman_points.csv", points))
    files.append(C.write_csv(SOURCE_DIR / "F8_bland_altman_lines.csv", lines))

    # F9: replicate pairs.
    keep = ("cam_H", "cam_W", "sim_H", "sim_W", "e_H", "e_W")
    files.append(C.write_csv(SOURCE_DIR / "F9_replicates.csv", [r for r in pairs if r["quantity"] in keep]))

    # F10: no-pool fraction and coverage against VED and speed.
    f10 = [
        {
            "member": r["member"], "role": r["role"], "ved_J_mm3": _f(r, "ved_J_mm3"), "speed_mm_s": _f(r, "speed_mm_s"), "power_W": _f(r, "power_W"),
            "scored_frames": int(r["scored_frames"]), "no_pool_frames": int(r["no_pool_frames"]), "no_pool_fraction": _f(r, "no_pool_fraction"),
            "no_laser_associated_melt_frames": int(r["no_laser_associated_melt_frames"]), "zero_footprint_frames": int(r["zero_footprint_frames"]), "coverage": _f(r, "coverage"),
        }
        for r in d3
    ]
    files.append(C.write_csv(SOURCE_DIR / "F10_no_pool_coverage.csv", f10))

    # F12: track medians through the layer for three representative coupons.
    f12 = []
    for member, label in REPRESENTATIVE:
        for r in d2:
            if r["member"] == member and int(r["scored_frames"]) > 0:
                f12.append(
                    {
                        "member": member, "panel": label, "ved_J_mm3": _f(r, "ved_J_mm3"), "scan_track_id": int(r["scan_track_id"]), "scored_frames": int(r["scored_frames"]),
                        "camera_H_um": C.UM_PER_PX * _f(r, "cam_H_px_median"), "camera_W_um": C.UM_PER_PX * _f(r, "cam_W_px_median"),
                        "model_H_um": C.UM_PER_PX * _f(r, "sim_H_px_median_pool"), "model_W_um": C.UM_PER_PX * _f(r, "sim_W_px_median_pool"),
                        "no_pool_frames": int(r["no_pool_frames"]),
                    }
                )
    files.append(C.write_csv(SOURCE_DIR / "F12_within_layer.csv", f12))

    # F14: peak temperature.
    f14a = [{"member": r["member"], "role": r["role"], "ved_J_mm3": _f(r, "ved_J_mm3"), "peak_above_boiling_fraction": _f(r, "peak_above_boiling_fraction"), "median_peak_surface_K": _f(r, "median_peak_surface_K")} for r in d3]
    f14b = [{k: r[k] for k in ("candidate", "origin", "t", "ck", "eta", "J", "e_H", "e_W", "fraction_peak_above_boiling", "median_peak_surface_K", "selected", "near_best")} for r in cands]
    f14c = [{k: r[k] for k in ("candidate", "member", "condition", "median_r_H", "median_r_W", "e_H", "e_W", "median_peak_surface_K", "fraction_peak_above_boiling", "p95_peak_surface_K")} for r in cand_coupons]
    peaks = [_f(r, "median_peak_surface_K") for r in cand_coupons]
    f14s = [
        {
            "statistic": f"spearman_median_peak_vs_abs_median_r_{q}", "points": len(cand_coupons),
            "value": C.spearman(peaks, [abs(_f(r, f"median_r_{q}")) for r in cand_coupons]),
        }
        for q in ("H", "W")
    ]
    files.append(C.write_csv(SOURCE_DIR / "F14_c1_coupons.csv", f14a))
    files.append(C.write_csv(SOURCE_DIR / "F14_candidates.csv", f14b))
    files.append(C.write_csv(SOURCE_DIR / "F14_candidate_coupons.csv", f14c))
    files.append(C.write_csv(SOURCE_DIR / "F14_rank_correlation.csv", f14s))

    # F15: condition values over process space.
    f15 = [
        {
            "condition": r["name"], "role": r["role"], "power_W": _f(r, "power_W"), "speed_mm_s": _f(r, "speed_mm_s"), "ved_J_mm3": _f(r, "ved_J_mm3"), "coupons": int(r["coupons"]),
            "median_H_ratio": _f(r, "median_H_ratio"), "median_W_ratio": _f(r, "median_W_ratio"), "e_H": _f(r, "e_H"), "e_W": _f(r, "e_W"),
            "no_pool_fraction": int(r["no_pool_frames"]) / int(r["scored_frames"]),
        }
        for r in conditions
    ]
    files.append(C.write_csv(SOURCE_DIR / "F15_process_space.csv", f15))
    return files


# ---------------------------------------------------------------------- renders


def f2(plt) -> list:
    from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

    src = {r["level"]: int(r["count"]) for r in C.read_csv(SOURCE_DIR / "F2_hierarchy.csv")}
    levels = [
        ("Camera frames", f"{src['laser_on_mapped_frames']:,} laser-on mapped\n{src['eligible_frames']:,} eligible\n{src['scored_frames']:,} scored",
         "Residual per frame:\nr = ln(max(model, 1 px)\n         / max(camera, 1 px))",
         f"− {src['camera_invalid_frames']} camera-invalid, never scored\n− {src['excluded_by_rule']:,} first or last of a track (A22)\n− {src['undefined_frames']} undefined (A23)\n{src['no_pool_frames']} no-pool frames scored as 0 (D1)"),
        ("Scan tracks", f"{src['scan_tracks']:,} tracks", "Track = mean of r² over\nits frames (each frame equal)", "Bootstrap for one coupon or\ncondition: tracks resampled\nwithin each coupon"),
        ("Coupons", f"{src['coupons']} coupons", "Coupon = mean over its tracks\n(each track equal, whatever\nits length)", "Coverage checked per coupon\n(floor 95 %). The inferential\nunit"),
        ("Conditions", f"{src['conditions']} exact conditions\n{src['conditions_with_two_coupons']} with two July replicates", "Condition = mean over\nits coupons", "Day-to-day differences\n(0730 vs 0731) sit here (T10)"),
        ("Groups", f"conditions: calibration {src['calibration_conditions']},\nheld out {src['in_window_held_out_conditions']}, out of window {src['out_of_window_conditions']}", "Group = mean over its conditions;\ne = √(mean), J = ½ e_H² + ½ e_W²", "Bootstrap for a group:\ncoupons resampled within\nthe group"),
    ]
    fig, ax = plt.subplots(figsize=(6.5, 6.4))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 10.5)
    ax.axis("off")
    x_weight, x_note = 3.15, 6.85
    ax.text(x_weight, 10.3, "Averaging and weighting", fontsize=7.5, color=MUTED, ha="left", va="center", fontweight="bold")
    ax.text(x_note, 10.3, "Exclusions and uncertainty", fontsize=7.5, color=MUTED, ha="left", va="center", fontweight="bold")
    tops = [9.95 - k * 2.0 for k in range(len(levels))]
    for k, ((name, count, weight, note), top) in enumerate(zip(levels, tops)):
        box = FancyBboxPatch((0.05, top - 1.5), 2.8, 1.5, boxstyle="round,pad=0.02,rounding_size=0.12", facecolor=WINDOW_FILL, edgecolor=AXIS, linewidth=0.8)
        ax.add_patch(box)
        ax.text(0.22, top - 0.3, name, fontsize=8.5, color=INK, fontweight="bold", va="center")
        ax.text(0.22, top - 0.95, count, fontsize=6.6, color=INK_2, va="center", linespacing=1.3)
        ax.text(x_weight, top - 0.75, weight, fontsize=6.6, color=INK, va="center", linespacing=1.35)
        ax.text(x_note, top - 0.75, note, fontsize=6.6, color=INK_2, va="center", linespacing=1.35)
        if k < len(levels) - 1:
            ax.add_patch(FancyArrowPatch((1.45, top - 1.53), (1.45, tops[k + 1] + 0.03), arrowstyle="-|>", mutation_scale=9, color=MUTED, linewidth=1.0))
            ax.plot([3.0, 9.95], [top - 1.75, top - 1.75], color=GRID, linewidth=0.6)
    fig.suptitle("Analysis hierarchy", x=0.0, ha="left", fontsize=10, fontweight="bold", color=INK)
    fig.text(0.0, 0.02, "Every level is an unweighted mean of the level below (A10, A26): frame counts never weight tracks, coupons or conditions.", fontsize=7, color=INK_2)
    out = _save(fig, "F2_hierarchy")
    plt.close(fig)
    return out


def f4(plt) -> list:
    from matplotlib.colors import LinearSegmentedColormap

    from lpbf.calibration import CODED_CENTER, CODED_HALF_RANGE

    surface = C.read_csv(SOURCE_DIR / "F4_surrogate_slices.csv")
    guard = C.read_csv(SOURCE_DIR / "F4_guard_slices.csv")
    meta = C.load_json(SOURCE_DIR / "F4_surface_meta.json")
    points = C.read_csv(SOURCE_DIR / "F4_candidates.csv")
    cmap = LinearSegmentedColormap.from_list("seq", SEQUENTIAL[::-1])  # dark = low J = better
    names = {0: ("t", "abs_depth"), 1: ("ck", "ck"), 2: ("η", "eta")}
    panels = (("t_ck", 0, 1, 2), ("t_eta", 0, 2, 1), ("ck_eta", 1, 2, 0))
    fig, axes = plt.subplots(1, 3, figsize=(6.5, 2.75))
    levels = np.array([0.28, 0.30, 0.32, 0.35, 0.40, 0.50, 0.60, 0.80, 1.00, 1.30])  # dense near the minimum (0.283)
    for ax, (name, ix, iy, ifix) in zip(axes, panels):
        rows = [r for r in surface if r["slice"] == name]
        n = int(meta["grid"])
        X = np.array([float(r["x_coded"]) for r in rows]).reshape(n, n)
        Y = np.array([float(r["y_coded"]) for r in rows]).reshape(n, n)
        Z = np.array([float(r["J_surrogate"]) for r in rows]).reshape(n, n)
        to_x = lambda c, i=ix: CODED_CENTER[i] + CODED_HALF_RANGE[i] * np.asarray(c)
        to_y = lambda c, i=iy: CODED_CENTER[i] + CODED_HALF_RANGE[i] * np.asarray(c)
        filled = ax.contourf(to_x(X), to_y(Y), np.clip(Z, levels[0], levels[-1] - 1e-9), levels=levels, cmap=cmap, extend="neither")
        ax.contour(to_x(X), to_y(Y), Z, levels=levels, colors=SURFACE, linewidths=0.4)
        grows = [r for r in guard if r["slice"] == name]
        m = int(meta["guard_grid"])
        GX = np.array([float(r["x_coded"]) for r in grows]).reshape(m, m)
        GY = np.array([float(r["y_coded"]) for r in grows]).reshape(m, m)
        GZ = np.array([float(r["guard_value"]) for r in grows]).reshape(m, m)
        if GZ.max() > meta["guard_maximum"]:
            ax.contourf(to_x(GX), to_y(GY), GZ, levels=[meta["guard_maximum"], GZ.max() + 1], colors=[NEUTRAL_FILL], alpha=0.92)
            ax.contour(to_x(GX), to_y(GY), GZ, levels=[meta["guard_maximum"]], colors=[INK], linewidths=1.0)
        for edge in (-0.9, 0.9):
            ax.axvline(to_x(edge), color=SURFACE, linewidth=0.6, alpha=0.8)
            ax.axhline(to_y(edge), color=SURFACE, linewidth=0.6, alpha=0.8)
        for p in points:
            x, y = float(p[f"coded_x{ix + 1}"]), float(p[f"coded_x{iy + 1}"])
            if p["selected"] == "true":
                ax.scatter([to_x(x)], [to_y(y)], s=110, marker="*", color=INK, edgecolors=SURFACE, linewidths=1.0, zorder=6, clip_on=False)
            elif p["origin"] == "confirmation":
                ax.scatter([to_x(x)], [to_y(y)], s=30, marker="s", color=INK_2, edgecolors=SURFACE, linewidths=1.0, zorder=5, clip_on=False)
            else:
                ax.scatter([to_x(x)], [to_y(y)], s=18, marker="o", facecolors=SURFACE, edgecolors=INK_2, linewidths=0.9, zorder=4, clip_on=False)
        fixed = CODED_CENTER[ifix] + CODED_HALF_RANGE[ifix] * meta["c1_coded"][ifix]
        ax.set_title(f"{names[ifix][0]} = {fixed:.3g} (c1)", fontsize=8.5, loc="left")
        ax.set_xlabel(names[ix][0])
        ax.set_ylabel(names[iy][0])
        ax.grid(False)
        ax.set_xlim(to_x(-1), to_x(1))
        ax.set_ylim(to_y(-1), to_y(1))
    cbar = fig.colorbar(filled, ax=axes, orientation="horizontal", fraction=0.05, pad=0.28, aspect=50, spacing="uniform")
    cbar.set_label("Surrogate J (quadratic fit to the 17 design points)", fontsize=7.5, color=INK_2)
    cbar.ax.tick_params(labelsize=7)
    cbar.outline.set_visible(False)
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch

    handles = [
        Line2D([], [], linestyle="none", marker="o", markersize=5, markerfacecolor=SURFACE, markeredgecolor=INK_2, label="design point (projected)"),
        Line2D([], [], linestyle="none", marker="s", markersize=5, color=INK_2, label="confirmation c2"),
        Line2D([], [], linestyle="none", marker="*", markersize=9, color=INK, label="selected c1"),
        Patch(facecolor=NEUTRAL_FILL, edgecolor=INK, linewidth=0.8, label="guard > 0.95 (inadmissible)"),
    ]
    fig.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, 1.07), ncol=4, fontsize=7, handletextpad=0.3, columnspacing=1.0)
    fig.suptitle("Calibration response surface", x=0.0, y=1.15, ha="left", fontsize=10, fontweight="bold", color=INK)
    fit = C.load_json(C.DATA_DIR / "D6_candidate_search" / "D6_selection_reconstruction.json")["surrogate_refit"]
    fig.text(0.0, -0.2, f"Surface: the recorded quadratic surrogate (R² {fit['r_squared_recorded']:.4f}, LOO RMSE {fit['loo_rmse_recorded']:.3f}) on slices through c1; the surrogate proposed c1, the measured J selected it.\nPanel limits = the box; white lines: |coded| = 0.9 (reading C edge). Points are the 19 measured candidates projected onto each plane.", fontsize=7, color=INK_2)
    fig.subplots_adjust(wspace=0.45, bottom=0.3)
    out = _save(fig, "F4_response_surface")
    plt.close(fig)
    return out


def f8(plt) -> list:
    points = C.read_csv(SOURCE_DIR / "F8_bland_altman_points.csv")
    lines = {r["quantity"]: r for r in C.read_csv(SOURCE_DIR / "F8_bland_altman_lines.csv")}
    fig, axes = plt.subplots(1, 2, figsize=(6.5, 3.3), sharey=True)
    for ax, q in ((axes[0], "H"), (axes[1], "W")):
        L = lines[q]
        ax.set_xscale("log")
        ax.axhline(0.0, color=AXIS, linewidth=1.0, zorder=1)
        ax.axhspan(float(L["bias_ci_lo"]), float(L["bias_ci_hi"]), color=MODEL_HUE, alpha=0.12, linewidth=0, zorder=1)
        ax.axhline(float(L["bias"]), color=MODEL_HUE, linewidth=1.2, zorder=2)
        for key in ("loa_lo", "loa_hi"):
            ax.axhline(float(L[key]), color=MUTED, linewidth=0.8, zorder=2)
        for r in points:
            if r["quantity"] != q:
                continue
            x, y = float(r["geometric_mean_size_um"]), float(r["median_log_ratio"])
            heavy = float(r["no_pool_fraction"]) > 0.05
            role = r["role"]
            ax.scatter([x], [y], s=40, marker=MARKER[role], facecolors=SURFACE if heavy else HUE[role], edgecolors=HUE[role] if heavy else SURFACE, linewidths=1.2, zorder=3)
        ax.text(
            0.03, 0.97,
            f"In-window bias {float(L['bias']):+.2f} [{float(L['bias_ci_lo']):+.2f}, {float(L['bias_ci_hi']):+.2f}] (×{float(L['bias_as_ratio']):.2f})\n"
            f"limits {float(L['loa_lo']):+.2f} to {float(L['loa_hi']):+.2f}; slope on ln size (24) {float(L['proportional_slope_all_24']):+.2f}",
            transform=ax.transAxes, fontsize=6.5, color=INK_2, va="top",
        )
        ax.set_xlabel(f"√(camera {q} × model {q}), coupon medians (µm)", fontsize=8)
        ax.set_title(f"{q}", loc="left")
        from matplotlib.ticker import FixedLocator, NullFormatter, NullLocator, ScalarFormatter

        ax.xaxis.set_major_locator(FixedLocator([60, 80, 100, 120, 150] if q == "H" else [40, 50, 60, 70, 80, 90]))
        ax.xaxis.set_major_formatter(ScalarFormatter())
        ax.xaxis.set_minor_locator(NullLocator())
        ax.xaxis.set_minor_formatter(NullFormatter())
    axes[0].set_ylabel("ln(model / camera), coupon median")
    fig.suptitle("Bland–Altman agreement", x=0.0, ha="left", fontsize=10, fontweight="bold", color=INK)
    fig.legend(handles=_role_handles(plt), loc="lower center", bbox_to_anchor=(0.5, -0.1), ncol=4, fontsize=7.5, handletextpad=0.3, columnspacing=1.0)
    fig.text(0.0, -0.2, "Bias line, its 95 % coupon-bootstrap band and ±1.96 SD limits over the 14 in-window coupons; points outside the window show the proportional trend (T9).\nOpen markers: no pool on > 5 % of frames. On the log scale a difference is a ratio; sizes at the nominal 8 µm/px (A24).", fontsize=7, color=INK_2)
    fig.tight_layout()
    out = _save(fig, "F8_bland_altman")
    plt.close(fig)
    return out


def f9(plt) -> list:
    rows = C.read_csv(SOURCE_DIR / "F9_replicates.csv")
    panels = (("cam_H", "Camera H (px)"), ("cam_W", "Camera W (px)"), ("e_H", "e_H"), ("sim_H", "Model H (px)"), ("sim_W", "Model W (px)"), ("e_W", "e_W"))
    fig, axes = plt.subplots(2, 3, figsize=(6.5, 4.6))
    for ax, (key, label) in zip(axes.ravel(), panels):
        sub = [r for r in rows if r["quantity"] == key]
        xs = [float(r["value_0730"]) for r in sub]
        ys = [float(r["value_0731"]) for r in sub]
        lo = min(min(float(r["value_0730_ci_lo"]) for r in sub), min(float(r["value_0731_ci_lo"]) for r in sub))
        hi = max(max(float(r["value_0730_ci_hi"]) for r in sub), max(float(r["value_0731_ci_hi"]) for r in sub))
        pad = 0.06 * (hi - lo)
        lim = (lo - pad, hi + pad)
        ax.plot(lim, lim, color=AXIS, linewidth=1.0, zorder=1)
        for r, x, y in zip(sub, xs, ys):
            role = r["role"]
            ax.plot([float(r["value_0730_ci_lo"]), float(r["value_0730_ci_hi"])], [y, y], color=HUE[role], linewidth=1.0, zorder=2)
            ax.plot([x, x], [float(r["value_0731_ci_lo"]), float(r["value_0731_ci_hi"])], color=HUE[role], linewidth=1.0, zorder=2)
            _scatter(ax, [x], [y], role, size=30)
        ax.set_xlim(*lim)
        ax.set_ylim(*lim)
        ax.set_title(label, loc="left", fontsize=8.5)
        if key.startswith("e_"):
            gap = max(float(r["difference"]) for r in sub)
            ax.text(0.97, 0.05, f"0731 − 0730: up to {gap:+.2f}", transform=ax.transAxes, fontsize=6.5, color=INK_2, ha="right")
        else:
            gap = max(abs(math.exp(float(r["difference"])) - 1.0) for r in sub)
            ax.text(0.97, 0.05, f"|Δ| ≤ {100 * gap:.1f} %", transform=ax.transAxes, fontsize=6.5, color=INK_2, ha="right")
        ax.tick_params(labelsize=7)
    for ax in axes[1]:
        ax.set_xlabel("20260730", fontsize=8)
    for ax in axes[:, 0]:
        ax.set_ylabel("20260731", fontsize=8)
    fig.suptitle("Replicate agreement", x=0.0, ha="left", fontsize=10, fontweight="bold", color=INK)
    fig.legend(handles=_role_handles(plt, ("calibration", "in_window_held_out")), loc="lower center", bbox_to_anchor=(0.5, -0.06), ncol=2, fontsize=7.5)
    fig.text(0.0, -0.11, "Coupon medians (px) and coupon e; bars: 95 % track-bootstrap intervals within each coupon. Grey line 1:1. Paired differences in T10.", fontsize=7, color=INK_2)
    fig.tight_layout()
    out = _save(fig, "F9_replicate_agreement")
    plt.close(fig)
    return out


def f10(plt) -> list:
    rows = C.read_csv(SOURCE_DIR / "F10_no_pool_coverage.csv")
    fig, axes = plt.subplots(1, 2, figsize=(6.5, 3.1), sharey=True)
    for ax, key, label in ((axes[0], "ved_J_mm3", "VED (J/mm³)"), (axes[1], "speed_mm_s", "Scan speed v (mm/s)")):
        if key == "ved_J_mm3":
            ax.axvspan(*C.VED_WINDOW_J_MM3, color=WINDOW_FILL, zorder=0, linewidth=0)
        for r in rows:
            _scatter(ax, [float(r[key])], [100.0 * float(r["no_pool_fraction"])], r["role"], size=40)
        worst = max(rows, key=lambda r: float(r["no_pool_fraction"]))
        right = key == "speed_mm_s"  # the worst coupon sits at the right edge of the speed axis
        ax.annotate(f"{worst['member']}\n{int(worst['no_pool_frames'])} of {int(worst['scored_frames'])} frames", (float(worst[key]), 100.0 * float(worst["no_pool_fraction"])),
                    xytext=(-10, -6) if right else (10, -6), textcoords="offset points", fontsize=6.5, color=INK_2, ha="right" if right else "left", va="top")
        ax.set_xlabel(label)
    axes[0].set_ylabel("No-pool frames (% of scored)")
    axes[0].set_ylim(-3, 60)
    cov = sorted({float(r["coverage"]) for r in rows})
    cov_text = f"{cov[0]:.3f}" if len(cov) == 1 else f"{cov[0]:.3f}–{cov[-1]:.3f}"
    fig.suptitle("Frames without a predicted pool", x=0.0, ha="left", fontsize=10, fontweight="bold", color=INK)
    fig.legend(handles=_role_handles(plt), loc="lower center", bbox_to_anchor=(0.5, -0.1), ncol=4, fontsize=7.5, handletextpad=0.3, columnspacing=1.0)
    fig.text(0.0, -0.17, f"No laser-associated melt or zero footprint: scored as H = W = 0 with the 1 px floor (D1). Coverage = {cov_text} for every coupon: no observation was dropped (T4, T13).", fontsize=7, color=INK_2)
    fig.tight_layout()
    out = _save(fig, "F10_no_pool_coverage")
    plt.close(fig)
    return out


def f12(plt) -> list:
    rows = C.read_csv(SOURCE_DIR / "F12_within_layer.csv")
    fig, axes = plt.subplots(2, 3, figsize=(6.5, 4.2), sharex=True)
    for col, (member, label) in enumerate(REPRESENTATIVE):
        sub = sorted((r for r in rows if r["member"] == member), key=lambda r: int(r["scan_track_id"]))
        x = [int(r["scan_track_id"]) for r in sub]
        for row, q in enumerate(("H", "W")):
            ax = axes[row, col]
            ax.plot(x, [float(r[f"camera_{q}_um"]) for r in sub], color=CAMERA_LINE, linewidth=1.4, marker="o", markersize=2.5, label="camera")
            ax.plot(x, [float(r[f"model_{q}_um"]) for r in sub], color=MODEL_HUE, linewidth=1.4, marker="s", markersize=2.5, label="model")
            ax.set_ylim(bottom=0)
            ax.tick_params(labelsize=7)
            if row == 0:
                ax.set_title(f"{label}: {member}\n{float(sub[0]['ved_J_mm3']):.1f} J/mm³", loc="left", fontsize=8)
            if col == 0:
                ax.set_ylabel(f"Track median {q} (µm)", fontsize=8)
            if row == 1:
                ax.set_xlabel("Scan track (scan order)", fontsize=8)
    from matplotlib.lines import Line2D

    handles = [Line2D([], [], color=CAMERA_LINE, marker="o", markersize=4, linewidth=1.4, label="Camera, threshold 150"), Line2D([], [], color=MODEL_HUE, marker="s", markersize=4, linewidth=1.4, label="Model liquidus, confirm_c1")]
    fig.legend(handles=handles, loc="lower center", bbox_to_anchor=(0.5, -0.05), ncol=2, fontsize=7.5)
    fig.suptitle("Track medians in scan order", x=0.0, ha="left", fontsize=10, fontweight="bold", color=INK)
    fig.text(0.0, -0.1, "Model medians over frames with a predicted pool; nominal 8 µm/px (A24). Three A8 calibration members (examined by 22.3.8).", fontsize=7, color=INK_2)
    fig.tight_layout()
    out = _save(fig, "F12_within_layer")
    plt.close(fig)
    return out


def f14(plt) -> list:
    c1 = C.read_csv(SOURCE_DIR / "F14_c1_coupons.csv")
    cands = C.read_csv(SOURCE_DIR / "F14_candidates.csv")
    cc = C.read_csv(SOURCE_DIR / "F14_candidate_coupons.csv")
    fig, axes = plt.subplots(1, 3, figsize=(6.5, 2.9))
    ax = axes[0]
    ax.axvspan(*C.VED_WINDOW_J_MM3, color=WINDOW_FILL, zorder=0, linewidth=0)
    for r in c1:
        _scatter(ax, [float(r["ved_J_mm3"])], [100.0 * float(r["peak_above_boiling_fraction"])], r["role"], size=30)
    ax.set_xlabel("VED (J/mm³)")
    ax.set_ylabel("Frames with peak > 3133 K (%)")
    ax.set_title("a. c1, by coupon", loc="left", fontsize=8.5)
    ax = axes[1]
    for r in cands:
        sel, conf = r["selected"] == "true", r["origin"] == "confirmation"
        ax.scatter([float(r["t"])], [100.0 * float(r["fraction_peak_above_boiling"])], s=110 if sel else (22 if conf else 22), marker="*" if sel else ("s" if conf else "o"),
                   facecolors=INK if sel else (INK_2 if conf else SURFACE), edgecolors=SURFACE if (sel or conf) else INK_2, linewidths=0.9, zorder=5 if sel else (4 if conf else 3), clip_on=False)
    ax.set_xlabel("t (absorptivity–depth coordinate)")
    ax.set_title("b. 19 candidates, calibration", loc="left", fontsize=8.5)
    ax = axes[2]
    for r in cc:
        if r["candidate"] == C.CANDIDATE:
            continue
        ax.scatter([float(r["median_peak_surface_K"])], [abs(float(r["median_r_H"]))], s=12, facecolors=SURFACE, edgecolors=MUTED, linewidths=0.7, zorder=2)
    for r in cc:
        if r["candidate"] == C.CANDIDATE:
            ax.scatter([float(r["median_peak_surface_K"])], [abs(float(r["median_r_H"]))], s=40, marker="*", color=INK, edgecolors=SURFACE, linewidths=0.8, zorder=4)
    ax.axvline(C.BOILING_K, color=AXIS, linewidth=1.0)
    ax.text(C.BOILING_K + 25, 0.02, "3133 K", transform=ax.get_xaxis_transform(), fontsize=6.5, color=MUTED, va="bottom", ha="left")
    ax.set_xlabel("Coupon median peak T (K)")
    ax.set_ylabel("|coupon median r_H|")
    ax.set_title("c. candidate × coupon", loc="left", fontsize=8.5)
    for a in axes:
        a.tick_params(labelsize=7)
    rho = {r["statistic"][-1]: float(r["value"]) for r in C.read_csv(SOURCE_DIR / "F14_rank_correlation.csv")}
    fig.suptitle("Peak surface temperature", x=0.0, ha="left", fontsize=10, fontweight="bold", color=INK)
    fig.text(
        0.0, -0.08,
        "a: role markers as in F5. b, c: star = selected c1, square = c2, open = design points (c: the 17 design points and c2 on the 9 calibration coupons; stars: c1).\n"
        f"Across candidates and coupons, Spearman ρ(peak T, |r_H|) = {rho['H']:.2f} and ρ(peak T, |r_W|) = {rho['W']:.2f}"
        + (": the best H agreement comes at the coolest peaks,\nnot at temperatures above boiling." if rho["H"] > 0 else ": better H agreement comes with hotter peaks.\n")
        + " The regulator is a surface loss above 3133 K, not a cap (T5).",
        fontsize=7, color=INK_2,
    )
    fig.tight_layout()
    out = _save(fig, "F14_peak_temperature")
    plt.close(fig)
    return out


def f15(plt) -> list:
    from matplotlib.colors import LinearSegmentedColormap, LogNorm, Normalize
    from matplotlib.patches import Rectangle

    rows = C.read_csv(SOURCE_DIR / "F15_process_space.csv")
    powers = sorted({float(r["power_W"]) for r in rows})
    speeds = sorted({float(r["speed_mm_s"]) for r in rows})
    seq = LinearSegmentedColormap.from_list("seq", SEQUENTIAL)
    div = LinearSegmentedColormap.from_list("div", DIVERGING)
    from matplotlib.ticker import FixedLocator, FuncFormatter

    panels = (
        ("median_H_ratio", "Median H ratio (model / camera)", div, LogNorm(vmin=0.25, vmax=4.0), "{:.2f}"),
        ("median_W_ratio", "Median W ratio (model / camera)", div, LogNorm(vmin=0.25, vmax=4.0), "{:.2f}"),
        ("e_H", "e_H", seq, Normalize(vmin=0.0, vmax=1.6), "{:.2f}"),
        ("e_W", "e_W", seq, Normalize(vmin=0.0, vmax=1.6), "{:.2f}"),
        ("no_pool_fraction", "No-pool fraction", seq, Normalize(vmin=0.0, vmax=0.6), "{:.0%}"),
    )
    fig, axes = plt.subplots(3, 2, figsize=(6.5, 7.4))
    axes = axes.ravel()
    for ax, (key, title, cmap, norm, fmt) in zip(axes, panels):
        ax.set_facecolor(SURFACE)
        for r in rows:
            i, j = speeds.index(float(r["speed_mm_s"])), powers.index(float(r["power_W"]))
            value = float(r[key])
            color = cmap(norm(value))
            ax.add_patch(Rectangle((i - 0.46, j - 0.46), 0.92, 0.92, facecolor=color, edgecolor=INK if r["role"] in ("calibration", "in_window_held_out") else "none", linewidth=0.9))
            luminance = 0.2126 * color[0] + 0.7152 * color[1] + 0.0722 * color[2]
            ax.text(i, j, fmt.format(value), ha="center", va="center", fontsize=6.3, color=SURFACE if luminance < 0.5 else INK)
        ax.set_xlim(-0.6, len(speeds) - 0.4)
        ax.set_ylim(-0.6, len(powers) - 0.4)
        ax.set_xticks(range(len(speeds)), [f"{s:.0f}" for s in speeds], fontsize=6.3, rotation=45, ha="right", rotation_mode="anchor")
        ax.set_yticks(range(len(powers)), [f"{p:.0f}" for p in powers], fontsize=6.5)
        ax.grid(False)
        ax.tick_params(length=0)
        for s in ax.spines.values():
            s.set_visible(False)
        ax.set_title(title, loc="left", fontsize=8.5)
        sm = plt.cm.ScalarMappable(norm=norm, cmap=cmap)
        cb = fig.colorbar(sm, ax=ax, fraction=0.04, pad=0.02)
        if isinstance(norm, LogNorm):
            cb.ax.yaxis.set_major_locator(FixedLocator([0.25, 0.5, 1.0, 2.0, 4.0]))
            cb.ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}"))
            cb.ax.yaxis.set_minor_locator(FixedLocator([]))
        cb.ax.tick_params(labelsize=6)
        cb.outline.set_visible(False)
    axes[-1].axis("off")
    axes[-1].text(0.02, 0.92, "Rows: power P (W). Columns: scan speed v (mm/s),\nas categories (not to scale).\n\nOutlined cells: inside the calibration window\n(65–85 J/mm³).\n\nRatios: blue below 1 (model smaller), red above\n1 (model larger), log scale centred at 1.\n\nCondition values: the coupons of a replicate pair\npooled (D4).", fontsize=7, color=INK_2, va="top", transform=axes[-1].transAxes)
    for ax in axes[[0, 2, 4]]:
        ax.set_ylabel("P (W)", fontsize=8)
    for ax in axes[[3, 4]]:
        ax.set_xlabel("v (mm/s)", fontsize=8)
    fig.suptitle("Agreement over process space", x=0.0, ha="left", fontsize=10, fontweight="bold", color=INK)
    fig.tight_layout()
    out = _save(fig, "F15_process_space_heatmaps")
    plt.close(fig)
    return out


def render() -> list:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from figures import _style

    _style(plt)
    out = []
    for fn in (f2, f4, f8, f9, f10, f12, f14, f15):
        out += fn(plt)
    return out
