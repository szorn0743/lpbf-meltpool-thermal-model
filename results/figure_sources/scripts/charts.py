"""Chart figures: sources from the committee package data (numpy only) and renders (matplotlib).

Every plotted value is written to ``source/`` first. Model sizes are medians over frames with a predicted pool;
ratios include the no-pool frames (scored H = W = 0 with the 1 px floor), as in the committee package.
"""
from __future__ import annotations

import math
from statistics import median
from typing import Any, Mapping, Sequence

import numpy as np

import style as S
from style import C

UM = S.UM_PER_PX
GROUP_LABEL = {"calibration": "calibration", "in_window_held_out": "held out", "out_of_window_examined": "outside window", "out_of_window_blind": "outside window (blind)"}
CANDIDATE_LABEL = {
    "confirm_c1": "c1 (selected)", "confirm_c2": "c2", "anchor_center": "centre anchor", "anchor_t_min": "anchor, t min", "anchor_t_max": "anchor, t max",
    "anchor_transport_guard_edge": "anchor, guard edge", "anchor_low_ck_high_eta": "anchor, low ck high η",
}
SYNTH_CASES = {"lam850_uniform_sig0.0": "sharp", "lam850_uniform_sig2.0": "2 px blur"}


def _f(row: Mapping[str, str], key: str) -> float:
    return float(row[key]) if row[key] not in ("", None) else float("nan")


def candidate_label(name: str) -> str:
    if name in CANDIDATE_LABEL:
        return CANDIDATE_LABEL[name]
    if name.startswith("halton_"):
        return f"Halton {int(name.split('_')[1])}"
    return name


# ---------------------------------------------------------------------- sources


def kde(values: np.ndarray, grid: np.ndarray, bandwidth: float) -> np.ndarray:
    z = (grid[:, None] - values[None, :]) / bandwidth
    return np.exp(-0.5 * z * z).sum(axis=1) / (values.size * bandwidth * math.sqrt(2.0 * math.pi))


def power_law(rows: Sequence[Mapping[str, Any]], key: str) -> dict[str, float]:
    """Least squares of ln(size) on [1, ln P, ln v] over coupons (descriptive)."""

    y = np.log([r[key] for r in rows])
    X = np.column_stack([np.ones(len(rows)), np.log([r["power_W"] for r in rows]), np.log([r["speed_mm_s"] for r in rows])])
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    return {"intercept": float(coef[0]), "ln_P": float(coef[1]), "ln_v": float(coef[2])}


