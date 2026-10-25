"""T10: replicate repeatability (20260730 vs 20260731) and the measurement floor (plan Part 1, item 3).

Replicates. The six July conditions were built twice, once per day, by the same part number (confound table). For
each pair the coupon statistics are compared directly; intervals come from a track bootstrap inside each coupon
(family 5, independent per coupon), so they describe within-coupon sampling, not day-to-day variation.

Measurement floor. Three descriptive floors against which e_H and e_W are read:
- resolution: the camera blob is 9-13 px long, so 1 px is 8-11 % of it;
- re-measurement: the supplied camera H/W against the 22.4.3.2 reading-S re-measurement of the same images at
  threshold 150 (camera side only);
- oracle floors: the e that a predictor would score if it knew the camera exactly at track or coupon level and
  predicted that one value for every frame (track oracle: the camera median of the frame's own track; coupon oracle:
  the coupon median; replicate oracle: the other July day's coupon median). They bound what any model that is
  constant within a track or coupon could reach. They use the camera data and are descriptive only.
"""
from __future__ import annotations

import math
from statistics import median
from typing import Any, Mapping, Sequence

import numpy as np

import common as C
from bootstrap import save_npz, weighted_median

FAMILY_REPLICATE = 5
SIZE_QUANTITIES = (("cam_H", "Camera H"), ("cam_W", "Camera W"), ("cam_HW", "Camera H/W"), ("sim_H", "Model H"), ("sim_W", "Model W"))
RESIDUAL_QUANTITIES = (("median_r_H", "Median r_H"), ("median_r_W", "Median r_W"), ("e_H", "e_H"), ("e_W", "e_W"))


def _frame_arrays(tracks: Sequence[Mapping[str, Any]]) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """Per quantity: values and their track index (model sizes over frames with a predicted pool only)."""

    out: dict[str, tuple[list, list]] = {k: ([], []) for k in ("cam_H", "cam_W", "cam_HW", "sim_H", "sim_W", "r_H", "r_W")}
    for k, t in enumerate(tracks):
        for f in t["frames"]:
            values = {
                "cam_H": float(f["cam_H_px"]), "cam_W": float(f["cam_W_px"]), "cam_HW": float(f["cam_H_px"]) / float(f["cam_W_px"]),
                "r_H": f["r_H"], "r_W": f["r_W"],
            }
            if not f["no_pool"]:
                values.update({"sim_H": float(f["sim_H_px"]), "sim_W": float(f["sim_W_px"])})
            for key, value in values.items():
                out[key][0].append(value)
                out[key][1].append(k)
    return {key: (np.array(v), np.array(u, dtype=np.int64)) for key, (v, u) in out.items()}


def coupon_draws(tracks: Sequence[Mapping[str, Any]], index: int, replicates: int) -> dict[str, np.ndarray]:
    counts = C.draw_counts(C.rng(FAMILY_REPLICATE, index), len(tracks), replicates)
    arrays = _frame_arrays(tracks)
    draws: dict[str, np.ndarray] = {}
    for key, name in (("cam_H", "cam_H"), ("cam_W", "cam_W"), ("cam_HW", "cam_HW"), ("sim_H", "sim_H"), ("sim_W", "sim_W"), ("r_H", "median_r_H"), ("r_W", "median_r_W")):
        values, unit = arrays[key]
        weight = counts[:, np.unique(unit)].sum(axis=1)
        out = weighted_median(values, unit, counts)
        out[weight == 0] = np.nan
        draws[name] = out
    for q in ("H", "W"):
        msq = np.array([t[f"{q}_mean_sq_log"] for t in tracks])
        draws[f"e_{q}"] = np.sqrt(counts @ msq / len(tracks))
    return draws


def point_values(coupon: Mapping[str, Any]) -> dict[str, float]:
    return {
        "cam_H": coupon["cam_H_px_median"], "cam_W": coupon["cam_W_px_median"], "cam_HW": coupon["cam_HW_median"],
        "sim_H": coupon["sim_H_px_median_pool"], "sim_W": coupon["sim_W_px_median_pool"],
        "median_r_H": coupon["median_r_H"], "median_r_W": coupon["median_r_W"], "e_H": coupon["e_H"], "e_W": coupon["e_W"],
    }


def replicate_pairs(analysis: Mapping[str, Any]) -> list[tuple[str, str, str]]:
    pairs = []
    for cid, row in analysis["conditions"].items():
        if row["coupons"] == 2:
            a, b = sorted(row["members"], key=C.member_key)
            if (C.member_key(a)[0], C.member_key(b)[0]) != ("20260730", "20260731"):
                raise RuntimeError(f"{cid}: unexpected replicate pair {a}, {b}")
            pairs.append((cid, a, b))
    return pairs


def _tracks_by_member(analysis: Mapping[str, Any]) -> dict[str, list]:
    out: dict[str, list] = {}
    for t in analysis["tracks"]:
        out.setdefault(t["member"], []).append(t)
    return out


