"""T14: measurement-operator comparison (camera threshold 150, model liquidus, synthetic camera, width-matched isotherm).

Every comparison in the package pairs two different boundaries (A12, A24). This module sets the operators side by
side from committed records only:
- liquidus: the c1 production H/W against the supplied camera H/W (the objective's pairing);
- synthetic camera: the Patch 22.4.3.2 reading-S render of the c1 fields at the fixed T150 = 1950 K (850 nm, uniform
  emissivity, PSF sigma 0 and 2 px), against the camera re-measured at threshold 150 on the same frames. The
  hierarchy is recomputed from ``synthetic_frames.csv.gz`` and checked against the synthetic stage manifest;
- width-matched isotherm (Patch 22.3.8 Steps 3-4): per frame, the highest model isotherm whose W reaches the
  camera's W; model H there / camera H. Evaluated for the frozen design candidates, not for c1;
- the camera's own threshold family (22.3.8 Step 0, the 16 A8 calibration members, thresholds 30-250).
Slopes for each operator use the T11 method (coupon medians, [1, ln P, ln v], coupon bootstrap, family 8, shared
draws across operators).
"""
from __future__ import annotations

import math
from statistics import median
from typing import Any, Mapping, Sequence

import numpy as np

import common as C
from bootstrap import save_npz

FAMILY_OPERATOR_SLOPES = 8
SYNTHETIC_CASES = {"lam850_uniform_sig0.0": "Synthetic camera, PSF 0 px", "lam850_uniform_sig2.0": "Synthetic camera, PSF 2 px"}
GROUPS = ("calibration", "in_window_held_out", "cross_campaign_20260904_part_5", "out_of_window_examined", "out_of_window_blind", "out_of_window_all")
C1_CODED = (-1.0, 0.8354817708333329, -1.0)


def synthetic_frames(analysis: Mapping[str, Any]) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, dict[str, int]]]]:
    """PAIRED frames per case (prediction = synthetic H/W, observation = camera re-measured at 150) and status counts."""

    record = analysis["record"]
    frames: dict[str, list[dict[str, Any]]] = {case: [] for case in SYNTHETIC_CASES}
    status: dict[str, dict[str, dict[str, int]]] = {case: {} for case in SYNTHETIC_CASES}
    for row in C.read_csv(C.SYNTHETIC_FRAMES):
        case, member = row["case_id"], row["member_identity"]
        counts = status[case].setdefault(member, {})
        counts[row["synthetic_status"]] = counts.get(row["synthetic_status"], 0) + 1
        if row["synthetic_status"] != "PAIRED":
            continue
        sim_h, sim_w = float(row["simulated_H_pixels"]), float(row["simulated_W_pixels"])
        cam_h, cam_w = float(row["experimental_H_pixels"]), float(row["experimental_W_pixels"])
        frames[case].append(
            {
                "member": member, "scan_track_id": int(row["scan_track_id"]), "frame_index": int(row["frame_index"]),
                "condition": record[member]["condition"], "sim_H_px": sim_h, "sim_W_px": sim_w, "cam_H_px": cam_h, "cam_W_px": cam_w,
                "r_H": C.log_ratio(sim_h, cam_h), "r_W": C.log_ratio(sim_w, cam_w),
            }
        )
    for case, by_member in status.items():
        for member, counts in by_member.items():
            if sum(counts.values()) != analysis["coupons"][member]["scored_frames"]:
                raise RuntimeError(f"{case} {member}: synthetic rows do not cover the scored frames")
    return frames, status