def write_sources() -> list:
    S.SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    files = []
    d3 = C.read_csv(C.DATA_DIR / "D3_coupons.csv")
    coupons = []
    for r in d3:
        coupons.append(
            {
                "member": r["member"], "condition": r["condition"], "role": r["role"], "power_W": _f(r, "power_W"), "speed_mm_s": _f(r, "speed_mm_s"),
                "ved_J_mm3": _f(r, "ved_J_mm3"), "camera_H_um": _f(r, "cam_H_um_median"), "camera_W_um": _f(r, "cam_W_um_median"),
                "model_H_um": _f(r, "sim_H_um_median_pool"), "model_W_um": _f(r, "sim_W_um_median_pool"), "median_H_ratio": _f(r, "median_H_ratio"),
                "median_W_ratio": _f(r, "median_W_ratio"), "no_pool_fraction": _f(r, "no_pool_fraction"), "scored_frames": int(r["scored_frames"]),
                "e_H": _f(r, "e_H"), "e_W": _f(r, "e_W"), "J": _f(r, "J"),
            }
        )
    coupons.sort(key=lambda r: (r["ved_J_mm3"], r["member"]))
    files.append(C.write_csv(S.SOURCE_DIR / "coupon_sizes.csv", coupons))

    # Power-law fits over the 24 coupons; checked against the committee package's T11 estimates.
    t11 = {(r["subset"], r["design"], r["term"], r["source"], r["quantity"]): float(r["estimate"]) for r in C.read_csv(C.DATA_DIR / "T11_process_slopes.csv")}
    fits = []
    for source in ("camera", "model"):
        for q in ("H", "W"):
            fit = power_law(coupons, f"{source}_{q}_um")
            for term in ("ln_P", "ln_v"):
                ref = t11[("all_24", "P_v", term, source, q)]
                if abs(fit[term] - ref) > 1e-9:
                    raise RuntimeError(f"power-law fit {source} {q} {term} {fit[term]} differs from T11 {ref}")
            fits.append({"source": source, "quantity": q, **fit})
    files.append(C.write_csv(S.SOURCE_DIR / "process_power_law.csv", fits))

    d4 = [r for r in C.read_csv(C.DATA_DIR / "D4_conditions_groups.csv") if r["level"] == "condition"]
    conditions = []
    for r in d4:
        roles = sorted({C.ROLE[m] for m in r["members"].split()})
        conditions.append(
            {
                "condition": r["name"], "members": r["members"], "roles": ";".join(roles), "power_W": _f(r, "power_W"), "speed_mm_s": _f(r, "speed_mm_s"),
                "ved_J_mm3": _f(r, "ved_J_mm3"), "camera_H_um": _f(r, "cam_H_px_median") * UM, "camera_W_um": _f(r, "cam_W_px_median") * UM,
                "model_H_um": _f(r, "sim_H_px_median_pool") * UM, "model_W_um": _f(r, "sim_W_px_median_pool") * UM,
                "median_H_ratio": _f(r, "median_H_ratio"), "median_W_ratio": _f(r, "median_W_ratio"), "no_pool_frames": int(r["no_pool_frames"]),
                "scored_frames": int(r["scored_frames"]),
            }
        )
    conditions.sort(key=lambda r: (r["ved_J_mm3"], r["condition"]))
    files.append(C.write_csv(S.SOURCE_DIR / "condition_sizes.csv", conditions))

    # Frames (ridgeline and density figures).
    d1 = C.read_csv(C.DATA_DIR / "D1_frames.csv.gz")
    frames = [
        {
            "condition": r["condition"], "ved_J_mm3": round(_f(r, "ved_J_mm3"), 6), "camera_H_um": _f(r, "cam_H_px") * UM, "camera_W_um": _f(r, "cam_W_px") * UM,
            "model_H_um": _f(r, "sim_H_px") * UM, "model_W_um": _f(r, "sim_W_px") * UM, "no_pool": r["no_pool"],
        }
        for r in d1
    ]
    files.append(_write_gz(S.SOURCE_DIR / "frame_sizes.csv.gz", frames))
    grids = {"H": np.linspace(0.0, 360.0, 361), "W": np.linspace(0.0, 130.0, 261)}
    bandwidth = {"H": 4.0, "W": 2.5}
    density = []
    for cond in conditions:
        sub = [r for r in frames if r["condition"] == cond["condition"]]
        for q in ("H", "W"):
            for source in ("camera", "model"):
                vals = np.array([r[f"{source}_{q}_um"] for r in sub if source == "camera" or r["no_pool"] == "false"])
                dens = kde(vals, grids[q], bandwidth[q])
                for x, d in zip(grids[q], dens):
                    density.append({"condition": cond["condition"], "quantity": q, "source": source, "x_um": float(x), "density": float(d), "frames": int(vals.size)})
    files.append(_write_gz(S.SOURCE_DIR / "ridgeline_density.csv.gz", density))

    # Candidates: design coordinates, recorded scores and median sizes over the 9 calibration coupons.
    sizes = C.read_csv(S.SOURCE_DIR / "candidate_coupon_sizes.csv")
    cands = []
    for r in C.read_csv(C.DATA_DIR / "D6_candidate_search" / "D6_candidates.csv"):
        sub = [s for s in sizes if s["candidate"] == r["candidate"] and C.ROLE[s["member"]] == "calibration"]
        if len(sub) != 9:
            raise RuntimeError(f"{r['candidate']}: {len(sub)} calibration coupons in the unit files")
        cands.append(
            {
                "candidate": r["candidate"], "label": candidate_label(r["candidate"]), "origin": r["origin"], "t": _f(r, "t"), "ck": _f(r, "ck"), "eta": _f(r, "eta"),
                "J": _f(r, "J"), "e_H": _f(r, "e_H"), "e_W": _f(r, "e_W"), "H_component": _f(r, "H_component"), "W_component": _f(r, "W_component"),
                "rank_by_J": int(r["rank_by_J"]), "selected": r["selected"] == "true", "near_best": r["near_best"] == "true",
                "absorptivity": _f(r, "absorptivity"), "deposition_depth_mm": _f(r, "deposition_depth_mm"),
                "model_H_um": median(float(s["model_H_px_median_pool"]) for s in sub) * UM, "model_W_um": median(float(s["model_W_px_median_pool"]) for s in sub) * UM,
                "camera_H_um": median(float(s["camera_H_px_median"]) for s in sub) * UM, "camera_W_um": median(float(s["camera_W_px_median"]) for s in sub) * UM,
                "median_peak_surface_K": _f(r, "median_peak_surface_K"),
            }
        )
    cands.sort(key=lambda r: r["rank_by_J"])
    files.append(C.write_csv(S.SOURCE_DIR / "candidates.csv", cands))

    # Synthetic camera ratios per coupon (recorded in the reading-S manifest) beside the liquidus ratios.
    manifest = C.load_json(C.SYNTHETIC_MANIFEST)
    paired: dict[tuple[str, str], list[tuple[float, float]]] = {}
    for row in C.read_csv(C.SYNTHETIC_FRAMES):
        if row["synthetic_status"] == "PAIRED":
            paired.setdefault((row["case_id"], row["member_identity"]), []).append(
                (C.log_ratio(float(row["simulated_H_pixels"]), float(row["experimental_H_pixels"])), C.log_ratio(float(row["simulated_W_pixels"]), float(row["experimental_W_pixels"])))
            )
    # Check the recomputation against every recorded median ratio: per condition in each group, and per coupon where the
    # manifest has one (the out-of-window coupons). Coverage per coupon is recorded for every group.
    coverage: dict[tuple[str, str], float] = {}
    checked = 0
    for case in SYNTH_CASES:
        ref_case = manifest["cases"][case]
        refs = [cond for g in ref_case["groups"].values() for cond in g["condition_rows"]]
        refs += [cond for pc in ref_case["per_coupon"].values() for cond in pc["condition_rows"]]
        for g in ref_case["groups"].values():
            coverage.update({(case, m): float(v) for m, v in g["coverage_by_coupon"].items()})
        for cond in refs:
            pooled = [p for m in cond["member_identities"] for p in paired[(case, m)]]
            mh, mw = float(median(math.exp(a) for a, _ in pooled)), float(median(math.exp(b) for _, b in pooled))
            if abs(mh - cond["median_H_ratio"]) > 1e-12 or abs(mw - cond["median_W_ratio"]) > 1e-12:
                raise RuntimeError(f"{case} {cond['exact_condition_id']}: synthetic ratio differs from the reading-S manifest")
            checked += 2
    if checked < 4 * len(conditions):
        raise RuntimeError("too few synthetic ratios checked against the manifest")
    synth = []
    for cp in coupons:
        member = cp["member"]
        synth.append({"member": member, "ved_J_mm3": cp["ved_J_mm3"], "role": cp["role"], "operator": "liquidus", "median_H_ratio": cp["median_H_ratio"], "median_W_ratio": cp["median_W_ratio"], "coverage": 1.0})
        for case, label in SYNTH_CASES.items():
            mine = paired[(case, member)]
            mh, mw = float(median(math.exp(a) for a, _ in mine)), float(median(math.exp(b) for _, b in mine))
            synth.append({"member": member, "ved_J_mm3": cp["ved_J_mm3"], "role": cp["role"], "operator": label, "median_H_ratio": mh, "median_W_ratio": mw, "coverage": coverage[(case, member)]})
    files.append(C.write_csv(S.SOURCE_DIR / "operator_ratios.csv", synth))
    return files


