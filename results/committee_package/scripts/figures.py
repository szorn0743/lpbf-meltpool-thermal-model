"""Pass-1 figures F1, F3, F5, F6, F7, F11: source CSVs (numpy only) and PNG + SVG renders (matplotlib).

``write_sources`` builds every plotted value from the package data files, so the figure sources are reproducible in
``.venv``. ``render`` needs matplotlib (``.venv-analysis``) and draws only from those source files.

Encoding (light surface, static print figures): hue = window role, from the reference palette's first three
categorical slots (validated all-pairs for scatter forms); marker shape = data status, so the two out-of-window
groups share a hue and differ by shape, and no identity is carried by color alone.
"""
from __future__ import annotations

from typing import Any, Mapping

import numpy as np

import common as C

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
WINDOW_FILL = "#ecebe6"
HUE = {"calibration": "#2a78d6", "in_window_held_out": "#eb6834", "out_of_window_examined": "#1baf7a", "out_of_window_blind": "#1baf7a"}
MARKER = {"calibration": "o", "in_window_held_out": "s", "out_of_window_examined": "^", "out_of_window_blind": "D"}
CAMERA_HUE = INK_2
MODEL_HUE = "#2a78d6"
SOURCE_DIR = C.FIGURES_DIR / "source"


def _num(row: Mapping[str, str], key: str) -> float:
    return float(row[key]) if row[key] != "" else float("nan")


# ---------------------------------------------------------------------- sources (numpy only)


def write_sources() -> list:
    d3 = C.read_csv(C.DATA_DIR / "D3_coupons.csv")
    band = C.read_csv(C.DATA_DIR / "ratio_vs_ved_band.csv")
    trend = C.read_csv(C.DATA_DIR / "ratio_vs_ved_trend.csv")
    slopes = C.read_csv(C.DATA_DIR / "T11_process_slopes.csv")
    frames = C.read_csv(C.DATA_DIR / "D1_frames.csv.gz")
    files = []

    f1 = [
        {
            "member": r["member"], "acquisition_set": r["acquisition_set"], "part": int(r["part"]), "role": r["role"],
            "power_W": _num(r, "power_W"), "speed_mm_s": _num(r, "speed_mm_s"), "ved_J_mm3": _num(r, "ved_J_mm3"), "a8_role": r["a8_role"],
        }
        for r in d3
    ]
    files.append(C.write_csv(SOURCE_DIR / "F1_partition.csv", f1))
    files.append(C.write_csv(SOURCE_DIR / "F3_process_space.csv", f1))

    f5 = []
    for r in d3:
        for q in ("H", "W"):
            f5.append(
                {
                    "member": r["member"], "role": r["role"], "quantity": q, "ved_J_mm3": _num(r, "ved_J_mm3"),
                    "camera_um_median": _num(r, f"cam_{q}_um_median"), "model_um_median_pool": _num(r, f"sim_{q}_um_median_pool"),
                    "no_pool_fraction": _num(r, "no_pool_fraction"),
                }
            )
    files.append(C.write_csv(SOURCE_DIR / "F5_observed_vs_predicted.csv", f5))

    f6 = []
    for r in d3:
        for q in ("H", "W"):
            f6.append(
                {
                    "member": r["member"], "role": r["role"], "quantity": q, "ved_J_mm3": _num(r, "ved_J_mm3"),
                    "median_ratio": _num(r, f"median_{q}_ratio"), "ci_lo": _num(r, f"median_{q}_ratio_ci_lo"), "ci_hi": _num(r, f"median_{q}_ratio_ci_hi"),
                    "ci_unit": r["ci_unit"],
                }
            )
    files.append(C.write_csv(SOURCE_DIR / "F6_ratio_vs_ved_points.csv", f6))
    files.append(C.write_csv(SOURCE_DIR / "F6_ratio_vs_ved_band.csv", band))
    files.append(C.write_csv(SOURCE_DIR / "F6_ratio_vs_ved_trend.csv", trend))

    def f7_group(row: Mapping[str, Any]) -> str:
        role, ved_value = row["role"], float(row["ved_J_mm3"])
        if role in ("calibration", "in_window_held_out"):
            return role
        return "out_of_window_low_ved" if ved_value < C.VED_WINDOW_J_MM3[0] else "out_of_window_high_ved"

    quantiles = []
    for group in ("calibration", "in_window_held_out", "out_of_window_low_ved", "out_of_window_high_ved"):
        sub = [r for r in frames if f7_group(r) == group]
        for q in ("H", "W"):
            values = np.array([float(r[f"r_{q}"]) for r in sub])
            row = {"group": group, "quantity": q, "frames": values.size, "coupons": len({r["member"] for r in sub})}
            for p in (1, 5, 10, 25, 50, 75, 90, 95, 99):
                row[f"p{p:02d}"] = float(np.percentile(values, p))
            row["share_no_pool"] = sum(1 for r in sub if r["no_pool"] == "true") / len(sub)
            quantiles.append(row)
    files.append(C.write_csv(SOURCE_DIR / "F7_residual_quantiles.csv", quantiles))
    f7c = [
        {"member": r["member"], "group": f7_group(r), "role": r["role"], "median_r_H": _num(r, "median_r_H"), "median_r_W": _num(r, "median_r_W"), "scored_frames": int(r["scored_frames"])}
        for r in d3
    ]
    files.append(C.write_csv(SOURCE_DIR / "F7_coupon_medians.csv", f7c))
    # The violins are drawn from the frame-level residuals in D1 (data/D1_frames.csv.gz), columns r_H and r_W.

    f11 = [
        {k: r[k] for k in ("subset", "design", "term", "source", "quantity", "estimate", "ci_lo", "ci_hi", "rosenthal_reference", "replicates_used")}
        for r in slopes
        if r["subset"] == "all_24" and r["design"] == "P_v" and r["source"] in ("camera", "model")
    ]
    files.append(C.write_csv(SOURCE_DIR / "F11_slopes.csv", f11))
    return files


