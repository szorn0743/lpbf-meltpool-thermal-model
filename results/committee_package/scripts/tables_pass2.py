"""Pass-2 (appendix) tables: T5, T9, T10, T12, T14, T15, T16 and the synchronization table (T19).

Same conventions as ``tables.py``: Markdown rounded for reading, CSV at full precision. The computations live in
``controls.py``, ``replicates.py``, ``variance.py``, ``operators.py``, ``sensitivity.py`` and ``sync.py``; this module
only lays them out.
"""
from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

import common as C
from tables import ROLE_SHORT, ci, f, write_table


def pct(value: Any, digits: int = 1) -> str:
    return "–" if value is None else f"{100.0 * value:.{digits}f} %"


def signed_pct(log_diff: float) -> str:
    return f"{100.0 * (math.exp(log_diff) - 1.0):+.1f} %"


def span(values: Sequence[float], fmt: str = "{:.2f}") -> str:
    """'a–b' for a range, or a single value when the range is degenerate at the printed precision."""

    lo, hi = fmt.format(min(values)), fmt.format(max(values))
    return lo if lo == hi else f"{lo}–{hi}"


# ---------------------------------------------------------------------- T5


def t5(controls_rows: Sequence[Mapping[str, Any]], consistency: Mapping[str, Any]) -> list:
    cols = [
        ("g", "Group", lambda r: r["group"]), ("c", "Control", lambda r: r["control"]), ("v", "Value", lambda r: r["value"]),
        ("var", "Varied by the calibration", lambda r: "**yes**" if r["varied_by_calibration"] else "no"), ("s", "Source (read at build time)", lambda r: r["source"]),
    ]
    notes = [
        "Every value is read from the code the Patch 22.4.3.2 runner imported, when the package is built; nothing is copied by hand.",
        "Only three coordinates were calibrated: t (absorptivity and deposition depth together, A9), ck (liquid conductivity) and η (directional conductivity). Everything else was fixed before the calibration (A25, A26).",
        f"The smoke, calibrate, confirm and evaluate manifests all recorded the same beam-share floor, coverage floor, pixel floor, window, semantic versions, design file, objective module and plan (sha256): {'yes' if consistency['all_constant'] else 'NO'} (T16).",
        "The runner module changed once between calibrate and confirm (the c2 walk fix, `ec53a55`, T17 deviation); the objective module did not change.",
        "Boiling: the model has no temperature cap; above the boiling point a surface loss flux grows quadratically (A27 failure mode: peaks above 3133 K remain).",
    ]
    return write_table("T05_fixed_controls", "Fixed model and numerical controls", ["What the calibration held fixed, so that the numerical framework could not be adjusted opportunistically."], [(None, controls_rows, cols)], notes, controls_rows)


# ---------------------------------------------------------------------- T9


def t9(analysis: Mapping[str, Any], d3: Sequence[Mapping[str, Any]], d4: Sequence[Mapping[str, Any]]) -> list:
    record = analysis["record"]
    lo, hi = C.VED_WINDOW_J_MM3
    coupons = []
    for r in sorted((r for r in d3 if r["role"].startswith("out_of_window")), key=lambda r: r["ved_J_mm3"]):
        v = r["ved_J_mm3"]
        coupons.append({**r, "_label": r["member"], "status": "blind" if r["role"] == "out_of_window_blind" else "examined", "distance_from_window": max(lo - v, v - hi, 0.0), "side": "below" if v < lo else "above"})
    groups = {r["name"]: r for r in d4 if r["level"] == "group"}
    group_rows = [{**groups[n], "_label": f"**{C.GROUP_LABEL[n]}**", "status": "", "coverage": 1.0} for n in ("out_of_window_all", "out_of_window_low_ved", "out_of_window_high_ved", "out_of_window_examined", "out_of_window_blind")]
    cols = [
        ("n", "Coupon / group", lambda r: r["_label"]), ("c", "Condition", lambda r: r.get("condition") or "–"),
        ("ved", "VED", lambda r: f(r.get("ved_J_mm3"), 1)), ("d", "Outside window by", lambda r: f(r.get("distance_from_window"), 1)),
        ("s", "Status", lambda r: r["status"] or "–"),
        ("hr", "H ratio", lambda r: ci(r, "median_H_ratio", 2)), ("wr", "W ratio", lambda r: ci(r, "median_W_ratio", 2)),
        ("eh", "e_H", lambda r: ci(r, "e_H")), ("ew", "e_W", lambda r: ci(r, "e_W")), ("j", "J", lambda r: f(r["J"])),
        ("np", "No-pool", lambda r: pct(r["no_pool_frames"] / r["scored_frames"])), ("cov", "Coverage", lambda r: f(r.get("coverage"), 3)),
        ("b", "Peak > 3133 K", lambda r: pct(r["peak_above_boiling_fraction"])), ("pk", "Median peak (K)", lambda r: f(r["median_peak_surface_K"], 0)),
    ]
    x = C.evaluate_manifest()["readings"]["X"]
    xrows = [
        {"reading": "X2 (H)", "statistic": "Spearman ρ(VED, coupon median r_H), 10 coupons", "value": x["X2_H"]["spearman_rho"], "rule": f"ρ >= 0.6 and the predicted signs (over-prediction above {C.VED_WINDOW_J_MM3[1]:g}, under below)", "holds": x["X2_H"]["holds"]},
        {"reading": "X1 (W)", "statistic": "Spearman ρ(VED, coupon median r_W), 10 coupons", "value": x["X1_W"]["spearman_rho"], "rule": "ρ >= 0.6 and the signs: over-prediction for " + ", ".join(x["X1_W"]["over_members"]) + "; under for the rest", "holds": x["X1_W"]["holds"]},
    ]
    xcols = [("r", "Reading", lambda r: r["reading"]), ("s", "Statistic", lambda r: r["statistic"]), ("v", "Value", lambda r: f(r["value"])), ("u", "Predeclared rule (plan 22.4.3.2)", lambda r: r["rule"]), ("h", "Holds", lambda r: f(r["holds"]))]
    worst = max(coupons, key=lambda r: r["no_pool_frames"] / r["scored_frames"])
    notes = [
        f"Reading X_PARTIAL (A27): error grows with distance in VED, almost monotonically in rank (ρ {x['X2_H']['spearman_rho']:.2f} for H, {x['X1_W']['spearman_rho']:.2f} for W), but the W signs do not all match the prediction (X1 fails on signs only).",
        "Coupon intervals: tracks resampled within the coupon (within-coupon sampling only). Group intervals: coupons resampled within the group; with 3-7 coupons they are coarse.",
        "Examined: A8 calibration members read by Patch 22.3.8 before the window was chosen. Blind: A8 held out, first compared at the 22.4.3.2 evaluation. The blind coupons lie nearer the window (confound table), so their lower error reflects VED distance, not blindness.",
        f"No-pool frames are model predictions scored as H = W = 0 (D1); they dominate {worst['member']} ({100 * worst['no_pool_frames'] / worst['scored_frames']:.0f} %). Coverage is 1.000 for every coupon (T4).",
        "All ten coupons were opened by the 22.4.3.2 evaluation; the three blind ones are now spent as held-out data (A8, A27).",
    ]
    data = [{k: v for k, v in r.items() if not k.startswith("_")} | {"level": "coupon"} for r in coupons] + [{k: v for k, v in r.items() if not k.startswith("_")} | {"level": "group"} for r in group_rows]
    return write_table(
        "T09_out_of_window_performance", "Out-of-window performance", ["The frozen calibration applied to the 10 coupons outside 65–85 J/mm³, sorted by VED, with the predeclared reading X."],
        [("Reading X", xrows, xcols), ("By coupon and group", coupons + group_rows, cols)], notes, data + [{"level": "reading_X", **r} for r in xrows],
    )


