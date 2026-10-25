"""T15: sensitivity and robustness of the confirm_c1 results, from the frozen records only (no new search).

Sections:
A. objective choice: how the 19 calibrated candidates rank under J, its H-only and W-only components and the
   superseded 22.3.7 pixel objective (all recorded by the calibrate and confirm stages);
B. selected versus near-best: c1 against c2 on calibration, reading V and the out-of-window coupons (c2 recomputed
   from its evaluate unit files, which are checked against the manifest);
C. summary statistic: median, geometric and arithmetic means of the model/camera ratio;
D. weighting (plan Part 1, item 7): the contract hierarchy against frame-, track- and coupon-weighted means;
E. pixel floor and no-pool treatment: floors of 0.5, 1 (contract) and 2 px, and no-pool frames left out;
F. short tracks: tracks with fewer than k scored frames left out;
G. leave one coupon out: the range of each group's errors when any single coupon is dropped;
H. camera threshold (plan Part 1, item 7): the c1 model/camera ratios if the camera were thresholded at 30-250
   instead of 150 (22.3.8 Step 0 threshold family, 16 A8 calibration members, coupon medians).
"""
from __future__ import annotations

import hashlib
import json
import math
from statistics import median
from typing import Any, Mapping, Sequence

import numpy as np

import common as C

GROUPS = ("calibration", "in_window_held_out", "out_of_window_all")
OBJECTIVES = (
    ("J", "J (log ratio, contract 22.4.3.2)"),
    ("H_only", "H term only (e_H²)"),
    ("W_only", "W term only (e_W²)"),
    ("pixel_22_3_7", "Pixel residual objective (22.3.7, superseded, S11)"),
)


def _frames_of(analysis: Mapping[str, Any], name: str) -> list[Mapping[str, Any]]:
    members = set(C.group_members()[name])
    return [f for f in analysis["scored"] if f["member"] in members]


# ---------------------------------------------------------------------- A, B


def objective_rows() -> list[dict[str, Any]]:
    reading = C.load_json(C.CALIBRATION_READING)
    scores = reading["scores"]
    coords = {c["candidate_id"]: c["coordinates"] for c in reading["candidates"]}
    value = {cid: {"J": s["J"], "H_only": s["sensitivity"]["H_only"], "W_only": s["sensitivity"]["W_only"], "pixel_22_3_7": s["sensitivity"]["pixel_22_3_7"]} for cid, s in scores.items()}
    ids = sorted(value)
    j_rank = {cid: k + 1 for k, cid in enumerate(sorted(ids, key=lambda c: value[c]["J"]))}
    rows = []
    for key, label in OBJECTIVES:
        order = sorted(ids, key=lambda c: value[c][key])
        rank = {cid: k + 1 for k, cid in enumerate(order)}
        winner = order[0]
        rows.append(
            {
                "objective": key, "label": label, "candidates": len(ids), "winner": winner,
                "winner_t": coords[winner]["abs_depth_identifiable_coordinate"], "winner_ck": coords[winner]["liquid_conductivity_enhancement_factor"],
                "winner_eta": coords[winner]["eta_directional"], "c1_rank": rank[C.CANDIDATE], "c1_value": value[C.CANDIDATE][key],
                "winner_value": value[winner][key], "c2_rank": rank["confirm_c2"],
                "spearman_with_J_ranking": C.spearman([j_rank[c] for c in ids], [rank[c] for c in ids]),
            }
        )
    return rows


def _unit_frames(member: str, candidate: str, expected_sha: str) -> list[dict[str, Any]]:
    path = C.UNITS_DIR / f"{candidate}__{member.replace(':', '_')}.json"
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha:
        raise RuntimeError(f"{path.name}: sha256 differs from the evaluate manifest")
    unit = json.loads(raw)
    out = []
    for rec in unit["frame_records"]:
        if rec.get("scored_frame") and rec["status"] == "PASS":
            out.append(
                {
                    "member": member, "scan_track_id": int(rec["scan_track_id"]), "condition": rec["exact_condition_id"],
                    "r_H": C.log_ratio(rec["simulated_H_pixels"], rec["experimental_H_pixels"]), "r_W": C.log_ratio(rec["simulated_W_pixels"], rec["experimental_W_pixels"]),
                }
            )
    return out