# ---------------------------------------------------------------------- rendering (matplotlib)


def _style(plt) -> None:
    plt.rcParams.update(
        {
            "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
            "axes.edgecolor": AXIS, "axes.linewidth": 0.8, "axes.labelcolor": INK_2, "axes.titlecolor": INK,
            "axes.titlesize": 10, "axes.titleweight": "bold", "axes.titlelocation": "left", "axes.labelsize": 9,
            "xtick.color": MUTED, "ytick.color": MUTED, "xtick.labelcolor": INK_2, "ytick.labelcolor": INK_2,
            "xtick.labelsize": 8, "ytick.labelsize": 8, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
            "grid.linestyle": "-", "axes.axisbelow": True, "legend.frameon": False, "legend.fontsize": 8,
            "font.size": 9, "svg.hashsalt": "lpbf-committee-package", "svg.fonttype": "none",
            "axes.spines.top": False, "axes.spines.right": False,
        }
    )


def _save(fig, name: str) -> list:
    out = []
    for ext, meta in (("png", {"Software": None}), ("svg", {"Date": None, "Creator": None})):
        path = C.FIGURES_DIR / f"{name}.{ext}"
        fig.savefig(path, dpi=300 if ext == "png" else None, metadata=meta, bbox_inches="tight", pad_inches=0.05)
        out.append(path)
    return out


def _role_handles(plt, roles=C.ROLE_ORDER):
    from matplotlib.lines import Line2D

    return [
        Line2D([], [], linestyle="none", marker=MARKER[r], markersize=7, markerfacecolor=HUE[r], markeredgecolor=SURFACE, markeredgewidth=1.2, label=C.ROLE_LABEL[r])
        for r in roles
    ]


def _scatter(ax, x, y, role, size=46, **kw):
    ax.scatter(x, y, s=size, marker=MARKER[role], color=HUE[role], edgecolors=SURFACE, linewidths=1.2, zorder=3, **kw)