def pair_rows(analysis: Mapping[str, Any], replicates: int) -> tuple[list[dict[str, Any]], dict[str, np.ndarray]]:
    order = sorted(C.ROLE, key=C.member_key)
    tracks = _tracks_by_member(analysis)
    coupons = analysis["coupons"]
    rows, arrays = [], {}
    for cid, a, b in replicate_pairs(analysis):
        da = coupon_draws(tracks[a], order.index(a), replicates)
        db = coupon_draws(tracks[b], order.index(b), replicates)
        pa, pb = point_values(coupons[a]), point_values(coupons[b])
        for key, label in (*SIZE_QUANTITIES, *RESIDUAL_QUANTITIES):
            is_size = key in dict(SIZE_QUANTITIES)
            diff = np.log(db[key] / da[key]) if is_size else db[key] - da[key]
            point = math.log(pb[key] / pa[key]) if is_size else pb[key] - pa[key]
            lo, hi = C.percentile_ci(diff)
            ci_a, ci_b = C.percentile_ci(da[key]), C.percentile_ci(db[key])
            rows.append(
                {
                    "condition": cid, "role": C.ROLE[a], "ved_J_mm3": analysis["record"][a]["ved_J_mm3"], "quantity": key, "label": label,
                    "member_0730": a, "member_0731": b, "value_0730": pa[key], "value_0730_ci_lo": float(ci_a[0]), "value_0730_ci_hi": float(ci_a[1]),
                    "value_0731": pb[key], "value_0731_ci_lo": float(ci_b[0]), "value_0731_ci_hi": float(ci_b[1]),
                    "difference_kind": "ln(0731 / 0730)" if is_size else "0731 - 0730", "difference": point,
                    "difference_ci_lo": float(lo), "difference_ci_hi": float(hi), "ci_excludes_zero": bool(lo > 0 or hi < 0),
                    "replicate_cv": abs(pa[key] - pb[key]) / math.sqrt(2.0) / (0.5 * (pa[key] + pb[key])) if is_size else None,
                    "resampling_unit": "track within each coupon (independent)", "replicates": replicates,
                    "generator_keys": f"[{C.SEED}, {FAMILY_REPLICATE}, {order.index(a)}] and [{C.SEED}, {FAMILY_REPLICATE}, {order.index(b)}]",
                }
            )
            arrays[f"{cid}__{key}__difference"] = diff
    return rows, arrays