# ---------------------------------------------------------------------- T10


def t10(rep: Mapping[str, Any]) -> list:
    pairs = rep["pairs"]
    by = {(r["condition"], r["quantity"]): r for r in pairs}
    conditions = list(dict.fromkeys(r["condition"] for r in pairs))

    def size_cell(cid: str, q: str) -> str:
        r = by[(cid, q)]
        return f"{r['value_0730']:.2f} / {r['value_0731']:.2f} ({signed_pct(r['difference'])})"

    def diff_cell(cid: str, q: str) -> str:
        r = by[(cid, q)]
        return f"{r['value_0730']:.3f} / {r['value_0731']:.3f} ({r['difference']:+.3f} [{r['difference_ci_lo']:+.3f}, {r['difference_ci_hi']:+.3f}])"

    compact = [
        {
            "condition": cid, "role": ROLE_SHORT[by[(cid, "cam_H")]["role"]], "ved": by[(cid, "cam_H")]["ved_J_mm3"],
            **{q: size_cell(cid, q) for q in ("cam_H", "cam_W", "cam_HW", "sim_H", "sim_W")}, **{q: diff_cell(cid, q) for q in ("e_H", "e_W")},
        }
        for cid in conditions
    ]
    ccols = [
        ("c", "Condition", lambda r: r["condition"]), ("r", "Role", lambda r: r["role"]), ("v", "VED", lambda r: f(r["ved"], 1)),
        ("ch", "Camera H, px (0730 / 0731, Δ)", lambda r: r["cam_H"]), ("cw", "Camera W, px", lambda r: r["cam_W"]), ("chw", "Camera H/W", lambda r: r["cam_HW"]),
        ("mh", "Model H, px", lambda r: r["sim_H"]), ("mw", "Model W, px", lambda r: r["sim_W"]),
        ("eh", "e_H (0730 / 0731, Δ [95 % CI])", lambda r: r["e_H"]), ("ew", "e_W", lambda r: r["e_W"]),
    ]
    s = rep["summary"]
    srows = [
        {"quantity": label, "mean": s[key]["mean_abs_log_difference"], "max": s[key]["max_abs_log_difference"], "ci0": s[key]["pairs_with_ci_excluding_zero"]}
        for key, label in (("cam_H", "Camera H"), ("cam_W", "Camera W"), ("sim_H", "Model H"), ("sim_W", "Model W"))
    ]
    scols = [("q", "Coupon median", lambda r: r["quantity"]), ("m", "Mean absolute ln(0731/0730), 6 pairs", lambda r: f"{r['mean']:.4f} ({100 * r['mean']:.1f} %)"), ("x", "Largest", lambda r: f"{r['max']:.4f}"), ("z", "Pairs whose CI excludes 0", lambda r: f"{r['ci0']} of 6")]
    spread = rep["spreads"]
    spcols = [
        ("m", "Coupon", lambda r: r["member"]), ("r", "Role", lambda r: ROLE_SHORT[r["role"]]),
        ("cht", "Camera H: track SD", lambda r: f(r["cam_H_track_sd_log"])), ("chf", "frame SD", lambda r: f(r["cam_H_frame_sd_log"])),
        ("cwt", "Camera W: track SD", lambda r: f(r["cam_W_track_sd_log"])), ("cwf", "frame SD", lambda r: f(r["cam_W_frame_sd_log"])),
        ("mht", "Model H: track SD", lambda r: f(r["sim_H_track_sd_log"])), ("mhf", "frame SD", lambda r: f(r["sim_H_frame_sd_log"])),
        ("mwt", "Model W: track SD", lambda r: f(r["sim_W_track_sd_log"])), ("mwf", "frame SD", lambda r: f(r["sim_W_frame_sd_log"])),
    ]
    fcols = [
        ("g", "Group", lambda r: r["label"]),
        ("sz", "Camera median H / W (px)", lambda r: f"{r['cam_H_px_median_min']:.1f}–{r['cam_H_px_median_max']:.1f} / {r['cam_W_px_median_min']:.1f}–{r['cam_W_px_median_max']:.1f}"),
        ("px", "1 px is up to", lambda r: pct(r["one_px_relative_max"], 0)),
        ("rm", "Re-measurement, median absolute Δln, H / W", lambda r: f"{r['remeasure_H_median_abs_log_diff']:.3f} / {r['remeasure_W_median_abs_log_diff']:.3f}"),
        ("ot", "Track oracle e_H / e_W", lambda r: f"{r['oracle_track_e_H']:.3f} / {r['oracle_track_e_W']:.3f}"),
        ("oc", "Coupon oracle e_H / e_W", lambda r: f"{r['oracle_coupon_e_H']:.3f} / {r['oracle_coupon_e_W']:.3f}"),
        ("orp", "Replicate oracle e_H / e_W", lambda r: "–" if r["oracle_replicate_e_H"] is None else f"{r['oracle_replicate_e_H']:.3f} / {r['oracle_replicate_e_W']:.3f} ({r['oracle_replicate_coupons']} coupons)"),
        ("me", "Model e_H / e_W", lambda r: f"**{r['model_e_H']:.3f} / {r['model_e_W']:.3f}**"),
    ]
    def worst(keys: Sequence[str]) -> float:
        return max(abs(math.exp(r["difference"]) - 1.0) for r in pairs if r["quantity"] in keys)

    higher = {q: sum(1 for cid in conditions if by[(cid, q)]["difference"] > 0) for q in ("e_H", "e_W")}
    size_ci = sum(1 for r in pairs if r["quantity"] in ("cam_H", "cam_W", "sim_H", "sim_W") and r["ci_excludes_zero"])
    floors = {r["group"]: r for r in rep["floors"]}
    everything = floors["all_24"]
    in_groups = [floors[g] for g in ("calibration", "in_window_held_out", "out_of_window_all")]
    ratio = {q: [r[f"model_e_{q}"] / r[f"oracle_coupon_e_{q}"] for r in in_groups] for q in ("H", "W")}
    notes = [
        "Replicates. The six July conditions were built on 20260730 and again on 20260731 by the same part number (confound table), so a pair differs by day only. Δ for sizes is the relative difference of the coupon medians, for e the plain difference; intervals: tracks resampled within each coupon independently (family 5, 4,000 replicates), i.e. within-coupon sampling only.",
        f"The camera's coupon medians repeat between days to within {100 * worst(('cam_H', 'cam_W')):.1f} % and the model's to within {100 * worst(('sim_H', 'sim_W')):.1f} %; {size_ci} of 24 size differences have an interval excluding zero. The day difference sits in e: 0731 has the larger e_H in {higher['e_H']} of 6 pairs and the larger e_W in {higher['e_W']} of 6, consistent with the 0731-only end-of-track frames without a predicted pool (confound table, T15 E).",
        "Within-coupon spread is on the log scale (≈ relative spread): SD of the ln track medians, and the pooled SD of ln frame values within tracks.",
        f"Measurement floor. The camera's coupon-median blob is {everything['cam_W_px_median_min']:.1f}–{everything['cam_H_px_median_max']:.1f} px across, so a 1 px step is up to {100 * everything['one_px_relative_max']:.0f} % of a dimension. Re-measuring the supplied images at threshold 150 (reading S) reproduces the supplied H and W to a median {100 * everything['remeasure_H_median_abs_log_diff']:.1f} % and {100 * everything['remeasure_W_median_abs_log_diff']:.1f} % per frame.",
        f"Oracle floors: the e a predictor would score if it knew the camera exactly and predicted one value per track (track oracle), per coupon (coupon oracle) or the other day's coupon value (replicate oracle). Any model that is constant within a coupon scores at least the coupon oracle. Across the three groups the model's e_H is {min(ratio['H']):.1f}–{max(ratio['H']):.1f} times the coupon floor and its e_W {min(ratio['W']):.1f}–{max(ratio['W']):.1f} times.",
        "Sources: `data/T10_replicate_pairs.csv` (every quantity with intervals), `data/T10_within_coupon_spread.csv`, `data/T10_measurement_floor.csv`, `data/T10_camera_remeasurement.csv`, `data/bootstrap/D5_replicate_bootstrap.npz`.",
    ]
    return write_table(
        "T10_replicates_and_measurement_floor", "Replicates and measurement floor",
        ["How well the experiment repeats between the two July days, and how small an error is attainable at all, so that the model's e_H and e_W are read against a floor rather than against zero."],
        [("Replicate pairs (20260730 / 20260731)", compact, ccols), ("Day-to-day agreement of coupon medians", srows, scols), ("Measurement floor", rep["floors"], fcols), ("Within-coupon spread (log scale)", spread, spcols)],
        notes, [{"section": "pairs", **r} for r in pairs] + [{"section": "floor", **r} for r in rep["floors"]] + [{"section": "spread", **r} for r in spread],
    )