def f1(plt) -> list:
    rows = C.read_csv(SOURCE_DIR / "F1_partition.csv")
    sets = ["20260730", "20260731", "20260904", "20260910"]
    fig, ax = plt.subplots(figsize=(6.5, 4.6))
    ax.grid(False)
    for r in rows:
        x, y = sets.index(r["acquisition_set"]), int(r["part"])
        role = r["role"]
        ax.add_patch(plt.Rectangle((x - 0.47, y - 0.44), 0.94, 0.88, facecolor=HUE[role], alpha=0.13, edgecolor="none"))
        ax.scatter([x - 0.36], [y], s=40, marker=MARKER[role], color=HUE[role], edgecolors=SURFACE, linewidths=1.0, zorder=3)
        ax.text(x - 0.25, y + 0.13, f"P{float(r['power_W']):.0f} · v{float(r['speed_mm_s']):.0f}", fontsize=7.5, color=INK, va="center")
        ax.text(x - 0.25, y - 0.17, f"{float(r['ved_J_mm3']):.1f} J/mm³", fontsize=7, color=INK_2, va="center")
    ax.set_xlim(-0.55, 3.55)
    ax.set_ylim(6.6, 0.4)
    ax.set_xticks(range(4), ["20260730\nJuly, replicate A", "20260731\nJuly, replicate B", "20260904\nspeed sweep", "20260910\npower sweep"])
    ax.set_yticks(range(1, 7), [f"part {p}" for p in range(1, 7)])
    ax.tick_params(length=0)
    for s in ("left", "bottom"):
        ax.spines[s].set_visible(False)
    ax.xaxis.tick_top()
    ax.set_title("Coupons by acquisition set and part", pad=28)
    ax.legend(handles=_role_handles(plt), loc="upper center", bbox_to_anchor=(0.5, -0.02), ncol=2, handletextpad=0.4, columnspacing=1.5)
    fig.text(0.0, -0.1, "Calibration window 65–85 J/mm³ (A25). Held-out and blind coupons were first compared with the model after the selection freeze.", fontsize=7, color=INK_2)
    out = _save(fig, "F1_partition")
    plt.close(fig)
    return out


def f3(plt) -> list:
    rows = C.read_csv(SOURCE_DIR / "F3_process_space.csv")
    fig, ax = plt.subplots(figsize=(6.5, 4.4))
    v = np.linspace(520, 1480, 200)
    k = C.HATCH_MM * C.LAYER_MM
    ax.fill_between(v, 65 * v * k, 85 * v * k, color=WINDOW_FILL, zorder=0, linewidth=0)
    for ved_level in (45, 55, 65, 75, 85, 100, 115):
        p = ved_level * v * k
        ax.plot(v, p, color=GRID if ved_level not in (65, 85) else AXIS, linewidth=0.8, zorder=1)
        top = 196.0 / (ved_level * k)
        if top <= 1470:  # label where the isoline leaves the plot: top edge, else right edge
            ax.text(top, 196.4, f"{ved_level}", fontsize=7, color=MUTED, ha="center", va="bottom")
        else:
            ax.text(1484, ved_level * 1480 * k, f"{ved_level}", fontsize=7, color=MUTED, ha="left", va="center")
    ax.text(540, 196.4, "VED (J/mm³):", fontsize=7, color=MUTED, ha="left", va="bottom")
    seen = {}
    for r in rows:
        key = (float(r["speed_mm_s"]), float(r["power_W"]))
        seen.setdefault(key, []).append(r)
    for (sp, pw), group in seen.items():
        role = group[0]["role"]
        _scatter(ax, [sp], [pw], role, size=60)
        if len(group) > 1:
            ax.text(sp + 14, pw + 1.2, "×2", fontsize=7, color=INK_2, va="bottom")
    ax.set_xlim(540, 1480)
    ax.set_ylim(132, 196)
    ax.set_xlabel("Scan speed v (mm/s)")
    ax.set_ylabel("Laser power P (W)")
    ax.set_title("Process space and calibration window", pad=18)
    ax.legend(handles=_role_handles(plt), loc="upper center", bbox_to_anchor=(0.5, -0.13), ncol=4, fontsize=7.5, handletextpad=0.3, columnspacing=1.0)
    fig.text(0.0, -0.1, "×2: replicate pair (20260730 and 20260731). Isolines: P = VED · v · 0.080 mm · 0.030 mm.", fontsize=7, color=INK_2)
    out = _save(fig, "F3_process_space")
    plt.close(fig)
    return out