def verify_synthetic(analysis: Mapping[str, Any], frames: Mapping[str, Sequence[Mapping[str, Any]]]) -> dict[str, Any]:
    manifest = C.load_json(C.SYNTHETIC_MANIFEST)
    groups = C.group_members()
    worst, checked = 0.0, 0
    for case in SYNTHETIC_CASES:
        ref_case = manifest["cases"][case]
        for name, ref in ref_case["groups"].items():
            mine = C.contract_errors([f for f in frames[case] if f["member"] in set(groups[name])])
            for key in ("e_H", "e_W", "J"):
                worst = max(worst, abs(mine[key] - ref[key]))
                checked += 1
            if mine["frames"] != ref["scored_frame_count"]:
                raise RuntimeError(f"{case} {name}: PAIRED frames {mine['frames']} != manifest {ref['scored_frame_count']}")
            for cond in ref["condition_rows"]:
                pooled = [math.exp(f["r_H"]) for f in frames[case] if f["condition"] == cond["exact_condition_id"] and f["member"] in set(groups[name])]
                worst = max(worst, abs(float(median(pooled)) - cond["median_H_ratio"]))
                checked += 1
        for member, ref in ref_case["per_coupon"].items():
            mine = C.contract_errors([f for f in frames[case] if f["member"] == member])
            worst = max(worst, abs(mine["e_H"] - ref["e_H"]), abs(mine["e_W"] - ref["e_W"]))
            checked += 2
    if worst > 1e-12:
        raise RuntimeError(f"synthetic recomputation differs from the synthetic manifest by {worst}")
    return {"synthetic_manifest_sha256": C.sha256_file(C.SYNTHETIC_MANIFEST), "values_checked": checked, "max_abs_difference": worst, "status": "PASS"}