# ---------------------------------------------------------------------- T12


def t12(var: Mapping[str, Any]) -> list:
    pcols = [
        ("s", "Scope", lambda r: {"all_24": "All 24 coupons", "calibration": "Calibration (9)"}[r["scope"]]), ("q", "Quantity", lambda r: r["label"]),
        ("n", "Frames / tracks / coupons / conditions", lambda r: f"{r['frames']:,} / {r['tracks']:,} / {r['coupons']} / {r['conditions']}"),
        ("w", "Within track", lambda r: pct(r["share_within_track"])), ("t", "Between tracks (in coupon)", lambda r: pct(r["share_between_tracks_within_coupon"])),
        ("c", "Between coupons (in condition)", lambda r: pct(r["share_between_coupons_within_condition"])), ("k", "Between conditions", lambda r: pct(r["share_between_conditions"])),
        ("v", "Total variance", lambda r: f(r["total_variance"], 4)),
    ]
    ecols = [
        ("g", "Group", lambda r: r["label"]), ("n", "Frames / tracks / coupons / conditions", lambda r: f"{r['frames']:,} / {r['tracks']:,} / {r['coupons']} / {r['conditions']}"),
        ("ih", "ICC coupon r_H / r_W", lambda r: f"{r['icc_coupon_r_H']:.3f} / {r['icc_coupon_r_W']:.3f}"),
        ("dh", "Design effect r_H / r_W", lambda r: f"{r['deff_coupon_r_H']:.0f} / {r['deff_coupon_r_W']:.0f}"),
        ("nh", "Effective n (frames) r_H / r_W", lambda r: f"{r['n_eff_coupon_r_H']:.0f} / {r['n_eff_coupon_r_W']:.0f}"),
        ("it", "ICC track r_H / r_W", lambda r: f"{r['icc_track_r_H']:.3f} / {r['icc_track_r_W']:.3f}"),
        ("u", "Inferential unit", lambda r: f"{r['coupons']} coupons, {r['conditions']} conditions"),
    ]
    xcols = [
        ("g", "Group", lambda r: r["label"]),
        ("fs", "Median frame ρ(model, camera) H / W", lambda r: f"{r['median_frame_spearman_H']:+.2f} / {r['median_frame_spearman_W']:+.2f}"),
        ("ts", "Median track ρ H / W", lambda r: f"{r['median_track_spearman_H']:+.2f} / {r['median_track_spearman_W']:+.2f}"),
        ("ra", "Median e(actual) / e(shuffled) H / W", lambda r: f"{r['median_e_H_actual_over_shuffled']:.3f} / {r['median_e_W_actual_over_shuffled']:.3f}"),
        ("p", "Coupons with p < 0.05, H / W", lambda r: f"{r['coupons_p_H_below_0_05']} / {r['coupons_p_W_below_0_05']} of {r['coupons']}"),
    ]
    ccols = [
        ("m", "Coupon", lambda r: r["member"]), ("r", "Role", lambda r: ROLE_SHORT[r["role"]]), ("v", "VED", lambda r: f(r["ved_J_mm3"], 1)),
        ("fh", "Frame ρ H", lambda r: f"{r['frame_spearman_H']:+.2f}"), ("th", "Track ρ H", lambda r: f"{r['track_spearman_H']:+.2f}"),
        ("rh", "e_H actual / shuffled", lambda r: f"{r['e_H_actual']:.3f} / {r['e_H_shuffled_mean']:.3f}"), ("ph", "p (H)", lambda r: f"{r['p_H_shuffled_at_or_below_actual']:.3f}"),
        ("fw", "Frame ρ W", lambda r: f"{r['frame_spearman_W']:+.2f}"), ("tw", "Track ρ W", lambda r: f"{r['track_spearman_W']:+.2f}"),
        ("rw", "e_W actual / shuffled", lambda r: f"{r['e_W_actual']:.3f} / {r['e_W_shuffled_mean']:.3f}"), ("pw", "p (W)", lambda r: f"{r['p_W_shuffled_at_or_below_actual']:.3f}"),
    ]
    part = {(r["scope"], r["quantity"]): r for r in var["partition"]}
    cam, sim = part[("all_24", "ln_cam_H")], part[("all_24", "ln_sim_H")]
    notes = [
        f"A. Exact frame-weighted sum-of-squares partition (within-track + between-track + between-coupon + between-condition = total). Between coupons within a condition is the 0730/0731 day difference (6 July conditions; September conditions have one coupon each). Over all 24 coupons the camera H varies {100 * cam['share_between_tracks_within_coupon']:.0f} % between tracks of a coupon and {100 * cam['share_between_conditions']:.0f} % between conditions; the model's H varies {100 * sim['share_between_tracks_within_coupon']:.0f} % between tracks and {100 * sim['share_between_conditions']:.0f} % between conditions.",
        f"B. One-way random-effects ICC (ANOVA estimator, unbalanced n0) with coupons as clusters; design effect 1 + (m̄ − 1) ICC with m̄ ≈ 1,000 frames per coupon. Even a small coupon ICC shrinks the frames to an effective {span([r[f'n_eff_coupon_r_{q}'] for r in var['effective'] for q in ('H', 'W')], '{:.0f}')} independent ones per group (against {span([r['frames'] for r in var['effective']], '{:,}')} scored); the package therefore infers over coupons and conditions, never frames (T1).",
        "C. Within-coupon explanatory power (exploratory, plan Part 1, item 4). ρ: Spearman over frames with a predicted pool, and over track medians (tracks with ≥ 3 such frames). Permutation control: the camera values are shuffled across the coupon's scored frames 1,000 times (family 6) and the coupon e is recomputed through the track hierarchy; p is the share of shuffles with e at or below the actual e. A ratio near 1 means the pairing of model and camera frames inside a coupon carries no information: the model explains differences between conditions, not the variation within a coupon (cf. the track-order confound).",
        "Sources: `data/T12_variance_partition.csv`, `data/T12_effective_sample_size.csv`, `data/T12_within_coupon_power.csv`, `data/T12_within_coupon_power_summary.csv`.",
    ]
    return write_table(
        "T12_variance_and_sample_size", "Variance and effective sample size",
        ["Where the data vary, why the frame count is not the sample size, and whether the model follows the camera inside a coupon."],
        [("A. Where the variation sits (share of the frame-level sum of squares)", var["partition"], pcols), ("B. Effective sample size", var["effective"], ecols), ("C. Within-coupon explanatory power, by group", var["explanatory_summary"], xcols), ("C. Within-coupon explanatory power, by coupon", var["explanatory"], ccols)],
        notes, [{"section": "partition", **r} for r in var["partition"]] + [{"section": "effective", **r} for r in var["effective"]] + [{"section": "within_coupon_summary", **r} for r in var["explanatory_summary"]] + [{"section": "within_coupon", **r} for r in var["explanatory"]],
    )