def f5(plt) -> list:
    rows = C.read_csv(SOURCE_DIR / "F5_observed_vs_predicted.csv")
    fig, axes = plt.subplots(1, 2, figsize=(6.5, 3.4))
    for ax, q, lim in ((axes[0], "H", (30, 330)), (axes[1], "W", (25, 100))):
        sub = [r for r in rows if r["quantity"] == q]
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.plot(lim, lim, color=AXIS, linewidth=1.0, zorder=1)
        ax.text(lim[1] * 0.93, lim[1] * 0.85, "1:1", fontsize=7, color=MUTED, ha="right")
        for r in sub:
            role = r["role"]
            x, y = float(r["camera_um_median"]), float(r["model_um_median_pool"])
            heavy = float(r["no_pool_fraction"]) > 0.05
            ax.scatter([x], [y], s=46, marker=MARKER[role], facecolors=SURFACE if heavy else HUE[role], edgecolors=HUE[role] if heavy else SURFACE, linewidths=1.3, zorder=3)
            if heavy:
                offset = (8, -16) if r["member"] == "20260904:part_3" else (8, 6)  # keep the two labels apart
                ax.annotate(f"{r['member']}\nno pool on {100 * float(r['no_pool_fraction']):.0f} %", (x, y), xytext=offset, textcoords="offset points", fontsize=6.5, color=INK_2)
        ax.set_xlim(*lim)
        ax.set_ylim(*lim)
        ax.set_xlabel(f"Camera {q}, coupon median (µm)")
        ax.set_ylabel(f"Model {q}, coupon median (µm)")
        ax.set_title(f"{q}", loc="left")
        from matplotlib.ticker import FixedLocator, NullFormatter, ScalarFormatter

        ticks = [30, 50, 100, 200, 300] if q == "H" else [30, 40, 60, 80, 100]
        for axis in (ax.xaxis, ax.yaxis):
            axis.set_major_locator(FixedLocator(ticks))
            axis.set_major_formatter(ScalarFormatter())
            axis.set_minor_formatter(NullFormatter())
    fig.suptitle("Camera and model melt pool size by coupon", x=0.0, ha="left", fontsize=10, fontweight="bold", color=INK)
    fig.legend(handles=_role_handles(plt), loc="lower center", bbox_to_anchor=(0.5, -0.1), ncol=4, fontsize=7.5, handletextpad=0.3, columnspacing=1.0)
    fig.text(0.0, -0.17, "Nominal 8 µm/px (A24). Model medians over frames with a predicted pool; open markers: no pool on > 5 % of scored frames.", fontsize=7, color=INK_2)
    fig.tight_layout()
    out = _save(fig, "F5_observed_vs_predicted")
    plt.close(fig)
    return out