def spread_rows(analysis: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Within-coupon spread on the log scale: track-to-track (SD of ln track medians) and frame-to-frame (pooled SD within tracks)."""

    rows = []
    for member, tracks in _tracks_by_member(analysis).items():
        row: dict[str, Any] = {"member": member, "role": C.ROLE[member], "condition": coupons_condition(analysis, member), "tracks": len(tracks)}
        for key, source, pool_only in (("cam_H", "cam_H_px", False), ("cam_W", "cam_W_px", False), ("sim_H", "sim_H_px", True), ("sim_W", "sim_W_px", True)):
            track_medians, within = [], []
            for t in tracks:
                values = [math.log(float(f[source])) for f in t["frames"] if not (pool_only and f["no_pool"])]
                if values:
                    track_medians.append(median(values))
                if len(values) >= 2:
                    within.append(float(np.var(values, ddof=1)))
            row[f"{key}_track_sd_log"] = float(np.std(track_medians, ddof=1))
            row[f"{key}_frame_sd_log"] = math.sqrt(C.fmean(within))
        rows.append(row)
    return rows


def coupons_condition(analysis: Mapping[str, Any], member: str) -> str:
    return analysis["coupons"][member]["condition"]


def remeasurement(analysis: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Supplied camera H/W against the reading-S re-measurement at threshold 150 (case 850 nm, sigma 0, every scored frame)."""

    out: dict[str, dict[str, list]] = {}
    skipped: dict[str, int] = {}
    for row in C.read_csv(C.SYNTHETIC_FRAMES):
        if row["case_id"] != "lam850_uniform_sig0.0":
            continue
        member = row["member_identity"]
        item = out.setdefault(member, {"H": [], "W": []})
        measured_ok = row["experimental_H_pixels"] != "" and float(row["experimental_H_pixels"]) > 0 and float(row["experimental_W_pixels"]) > 0
        if row["synthetic_status"] == "CAMERA_BLOB_150_ABSENT_OR_EDGE" or not measured_ok:
            skipped[member] = skipped.get(member, 0) + 1  # the re-measurement found no usable blob; nothing to compare
            continue
        for q in ("H", "W"):
            supplied, measured = float(row[f"stored_experimental_{q}_pixels"]), float(row[f"experimental_{q}_pixels"])
            item[q].append((supplied, measured))
    summary = {}
    for member, item in out.items():
        summary[member] = {"frames": len(item["H"]), "frames_without_remeasured_blob": skipped.get(member, 0)}
        for q in ("H", "W"):
            pairs = np.array(item[q])
            log_diff = np.abs(np.log(pairs[:, 0] / pairs[:, 1]))
            summary[member].update(
                {
                    f"{q}_median_abs_log_diff": float(np.median(log_diff)), f"{q}_p95_abs_log_diff": float(np.percentile(log_diff, 95)),
                    f"{q}_share_within_half_px": float(np.mean(np.abs(pairs[:, 0] - pairs[:, 1]) <= 0.5)),
                    f"{q}_rms_log_diff": float(np.sqrt(np.mean(np.log(pairs[:, 0] / pairs[:, 1]) ** 2))),
                }
            )
    return summary


def oracle_frames(analysis: Mapping[str, Any], kind: str) -> list[dict[str, Any]]:
    """Frames whose residual is the camera against an oracle prediction (track median, coupon median or the other replicate)."""

    coupons = analysis["coupons"]
    partner = {}
    for _, a, b in replicate_pairs(analysis):
        partner[a], partner[b] = b, a
    out = []
    for t in analysis["tracks"]:
        member = t["member"]
        if kind == "replicate" and member not in partner:
            continue
        if kind == "track":
            ref_h = median([float(f["cam_H_px"]) for f in t["frames"]])
            ref_w = median([float(f["cam_W_px"]) for f in t["frames"]])
        elif kind == "coupon":
            ref_h, ref_w = coupons[member]["cam_H_px_median"], coupons[member]["cam_W_px_median"]
        else:
            ref_h, ref_w = coupons[partner[member]]["cam_H_px_median"], coupons[partner[member]]["cam_W_px_median"]
        for f in t["frames"]:
            out.append(
                {
                    "member": member, "scan_track_id": t["scan_track_id"], "condition": t["condition"],
                    "r_H": C.log_ratio(ref_h, float(f["cam_H_px"])), "r_W": C.log_ratio(ref_w, float(f["cam_W_px"])),
                }
            )
    return out


def floor_rows(analysis: Mapping[str, Any], remeasured: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    groups = C.group_members()
    oracles = {kind: oracle_frames(analysis, kind) for kind in ("track", "coupon", "replicate")}
    coupons = analysis["coupons"]
    rows = []
    for name in ("calibration", "in_window_held_out", "out_of_window_all", "all_24"):
        members = set(groups[name])
        row: dict[str, Any] = {"group": name, "label": C.GROUP_LABEL[name], "coupons": len(members)}
        model = analysis["groups"][name]
        for q in ("H", "W"):
            row[f"model_e_{q}"] = model[f"e_{q}"]
            for kind, frames in oracles.items():
                sub = [f for f in frames if f["member"] in members]
                row[f"oracle_{kind}_e_{q}"] = C.contract_errors(sub)[f"e_{q}"] if sub else None
            sizes = [coupons[m][f"cam_{q}_px_median"] for m in members]
            row[f"cam_{q}_px_median_min"], row[f"cam_{q}_px_median_max"] = min(sizes), max(sizes)
            row[f"one_px_relative_max"] = max(row.get("one_px_relative_max", 0.0), 1.0 / min(sizes))
            row[f"remeasure_{q}_median_abs_log_diff"] = median([remeasured[m][f"{q}_median_abs_log_diff"] for m in members])
            row[f"remeasure_{q}_share_within_half_px"] = C.fmean([remeasured[m][f"{q}_share_within_half_px"] for m in members])
        row["oracle_replicate_coupons"] = len({f["member"] for f in oracles["replicate"] if f["member"] in members})
        rows.append(row)
    return rows


def run(analysis: Mapping[str, Any], replicates: int = C.BOOTSTRAP_REPLICATES) -> dict[str, Any]:
    pairs, arrays = pair_rows(analysis, replicates)
    spreads = spread_rows(analysis)
    remeasured = remeasurement(analysis)
    floors = floor_rows(analysis, remeasured)
    remeasure_rows = [{"member": m, "role": C.ROLE[m], **v} for m, v in sorted(remeasured.items(), key=lambda item: C.member_key(item[0]))]
    size_pairs = [r for r in pairs if r["quantity"] in ("cam_H", "cam_W", "sim_H", "sim_W")]
    summary = {
        key: {
            "mean_abs_log_difference": C.fmean([abs(r["difference"]) for r in size_pairs if r["quantity"] == key]),
            "max_abs_log_difference": max(abs(r["difference"]) for r in size_pairs if r["quantity"] == key),
            "pairs_with_ci_excluding_zero": sum(1 for r in size_pairs if r["quantity"] == key and r["ci_excludes_zero"]),
        }
        for key in ("cam_H", "cam_W", "sim_H", "sim_W")
    }
    paths = {
        "pairs": C.write_csv(C.DATA_DIR / "T10_replicate_pairs.csv", pairs),
        "spread": C.write_csv(C.DATA_DIR / "T10_within_coupon_spread.csv", spreads),
        "floor": C.write_csv(C.DATA_DIR / "T10_measurement_floor.csv", floors),
        "remeasure": C.write_csv(C.DATA_DIR / "T10_camera_remeasurement.csv", remeasure_rows),
        "draws": save_npz(C.DATA_DIR / "bootstrap" / "D5_replicate_bootstrap.npz", arrays),
    }
    return {"pairs": pairs, "spreads": spreads, "floors": floors, "remeasure": remeasure_rows, "summary": summary, "paths": paths}