def near_best_rows(analysis: Mapping[str, Any]) -> list[dict[str, Any]]:
    reading = C.load_json(C.CALIBRATION_READING)["scores"]
    manifest = C.evaluate_manifest()
    shas = {u["work_unit_id"]: u["unit_sha256"] for u in manifest["units"]}
    record = analysis["record"]
    oow = C.group_members()["out_of_window_all"]
    rows = []
    for cid in (C.CANDIDATE, "confirm_c2"):
        v = manifest["readings"]["V"][cid]
        frames = [f for m in oow for f in _unit_frames(m, cid, shas[f"22.4.3.2:{cid}@{m}"])]
        err = C.contract_errors(frames)
        medians = {m: {q: float(median(f[f"r_{q}"] for f in frames if f["member"] == m)) for q in ("H", "W")} for m in oow}
        veds = [record[m]["ved_J_mm3"] for m in oow]
        rows.append(
            {
                "candidate": cid, "calibration_J": reading[cid]["J"], "calibration_e_H": reading[cid]["e_H"], "calibration_e_W": reading[cid]["e_W"],
                "calibration_peak_above_boiling": reading[cid]["fraction_peak_above_boiling"],
                "held_out_e_H": v["held_out"]["e_H"], "held_out_e_W": v["held_out"]["e_W"], "v_ratio_H": v["ratio_H"], "v_ratio_W": v["ratio_W"],
                "v_reading": v["reading"], "part_5_ratio_H": v["cross_campaign_20260904_part_5"]["ratio_H"], "part_5_ratio_W": v["cross_campaign_20260904_part_5"]["ratio_W"],
                "out_of_window_e_H": err["e_H"], "out_of_window_e_W": err["e_W"], "out_of_window_J": err["J"],
                "spearman_ved_median_r_H": C.spearman(veds, [medians[m]["H"] for m in oow]),
                "spearman_ved_median_r_W": C.spearman(veds, [medians[m]["W"] for m in oow]),
            }
        )
    c1 = rows[0]
    x = manifest["readings"]["X"]
    if not (math.isclose(c1["spearman_ved_median_r_H"], x["X2_H"]["spearman_rho"], abs_tol=1e-12) and math.isclose(c1["spearman_ved_median_r_W"], x["X1_W"]["spearman_rho"], abs_tol=1e-12)):
        raise RuntimeError("c1 out-of-window Spearman differs from reading X")
    if not math.isclose(c1["out_of_window_e_H"], analysis["groups"]["out_of_window_all"]["e_H"], rel_tol=1e-15):
        raise RuntimeError("c1 out-of-window e_H differs from the package hierarchy")
    return rows


# ---------------------------------------------------------------------- C-G


