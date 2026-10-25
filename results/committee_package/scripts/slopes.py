"""T11 and the F6 trend: process-response slopes of camera and model H, W and H/W, and model/camera ratio vs VED.

Pattern of ``member_trend`` (``src/lpbf/camera_observations.py``): least squares of the log of coupon medians on
[1, ln P, ln v] (and on [1, ln VED]), with a coupon-resampling percentile bootstrap. Draws whose design loses rank are
skipped and counted. Camera and model share the same draws, so model - camera differences are paired.

Medians per coupon: camera over all scored frames; model over scored frames with a predicted pool (the results
report's convention; frames without a pool have no size).
"""
from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

import numpy as np

import common as C
from bootstrap import save_npz

FAMILY_SLOPES = 3
FAMILY_TREND = 4
QUANTITIES = (("H", "H_px"), ("W", "W_px"), ("HW", "HW"))
TREND_GRID = np.linspace(40.0, 130.0, 91)


def subsets(record: Mapping[str, Mapping[str, Any]]) -> dict[str, tuple[str, ...]]:
    members = tuple(sorted(C.ROLE, key=C.member_key))
    a8_cal = tuple(m for m in members if m not in C.A8_HELD_OUT)
    return {
        "all_24": members,
        "a8_calibration_16": a8_cal,
        "in_window_14": tuple(m for m in members if C.ROLE[m] in ("calibration", "in_window_held_out")),
        "out_of_window_10": tuple(m for m in members if C.ROLE[m].startswith("out_of_window")),
        "all_but_20260904_part_3": tuple(m for m in members if m != "20260904:part_3"),
    }


def _responses(coupons: Mapping[str, Mapping[str, Any]], members: Sequence[str]) -> dict[tuple[str, str], np.ndarray]:
    out = {}
    for q, key in QUANTITIES:
        out[("camera", q)] = np.log([coupons[m][f"cam_{key}_median"] for m in members])
        out[("model", q)] = np.log([coupons[m][f"sim_{key}_median_pool"] for m in members])
    return out


def _fit(design: np.ndarray, ys: np.ndarray) -> np.ndarray:
    return np.linalg.lstsq(design, ys, rcond=None)[0]


def fit_subset(name: str, index: int, members: Sequence[str], coupons, record, replicates: int) -> tuple[list[dict[str, Any]], dict[str, np.ndarray]]:
    lp = np.log([record[m]["power_W"] for m in members])
    lv = np.log([record[m]["speed_mm_s"] for m in members])
    le = np.log([record[m]["ved_J_mm3"] for m in members])
    responses = _responses(coupons, members)
    keys = list(responses)
    ys = np.column_stack([responses[k] for k in keys])
    designs = {"P_v": (np.column_stack([np.ones_like(lp), lp, lv]), ("ln_P", "ln_v")), "VED": (np.column_stack([np.ones_like(le), le]), ("ln_VED",))}
    generator = C.rng(FAMILY_SLOPES, index)
    picks = generator.integers(0, len(members), size=(replicates, len(members)))
    rows, arrays = [], {}
    for dname, (design, terms) in designs.items():
        rank = np.linalg.matrix_rank(design)
        point = _fit(design, ys) if rank == design.shape[1] else np.full((design.shape[1], ys.shape[1]), np.nan)
        draws = np.full((replicates, design.shape[1], ys.shape[1]), np.nan)
        for r, pick in enumerate(picks):
            sample = design[pick]
            if np.linalg.matrix_rank(sample) == design.shape[1]:
                draws[r] = _fit(sample, ys[pick])
        used = int(np.isfinite(draws[:, 0, 0]).sum())
        cond = float(np.linalg.cond(design[:, 1:] - design[:, 1:].mean(axis=0))) if design.shape[1] > 2 else 1.0
        for t, term in enumerate(terms, start=1):
            for k, (source, q) in enumerate(keys):
                lo, hi = C.percentile_ci(draws[:, t, k])
                rows.append(_row(name, members, dname, term, source, q, point[t, k], lo, hi, used, cond, replicates))
                arrays[f"{name}__{dname}__{term}__{source}_{q}"] = draws[:, t, k]
            for q, _ in QUANTITIES:
                km, kc = keys.index(("model", q)), keys.index(("camera", q))
                diff = draws[:, t, km] - draws[:, t, kc]
                lo, hi = C.percentile_ci(diff)
                rows.append(_row(name, members, dname, term, "model_minus_camera", q, point[t, km] - point[t, kc], lo, hi, used, cond, replicates))
    return rows, arrays