def _pooled(frames: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    return {
        "median_H_ratio": float(median(math.exp(f["r_H"]) for f in frames)),
        "median_W_ratio": float(median(math.exp(f["r_W"]) for f in frames)),
        "model_HW_median": float(median(f["sim_H_px"] / f["sim_W_px"] for f in frames if f["sim_W_px"] > 0)),
        "camera_HW_median": float(median(f["cam_H_px"] / f["cam_W_px"] for f in frames)),
    }


def operator_rows(analysis: Mapping[str, Any], synth: Mapping[str, Sequence[Mapping[str, Any]]]) -> list[dict[str, Any]]:
    groups = C.group_members()
    rows = []
    for name in GROUPS:
        members = set(groups[name])
        scored = sum(analysis["coupons"][m]["scored_frames"] for m in members)
        g = analysis["groups"][name]
        liquid_pool = [f for f in analysis["scored"] if f["member"] in members and not f["no_pool"]]
        rows.append(
            {
                "group": name, "label": C.GROUP_LABEL[name], "operator": "liquidus", "operator_label": "Model liquidus (production H/W)",
                "observation": "camera, supplied H/W (threshold 150)", "frames": g["scored_frames"], "coverage": g["scored_frames"] / scored,
                "median_H_ratio": g["median_H_ratio"], "median_W_ratio": g["median_W_ratio"],
                "model_HW_median": float(median(float(f["sim_H_px"]) / float(f["sim_W_px"]) for f in liquid_pool)),
                "camera_HW_median": g["cam_HW_median"], "e_H": g["e_H"], "e_W": g["e_W"], "J": g["J"],
            }
        )
        for case, label in SYNTHETIC_CASES.items():
            sub = [f for f in synth[case] if f["member"] in members]
            err = C.contract_errors(sub)
            rows.append(
                {
                    "group": name, "label": C.GROUP_LABEL[name], "operator": case, "operator_label": label + ", T150 1950 K",
                    "observation": "camera re-measured at threshold 150", "frames": len(sub), "coverage": len(sub) / scored,
                    **_pooled(sub), "e_H": err["e_H"], "e_W": err["e_W"], "J": err["J"],
                }
            )
    for r in rows:
        r["shape_ratio"] = r["model_HW_median"] / r["camera_HW_median"]
    return rows


def width_matched_rows() -> list[dict[str, Any]]:
    """Patch 22.3.8 Steps 3-4 width-matched H ratio (frozen design candidates; c1 was not evaluated)."""

    level_free = C.load_json(C.STEP3_LEVEL_FREE)
    rows = []

    def from_summary(item: Mapping[str, Any], scope: str, coupons: int) -> dict[str, Any]:
        counts = item["status_counts"]
        return {
            "candidate": item["candidate_id"], "scope": scope, "coupons": coupons, "frames": sum(counts.values()),
            "defined_share": counts.get("DEFINED", 0) / sum(counts.values()),
            "median_of_coupon_H_ratio": item["median_of_member_H_ratio"], "pooled_median_H_ratio": item["pooled_H_ratio_quantiles"]["50"],
            "pooled_H_ratio_p25": item["pooled_H_ratio_quantiles"]["25"], "pooled_H_ratio_p75": item["pooled_H_ratio_quantiles"]["75"],
            "median_level_K": item["pooled_level_K_quantiles"]["50"], "fraction_level_below_liquidus": item["fraction_level_below_liquidus"],
            "source": "22.3.8 step3_level_free.json",
        }

    rows.append(from_summary(level_free["primary"], "16 A8 calibration members", len(level_free["primary"]["members"])))
    for cid, item in level_free["corners"].items():
        rows.append(from_summary(item, "4 corner coupons (20260904 parts 1, 3, 4, 6)", len(item["members"])))
    step4 = C.read_csv(C.STEP4_CANDIDATES)
    half = (3.0, 0.5, 0.5)
    centre = (0.0, 2.0, 0.5)
    for r in step4:
        coded = [(float(r[k]) - c) / h for k, c, h in zip(("abs_depth_identifiable_coordinate", "liquid_conductivity_enhancement_factor", "eta_directional"), centre, half)]
        r["_distance"] = math.dist(coded, C1_CODED)
    nearest = min(step4, key=lambda r: r["_distance"])
    ratios = [float(r["L_median_member_H_ratio"]) for r in step4]
    rows.append(
        {
            "candidate": "17 frozen design candidates", "scope": "4 corner coupons", "coupons": 4,
            "median_of_coupon_H_ratio_min": min(ratios), "median_of_coupon_H_ratio_max": max(ratios),
            "candidates_in_band_0_87_1_15": sum(1 for x in ratios if 0.87 <= x <= 1.15), "source": "22.3.8 step4_candidates.csv (reading Q-b)",
        }
    )
    rows.append(
        {
            "candidate": nearest["candidate_id"], "scope": "4 corner coupons; nearest design candidate to c1", "coupons": 4,
            "median_of_coupon_H_ratio": float(nearest["L_median_member_H_ratio"]), "median_level_K": float(nearest["L_level_median_K"]),
            "coded_distance_to_c1": nearest["_distance"], "source": "22.3.8 step4_candidates.csv",
        }
    )
    return rows


def threshold_rows() -> list[dict[str, Any]]:
    """The camera's own threshold family (22.3.8 Step 0, layer 53, 16 A8 calibration members)."""

    family = [r for r in C.read_csv(C.STEP0_FAMILY) if r["layer"] == "layer53"]
    at150 = {r["member_identity"]: r for r in family if r["threshold"] == "150"}
    rows = []
    for t in sorted({int(r["threshold"]) for r in family}):
        sub = [r for r in family if int(r["threshold"]) == t]
        rows.append(
            {
                "threshold": t, "members": len(sub),
                "median_H_px": float(median(float(r["median_H_px"]) for r in sub)), "median_W_px": float(median(float(r["median_W_px"]) for r in sub)),
                "median_HW": float(median(float(r["median_HW"]) for r in sub)),
                "H_relative_to_150": float(median(float(r["median_H_px"]) / float(at150[r["member_identity"]]["median_H_px"]) for r in sub)),
                "W_relative_to_150": float(median(float(r["median_W_px"]) / float(at150[r["member_identity"]]["median_W_px"]) for r in sub)),
                "median_edge_touch_fraction": float(median(float(r["edge_touch_fraction"]) for r in sub)),
            }
        )
    return rows


def operator_slopes(analysis: Mapping[str, Any], synth: Mapping[str, Sequence[Mapping[str, Any]]], replicates: int) -> tuple[list[dict[str, Any]], dict[str, np.ndarray]]:
    record, coupons = analysis["record"], analysis["coupons"]
    members = sorted(C.ROLE, key=C.member_key)
    sources: dict[str, dict[str, np.ndarray]] = {
        "camera_supplied": {"H": [coupons[m]["cam_H_px_median"] for m in members], "W": [coupons[m]["cam_W_px_median"] for m in members], "HW": [coupons[m]["cam_HW_median"] for m in members]},
        "liquidus": {"H": [coupons[m]["sim_H_px_median_pool"] for m in members], "W": [coupons[m]["sim_W_px_median_pool"] for m in members], "HW": [coupons[m]["sim_HW_median_pool"] for m in members]},
    }
    coverage: dict[str, list[float]] = {}
    for case in SYNTHETIC_CASES:
        by: dict[str, list] = {}
        for f in synth[case]:
            by.setdefault(f["member"], []).append(f)
        sources[case] = {
            "H": [median(f["sim_H_px"] for f in by[m]) for m in members], "W": [median(f["sim_W_px"] for f in by[m]) for m in members],
            "HW": [median(f["sim_H_px"] / f["sim_W_px"] for f in by[m] if f["sim_W_px"] > 0) for m in members],  # zero-width blobs have no shape
        }
        coverage[case] = [len(by[m]) / coupons[m]["scored_frames"] for m in members]
        if case == "lam850_uniform_sig0.0":
            sources["camera_remeasured"] = {
                "H": [median(f["cam_H_px"] for f in by[m]) for m in members], "W": [median(f["cam_W_px"] for f in by[m]) for m in members],
                "HW": [median(f["cam_H_px"] / f["cam_W_px"] for f in by[m]) for m in members],
            }
    lp = np.log([record[m]["power_W"] for m in members])
    lv = np.log([record[m]["speed_mm_s"] for m in members])
    design = np.column_stack([np.ones_like(lp), lp, lv])
    picks = C.rng(FAMILY_OPERATOR_SLOPES, 0).integers(0, len(members), size=(replicates, len(members)))
    rows, arrays = [], {}
    for source, values in sources.items():
        for q in ("H", "W", "HW"):
            y = np.log(np.asarray(values[q], dtype=float))
            beta = np.linalg.lstsq(design, y, rcond=None)[0]
            draws = np.full((replicates, 3), np.nan)
            for r, pick in enumerate(picks):
                if np.linalg.matrix_rank(design[pick]) == 3:
                    draws[r] = np.linalg.lstsq(design[pick], y[pick], rcond=None)[0]
            for t, term in ((1, "ln_P"), (2, "ln_v")):
                lo, hi = C.percentile_ci(draws[:, t])
                rows.append(
                    {
                        "source": source, "quantity": q, "term": term, "estimate": float(beta[t]), "ci_lo": float(lo), "ci_hi": float(hi),
                        "coupons": len(members), "replicates_used": int(np.isfinite(draws[:, t]).sum()), "bootstrap_replicates": replicates,
                        "min_coupon_coverage": min(coverage[source]) if source in coverage else (min(coverage["lam850_uniform_sig0.0"]) if source == "camera_remeasured" else 1.0),
                        "generator_keys": f"[{C.SEED}, {FAMILY_OPERATOR_SLOPES}, 0]",
                    }
                )
                arrays[f"{source}__{q}__{term}"] = draws[:, t]
    return rows, arrays


def run(analysis: Mapping[str, Any], replicates: int = C.BOOTSTRAP_REPLICATES) -> dict[str, Any]:
    synth, status = synthetic_frames(analysis)
    check = verify_synthetic(analysis, synth)
    ops = operator_rows(analysis, synth)
    widths = width_matched_rows()
    thresholds = threshold_rows()
    slope_rows, arrays = operator_slopes(analysis, synth, replicates)
    status_rows = [
        {"case": case, "member": m, "role": C.ROLE[m], **counts}
        for case, by in status.items() for m, counts in sorted(by.items(), key=lambda item: C.member_key(item[0]))
    ]
    paths = {
        "operators": C.write_csv(C.DATA_DIR / "T14_operator_groups.csv", ops),
        "width": C.write_csv(C.DATA_DIR / "T14_width_matched.csv", widths),
        "thresholds": C.write_csv(C.DATA_DIR / "T14_camera_threshold_family.csv", thresholds),
        "slopes": C.write_csv(C.DATA_DIR / "T14_operator_slopes.csv", slope_rows),
        "status": C.write_csv(C.DATA_DIR / "T14_synthetic_status_by_coupon.csv", status_rows, ["case", "member", "role", "PAIRED", "SYNTHETIC_ABSENT", "SYNTHETIC_EDGE", "CAMERA_BLOB_150_ABSENT_OR_EDGE"]),
        "draws": save_npz(C.DATA_DIR / "bootstrap" / "D5_operator_slopes_bootstrap.npz", arrays),
    }
    return {"operators": ops, "width": widths, "thresholds": thresholds, "slopes": slope_rows, "status": status_rows, "check": check, "synthetic_frames": synth, "paths": paths}