# ---------------------------------------------------------------------- T14


SCALE_ROWS = (
    ("Absolute sizes (µm)", "yes", "camera µm = px x 8 µm/px; the scale is unvalidated (A24)"),
    ("Model/camera H and W ratios; e_H, e_W, J", "yes", "the model's µm are converted to camera px with 8 µm/px; a true scale s multiplies both ratios by 8/s and shifts every r by ln(8/s)"),
    ("Synthetic-camera and width-matched comparisons", "yes", "both render the model field on the 8 µm camera grid"),
    ("Shape ratio (model H/W ÷ camera H/W)", "no", "a common scale factor cancels"),
    ("H ratio ÷ W ratio", "no", "a common scale factor cancels"),
    ("Process slopes (T11, this table)", "no", "a constant factor only shifts the intercept"),
    ("Rank correlations (reading X)", "no", "a constant shift of r leaves ranks unchanged"),
)


def t14(ops: Mapping[str, Any]) -> list:
    gcols = [
        ("g", "Group", lambda r: r["label"]), ("o", "Operator (model side)", lambda r: r["operator_label"]), ("ob", "Camera side", lambda r: r["observation"]),
        ("n", "Frames (coverage)", lambda r: f"{r['frames']:,} ({r['coverage']:.3f})"),
        ("hr", "H ratio", lambda r: f(r["median_H_ratio"], 2)), ("wr", "W ratio", lambda r: f(r["median_W_ratio"], 2)),
        ("hw", "Model H/W / camera H/W", lambda r: f"{r['model_HW_median']:.2f} / {r['camera_HW_median']:.2f}"), ("sr", "Shape ratio", lambda r: f(r["shape_ratio"], 2)),
        ("eh", "e_H", lambda r: f(r["e_H"])), ("ew", "e_W", lambda r: f(r["e_W"])),
    ]
    wcols = [
        ("c", "Candidate", lambda r: r["candidate"]), ("s", "Coupons", lambda r: r["scope"]),
        ("h", "Width-matched H ratio (median of coupons)", lambda r: f(r.get("median_of_coupon_H_ratio"), 2) if r.get("median_of_coupon_H_ratio") is not None else f"{r['median_of_coupon_H_ratio_min']:.2f}–{r['median_of_coupon_H_ratio_max']:.2f}"),
        ("p", "Pooled median [IQR]", lambda r: f"{r['pooled_median_H_ratio']:.2f} [{r['pooled_H_ratio_p25']:.2f}, {r['pooled_H_ratio_p75']:.2f}]" if r.get("pooled_median_H_ratio") is not None else "–"),
        ("l", "Matched isotherm (median K)", lambda r: f(r.get("median_level_K"), 0)), ("b", "Below liquidus", lambda r: pct(r.get("fraction_level_below_liquidus"), 0)),
        ("d", "Note", lambda r: f"{r['candidates_in_band_0_87_1_15']} of 17 within [0.87, 1.15]" if "candidates_in_band_0_87_1_15" in r else (f"coded distance to c1 {r['coded_distance_to_c1']:.2f}" if "coded_distance_to_c1" in r else "")),
    ]
    tcols = [
        ("t", "Threshold", lambda r: ("**150**" if r["threshold"] == 150 else str(r["threshold"]))), ("h", "Camera H (px)", lambda r: f(r["median_H_px"], 1)),
        ("w", "Camera W (px)", lambda r: f(r["median_W_px"], 1)), ("hw", "Camera H/W", lambda r: f(r["median_HW"], 2)),
        ("rh", "H / H(150)", lambda r: f(r["H_relative_to_150"], 2)), ("rw", "W / W(150)", lambda r: f(r["W_relative_to_150"], 2)),
        ("e", "Blob at crop edge", lambda r: pct(r["median_edge_touch_fraction"])),
    ]
    labels = {"camera_supplied": "Camera, supplied (threshold 150)", "camera_remeasured": "Camera, re-measured (150, synthetic-paired frames)", "liquidus": "Model liquidus (c1)", "lam850_uniform_sig0.0": "Synthetic camera, PSF 0 px", "lam850_uniform_sig2.0": "Synthetic camera, PSF 2 px"}
    by = {(r["source"], r["quantity"], r["term"]): r for r in ops["slopes"]}
    slope_rows = [
        {
            "source": labels[s], "min_coverage": by[(s, "H", "ln_P")]["min_coupon_coverage"],
            **{f"{q}_{t}": f"{by[(s, q, t)]['estimate']:.2f} [{by[(s, q, t)]['ci_lo']:.2f}, {by[(s, q, t)]['ci_hi']:.2f}]" for q in ("H", "W", "HW") for t in ("ln_P", "ln_v")},
        }
        for s in labels
    ]
    slcols = [
        ("s", "Operator", lambda r: r["source"]), ("cv", "Lowest coupon coverage", lambda r: f(r["min_coverage"], 2)),
        ("hp", "ln H on ln P", lambda r: r["H_ln_P"]), ("hv", "ln H on ln v", lambda r: r["H_ln_v"]),
        ("wp", "ln W on ln P", lambda r: r["W_ln_P"]), ("wv", "ln W on ln v", lambda r: r["W_ln_v"]),
        ("rp", "ln H/W on ln P", lambda r: r["HW_ln_P"]), ("rv", "ln H/W on ln v", lambda r: r["HW_ln_v"]),
    ]
    scale = [{"quantity": a, "depends_on_8_um_per_px": b, "why": c} for a, b, c in SCALE_ROWS]
    sccols = [("q", "Quantity", lambda r: r["quantity"]), ("d", "Depends on the 8 µm/px scale", lambda r: r["depends_on_8_um_per_px"]), ("w", "Why", lambda r: r["why"])]
    check = ops["check"]
    liquid = [r["shape_ratio"] for r in ops["operators"] if r["operator"] == "liquidus"]
    synth = [r["shape_ratio"] for r in ops["operators"] if r["operator"] != "liquidus"]
    oow_cov = [r["coverage"] for r in ops["operators"] if r["operator"] != "liquidus" and r["group"].startswith("out_of_window")]
    width_values = [v for r in ops["width"] for v in (r.get("median_of_coupon_H_ratio"), r.get("median_of_coupon_H_ratio_min"), r.get("median_of_coupon_H_ratio_max")) if v is not None]
    th = {r["threshold"]: r for r in ops["thresholds"]}
    hw_values = [r["median_HW"] for r in ops["thresholds"]]
    low_cov = min(r["min_coupon_coverage"] for r in ops["slopes"] if r["source"] == "lam850_uniform_sig0.0")
    notes = [
        "Different operators measure different boundaries: the liquidus contour of the laser-associated melt, a rendered brightness threshold, the camera's threshold-150 blob. Agreement under one operator is not agreement under another (A12, A24).",
        f"Synthetic camera (reading S, S_DESCRIPTIVE): T150 = 1950 K was fixed on the 9 calibration coupons (closest H/W shape at threshold 150) and then held for all coupons. Its group e_H, e_W and J were recomputed here from `synthetic_frames.csv.gz` and equal the synthetic manifest ({check['values_checked']} values, largest difference {check['max_abs_difference']:.1e}). Coverage counts frames where both the synthetic and the re-measured camera blob exist.",
        f"The synthetic camera reproduces the camera's shape (shape ratio {min(synth):.2f}–{max(synth):.2f}, against {min(liquid):.2f}–{max(liquid):.2f} for the liquidus) but not its size, and its coverage falls to {100 * min(oow_cov):.0f}–{100 * max(oow_cov):.0f} % out of window (no blob above the fixed T150 at low VED): no fixed synthetic operator follows the camera across VED (A27).",
        f"Width-matched isotherm (Patch 22.3.8, readings R-b and Q-b): with the model contour chosen per frame to match the camera's W, the model's H is still {min(width_values):.2f}–{max(width_values):.2f} times the camera's (median over coupons) for every frozen design candidate; c1 itself was not evaluated with this operator.",
        f"The camera's own threshold family: from threshold 30 to 250 the camera H falls by a factor of {th[30]['median_H_px'] / th[250]['median_H_px']:.2f} and W by {th[30]['median_W_px'] / th[250]['median_W_px']:.2f}, while its H/W stays within {min(hw_values):.2f}–{max(hw_values):.2f}: the camera's size is operator-dependent, its shape much less so.",
        f"Slopes: least squares of ln coupon medians on [1, ln P, ln v], 24 coupons, 95 % coupon bootstrap (family 8; all operators share the draws). Synthetic slopes rest on low coverage at low VED (lowest coupon {100 * low_cov:.0f} % at PSF 0) and are descriptive only.",
        "Sources: `data/T14_operator_groups.csv`, `T14_width_matched.csv`, `T14_camera_threshold_family.csv`, `T14_operator_slopes.csv`, `T14_synthetic_status_by_coupon.csv`.",
    ]
    return write_table(
        "T14_measurement_operators", "Measurement operators",
        ["The same frames under different measurement operators, and which conclusions depend on the unvalidated 8 µm/px scale."],
        [("A. Operators by group", ops["operators"], gcols), ("B. Width-matched model isotherm (Patch 22.3.8; frozen design candidates)", ops["width"], wcols),
         ("C. The camera's own threshold family (16 A8 calibration members, layer 53)", ops["thresholds"], tcols), ("D. Process slopes by operator (24 coupons)", slope_rows, slcols),
         ("E. Scale dependence", scale, sccols)],
        notes,
        [{"section": "operators", **r} for r in ops["operators"]] + [{"section": "width_matched", **r} for r in ops["width"]] + [{"section": "threshold_family", **r} for r in ops["thresholds"]] + [{"section": "slopes", **r} for r in ops["slopes"]] + [{"section": "scale", **r} for r in scale],
    )