def _row(subset, members, design, term, source, q, estimate, lo, hi, used, cond, replicates) -> dict[str, Any]:
    reference = {"H": {"ln_P": 1.0, "ln_v": 0.0}, "W": {"ln_P": 0.5, "ln_v": -0.5}, "HW": {"ln_P": 0.5, "ln_v": 0.5}}
    return {
        "subset": subset, "coupons": len(members), "design": design, "term": term, "source": source, "quantity": q,
        "estimate": float(estimate), "ci_lo": float(lo), "ci_hi": float(hi), "ci_excludes_zero": bool(lo > 0 or hi < 0),
        "rosenthal_reference": reference[q].get(term) if source != "model_minus_camera" else None,
        "bootstrap_replicates": replicates, "replicates_used": used, "centred_design_condition_number": cond,
        "resampling_unit": "coupon", "seed": C.SEED, "generator_keys": None,
    }


def ratio_trend(coupons, record, replicates: int) -> tuple[list[dict[str, Any]], dict[str, np.ndarray], list[dict[str, Any]]]:
    """Coupon median log ratio (model/camera, all scored frames) on [1, ln VED] over all 24 coupons, with a band."""

    members = sorted(C.ROLE, key=C.member_key)
    le = np.log([record[m]["ved_J_mm3"] for m in members])
    design = np.column_stack([np.ones_like(le), le])
    grid = np.column_stack([np.ones_like(TREND_GRID), np.log(TREND_GRID)])
    picks = C.rng(FAMILY_TREND, 0).integers(0, len(members), size=(replicates, len(members)))
    rows, arrays, band = [], {}, []
    for q in ("H", "W"):
        y = np.array([coupons[m][f"median_r_{q}"] for m in members])
        beta = _fit(design, y)
        draws = np.array([_fit(design[p], y[p]) if np.ptp(le[p]) > 0 else (np.nan, np.nan) for p in picks])
        curve = draws @ grid.T
        lo, hi = C.percentile_ci(curve)
        for v, c, l, h in zip(TREND_GRID, grid @ beta, lo, hi):
            band.append({"quantity": q, "ved_J_mm3": float(v), "fit_ratio": math.exp(c), "ci_lo_ratio": math.exp(l), "ci_hi_ratio": math.exp(h)})
        slo, shi = C.percentile_ci(draws[:, 1])
        rows.append(
            {
                "quantity": q, "intercept": float(beta[0]), "slope_ln_VED": float(beta[1]), "slope_ci_lo": float(slo), "slope_ci_hi": float(shi),
                "coupons": len(members), "bootstrap_replicates": replicates, "replicates_used": int(np.isfinite(draws[:, 1]).sum()),
                "seed": C.SEED, "generator_keys": f"[{C.SEED}, {FAMILY_TREND}, 0]",
            }
        )
        arrays[f"ratio_trend__{q}__intercept"] = draws[:, 0]
        arrays[f"ratio_trend__{q}__slope_ln_VED"] = draws[:, 1]
    return rows, arrays, band


def step0_check(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Camera slopes on the 16 A8 calibration members against the committed 22.3.8 Step-0 trends."""

    step0 = C.load_json(C.STEP0_TRENDS)
    out = {}
    for q, key in (("H", "log_H"), ("W", "log_W"), ("HW", "log_HW")):
        for term, field in (("ln_P", "slope_log_power"), ("ln_v", "slope_log_speed")):
            mine = next(r for r in rows if r["subset"] == "a8_calibration_16" and r["design"] == "P_v" and r["term"] == term and r["source"] == "camera" and r["quantity"] == q)
            ref = step0[key]
            out[f"{q}_{term}"] = {
                "package": mine["estimate"], "step0": ref[field], "difference": mine["estimate"] - ref[field],
                "package_ci": [mine["ci_lo"], mine["ci_hi"]], "step0_ci": ref[f"{field}_ci95"],
            }
    out["max_abs_difference"] = max(abs(v["difference"]) for v in out.values())
    out["note"] = "Step 0 measured the camera images itself (threshold 150) on the same scored frames; the package uses the supplied H/W."
    return out


def run(analysis: Mapping[str, Any], replicates: int = C.BOOTSTRAP_REPLICATES) -> dict[str, Any]:
    coupons, record = analysis["coupons"], analysis["record"]
    rows, arrays = [], {}
    for index, (name, members) in enumerate(subsets(record).items()):
        r, a = fit_subset(name, index, members, coupons, record, replicates)
        for row in r:
            row["generator_keys"] = f"[{C.SEED}, {FAMILY_SLOPES}, {index}]"
        rows.extend(r)
        arrays.update(a)
    trend_rows, trend_arrays, band = ratio_trend(coupons, record, replicates)
    arrays.update(trend_arrays)
    paths = {
        "slopes": C.write_csv(C.DATA_DIR / "T11_process_slopes.csv", rows),
        "trend": C.write_csv(C.DATA_DIR / "ratio_vs_ved_trend.csv", trend_rows),
        "band": C.write_csv(C.DATA_DIR / "ratio_vs_ved_band.csv", band),
        "draws": save_npz(C.DATA_DIR / "bootstrap" / "D5_slopes_bootstrap.npz", arrays),
    }
    return {"rows": rows, "trend": trend_rows, "band": band, "step0_check": step0_check(rows), "paths": paths}