def f6(plt) -> list:
    points = C.read_csv(SOURCE_DIR / "F6_ratio_vs_ved_points.csv")
    band = C.read_csv(SOURCE_DIR / "F6_ratio_vs_ved_band.csv")
    trend = {r["quantity"]: r for r in C.read_csv(SOURCE_DIR / "F6_ratio_vs_ved_trend.csv")}
    fig, axes = plt.subplots(1, 2, figsize=(6.5, 3.4), sharey=True)
    for ax, q in ((axes[0], "H"), (axes[1], "W")):
        ax.set_yscale("log")
        ax.axvspan(*C.VED_WINDOW_J_MM3, color=WINDOW_FILL, zorder=0, linewidth=0)
        ax.axhline(1.0, color=AXIS, linewidth=1.0, zorder=1)
        b = [r for r in band if r["quantity"] == q]
        xv = [float(r["ved_J_mm3"]) for r in b]
        ax.fill_between(xv, [float(r["ci_lo_ratio"]) for r in b], [float(r["ci_hi_ratio"]) for r in b], color=INK_2, alpha=0.10, linewidth=0, zorder=1)
        ax.plot(xv, [float(r["fit_ratio"]) for r in b], color=INK_2, linewidth=1.5, zorder=2)
        for r in points:
            if r["quantity"] != q:
                continue
            x, y = float(r["ved_J_mm3"]), float(r["median_ratio"])
            ax.plot([x, x], [float(r["ci_lo"]), float(r["ci_hi"])], color=HUE[r["role"]], linewidth=1.2, zorder=2)
            _scatter(ax, [x], [y], r["role"], size=40)
        t = trend[q]
        ax.text(0.98, 0.04, f"slope on ln VED {float(t['slope_ln_VED']):.2f} [{float(t['slope_ci_lo']):.2f}, {float(t['slope_ci_hi']):.2f}]", transform=ax.transAxes, fontsize=7, color=INK_2, ha="right")
        ax.set_xlabel("VED (J/mm³)")
        ax.set_title(f"{q} ratio (model / camera)", loc="left")
        ax.set_xlim(35, 132)
        ax.set_ylim(0.1, 5.0)
        ax.text(75, 4.3, "window", fontsize=7, color=MUTED, ha="center", va="top")
    from matplotlib.ticker import FixedLocator, NullFormatter, ScalarFormatter

    axes[0].yaxis.set_major_locator(FixedLocator([0.1, 0.2, 0.5, 1, 2, 3]))
    axes[0].yaxis.set_major_formatter(ScalarFormatter())
    axes[0].yaxis.set_minor_formatter(NullFormatter())
    axes[0].set_ylabel("Coupon median ratio")
    fig.suptitle("Model-to-camera ratio against VED", x=0.0, ha="left", fontsize=10, fontweight="bold", color=INK)
    fig.legend(handles=_role_handles(plt), loc="lower center", bbox_to_anchor=(0.5, -0.1), ncol=4, fontsize=7.5, handletextpad=0.3, columnspacing=1.0)
    fig.text(0.0, -0.17, "Bars: 95 % track-bootstrap interval within each coupon. Line and band: least squares of ln ratio on ln VED over 24 coupons, 95 % coupon bootstrap (descriptive).", fontsize=7, color=INK_2)
    fig.tight_layout()
    out = _save(fig, "F6_ratio_vs_ved")
    plt.close(fig)
    return out


F7_GROUPS = (
    ("calibration", "Calibration\n(9)", "calibration"),
    ("in_window_held_out", "Held out\n(5)", "in_window_held_out"),
    ("out_of_window_low_ved", "Out, VED\n< 65 (6)", "out_of_window_examined"),
    ("out_of_window_high_ved", "Out, VED\n> 85 (4)", "out_of_window_examined"),
)


def f7(plt) -> list:
    frames = C.read_csv(C.DATA_DIR / "D1_frames.csv.gz")
    coupons = C.read_csv(SOURCE_DIR / "F7_coupon_medians.csv")
    fig, axes = plt.subplots(1, 2, figsize=(6.5, 3.5), sharey=True)
    for ax, q in ((axes[0], "H"), (axes[1], "W")):
        ax.axhline(0.0, color=AXIS, linewidth=1.0, zorder=1)
        for i, (group, label, hue_role) in enumerate(F7_GROUPS):
            ved_lo, ved_hi = C.VED_WINDOW_J_MM3
            if group in ("calibration", "in_window_held_out"):
                values = [float(r[f"r_{q}"]) for r in frames if r["role"] == group]
            else:
                low = group == "out_of_window_low_ved"
                values = [float(r[f"r_{q}"]) for r in frames if r["role"].startswith("out_of_window") and ((float(r["ved_J_mm3"]) < ved_lo) if low else (float(r["ved_J_mm3"]) > ved_hi))]
            parts = ax.violinplot([values], positions=[i], widths=0.8, showextrema=False, bw_method=0.12)
            for body in parts["bodies"]:
                body.set_facecolor(HUE[hue_role])
                body.set_alpha(0.18)
                body.set_edgecolor(HUE[hue_role])
                body.set_linewidth(0.8)
            p25, p50, p75 = np.percentile(values, [25, 50, 75])
            ax.plot([i, i], [p25, p75], color=INK_2, linewidth=2.0, solid_capstyle="round", zorder=3)
            ax.scatter([i], [p50], s=22, color=SURFACE, edgecolors=INK_2, linewidths=1.2, zorder=4)
            cm = [float(c[f"median_r_{q}"]) for c in coupons if c["group"] == group]
            ax.scatter(np.full(len(cm), i + 0.32), cm, s=18, marker="o", color=HUE[hue_role], edgecolors=SURFACE, linewidths=0.8, zorder=4)
        ax.set_xticks(range(len(F7_GROUPS)), [g[1] for g in F7_GROUPS], fontsize=7)
        ax.set_title(f"r_{q} = ln(model {q} / camera {q})", loc="left")
        ax.grid(axis="x", visible=False)
    axes[0].set_ylabel("Frame-level log residual")
    fig.suptitle("Frame residuals by group", x=0.0, ha="left", fontsize=10, fontweight="bold", color=INK)
    fig.text(0.0, -0.11, "Violins: all scored frames (no-pool frames sit near −2.3, the 1 px floor). Bar and ring: frame quartiles and median. Dots at right: coupon medians.\nHeld out: in-window held out. Out: out-of-window coupons (examined and blind), VED in J/mm³.", fontsize=7, color=INK_2)
    fig.tight_layout()
    out = _save(fig, "F7_residual_distributions")
    plt.close(fig)
    return out