# ---------------------------------------------------------------------- T15


def t15(sens: Mapping[str, Any]) -> list:
    ocols = [
        ("o", "Objective", lambda r: r["label"]), ("w", "Winner", lambda r: r["winner"]),
        ("c", "Winner (t, ck, η)", lambda r: f"({r['winner_t']:.2f}, {r['winner_ck']:.3f}, {r['winner_eta']:.2f})"),
        ("r", "Rank of c1 / c2", lambda r: f"{r['c1_rank']} / {r['c2_rank']} of {r['candidates']}"), ("s", "ρ with the J ranking", lambda r: f"{r['spearman_with_J_ranking']:.2f}"),
    ]
    ncols = [
        ("c", "Candidate", lambda r: r["candidate"]), ("j", "Calibration J (e_H, e_W)", lambda r: f"{r['calibration_J']:.3f} ({r['calibration_e_H']:.3f}, {r['calibration_e_W']:.3f})"),
        ("h", "Held-out e_H, e_W", lambda r: f"{r['held_out_e_H']:.3f}, {r['held_out_e_W']:.3f}"), ("v", "V ratios H, W (reading)", lambda r: f"{r['v_ratio_H']:.3f}, {r['v_ratio_W']:.3f} ({r['v_reading']})"),
        ("p", "part_5 ratios H, W", lambda r: f"{r['part_5_ratio_H']:.3f}, {r['part_5_ratio_W']:.3f}"),
        ("o", "Out of window e_H, e_W", lambda r: f"{r['out_of_window_e_H']:.3f}, {r['out_of_window_e_W']:.3f}"),
        ("x", "ρ(VED, median r) H, W", lambda r: f"{r['spearman_ved_median_r_H']:.2f}, {r['spearman_ved_median_r_W']:.2f}"),
        ("b", "Peak > 3133 K (calibration)", lambda r: pct(r["calibration_peak_above_boiling"])),
    ]
    mcols = [
        ("g", "Group", lambda r: r["label"]), ("q", "Q", lambda r: r["quantity"]), ("m", "Median, pooled frames (package)", lambda r: f(r["median_ratio_pooled_frames"], 3)),
        ("gh", "Geometric mean, hierarchical", lambda r: f(r["geometric_mean_hierarchical"], 3)), ("gp", "Geometric mean, pooled", lambda r: f(r["geometric_mean_pooled_frames"], 3)),
        ("a", "Arithmetic mean, pooled", lambda r: f(r["arithmetic_mean_pooled_frames"], 3)), ("mc", "Median of coupon medians", lambda r: f(r["median_of_coupon_medians"], 3)),
    ]
    variants = sens["variants"]
    vcols = [
        ("g", "Group", lambda r: r["label"]), ("v", "Variant", lambda r: r["variant"]),
        ("eh", "e_H", lambda r: f(r["e_H"])), ("ew", "e_W", lambda r: f(r["e_W"])), ("j", "J", lambda r: f(r["J"])),
        ("n", "Frames / tracks / coupons", lambda r: f"{r['frames']:,} / {r['tracks']:,} / {r['coupons']}"),
    ]
    lcols = [
        ("g", "Group", lambda r: r["label"]), ("s", "Statistic", lambda r: r["statistic"]), ("f", "All coupons", lambda r: f(r["full"])),
        ("lo", "Lowest (dropping)", lambda r: f"{r['min']:.3f} ({r['min_when_dropping']})"), ("hi", "Highest (dropping)", lambda r: f"{r['max']:.3f} ({r['max_when_dropping']})"),
    ]
    tcols = [
        ("t", "Camera threshold", lambda r: ("**150**" if r["reference"] else str(r["threshold"]))), ("r", "Coupons", lambda r: r["label"]),
        ("h", "Model/camera H (median of coupon ratios)", lambda r: f(r["median_H_ratio_of_coupon_medians"], 2)), ("w", "W", lambda r: f(r["median_W_ratio_of_coupon_medians"], 2)),
        ("s", "Shape ratio", lambda r: f(r["median_shape_ratio"], 2)),
    ]
    sections = [
        ("A. Objective choice (19 calibrated candidates, recorded scores)", sens["objectives"], ocols),
        ("B. Selected versus near-best", sens["near_best"], ncols),
        ("C. Summary statistic of the model/camera ratio", sens["summary"], mcols),
        ("D. Weighting", [r for r in variants if r["section"] == "D_weighting"], vcols),
        ("E. Pixel floor and no-pool frames", [r for r in variants if r["section"] == "E_floor"], vcols),
        ("F. Short tracks", [r for r in variants if r["section"] == "F_short_tracks"], vcols),
        ("G. Leave one coupon out", [r for r in variants if r["section"] == "G_leave_one_coupon_out"], lcols),
        ("H. Camera threshold (coupon medians; 9 calibration and 7 examined coupons)", sens["thresholds"], tcols),
    ]
    selects_c1 = [r["label"] for r in sens["objectives"] if r["winner"] == C.CANDIDATE]
    others = [r for r in sens["objectives"] if r["winner"] != C.CANDIDATE]
    summ = sens["summary"]
    h_vals = [r[k] for r in summ if r["quantity"] == "H" for k in ("median_ratio_pooled_frames", "geometric_mean_hierarchical", "geometric_mean_pooled_frames", "arithmetic_mean_pooled_frames", "median_of_coupon_medians")]
    w_vals = [r[k] for r in summ if r["quantity"] == "W" for k in ("median_ratio_pooled_frames", "geometric_mean_hierarchical", "geometric_mean_pooled_frames", "arithmetic_mean_pooled_frames", "median_of_coupon_medians")]
    vby = {(r["section"], r["group"], r["variant"]): r for r in variants if r["section"] != "G_leave_one_coupon_out"}

    def delta(section: str, group: str, variant: str, key: str) -> float:
        base = next(r for (s, g, v), r in vby.items() if s == section and g == group and "contract" in v)
        return vby[(section, group, variant)][key] - base[key]

    tw = max(abs(delta("D_weighting", g, v, k)) for g in ("calibration", "in_window_held_out", "out_of_window_all") for v in ("every track equal", "every coupon equal") for k in ("e_H", "e_W"))
    nopool_in = delta("E_floor", "calibration", "no-pool frames left out (floor 1 px)", "e_W")
    nopool_out = delta("E_floor", "out_of_window_all", "no-pool frames left out (floor 1 px)", "e_W")
    short = min(delta("F_short_tracks", g, v, k) for g in ("calibration", "in_window_held_out", "out_of_window_all") for v in ("tracks with >= 10 scored frames", "tracks with >= 20 scored frames") for k in ("e_H", "e_W"))
    loo = {(r["group"], r["statistic"]): r for r in variants if r["section"] == "G_leave_one_coupon_out"}
    cal_j = loo[("calibration", "J")]
    held_j = loo[("in_window_held_out", "J")]
    shapes = [r["median_shape_ratio"] for r in sens["thresholds"]]
    near = {r["candidate"]: r for r in sens["near_best"]}
    notes = [
        "Descriptive checks on the frozen records, not new searches: no candidate was run or re-selected. A, B and H use recorded candidate scores and committed 22.3.8 camera measurements; C-G re-aggregate the c1 frames.",
        f"A. {len(selects_c1)} of {len(sens['objectives'])} objectives select c1: " + "; ".join(selects_c1) + ". " + " ".join(f"The {r['label'][0].lower() + r['label'][1:]} would select {r['winner']} and rank c1 {r['c1_rank']} of {r['candidates']}." for r in others) + " The selection is driven by H, the quantity the model cannot match (A27).",
        f"B. c2, the other near-best point, gives the same reading ({near['confirm_c2']['v_reading']}) with V and part_5 ratios within {max(abs(near['confirm_c2'][k] - near['confirm_c1'][k]) for k in ('v_ratio_H', 'v_ratio_W', 'part_5_ratio_H', 'part_5_ratio_W')):.3f} of c1's, "
        + ("the same rank correlations with VED" if max(abs(near['confirm_c2'][k] - near['confirm_c1'][k]) for k in ('spearman_ved_median_r_H', 'spearman_ved_median_r_W')) < 5e-4 else "similar rank correlations with VED")
        + f", and calibration J {near['confirm_c2']['calibration_J']:.3f} against {near['confirm_c1']['calibration_J']:.3f}. The conclusions do not hinge on the choice between them.",
        f"C. Across these summaries the model's H is {min(h_vals):.2f}–{max(h_vals):.2f} times the camera's and its W {min(w_vals):.2f}–{max(w_vals):.2f} times; the package reports the pooled-frame median, as the manifests do.",
        f"D. Weighting every frame equally changes e by up to {max(abs(delta('D_weighting', g, 'every frame equal', k)) for g in ('calibration', 'in_window_held_out', 'out_of_window_all') for k in ('e_H', 'e_W')):.2f} (large coupons dominate); weighting every track or every coupon equally stays within {tw:.3f} of the contract.",
        f"E. The 1 px floor matters only through the no-pool frames: leaving them out changes e_W by {nopool_in:+.2f} for calibration and {nopool_out:+.2f} out of window; a 0.5 or 2 px floor moves e in opposite directions by similar amounts. F. Keeping only tracks with at least 10 or 20 scored frames lowers e by up to {abs(short):.2f}.",
        f"G. Dropping any one calibration coupon moves J within {cal_j['min']:.3f}–{cal_j['max']:.3f} (full {cal_j['full']:.3f}); the held-out J ranges from {held_j['min']:.3f} (without {held_j['min_when_dropping']}) to {held_j['max']:.3f} (without {held_j['max_when_dropping']}), full {held_j['full']:.3f}.",
        f"H. With the camera thresholded lower its blob grows and the model's H ratio falls; the shape ratio stays within {min(shapes):.2f}–{max(shapes):.2f} at every threshold from 30 to 250, so no camera threshold reconciles the model's elongation (22.3.8 reading R-b).",
        "Sources: `data/T15_*.csv`.",
    ]
    flat = [{"section": "A_objective", **r} for r in sens["objectives"]] + [{"section": "B_near_best", **r} for r in sens["near_best"]] + [{"section": "C_summary", **r} for r in sens["summary"]] + list(variants) + [{"section": "H_threshold", **r} for r in sens["thresholds"]]
    return write_table("T15_sensitivity", "Sensitivity and robustness", ["How the reported errors and the selection respond to each analysis choice."], sections, notes, flat)