def _write_gz(path, rows):
    import csv
    import gzip
    import io

    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()), lineterminator="\n")
    writer.writeheader()
    for r in rows:
        writer.writerow({k: C.fmt(v) for k, v in r.items()})
    with open(path, "wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz:
            gz.write(buffer.getvalue().encode("utf-8"))
    return path


# ---------------------------------------------------------------------- helpers


def read(name: str) -> list[dict[str, str]]:
    return C.read_csv(S.SOURCE_DIR / name)


def ved_band(ax, axis="y", label=True, color=None):
    lo, hi = S.WINDOW
    if axis == "x":
        ax.axvspan(lo, hi, color=color or S.BAND, zorder=0, lw=0)
        if label:
            ax.text((lo + hi) / 2, 1.0, "calibration\nwindow", transform=ax.get_xaxis_transform(), ha="center", va="top", fontsize=9, color=S.INK_2)


def legend_dot(color, label, marker="o", mfc=None, ms=9):
    from matplotlib.lines import Line2D

    return Line2D([], [], ls="none", marker=marker, ms=ms, mfc=mfc or color, mec=S.SURFACE if mfc != "none" else color, mew=1.5, color=color, label=label)


def save(fig, name, plt):
    out = S.save(fig, name)
    plt.close(fig)
    return out


# ---------------------------------------------------------------------- figures


def dumbbell(plt) -> list:
    rows = read("coupon_sizes.csv")
    n = len(rows)
    fig, axes = plt.subplots(1, 2, figsize=(12.6, 9.0), sharey=True, gridspec_kw={"wspace": 0.08})
    y = np.arange(n)[::-1]
    lo, hi = S.WINDOW
    for ax, q, xmax in ((axes[0], "H", 340), (axes[1], "W", 100)):
        for yi, r in zip(y, rows):
            v = _f(r, "ved_J_mm3")
            if lo <= v <= hi:
                ax.axhspan(yi - 0.5, yi + 0.5, color=S.BAND, lw=0, zorder=0)
            c, m = _f(r, f"camera_{q}_um"), _f(r, f"model_{q}_um")
            ax.plot([c, m], [yi, yi], color=S.AXIS, lw=2.2, zorder=1, solid_capstyle="round")
            ax.scatter([c], [yi], s=70, color=S.CAMERA, edgecolors=S.SURFACE, linewidths=1.6, zorder=3)
            hollow = _f(r, "no_pool_fraction") > 0.05
            ax.scatter([m], [yi], s=70, facecolors=S.SURFACE if hollow else S.MODEL, edgecolors=S.MODEL if hollow else S.SURFACE, linewidths=1.6, zorder=3)
            ratio = _f(r, f"median_{q}_ratio")
            ax.text(xmax * 0.995, yi, f"{ratio:.2f}×", ha="right", va="center", fontsize=9.5, color=S.INK_2)
        ax.set_xlim(0, xmax)
        ax.grid(axis="y", visible=False)
        ax.set_xlabel(f"{q} (µm)")
        ax.set_title("H, melt pool length" if q == "H" else "W, melt pool width", fontsize=12.5, pad=10)
        ax.text(xmax * 0.995, n - 0.15, "model ÷ camera", ha="right", va="bottom", fontsize=9, color=S.MUTED)
        ax.tick_params(axis="y", length=0)
        ax.spines["left"].set_visible(False)
    axes[0].set_yticks(y, [f"{_f(r, 'ved_J_mm3'):.0f} J/mm³   {_f(r, 'power_W'):.0f} W · {_f(r, 'speed_mm_s'):.0f} mm/s" for r in rows], fontsize=9.5)
    axes[0].set_ylim(-0.7, n - 0.3 + 0.6)
    handles = [legend_dot(S.CAMERA, "Experiment (camera)"), legend_dot(S.MODEL, "Simulation (model)"),
               legend_dot(S.MODEL, "model without a pool on > 5 % of frames", mfc="none")]
    from matplotlib.patches import Patch

    handles.append(Patch(facecolor=S.BAND, edgecolor="none", label="calibration window, 65–85 J/mm³"))
    fig.legend(handles=handles, loc="lower left", bbox_to_anchor=(0.0, 0.905), ncol=4, fontsize=10.5, frameon=False, handletextpad=0.4, columnspacing=1.6)
    S.title(fig, "Melt pool size by coupon", y=0.95)
    S.note(fig, "Coupon medians, sorted by energy density (VED). Model medians over frames with a pool; the ratio is the median of the frame ratios (no-pool frames "
           "included, as scored). Nominal 8 µm/px.", y=0.045)
    return save(fig, "melt_pool_size_by_coupon", plt)


def shape_space(plt) -> list:
    rows = read("coupon_sizes.csv")
    fig, ax = plt.subplots(figsize=(10.5, 7.6))
    xmax, ymax = 100, 330
    for k, label in ((1.0, "H/W = 1, round"), (2.0, "H/W = 2"), (3.0, "H/W = 3"), (4.0, "H/W = 4")):
        x_end = min(xmax, ymax / k)
        ax.plot([0, x_end], [0, k * x_end], color=S.GRID if k != 1.0 else S.AXIS, lw=1.0, zorder=0)
        if x_end >= xmax:
            ax.text(xmax - 0.8, k * xmax + 2, label, fontsize=9.5, color=S.MUTED, ha="right", va="bottom")
        else:
            ax.text(x_end - 1.2, ymax - 2, label, fontsize=9.5, color=S.MUTED, ha="right", va="top")
    for r in rows:
        cx, cy = _f(r, "camera_W_um"), _f(r, "camera_H_um")
        mx, my = _f(r, "model_W_um"), _f(r, "model_H_um")
        ax.annotate("", xy=(mx, my), xytext=(cx, cy), arrowprops=dict(arrowstyle="-|>", color=S.AXIS, lw=0.9, alpha=0.7, shrinkA=5, shrinkB=5, mutation_scale=9), zorder=1)
    ax.scatter([_f(r, "camera_W_um") for r in rows], [_f(r, "camera_H_um") for r in rows], s=70, color=S.CAMERA, edgecolors=S.SURFACE, linewidths=1.6, zorder=3,
               label="Experiment (camera)")
    ax.scatter([_f(r, "model_W_um") for r in rows], [_f(r, "model_H_um") for r in rows], s=70, color=S.MODEL, edgecolors=S.SURFACE, linewidths=1.6, zorder=3,
               label="Simulation (model)")
    lo_r = min(rows, key=lambda r: _f(r, "ved_J_mm3"))
    hi_r = max(rows, key=lambda r: _f(r, "ved_J_mm3"))
    for r, offset, ha in ((lo_r, (14, -14), "left"), (hi_r, (-16, -4), "right")):
        ax.annotate(f"model, {_f(r, 'ved_J_mm3'):.0f} J/mm³", (_f(r, "model_W_um"), _f(r, "model_H_um")), xytext=offset, textcoords="offset points", fontsize=10,
                    color=S.INK, ha=ha, va="center", arrowprops=dict(arrowstyle="-", color=S.MUTED, lw=0.8))
    win = [r for r in rows if S.WINDOW[0] <= _f(r, "ved_J_mm3") <= S.WINDOW[1]]
    wx, wy = np.median([_f(r, "model_W_um") for r in win]), np.median([_f(r, "model_H_um") for r in win])
    ax.annotate(f"model, calibration window\n({len(win)} coupons)", (wx, wy), xytext=(-120, 40), textcoords="offset points", fontsize=10, color=S.INK, ha="center",
                arrowprops=dict(arrowstyle="-", color=S.MUTED, lw=0.8))
    cw, ch = np.median([_f(r, "camera_W_um") for r in rows]), np.median([_f(r, "camera_H_um") for r in rows])
    ax.annotate("all 24 camera pools", (cw, ch), xytext=(40, -60), textcoords="offset points", fontsize=10, color=S.INK, ha="left",
                arrowprops=dict(arrowstyle="-", color=S.MUTED, lw=0.8))
    ax.set_xlim(0, xmax)
    ax.set_ylim(0, ymax)
    ax.set_xlabel("W, melt pool width (µm)")
    ax.set_ylabel("H, melt pool length (µm)")
    ax.legend(loc="upper left", fontsize=10.5, frameon=False)
    S.title(fig, "Melt pool length against width", y=0.94)
    S.note(fig, "Each arrow goes from a coupon's camera median to its model median (24 coupons). Grey rays: constant shape H/W. Model medians over frames with a pool; "
           "nominal 8 µm/px.", y=0.02)
    return save(fig, "melt_pool_length_against_width", plt)


def ridgeline(plt) -> list:
    conds = read("condition_sizes.csv")
    dens = read("ridgeline_density.csv.gz")
    by: dict[tuple[str, str, str], tuple[np.ndarray, np.ndarray]] = {}
    for key in {(r["condition"], r["quantity"], r["source"]) for r in dens}:
        sub = [r for r in dens if (r["condition"], r["quantity"], r["source"]) == key]
        by[key] = (np.array([float(r["x_um"]) for r in sub]), np.array([float(r["density"]) for r in sub]))
    n = len(conds)
    fig, axes = plt.subplots(1, 2, figsize=(12.6, 10.0), sharey=True, gridspec_kw={"wspace": 0.06})
    overlap = 1.55
    lo, hi = S.WINDOW
    for ax, q, xmax in ((axes[0], "H", 360), (axes[1], "W", 130)):
        peak = max(max(by[(c["condition"], q, s)][1]) for c in conds for s in ("camera", "model"))
        for i, c in enumerate(conds):
            base = n - 1 - i
            if lo <= _f(c, "ved_J_mm3") <= hi:
                ax.axhspan(base - 0.05, base + 0.95, color=S.BAND, lw=0, zorder=0)
            for source, color, z in (("model", S.MODEL, 2 * i + 1), ("camera", S.CAMERA, 2 * i + 2)):
                x, d = by[(c["condition"], q, source)]
                h = d / peak * overlap * 1.6
                ax.fill_between(x, base, base + h, color=color, alpha=0.30, lw=0, zorder=z)
                ax.plot(x, base + h, color=color, lw=1.4, zorder=z)
            ax.plot([0, xmax], [base, base], color=S.GRID, lw=0.8, zorder=0)
            nopool = int(c["no_pool_frames"]) / int(c["scored_frames"])
            if q == "H" and nopool > 0.01:
                ax.text(xmax * 0.995, base + 0.15, f"model: no pool on {nopool:.0%} of frames", ha="right", va="bottom", fontsize=8.5, color=S.INK_2)
        ax.set_xlim(0, xmax)
        ax.set_xlabel(f"{q} (µm)")
        ax.grid(axis="y", visible=False)
        ax.set_title("H, melt pool length" if q == "H" else "W, melt pool width", fontsize=12.5, pad=10)
        ax.tick_params(axis="y", length=0)
        ax.spines["left"].set_visible(False)
    axes[0].set_yticks([n - 1 - i + 0.3 for i in range(n)], [f"{_f(c, 'ved_J_mm3'):.0f} J/mm³   {_f(c, 'power_W'):.0f} W · {_f(c, 'speed_mm_s'):.0f} mm/s" for c in conds], fontsize=9.5)
    axes[0].set_ylim(-0.2, n + 0.9)
    from matplotlib.patches import Patch

    handles = [Patch(facecolor=S.CAMERA, alpha=0.5, edgecolor=S.CAMERA, label="Experiment (camera)"), Patch(facecolor=S.MODEL, alpha=0.5, edgecolor=S.MODEL, label="Simulation (model)"),
               Patch(facecolor=S.BAND, edgecolor="none", label="calibration window")]
    fig.legend(handles=handles, loc="lower left", bbox_to_anchor=(0.0, 0.905), ncol=3, fontsize=10.5, frameon=False)
    S.title(fig, "Frame-by-frame melt pool size by condition", y=0.95)
    S.note(fig, "Distribution of every scored frame for each of the 18 process conditions (replicate coupons pooled), sorted by energy density. Smoothed histograms "
           "(Gaussian kernel, 4 µm for H, 2.5 µm for W),\nall on one height scale. Model: frames with a pool. Nominal 8 µm/px.", y=0.045)
    return save(fig, "frame_size_distributions_by_condition", plt)


def footprints(plt) -> list:
    from matplotlib.offsetbox import AnnotationBbox, DrawingArea
    from matplotlib.patches import Rectangle

    conds = read("condition_sizes.csv")
    fig, ax = plt.subplots(figsize=(13.0, 7.6))
    xlim, ylim = (555, 1445), (130, 200)
    v = np.linspace(500, 1500, 200)
    k = C.HATCH_MM * C.LAYER_MM
    lo, hi = S.WINDOW
    ax.fill_between(v, lo * v * k, hi * v * k, color=S.BAND, lw=0, zorder=0)
    for e in (40, 50, 60, 65, 85, 100, 125):
        ax.plot(v, e * v * k, color=S.AXIS if e in (65, 85) else S.GRID, lw=1.0, zorder=0)
        top_v = ylim[1] / (e * k)
        if top_v <= xlim[1]:
            ax.text(top_v, ylim[1] + 0.4, f"{e}", fontsize=9.5, color=S.INK_2, ha="center", va="bottom", clip_on=False)
        else:
            ax.text(xlim[1] + 8, e * xlim[1] * k, f"{e}", fontsize=9.5, color=S.INK_2, ha="left", va="center", clip_on=False)
    ax.text(xlim[1] + 8, ylim[1] + 0.4, "J/mm³", fontsize=9.5, color=S.INK_2, ha="left", va="bottom", clip_on=False)
    # The largest scale at which the two closest conditions (180 W at 1000 and 1050 mm/s) still clear each other.
    scale = 0.21  # points per micrometre
    for c in conds:
        ch, cw = _f(c, "camera_H_um") * scale, _f(c, "camera_W_um") * scale
        mh, mw = _f(c, "model_H_um") * scale, _f(c, "model_W_um") * scale
        width, height = max(ch, mh) + 4, max(cw, mw) + 4
        da = DrawingArea(width, height, 0, 0)
        da.add_artist(Rectangle(((width - mh) / 2, (height - mw) / 2), mh, mw, facecolor=S.MODEL, alpha=0.30, edgecolor="none"))
        da.add_artist(Rectangle(((width - mh) / 2, (height - mw) / 2), mh, mw, facecolor="none", edgecolor=S.MODEL, lw=1.4))
        da.add_artist(Rectangle(((width - ch) / 2, (height - cw) / 2), ch, cw, facecolor="none", edgecolor=S.CAMERA, lw=1.8))
        ax.add_artist(AnnotationBbox(da, (_f(c, "speed_mm_s"), _f(c, "power_W")), frameon=False, pad=0, zorder=3))
    # Scale key: a 100 um bar at the box scale, with its label.
    from matplotlib.offsetbox import AnchoredOffsetbox, TextArea, VPacker

    da = DrawingArea(100 * scale, 4, 0, 0)
    da.add_artist(Rectangle((0, 1), 100 * scale, 2.2, facecolor=S.INK, edgecolor="none"))
    key = VPacker(children=[da, TextArea("100 µm at box scale", textprops=dict(fontsize=9.5, color=S.INK))], align="left", pad=0, sep=4)
    ax.add_artist(AnchoredOffsetbox(loc="upper left", child=key, pad=0.4, borderpad=0.6, frameon=False))
    ax.set_xlim(*xlim)
    ax.set_ylim(*ylim)
    ax.set_xlabel("scan speed (mm/s)")
    ax.set_ylabel("laser power (W)")
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch

    handles = [Line2D([], [], color=S.CAMERA, lw=2, label="Experiment: camera H × W"), Patch(facecolor=S.MODEL, alpha=0.4, edgecolor=S.MODEL, label="Simulation: model H × W"),
               Patch(facecolor=S.BAND, edgecolor="none", label="calibration window, 65–85 J/mm³"), Line2D([], [], color=S.GRID, lw=1, label="lines of constant energy density")]
    fig.legend(handles=handles, loc="lower left", bbox_to_anchor=(0.0, 0.92), ncol=4, fontsize=10.5, frameon=False, columnspacing=1.6)
    S.title(fig, "Melt pool footprints over process space", y=0.965)
    S.note(fig, "Each pair of boxes sits at its process condition (18 conditions; replicate coupons pooled). Boxes are drawn to one size scale with H horizontal and W vertical; "
           "the model box is the\ncondition's median model H × W over frames with a pool, the orange outline the camera's. Nominal 8 µm/px.", y=0.03)
    return save(fig, "melt_pool_footprints_over_process_space", plt)


def _style_3d(ax):
    for axis in (ax.xaxis, ax.yaxis, ax.zaxis):
        axis.set_pane_color((0.988, 0.988, 0.984, 1.0))
        axis._axinfo["grid"].update({"color": S.GRID, "linewidth": 0.6})
        axis.line.set_color(S.AXIS)
    ax.tick_params(colors=S.INK_2, labelsize=9)


def process_3d(plt) -> list:
    rows = read("coupon_sizes.csv")
    fits = {(r["source"], r["quantity"]): r for r in read("process_power_law.csv")}
    fig = plt.figure(figsize=(13.4, 6.6))
    vv, pp = np.meshgrid(np.linspace(600, 1400, 25), np.linspace(140, 190, 25))
    for k, q in enumerate(("H", "W")):
        ax = fig.add_subplot(1, 2, k + 1, projection="3d")
        _style_3d(ax)
        for source, color in (("camera", S.CAMERA), ("model", S.MODEL)):
            fit = fits[(source, q)]
            zz = np.exp(float(fit["intercept"]) + float(fit["ln_P"]) * np.log(pp) + float(fit["ln_v"]) * np.log(vv))
            ax.plot_surface(vv, pp, zz, color=color, alpha=0.13, lw=0, antialiased=True, shade=False, zorder=1)
            ax.plot_wireframe(vv, pp, zz, color=color, alpha=0.25, lw=0.4, rstride=6, cstride=6, zorder=1)
        for r in rows:
            v, p = _f(r, "speed_mm_s"), _f(r, "power_W")
            c, m = _f(r, f"camera_{q}_um"), _f(r, f"model_{q}_um")
            ax.plot([v, v], [p, p], [c, m], color=S.INK_2, lw=0.9, alpha=0.7, zorder=2)
        ax.scatter([_f(r, "speed_mm_s") for r in rows], [_f(r, "power_W") for r in rows], [_f(r, f"camera_{q}_um") for r in rows], s=46, color=S.CAMERA,
                   edgecolors=S.SURFACE, linewidths=1.0, depthshade=False, zorder=3)
        ax.scatter([_f(r, "speed_mm_s") for r in rows], [_f(r, "power_W") for r in rows], [_f(r, f"model_{q}_um") for r in rows], s=46, color=S.MODEL,
                   edgecolors=S.SURFACE, linewidths=1.0, depthshade=False, zorder=3)
        ax.set_xlabel("scan speed (mm/s)", labelpad=8)
        ax.set_ylabel("laser power (W)", labelpad=8)
        ax.set_zlabel(f"{q} (µm)", labelpad=6)
        ax.view_init(elev=20, azim=-58)
        ax.set_box_aspect((1.25, 1.0, 0.95))
        cam, mod = fits[("camera", q)], fits[("model", q)]
        ax.text2D(0.0, 1.02, "H, melt pool length" if q == "H" else "W, melt pool width", transform=ax.transAxes, fontsize=12.5, fontweight="semibold", color=S.INK)
        exp = lambda fit: f"$P^{{{float(fit['ln_P']):.2f}}}\\ v^{{{float(fit['ln_v']):.2f}}}$"
        ax.text2D(0.0, 0.95, f"camera:  {q} $\\propto$ {exp(cam)}\nmodel:    {q} $\\propto$ {exp(mod)}", transform=ax.transAxes, fontsize=11, color=S.INK, va="top",
                  linespacing=1.7)
    handles = [legend_dot(S.CAMERA, "Experiment (camera), coupon median"), legend_dot(S.MODEL, "Simulation (model), coupon median")]
    from matplotlib.patches import Patch

    handles += [Patch(facecolor=S.CAMERA, alpha=0.3, label="camera power-law fit"), Patch(facecolor=S.MODEL, alpha=0.3, label="model power-law fit")]
    fig.legend(handles=handles, loc="lower left", bbox_to_anchor=(0.0, 0.915), ncol=4, fontsize=10.5, frameon=False)
    S.title(fig, "Melt pool size over power and speed", y=0.965)
    steep = [abs(float(fits[("model", q)][t]) / float(fits[("camera", q)][t])) for q in ("H", "W") for t in ("ln_P", "ln_v")]
    S.note(fig, "24 coupons; vertical lines join each coupon's camera and model medians. Surfaces: least-squares fits of ln(size) on ln P and ln v over the 24 coupons "
           "(descriptive; the exponents equal the committee package's process slopes).\n"
           f"The model's exponents are {min(steep):.1f} to {max(steep):.1f} times the camera's. Model medians over frames with a pool; nominal 8 µm/px.", y=0.05)
    fig.subplots_adjust(left=0.0, right=1.0, top=0.86, bottom=0.08, wspace=0.0)
    return save(fig, "melt_pool_size_over_power_and_speed", plt)


def calibration_3d(plt) -> list:
    import matplotlib as mpl

    cands = read("candidates.csv")
    fig = plt.figure(figsize=(13.4, 6.8))
    ax = fig.add_axes([0.0, 0.08, 0.56, 0.84], projection="3d")
    ax2 = fig.add_axes([0.66, 0.2, 0.32, 0.62])
    _style_3d(ax)
    J = np.array([_f(c, "J") for c in cands])
    cmap = S.ramp_cmap(S.BLUE_RAMP[3:], "J_ramp")
    norm = mpl.colors.Normalize(vmin=0.25, vmax=1.25)
    marker = {"frozen_design": "o", "confirmation": "D"}
    # Design box.
    T, K, E = (-3, 3), (1.5, 2.5), (0.0, 1.0)
    for a in T:
        for b in K:
            ax.plot([a, a], [b, b], E, color=S.AXIS, lw=0.7)
        for e in E:
            ax.plot([a, a], K, [e, e], color=S.AXIS, lw=0.7)
    for b in K:
        for e in E:
            ax.plot(T, [b, b], [e, e], color=S.AXIS, lw=0.7)
    for c in cands:
        t, k, e = _f(c, "t"), _f(c, "ck"), _f(c, "eta")
        ax.plot([t, t], [k, k], [0, e], color=S.MUTED, lw=0.7, alpha=0.6)
        ax.scatter([t], [k], [0], s=10, color=S.AXIS, depthshade=False)
        m = "*" if c["selected"] == "true" else ("s" if c["candidate"].startswith("anchor") else marker[c["origin"]])
        ax.scatter([t], [k], [e], s=260 if m == "*" else 80, marker=m, color=cmap(norm(_f(c, "J"))), edgecolors=S.INK if m == "*" else S.SURFACE,
                   linewidths=1.2, depthshade=False, zorder=5)
    sel = next(c for c in cands if c["selected"] == "true")
    ax.set_xlabel("t, absorptivity–depth coordinate", labelpad=8)
    ax.set_ylabel("ck, liquid conductivity factor", labelpad=8)
    ax.set_zlabel("η, directional factor", labelpad=6)
    ax.set_xlim(*T)
    ax.set_ylim(*K)
    ax.set_zlim(*E)
    ax.view_init(elev=22, azim=-62)
    from mpl_toolkits.mplot3d import proj3d

    fig.canvas.draw()
    sx, sy, _ = proj3d.proj_transform(_f(sel, "t"), _f(sel, "ck"), _f(sel, "eta"), ax.get_proj())
    ax.annotate("c1, selected", (sx, sy), xytext=(-85, -38), textcoords="offset points", fontsize=10.5, color=S.INK, fontweight="semibold", ha="right",
                va="center", zorder=20, bbox=dict(boxstyle="round,pad=0.2", fc=S.SURFACE, ec="none", alpha=0.9),
                arrowprops=dict(arrowstyle="-", color=S.INK_2, lw=0.9, shrinkB=9))
    cb_ax = fig.add_axes([0.06, 0.06, 0.4, 0.022])
    cb = fig.colorbar(mpl.cm.ScalarMappable(norm=norm, cmap=cmap), cax=cb_ax, orientation="horizontal")
    cb.outline.set_visible(False)
    cb.ax.tick_params(labelsize=9, length=2)
    cb.set_label("J, mismatch with the camera (lower is better)", fontsize=10, color=S.INK_2)
    for c in cands:
        m = "*" if c["selected"] == "true" else ("s" if c["candidate"].startswith("anchor") else marker[c["origin"]])
        ax2.scatter([_f(c, "t")], [_f(c, "J")], s=220 if m == "*" else 70, marker=m, color=cmap(norm(_f(c, "J"))), edgecolors=S.INK if m == "*" else S.SURFACE,
                    linewidths=1.2, zorder=3)
    ax2.annotate(f"c1: J {_f(sel, 'J'):.3f}", (_f(sel, "t"), _f(sel, "J")), xytext=(12, -16), textcoords="offset points", fontsize=10, color=S.INK)
    ax2.set_xlabel("t, absorptivity–depth coordinate")
    ax2.set_ylabel("J (lower is better)")
    ax2.set_xlim(-3.4, 3.4)
    ax2.set_ylim(0, 1.35)
    ax2.set_title("J against t", fontsize=12)
    from matplotlib.lines import Line2D

    handles = [Line2D([], [], ls="none", marker="o", color=S.INK_2, ms=8, label="Halton design point (12)"), Line2D([], [], ls="none", marker="s", color=S.INK_2, ms=8, label="anchor (5)"),
               Line2D([], [], ls="none", marker="D", color=S.INK_2, ms=7, label="confirmation (c2)"), Line2D([], [], ls="none", marker="*", color=S.INK_2, ms=14, label="selected (c1)")]
    ax2.legend(handles=handles, loc="upper left", fontsize=9.5, frameon=False, bbox_to_anchor=(0.0, 1.0))
    S.title(fig, "Calibration design in parameter space", y=0.95)
    n_halton = sum(c["candidate"].startswith("halton") for c in cands)
    n_anchor = sum(c["candidate"].startswith("anchor") for c in cands)
    n_confirm = sum(c["origin"] == "confirmation" for c in cands)
    t_min = min(_f(c, "t") for c in cands)
    edge = "on the box edge" if _f(sel, "t") == t_min else "inside the box"
    S.note(fig, f"The {len(cands)} calibrated candidates: {n_halton} Halton points and {n_anchor} anchors fixed before any run, plus {n_confirm} confirmation points. "
           "Colour: J, the mismatch between model and camera H and W on the 9 calibration coupons.\n"
           f"t sets absorptivity and heat-source depth together (t = {_f(sel, 't'):.0f}: absorptivity {_f(sel, 'absorptivity'):.2f}, depth "
           f"{_f(sel, 'deposition_depth_mm'):.3f} mm). The best match, c1, sits {edge} at t = {_f(sel, 't'):.0f}.".replace("t = -", "t = −"), y=0.0)
    return save(fig, "calibration_design_in_parameter_space", plt)


def candidate_shapes(plt) -> list:
    from matplotlib.patches import Rectangle

    cands = read("candidates.csv")
    ncol = 5
    nrow = math.ceil((len(cands) + 1) / ncol)
    fig = plt.figure(figsize=(13.0, 9.2))
    gs = fig.add_gridspec(nrow, ncol, hspace=0.55, wspace=0.08, left=0.0, right=1.0, top=0.86, bottom=0.07)
    hmax = max(_f(c, "model_H_um") for c in cands) * 1.08
    wmax = hmax * 0.42
    for k, c in enumerate(cands):
        ax = fig.add_subplot(gs[k // ncol, k % ncol])
        ax.set_xlim(-hmax / 2, hmax / 2)
        ax.set_ylim(-wmax / 2, wmax / 2)
        ax.set_aspect("equal")
        ax.axis("off")
        sel = c["selected"] == "true"
        ax.add_patch(Rectangle((-hmax / 2, -wmax / 2), hmax, wmax, facecolor=S.BAND if sel else "#f6f6f3", edgecolor=S.INK if sel else "none", lw=1.2, zorder=0))
        mh, mw = _f(c, "model_H_um"), _f(c, "model_W_um")
        ch, cw = _f(c, "camera_H_um"), _f(c, "camera_W_um")
        ax.add_patch(Rectangle((-mh / 2, -mw / 2), mh, mw, facecolor=S.MODEL, alpha=0.32, edgecolor="none", zorder=1))
        ax.add_patch(Rectangle((-mh / 2, -mw / 2), mh, mw, facecolor="none", edgecolor=S.MODEL, lw=1.4, zorder=2))
        ax.add_patch(Rectangle((-ch / 2, -cw / 2), ch, cw, facecolor="none", edgecolor=S.CAMERA, lw=1.8, zorder=3))
        ax.text(-hmax / 2, wmax / 2 + wmax * 0.30, c["label"], fontsize=11, fontweight="bold", color=S.INK, va="bottom")
        ax.text(-hmax / 2, wmax / 2 + wmax * 0.06, f"t {_f(c, 't'):+.2f} · ck {_f(c, 'ck'):.2f} · η {_f(c, 'eta'):.2f}", fontsize=9, color=S.INK_2, va="bottom")
        ax.text(hmax / 2, -wmax / 2 - wmax * 0.05, f"J {_f(c, 'J'):.3f}", fontsize=10, color=S.INK, va="top", ha="right")
        ax.text(-hmax / 2, -wmax / 2 - wmax * 0.05, f"{mh:.0f} × {mw:.0f} µm", fontsize=9, color=S.INK_2, va="top", ha="left")
    ax = fig.add_subplot(gs[(len(cands)) // ncol, len(cands) % ncol])
    ax.axis("off")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.add_patch(Rectangle((0.02, 0.62), 0.12, 0.12, facecolor=S.MODEL, alpha=0.32, edgecolor=S.MODEL, lw=1.4))
    ax.text(0.18, 0.68, "Simulation: model H × W", fontsize=10, va="center", color=S.INK)
    ax.add_patch(Rectangle((0.02, 0.38), 0.12, 0.12, facecolor="none", edgecolor=S.CAMERA, lw=1.8))
    ax.text(0.18, 0.44, "Experiment: camera H × W", fontsize=10, va="center", color=S.INK)
    ax.text(0.02, 0.18, "sorted by J, best first", fontsize=10, va="center", color=S.INK_2)
    S.title(fig, "Melt pool shape for each calibration candidate", y=0.95)
    longer = sum(_f(c, "model_H_um") > _f(c, "camera_H_um") for c in cands)
    narrower = [c for c in cands if _f(c, "model_W_um") < _f(c, "camera_W_um")]
    t_narrow = max(_f(c, "t") for c in narrower) if narrower else float("nan")
    S.note(fig, "Boxes drawn to one scale, H horizontal and W vertical: the median over the 9 calibration coupons of each coupon's median model H and W (frames with a pool) "
           "and of the camera's.\n"
           f"The model's pool is longer than the camera's for {longer} of {len(cands)} candidates and narrower for {len(narrower)} (all with t ≤ {t_narrow:+.2f}); "
           "lowering t shortens and narrows it. Nominal 8 µm/px.", y=0.035)
    return save(fig, "melt_pool_shape_by_calibration_candidate", plt)


def operators_vs_ved(plt) -> list:
    rows = read("operator_ratios.csv")
    fig, axes = plt.subplots(1, 2, figsize=(12.8, 5.8), sharey=True, gridspec_kw={"wspace": 0.08})
    style = {
        "liquidus": dict(color=S.MODEL, marker="o", label="Simulation: model liquidus"),
        "sharp": dict(color=S.SYNTH, marker="^", label="Simulated camera, sharp"),
        "2 px blur": dict(color=S.SYNTH, marker="v", label="Simulated camera, 2 px blur"),
    }
    for ax, q in zip(axes, ("H", "W")):
        ved_band(ax, axis="x", label=(q == "H"))
        ax.axhline(1.0, color=S.INK_2, lw=1.2, zorder=1)
        ax.text(76.0, 1.04, "matches the camera", fontsize=9.5, color=S.INK_2, ha="center", va="bottom")
        for op, st in style.items():
            sub = sorted((r for r in rows if r["operator"] == op), key=lambda r: _f(r, "ved_J_mm3"))
            x = np.array([_f(r, "ved_J_mm3") for r in sub])
            y = np.array([_f(r, f"median_{q}_ratio") for r in sub])
            full = np.array([_f(r, "coverage") >= 0.95 for r in sub])
            hollow = op == "2 px blur"
            ax.scatter(x[full], y[full], s=60, marker=st["marker"], facecolors=S.SURFACE if hollow else st["color"], edgecolors=st["color"] if hollow else S.SURFACE,
                       linewidths=1.5, zorder=3)
            ax.scatter(x[~full], y[~full], s=60, marker=st["marker"], facecolors=S.SURFACE if hollow else st["color"], edgecolors=st["color"] if hollow else S.SURFACE,
                       linewidths=1.5, alpha=0.35, zorder=2)
        ax.set_yscale("log")
        ax.set_yticks([0.1, 0.2, 0.5, 1, 2, 3], ["0.1", "0.2", "0.5", "1", "2", "3"])
        ax.set_ylim(0.09, 4.0)
        ax.set_xlim(38, 129)
        ax.set_xlabel("energy density, VED (J/mm³)")
        ax.set_title("H, melt pool length" if q == "H" else "W, melt pool width", fontsize=12.5)
    axes[0].set_ylabel("ratio to the camera (median, log scale)")
    handles = [legend_dot(st["color"], st["label"], marker=st["marker"], mfc="none" if op == "2 px blur" else None) for op, st in style.items()]
    handles.append(legend_dot(S.MUTED, "faded: simulated camera sees a pool on < 95 % of frames", marker="^"))
    handles[-1].set_alpha(0.35)
    fig.legend(handles=handles, loc="lower left", bbox_to_anchor=(0.0, 0.9), ncol=4, fontsize=10, frameon=False, columnspacing=1.4)
    S.title(fig, "Simulated camera and model against the camera", y=0.96)
    lo, hi = S.WINDOW

    def span(op, q, test):
        vals = [_f(r, f"median_{q}_ratio") for r in rows if r["operator"] == op and test(_f(r, "ved_J_mm3"))]
        return f"{min(vals):.2f}–{max(vals):.2f}"

    inside, above = (lambda v: lo <= v <= hi), (lambda v: v > hi)
    S.note(fig, "Coupon medians of the frame ratios (model or simulated camera ÷ camera), 24 coupons. The simulated camera's brightness scale was fixed once on the calibration "
           "coupons (1950 K sharp, 1825 K blurred).\n"
           f"In the window the sharp simulated camera's H ratio is {span('sharp', 'H', inside)} and the liquidus's {span('liquidus', 'H', inside)}; "
           f"above {hi:.0f} J/mm³ they are {span('sharp', 'H', above)} and {span('liquidus', 'H', above)}.", y=0.03)
    fig.subplots_adjust(top=0.82, bottom=0.17)
    return save(fig, "simulated_camera_and_model_against_camera", plt)


def frame_density(plt) -> list:
    import matplotlib as mpl

    frames = read("frame_sizes.csv.gz")
    pool = [r for r in frames if r["no_pool"] == "false"]
    coupons = read("coupon_sizes.csv")
    fig = plt.figure(figsize=(12.6, 6.2))
    gs = fig.add_gridspec(1, 3, width_ratios=[1, 1, 0.035], wspace=0.22, left=0.06, right=0.95, top=0.84, bottom=0.14)
    axes = [fig.add_subplot(gs[0, 0]), fig.add_subplot(gs[0, 1])]
    cmap = S.ramp_cmap(("#f0efec",) + S.BLUE_RAMP[2:], "density")
    from matplotlib.colors import LogNorm

    hbs = []
    for ax, q, lim in ((axes[0], "H", 360), (axes[1], "W", 130)):
        x = np.array([_f(r, f"camera_{q}_um") for r in pool])
        y = np.array([_f(r, f"model_{q}_um") for r in pool])
        hb = ax.hexbin(x, y, gridsize=46, extent=(0, lim, 0, lim), cmap=cmap, mincnt=1, norm=LogNorm(), lw=0.2, edgecolors=S.SURFACE, zorder=2)
        hbs.append(hb)
        ax.plot([0, lim], [0, lim], color=S.INK_2, lw=1.2, zorder=3)
        ax.text(lim * 0.97, lim * 0.93, "model = camera", fontsize=9.5, color=S.INK_2, ha="right", va="top", rotation=0)
        ax.scatter([_f(r, f"camera_{q}_um") for r in coupons], [_f(r, f"model_{q}_um") for r in coupons], s=30, color=S.INK, edgecolors=S.SURFACE,
                   linewidths=1.2, zorder=4)
        ax.set_xlim(0, lim)
        ax.set_ylim(0, lim)
        ax.set_aspect("equal")
        ax.set_xlabel(f"camera {q} (µm)")
        ax.set_ylabel(f"model {q} (µm)")
        ax.set_title("H, melt pool length" if q == "H" else "W, melt pool width", fontsize=12.5)
    top = max(float(h.get_array().max()) for h in hbs)
    for h in hbs:
        h.set_norm(LogNorm(vmin=1, vmax=top))
    cb = fig.colorbar(hbs[0], cax=fig.add_subplot(gs[0, 2]))
    cb.outline.set_visible(False)
    cb.ax.tick_params(labelsize=9)
    cb.set_label("frames per cell (log scale)", fontsize=9.5, color=S.INK_2)
    handles = [legend_dot(S.INK, "coupon median, camera against model (24 coupons)", ms=7)]
    fig.legend(handles=handles, loc="lower left", bbox_to_anchor=(0.0, 0.9), fontsize=10.5, frameon=False)
    S.title(fig, "Every frame: camera against model", y=0.96)
    S.note(fig, f"{len(pool):,} scored frames with a model pool ({len(frames) - len(pool):,} frames without one are not shown). Darker cells hold more frames. "
           "Points on the grey line would be perfect agreement. Nominal 8 µm/px.", y=0.03)
    return save(fig, "every_frame_camera_against_model", plt)


RENDERS = {
    "melt_pool_size_by_coupon": dumbbell,
    "melt_pool_length_against_width": shape_space,
    "frame_size_distributions_by_condition": ridgeline,
    "melt_pool_footprints_over_process_space": footprints,
    "melt_pool_size_over_power_and_speed": process_3d,
    "calibration_design_in_parameter_space": calibration_3d,
    "melt_pool_shape_by_calibration_candidate": candidate_shapes,
    "simulated_camera_and_model_against_camera": operators_vs_ved,
    "every_frame_camera_against_model": frame_density,
}


def render(plt, only=None) -> list:
    out = []
    for name, fn in RENDERS.items():
        if only and name not in only:
            continue
        out.extend(fn(plt))
    return out