def summary_rows(analysis: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for name in GROUPS:
        frames = _frames_of(analysis, name)
        g = analysis["groups"][name]
        members = C.group_members()[name]
        for q in ("H", "W"):
            ratios = np.exp([f[f"r_{q}"] for f in frames])
            rows.append(
                {
                    "group": name, "label": C.GROUP_LABEL[name], "quantity": q,
                    "median_ratio_pooled_frames": float(np.median(ratios)),
                    "geometric_mean_hierarchical": math.exp(g[f"{q}_mean_log"]),
                    "geometric_mean_pooled_frames": float(np.exp(np.mean(np.log(ratios)))),
                    "arithmetic_mean_pooled_frames": float(np.mean(ratios)),
                    "median_of_coupon_medians": float(median(analysis["coupons"][m][f"median_{q}_ratio"] for m in members)),
                    "e_contract": g[f"e_{q}"],
                }
            )
    return rows


def _variant(section: str, name: str, variant: str, frames: Sequence[Mapping[str, Any]], weighting: str = "contract", **extra: Any) -> dict[str, Any]:
    err = C.contract_errors(frames, weighting=weighting)
    return {
        "section": section, "group": name, "label": C.GROUP_LABEL[name], "variant": variant, "e_H": err["e_H"], "e_W": err["e_W"], "J": err["J"],
        "frames": err["frames"], "tracks": err["tracks"], "coupons": err["coupons"], "conditions": err["conditions"], **extra,
    }


def _refloor(frames: Sequence[Mapping[str, Any]], floor: float) -> list[dict[str, Any]]:
    def lr(sim: Any, cam: Any) -> float:
        return math.log(max(float(sim), floor) / max(float(cam), floor))

    return [{**f, "r_H": lr(f["sim_H_px"], f["cam_H_px"]), "r_W": lr(f["sim_W_px"], f["cam_W_px"])} for f in frames]


def variant_rows(analysis: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for name in (*GROUPS, "all_24"):
        frames = _frames_of(analysis, name)
        contract = analysis["groups"][name]
        for weighting, label in (("contract", "contract: track -> coupon -> condition"), ("frame", "every frame equal"), ("track", "every track equal"), ("coupon", "every coupon equal")):
            row = _variant("D_weighting", name, label, frames, weighting)
            if weighting == "contract" and not (math.isclose(row["e_H"], contract["e_H"], rel_tol=1e-15) and math.isclose(row["e_W"], contract["e_W"], rel_tol=1e-15)):
                raise RuntimeError(f"{name}: contract weighting differs from the hierarchy")
            rows.append(row)
        for floor in (0.5, 1.0, 2.0):
            rows.append(_variant("E_floor", name, f"pixel floor {floor:g} px" + (" (contract)" if floor == 1.0 else ""), _refloor(frames, floor), no_pool_frames=sum(1 for f in frames if f["no_pool"])))
        pool = [f for f in frames if not f["no_pool"]]
        rows.append(_variant("E_floor", name, "no-pool frames left out (floor 1 px)", pool, no_pool_frames=0))
        track_size: dict[tuple[str, int], int] = {}
        for f in frames:
            track_size[(f["member"], f["scan_track_id"])] = track_size.get((f["member"], f["scan_track_id"]), 0) + 1
        for k in (1, 3, 5, 10, 20):
            kept = [f for f in frames if track_size[(f["member"], f["scan_track_id"])] >= k]
            rows.append(_variant("F_short_tracks", name, f"tracks with >= {k} scored frames" + (" (contract)" if k == 1 else ""), kept))
        if name == "all_24":
            continue
        members = C.group_members()[name]
        loo = []
        for m in members:
            kept = [f for f in frames if f["member"] != m]
            err = C.contract_errors(kept)
            loo.append((m, err))
        for q in ("e_H", "e_W", "J"):
            lo = min(loo, key=lambda item: item[1][q])
            hi = max(loo, key=lambda item: item[1][q])
            rows.append(
                {
                    "section": "G_leave_one_coupon_out", "group": name, "label": C.GROUP_LABEL[name], "variant": f"{q}: range over the {len(members)} drops",
                    "statistic": q, "full": contract[q], "min": lo[1][q], "min_when_dropping": lo[0], "max": hi[1][q], "max_when_dropping": hi[0],
                    "coupons": len(members) - 1,
                }
            )
    return rows


def threshold_rows(analysis: Mapping[str, Any]) -> list[dict[str, Any]]:
    family = [r for r in C.read_csv(C.STEP0_FAMILY) if r["layer"] == "layer53"]
    coupons = analysis["coupons"]
    rows = []
    for t in sorted({int(r["threshold"]) for r in family}):
        sub = {r["member_identity"]: r for r in family if int(r["threshold"]) == t}
        for role in ("calibration", "out_of_window_examined"):
            members = [m for m in C.ROLE_MEMBERS[role] if m in sub]
            if len(members) != len(C.ROLE_MEMBERS[role]):
                raise RuntimeError(f"threshold family lacks {role} members")
            h = [coupons[m]["sim_H_px_median_pool"] / float(sub[m]["median_H_px"]) for m in members]
            w = [coupons[m]["sim_W_px_median_pool"] / float(sub[m]["median_W_px"]) for m in members]
            hw = [coupons[m]["sim_HW_median_pool"] / float(sub[m]["median_HW"]) for m in members]
            rows.append(
                {
                    "threshold": t, "role": role, "label": C.ROLE_LABEL[role], "coupons": len(members),
                    "median_H_ratio_of_coupon_medians": float(median(h)), "median_W_ratio_of_coupon_medians": float(median(w)),
                    "median_shape_ratio": float(median(hw)), "max_abs_ln_H_ratio": float(max(abs(math.log(x)) for x in h)),
                    "max_abs_ln_W_ratio": float(max(abs(math.log(x)) for x in w)), "reference": t == 150,
                }
            )
    return rows


def run(analysis: Mapping[str, Any]) -> dict[str, Any]:
    objectives = objective_rows()
    near = near_best_rows(analysis)
    summary = summary_rows(analysis)
    variants = variant_rows(analysis)
    thresholds = threshold_rows(analysis)
    paths = {
        "objectives": C.write_csv(C.DATA_DIR / "T15_objective_choice.csv", objectives),
        "near_best": C.write_csv(C.DATA_DIR / "T15_selected_vs_near_best.csv", near),
        "summary": C.write_csv(C.DATA_DIR / "T15_summary_statistic.csv", summary),
        "variants": C.write_csv(C.DATA_DIR / "T15_weighting_floor_tracks_loo.csv", variants),
        "thresholds": C.write_csv(C.DATA_DIR / "T15_camera_threshold.csv", thresholds),
    }
    return {"objectives": objectives, "near_best": near, "summary": summary, "variants": variants, "thresholds": thresholds, "paths": paths}