# ---------------------------------------------------------------------- T16


def t16(stage_rows: Sequence[Mapping[str, Any]], consistency: Mapping[str, Any], package: Mapping[str, Any]) -> list:
    cols = [
        ("s", "Stage", lambda r: r["stage"]), ("sc", "Scope", lambda r: r["scope"]),
        ("c", "Code commit (date)", lambda r: f"`{r['git_commit'][:7]}` {r['commit_date'][:10]}"), ("e", "Evidence committed", lambda r: f"`{r['evidence_committed_in']}` {r['evidence_commit_date'][:10]}"),
        ("d", "Clean tree", lambda r: "–" if r["worktree_dirty"] is None else f(not r["worktree_dirty"])),
        ("v", "Policy / semantics / rule / objective", lambda r: " / ".join(str(r[k] or "–") for k in ("association_policy_version", "hw_semantics_version", "scored_frame_rule_version", "objective_contract_version"))),
        ("w", "Workers", lambda r: "–" if r["workers"] is None else f"{r['workers']} ({r['start_method']})"),
        ("u", "Units run / reused", lambda r: "–" if r["units_run"] is None else f"{r['units_run']} / {r['units_reused'] if r['units_reused'] is not None else '–'}"),
        ("t", "Wall time", lambda r: "–" if r["wall_time_s"] is None else f"{r['wall_time_s'] / 3600:.2f} h"),
        ("rt", "Python / numpy", lambda r: "–" if r["python"] is None else f"{r['python']} / {r['numpy']}"),
        ("h", "Held-out coupons read", lambda r: "–" if r["held_out_members_read"] is None else str(r["held_out_members_read"])),
        ("f", "Fitting or selection", lambda r: r["fitting_or_selection"]),
        ("m", "Manifest sha256", lambda r: f"`{r['manifest_sha256'][:12]}`"),
    ]
    pkg = [{"item": k, "value": v} for k, v in package.items()]
    pcols = [("i", "Item", lambda r: r["item"]), ("v", "Value", lambda r: r["value"])]
    notes = [
        "Each stage's manifest records its code commit, a clean working tree, the semantic versions, the worker count and start method (4 spawn workers for every multi-unit stage, A19; the one-unit smoke gate ran serially), the runtime and the held-out members it read. No stage dispatched the 272-unit campaign, changed production semantics or lifted the dispatch lock.",
        "Held-out access: none of the 8 A8 held-out coupons was read before the freeze (smoke, calibrate, confirm, freeze: 0); the evaluate stage read all 8 after the committed freeze, and reading S rendered them afterwards at the T150 fixed on calibration coupons.",
        f"Fixed controls identical in every stage manifest: {'yes' if consistency['all_constant'] else 'NO'} ({', '.join(k for k in consistency if k != 'all_constant')}).",
        "Test status: each patch stage was gated on the full test suite (implementation report); the package's own checks are in `tests/test_committee_package.py`, and the suite result at the package commit is in the README. The build itself never runs tests, so this table stays byte-identical between builds.",
        "Run-specific facts (build time, git head, runtime, input hashes) are in `PROVENANCE.json`; output hashes in `OUTPUT_SHA256SUMS.txt`.",
    ]
    return write_table(
        "T16_provenance", "Provenance", ["Where every number in the package comes from: the Patch 22.4.3.2 stages and this package."],
        [("Patch 22.4.3.2 stages", stage_rows, cols), ("This package", pkg, pcols)], notes, [{"section": "stage", **r} for r in stage_rows] + [{"section": "package", **r} for r in pkg],
    )


