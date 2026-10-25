"""Confound table: design features that cannot be separated from the effects the package reports.

Each row is listed, not resolved. Where the data can show the confound, the check is computed here from the A17
record and the c1 frame table; the rest cite the ledger.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Mapping

import numpy as np

import common as C


def _spearman(x, y) -> float:
    rx = np.argsort(np.argsort(x, kind="stable"), kind="stable").astype(float)
    ry = np.argsort(np.argsort(y, kind="stable"), kind="stable").astype(float)
    # Average ranks for ties, so the value matches the usual definition.
    for values, ranks in ((np.asarray(x), rx), (np.asarray(y), ry)):
        for v in np.unique(values):
            idx = values == v
            if idx.sum() > 1:
                ranks[idx] = ranks[idx].mean()
    return float(np.corrcoef(rx, ry)[0, 1])


def checks(analysis: Mapping[str, Any]) -> dict[str, Any]:
    record = analysis["record"]
    july = {m: r for m, r in record.items() if r["acquisition_set"] in ("20260730", "20260731")}
    part_condition = {}
    for r in july.values():
        part_condition.setdefault(r["part"], set()).add(r["condition"])
    same_condition_per_part = all(len(v) == 1 for v in part_condition.values())
    unique_condition_per_part_september = {
        s: len({r["condition"] for r in record.values() if r["acquisition_set"] == s}) == 6 for s in ("20260904", "20260910")
    }
    ved_by_campaign = {
        "july": [min(r["ved_J_mm3"] for r in july.values()), max(r["ved_J_mm3"] for r in july.values())],
        "september": [min(r["ved_J_mm3"] for m, r in record.items() if m not in july), max(r["ved_J_mm3"] for m, r in record.items() if m not in july)],
    }
    cal = C.ROLE_MEMBERS["calibration"]
    on_line = [m for m in cal if record[m]["acquisition_set"] in ("20260730", "20260731")]
    lp = np.log([record[m]["power_W"] for m in cal])
    lv = np.log([record[m]["speed_mm_s"] for m in cal])
    corr_cal = float(np.corrcoef(lp, lv)[0, 1])

    # Track order versus camera and model H (interior tracks: >= 10 scored frames), per coupon.
    by_member: dict[str, list] = {}
    for t in analysis["tracks"]:
        if t["scored_frames"] >= 10:
            by_member.setdefault(t["member"], []).append(t)
    rho = {}
    for member, tracks in by_member.items():
        order = [t["scan_track_id"] for t in tracks]
        cam = [float(np.median([f["cam_H_px"] for f in t["frames"]])) for t in tracks]
        sim = [float(np.median([f["sim_H_px"] for f in t["frames"]])) for t in tracks]
        rho[member] = {"camera_H": _spearman(order, cam), "model_H": _spearman(order, sim), "interior_tracks": len(tracks)}
    in_window = [m for m in rho if C.ROLE[m] in ("calibration", "in_window_held_out")]

    # No-pool frames in the window: acquisition set and where in the track.
    where = Counter()
    for t in analysis["tracks"]:
        frames = sorted(t["frames"], key=lambda f: f["track_position"])
        for k, f in enumerate(frames):
            if f["no_pool"] and C.ROLE[f["member"]] in ("calibration", "in_window_held_out"):
                pos = "last_scored" if k == len(frames) - 1 else ("first_scored" if k == 0 else "interior")
                where[(f["acquisition_set"], pos)] += 1
    # Scan order within each set's layer: order of the coupons' first laser-on camera frame (whole-layer stream).
    first_on = {}
    for member in record:
        rows = C.characterization_rows(member)
        first_on[member] = min(k for k, row in rows.items() if row["laser_on"] == "True")
    scan_order = {}
    for acquisition_set in ("20260730", "20260731", "20260904", "20260910"):
        members = sorted((m for m in record if record[m]["acquisition_set"] == acquisition_set), key=first_on.get)
        scan_order[acquisition_set] = [record[m]["part"] for m in members]
    blind = C.ROLE_MEMBERS["out_of_window_blind"]
    examined = C.ROLE_MEMBERS["out_of_window_examined"]
    distance = lambda m: max(C.VED_WINDOW_J_MM3[0] - record[m]["ved_J_mm3"], record[m]["ved_J_mm3"] - C.VED_WINDOW_J_MM3[1], 0.0)
    return {
        "part_number_fixes_condition_in_july_sets": same_condition_per_part,
        "each_part_a_distinct_condition_in_september_sets": unique_condition_per_part_september,
        "ved_range_by_campaign_J_mm3": ved_by_campaign,
        "calibration_members_on_july_line": len(on_line),
        "calibration_corr_lnP_lnv": corr_cal,
        "track_order_spearman": rho,
        "track_order_camera_H_rho_in_window_range": [min(rho[m]["camera_H"] for m in in_window), max(rho[m]["camera_H"] for m in in_window)],
        "track_order_model_H_rho_in_window_range": [min(rho[m]["model_H"] for m in in_window), max(rho[m]["model_H"] for m in in_window)],
        "in_window_no_pool_frames_by_set_and_position": {f"{s}:{p}": n for (s, p), n in sorted(where.items())},
        "scan_order_parts_by_set": scan_order,
        "first_laser_on_camera_frame": first_on,
        "out_of_window_distance_J_mm3": {
            "examined": sorted(round(distance(m), 1) for m in examined),
            "blind": sorted(round(distance(m), 1) for m in blind),
        },
    }


def table_rows(c: Mapping[str, Any]) -> list[dict[str, Any]]:
    rho_cam = c["track_order_camera_H_rho_in_window_range"]
    rho_sim = c["track_order_model_H_rho_in_window_range"]
    nopool = c["in_window_no_pool_frames_by_set_and_position"]
    july_total = sum(n for k, n in nopool.items())
    only_0731 = all(k.startswith("20260731") for k in nopool)
    last = sum(n for k, n in nopool.items() if k.endswith("last_scored"))
    return [
        {
            "confound": "Part number and condition (July sets)",
            "what_is_confounded": "In 20260730 and 20260731 each part number carries the same P/v in both sets, so plate position, part number and condition move together; a replicate pair differs only by acquisition day.",
            "check": f"part number fixes the condition in both July sets: {c['part_number_fixes_condition_in_july_sets']}",
            "consequence": "Position-on-plate effects cannot be separated from condition effects; replicate differences (0730 vs 0731) are day effects, not independent position replicates.",
            "source": "docs/reference/LPBF_Process_Parameters.csv (A17)",
        },
        {
            "confound": "Part position and condition (September sets)",
            "what_is_confounded": "In 20260904 and 20260910 each part is a distinct condition, built once.",
            "check": f"six distinct conditions per September set: {c['each_part_a_distinct_condition_in_september_sets']}",
            "consequence": "No within-set replicate exists outside July; a single coupon carries each September condition.",
            "source": "A17",
        },
        {
            "confound": "Scan order within the layer and condition",
            "what_is_confounded": "The six coupons of a set are scanned one after another in a fixed part order, so each condition occupies one time slot in the layer; in July both days use the same order, so a replicate pair shares its slot.",
            "check": "scan order of parts (first laser-on camera frame): " + "; ".join(f"{s} {' '.join(map(str, o))}" for s, o in c["scan_order_parts_by_set"].items()),
            "consequence": "Effects of time in the layer (chamber or plate heating, spatter, gas flow) cannot be separated from condition. In 20260904 the 140 W parts precede the 180 W parts; in 20260910 the 700 mm/s parts precede the 1200 mm/s parts.",
            "source": "Patch 21.3 characterization frame_observations.csv (laser-on frame ranges)",
        },
        {
            "confound": "Campaign, sync convention and VED range",
            "what_is_confounded": "July (0730, 0731) and September (0904, 0910) differ in acquisition day, sync-anchor convention (O11: first bright frame at laser-on vs about 10 rows before; resample factor 1.1 vs 0.8) and design (July a diagonal locus, September factorial sweeps).",
            "check": f"VED range July {c['ved_range_by_campaign_J_mm3']['july'][0]:.1f}-{c['ved_range_by_campaign_J_mm3']['july'][1]:.1f}, September {c['ved_range_by_campaign_J_mm3']['september'][0]:.1f}-{c['ved_range_by_campaign_J_mm3']['september'][1]:.1f} J/mm3",
            "consequence": "Everything learned about the VED, power and speed response outside 68.6-72 J/mm3 comes from the September campaign alone; a campaign effect cannot be separated from it. 20260904:part_5, the only off-line in-window held-out coupon, is also the only September coupon in the window apart from 20260910:part_1.",
            "source": "docs/DECISIONS.md O11; docs/patches/22.3.6/PATCH_22_3_6_SYNC_AUDIT_FINDINGS.md",
        },
        {
            "confound": "Calibration design collinearity",
            "what_is_confounded": "Eight of the nine calibration members lie on one P/v line (68.6-72.0 J/mm3).",
            "check": f"{c['calibration_members_on_july_line']} of 9 on the July line; corr(ln P, ln v) over the 9 = {c['calibration_corr_lnP_lnv']:.3f}",
            "consequence": "Inside the window, power and speed effects are not separable (T11 in-window P/v slopes are not identified); in-window validation of P150_V900 and P170_V1000 is close to interpolation (A25 caveat).",
            "source": "A25; T11",
        },
        {
            "confound": "Track order, position in the coupon and time in the layer",
            "what_is_confounded": "Tracks are scanned in order, so track number is also position across the coupon and elapsed time (heat build-up).",
            "check": f"Spearman(track order, camera H) on in-window coupons {rho_cam[0]:.2f} to {rho_cam[1]:.2f}; model H {rho_sim[0]:.2f} to {rho_sim[1]:.2f} (interior tracks with >= 10 scored frames)",
            "consequence": "The camera blob grows through the layer while the model's pool does not; whether this is heat build-up, a threshold (brightness) effect or position cannot be separated. Exploratory, not predeclared.",
            "source": "docs/analysis/22.4.3.2_per_coupon_per_track/PER_COUPON_PER_TRACK_SUMMARY.md 5.1; D2",
        },
        {
            "confound": "Acquisition day and end-of-track pool loss",
            "what_is_confounded": "In the window, frames without a predicted pool occur only on 20260731 coupons and at the last scored frame of a track.",
            "check": f"{july_total} in-window no-pool frames; all on 20260731: {only_0731}; at the last scored frame: {last}; by set and position: {nopool}",
            "consequence": "Part of the 0731 vs 0730 error difference is this day-specific track-end effect, not condition; its cause (timing at track ends is a candidate) is not established.",
            "source": "PER_COUPON_PER_TRACK_SUMMARY.md 5.2; D7",
        },
        {
            "confound": "Examined vs blind and distance from the window",
            "what_is_confounded": "The 3 blind out-of-window coupons lie nearer the window than most of the 7 examined ones.",
            "check": f"VED distance outside [65, 85]: examined {c['out_of_window_distance_J_mm3']['examined']}, blind {c['out_of_window_distance_J_mm3']['blind']} J/mm3",
            "consequence": "Lower error on the blind group reflects VED distance, not blindness; group comparisons must be read against VED (A27, results report 4).",
            "source": "A25; T9 (pass 2); D3",
        },
    ]