def f11(plt) -> list:
    rows = C.read_csv(SOURCE_DIR / "F11_slopes.csv")
    order = [("H", "ln_P"), ("W", "ln_P"), ("HW", "ln_P"), ("H", "ln_v"), ("W", "ln_v"), ("HW", "ln_v")]
    labels = {"H": "ln H", "W": "ln W", "HW": "ln H/W"}
    fig, ax = plt.subplots(figsize=(6.5, 3.6))
    ax.axvline(0.0, color=AXIS, linewidth=1.0, zorder=1)
    for i, (q, term) in enumerate(order):
        y = len(order) - 1 - i
        for source, dy, hue, marker in (("camera", 0.14, CAMERA_HUE, "o"), ("model", -0.14, MODEL_HUE, "s")):
            r = next(x for x in rows if x["quantity"] == q and x["term"] == term and x["source"] == source)
            ax.plot([float(r["ci_lo"]), float(r["ci_hi"])], [y + dy, y + dy], color=hue, linewidth=2.0, solid_capstyle="round", zorder=2)
            ax.scatter([float(r["estimate"])], [y + dy], s=42, marker=marker, color=hue, edgecolors=SURFACE, linewidths=1.2, zorder=3)
        ref = next(x for x in rows if x["quantity"] == q and x["term"] == term)["rosenthal_reference"]
        ax.scatter([float(ref)], [y], s=46, marker="D", facecolors="none", edgecolors=INK, linewidths=1.0, zorder=3)
    ax.axhline(2.5, color=GRID, linewidth=0.8)
    ax.set_yticks(range(len(order)), [f"{labels[q]} on {'ln P' if t == 'ln_P' else 'ln v'}" for q, t in reversed(order)])
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("Slope (log-log), 95 % coupon-bootstrap interval")
    ax.set_title("Process-response slopes", pad=10)
    from matplotlib.lines import Line2D

    handles = [
        Line2D([], [], color=CAMERA_HUE, marker="o", markersize=6, linewidth=2, label="Camera, threshold 150"),
        Line2D([], [], color=MODEL_HUE, marker="s", markersize=6, linewidth=2, label="Model liquidus, confirm_c1"),
        Line2D([], [], linestyle="none", marker="D", markersize=6, markerfacecolor="none", markeredgecolor=INK, label="Rosenthal point source"),
    ]
    ax.legend(handles=handles, loc="lower right", fontsize=7.5)
    fig.text(0.0, -0.06, "ln of coupon medians on [1, ln P, ln v]; scale-free (independent of the 8 µm/px scale).", fontsize=7, color=INK_2)
    out = _save(fig, "F11_process_slopes")
    plt.close(fig)
    return out


def render() -> list:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    _style(plt)
    C.FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    out = []
    for fn in (f1, f3, f5, f6, f7, f11):
        out += fn(plt)
    return out