# ---------------------------------------------------------------------- T19


def t19(sync_result: Mapping[str, Any]) -> list:
    rows = sync_result["rows"]
    cols = [
        ("m", "Coupon", lambda r: r["member"]), ("r", "Role", lambda r: ROLE_SHORT[r["role"]]), ("c", "Campaign", lambda r: r["campaign"]),
        ("raw", "Raw (layer)", lambda r: f(r["raw_camera_frames_layer"])), ("map", "Sync-mapped", lambda r: f(r["sync_mapped_frames"])),
        ("on", "Laser-on", lambda r: f(r["laser_on_mapped_frames"])), ("el", "Eligible", lambda r: f(r["eligible_frames"])),
        ("tr", "Tracks", lambda r: r["tracks_with_eligible_frames"]),
        ("fs", "First frame at track start", lambda r: pct(r["first_maps_to_track_start_fraction"], 0)),
        ("ra", "Rising-edge anchor (first)", lambda r: pct(r["first_frame_rising_edge_anchor_fraction"], 0)),
        ("fa", "Falling-edge anchor (last)", lambda r: pct(r["last_frame_falling_edge_anchor_fraction"], 0)),
        ("rs", "Rows after start / before end (median)", lambda r: f"{r['median_rows_after_track_start']:.0f} / {r['median_rows_before_track_end']:.0f}"),
        ("st", "Single / short (< 4) tracks", lambda r: f"{r['single_frame_tracks']} / {r['short_tracks_lt_4_frames']}"),
        ("mb", "Row maps back to frame", lambda r: pct(r["row_maps_back_to_frame_fraction"])),
    ]
    check = sync_result["check"]
    methods = {(r["sync_method"], r["sync_version"]) for r in rows}
    clean = all(r["timestamps_strictly_increasing"] and r["out_of_range_mapped_frames"] == 0 and r["repeated_mapped_rows"] == 0 for r in rows)
    sep = [r for r in rows if r["campaign"] == "September"]
    jul = [r for r in rows if r["campaign"] == "July"]
    back = [r["row_maps_back_to_frame_fraction"] for r in rows]
    notes = [
        f"Sync method: {'; '.join(f'{m} (version {v})' for m, v in sorted(methods))}, the same for all 24 coupons. Timestamps strictly increasing and no out-of-range or repeated mapped rows in every coupon: {f(clean)}.",
        "Raw frames are the whole layer's camera stream shared by a set's six coupons; sync-mapped are those mapped to this coupon's process rows.",
        f"Anchor convention (ledger O11): in July the first eligible frame of a track maps to the track's first powered row ({span([100 * r['first_maps_to_track_start_fraction'] for r in jul], '{:.0f}')} % of tracks), on the rising-edge anchor; in September the first frame maps a median {span([r['median_rows_after_track_start'] for r in sep], '{:.0f}')} rows after the start and the last frame {span([r['median_rows_before_track_end'] for r in sep], '{:.0f}')} rows before the end, on the falling-edge anchor. The convention is campaign-wide and confounded with acquisition day (confound table).",
        f"The track-start and track-end mapping was recomputed here from the characterization files for all 24 coupons; for the {check['members_checked_against_22_3_6']} A8 calibration members it equals the Patch 22.3.6 audit ({check['values_checked']} values). The 8 held-out coupons were not in that audit (it read calibration members only), so their anchor fractions are not available; their start and end mapping follows their campaign.",
        f"Row maps back to frame: share of scored frames whose mapped process row maps back to the same camera frame (22.4.3.2 reading S): {100 * min(back):.1f}–{100 * max(back):.1f} %.",
    ]
    return write_table("T19_synchronization", "Synchronization quality", ["How each coupon's camera frames were tied to its process rows."], [(None, rows, cols)], notes, rows)
