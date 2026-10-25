"""D1-D4 and D7: frame, track, coupon, condition/group datasets and the exclusion ledger (confirm_c1).

``build()`` recomputes the contract-22.4.3.2 hierarchy from the c1 evaluate unit files and checks every coupon and
group value against the committed manifests (``verify()``); ``write()`` writes the data files. Confidence intervals
come from ``bootstrap.py`` and are joined here.
"""
from __future__ import annotations

import math
from typing import Any, Mapping

import numpy as np

import common as C

# Analysis groups: name -> (members, description). Calibration and in-window held-out are the A25 roles.
def analysis_groups() -> dict[str, tuple[tuple[str, ...], str]]:
    record = C.process_record()
    oow = C.ROLE_MEMBERS["out_of_window_examined"] + C.ROLE_MEMBERS["out_of_window_blind"]
    low = tuple(m for m in oow if record[m]["ved_J_mm3"] < C.VED_WINDOW_J_MM3[0])
    high = tuple(m for m in oow if record[m]["ved_J_mm3"] > C.VED_WINDOW_J_MM3[1])
    groups: dict[str, tuple[tuple[str, ...], str]] = {
        "calibration": (C.ROLE_MEMBERS["calibration"], "A25 calibration members (9 coupons, 5 conditions); objective J"),
        "in_window_held_out": (C.ROLE_MEMBERS["in_window_held_out"], "A25 in-window held out (5 coupons, 3 conditions); reading V"),
        "cross_campaign_20260904_part_5": ((C.CROSS_CAMPAIGN,), "in-window held-out coupon from the September campaign; reading V"),
        "out_of_window_examined": (C.ROLE_MEMBERS["out_of_window_examined"], "A25 out of window, examined by 22.3.8 (7)"),
        "out_of_window_blind": (C.ROLE_MEMBERS["out_of_window_blind"], "A25 out of window, A8 held out (3)"),
        "out_of_window_all": (oow, "all 10 out-of-window coupons; reading X"),
        "out_of_window_low_ved": (low, "out of window, VED < 65 J/mm3"),
        "out_of_window_high_ved": (high, "out of window, VED > 85 J/mm3"),
        "all_24": (tuple(sorted(C.ROLE, key=C.member_key)), "all 24 coupons (descriptive only)"),
    }
    for role in ("calibration", "in_window_held_out"):
        for acquisition_set in ("20260730", "20260731", "20260904", "20260910"):
            members = tuple(m for m in C.ROLE_MEMBERS[role] if m.startswith(acquisition_set))
            if members and len(members) < len(C.ROLE_MEMBERS[role]):
                groups[f"{role}__set_{acquisition_set}"] = (members, f"{role} members of acquisition set {acquisition_set}")
    return groups


def build(*, process_rows: bool = True) -> dict[str, Any]:
    units = C.load_units()
    frames = C.frame_table(units, process_rows=process_rows)
    scored = C.scored_frames(frames)
    tracks = C.track_rows(scored)
    coupons = C.coupon_rows(tracks)
    frames_by_member: dict[str, list] = {}
    for row in scored:
        frames_by_member.setdefault(row["member"], []).append(row)
    groups = {
        name: {"members": members, "description": text, **C.group_hierarchy(coupons, members, frames_by_member)}
        for name, (members, text) in analysis_groups().items()
    }
    by_condition: dict[str, list[str]] = {}
    for member, row in coupons.items():
        by_condition.setdefault(row["condition"], []).append(member)
    conditions = {
        cid: {"members": tuple(members), **C.group_hierarchy(coupons, members, frames_by_member)}
        for cid, members in sorted(by_condition.items(), key=lambda item: C.process_record()[item[1][0]]["ved_J_mm3"])
    }
    return {
        "units": units,
        "frames": frames,
        "scored": scored,
        "tracks": tracks,
        "coupons": coupons,
        "frames_by_member": frames_by_member,
        "groups": groups,
        "conditions": conditions,
        "record": C.process_record(),
    }


# ---------------------------------------------------------------------- verification against the manifests


def verify(analysis: Mapping[str, Any]) -> dict[str, Any]:
    """Every coupon and group e_H, e_W, J and median ratio equals the committed evaluate manifest (|diff| <= 1e-12)."""

    manifest = C.evaluate_manifest()
    official: dict[str, Mapping[str, Any]] = {}
    for row in manifest["calibration_score_selected"]["coupon_rows"]:
        official[row["member_identity"]] = row
    for row in manifest["readings"]["V"][C.CANDIDATE]["held_out"]["coupon_rows"]:
        official[row["member_identity"]] = row
    x_rows = {row["member_identity"]: row for row in manifest["readings"]["X"]["coupons"]}
    coupons = analysis["coupons"]
    worst = 0.0
    checked = 0
    for member, row in coupons.items():
        if member in official:
            ref = official[member]
            pairs = [("e_H", "e_H"), ("e_W", "e_W"), ("median_H_ratio", "median_H_ratio"), ("median_W_ratio", "median_W_ratio"), ("median_r_H", "median_r_H"), ("median_r_W", "median_r_W")]
            worst = max(worst, abs(row["J"] - ref["coupon_scalar_objective"]))
            if row["scored_frames"] != ref["scored_frame_count"]:
                raise RuntimeError(f"{member}: scored frames {row['scored_frames']} != manifest {ref['scored_frame_count']}")
        else:
            ref = x_rows[member]
            pairs = [("e_H", "e_H"), ("e_W", "e_W"), ("median_r_H", "median_r_H"), ("median_r_W", "median_r_W")]
            frac = row["peak_above_boiling_fraction"]
            worst = max(worst, abs(frac - ref["fraction_peak_above_boiling"]))
        for mine, theirs in pairs:
            worst = max(worst, abs(row[mine] - ref[theirs]))
            checked += 1
    group_refs = {
        "calibration": manifest["calibration_score_selected"],
        "in_window_held_out": manifest["readings"]["V"][C.CANDIDATE]["held_out"],
        "cross_campaign_20260904_part_5": manifest["readings"]["V"][C.CANDIDATE]["cross_campaign_20260904_part_5"]["score"],
    }
    for name, ref in group_refs.items():
        mine = analysis["groups"][name]
        for key_mine, key_ref in (("e_H", "e_H"), ("e_W", "e_W"), ("J", "J"), ("H_mean_sq_log", "H_component"), ("W_mean_sq_log", "W_component"), ("peak_above_boiling_fraction", "fraction_peak_above_boiling"), ("median_peak_surface_K", "median_peak_surface_K")):
            worst = max(worst, abs(mine[key_mine] - ref[key_ref]))
            checked += 1
        if mine["scored_frames"] != ref["scored_frame_count"] or mine["floored_frames"] != ref["floored_frame_count"]:
            raise RuntimeError(f"group {name}: frame counts disagree with the manifest")
        if mine["no_laser_associated_melt_frames"] != ref["no_laser_associated_melt_count"]:
            raise RuntimeError(f"group {name}: no-laser-associated-melt count disagrees with the manifest")
        for cond in ref["condition_rows"]:
            mc = mine["condition_rows"][cond["exact_condition_id"]]
            worst = max(worst, abs(mc["e_H"] - cond["e_H"]), abs(mc["e_W"] - cond["e_W"]), abs(mc["H_mean_log"] - cond["H_mean_log"]))
            checked += 3
    v = manifest["readings"]["V"][C.CANDIDATE]
    for q in ("H", "W"):
        ratio = analysis["groups"]["in_window_held_out"][f"e_{q}"] / analysis["groups"]["calibration"][f"e_{q}"]
        worst = max(worst, abs(ratio - v[f"ratio_{q}"]))
        checked += 1
    if worst > 1e-12:
        raise RuntimeError(f"recomputed hierarchy differs from the evaluate manifest by {worst}")
    # The production aggregator on the original records gives the same calibration score.
    from lpbf.log_ratio_objective import aggregate_log_ratio_records

    cal = C.ROLE_MEMBERS["calibration"]
    records = [rec for m in cal for rec in analysis["units"][m]["frame_records"]]
    prod = aggregate_log_ratio_records(records, member_ids=cal, condition_ids={analysis["coupons"][m]["condition"] for m in cal}, candidate_id=C.CANDIDATE)
    prod_diff = max(abs(prod["e_H"] - analysis["groups"]["calibration"]["e_H"]), abs(prod["e_W"] - analysis["groups"]["calibration"]["e_W"]), abs(prod["objective_value"] - analysis["groups"]["calibration"]["J"]))
    if prod_diff > 1e-12:
        raise RuntimeError(f"production aggregator differs by {prod_diff}")
    return {
        "evaluate_manifest_sha256": C.sha256_file(C.EVALUATE_MANIFEST),
        "values_checked": checked,
        "max_abs_difference_vs_manifest": worst,
        "production_aggregator_max_abs_difference_calibration": prod_diff,
        "tolerance": 1e-12,
        "status": "PASS",
    }


# ---------------------------------------------------------------------- writers


D1_FIELDS = [
    "member", "acquisition_set", "part", "condition", "power_W", "speed_mm_s", "ved_J_mm3", "role", "scan_track_id",
    "track_position", "track_eligible_frames", "frame_index", "process_row", "cam_H_px", "cam_W_px", "sim_H_px", "sim_W_px",
    "production_status", "production_beam_share", "no_pool", "r_H", "r_W", "floored", "peak_surface_K",
    "peak_above_boiling", *C.VERSIONS,
]


def _track_records(analysis: Mapping[str, Any]) -> list[dict[str, Any]]:
    record = analysis["record"]
    eligible: dict[tuple[str, int], dict[str, int]] = {}
    for row in analysis["frames"]:
        key = (row["member"], row["scan_track_id"])
        item = eligible.setdefault(key, {"eligible": 0, "excluded_first": 0, "excluded_last": 0, "excluded_single": 0, "camera_ineligible": 0})
        reason = row["exclusion_reason"]
        if reason == "NOT_ELIGIBLE":
            item["camera_ineligible"] += 1
            continue
        item["eligible"] += 1
        if reason == "EXCLUDED_TRACK_FIRST":
            item["excluded_first"] += 1
        elif reason == "EXCLUDED_TRACK_LAST":
            item["excluded_last"] += 1
        elif reason == "EXCLUDED_TRACK_SINGLE_FRAME":
            item["excluded_single"] += 1
    scored_tracks = {(t["member"], t["scan_track_id"]): t for t in analysis["tracks"]}
    out = []
    for (member, track), counts in sorted(eligible.items(), key=lambda item: (C.member_key(item[0][0]), item[0][1])):
        t = scored_tracks.get((member, track))
        row: dict[str, Any] = {
            "member": member, "role": C.ROLE[member], "condition": record[member]["condition"],
            "ved_J_mm3": record[member]["ved_J_mm3"], "scan_track_id": track,
            "track_order_fraction": track / 54.0, **counts,
            "first_last_excluded_by_rule": counts["excluded_first"] + counts["excluded_last"] + counts["excluded_single"],
            "scored_frames": t["scored_frames"] if t else 0,
        }
        if t:
            summary = C.frame_summary(t["frames"])
            row.update(
                {
                    "cam_H_px_median": summary["cam_H_px_median"], "cam_W_px_median": summary["cam_W_px_median"],
                    "sim_H_px_median_pool": summary["sim_H_px_median_pool"], "sim_W_px_median_pool": summary["sim_W_px_median_pool"],
                    "median_H_ratio": summary["median_H_ratio"], "median_W_ratio": summary["median_W_ratio"],
                    "H_mean_log": t["H_mean_log"], "W_mean_log": t["W_mean_log"],
                    "H_mean_sq_log": t["H_mean_sq_log"], "W_mean_sq_log": t["W_mean_sq_log"],
                    "e_H_track": math.sqrt(t["H_mean_sq_log"]), "e_W_track": math.sqrt(t["W_mean_sq_log"]),
                    "no_pool_frames": summary["no_pool_frames"], "peak_above_boiling_frames": sum(1 for f in t["frames"] if f["peak_above_boiling"]),
                }
            )
        out.append(row)
    return out


SUMMARY_KEYS = [
    "scored_frames", "tracks_scored", "e_H", "e_W", "J", "H_mean_sq_log", "W_mean_sq_log", "H_mean_log", "W_mean_log",
    "median_r_H", "median_r_W", "median_H_ratio", "median_W_ratio", "cam_H_px_median", "cam_W_px_median", "cam_HW_median",
    "sim_H_px_median_pool", "sim_W_px_median_pool", "sim_HW_median_pool", "no_pool_frames", "no_laser_associated_melt_frames",
    "zero_footprint_frames", "floored_frames", "peak_above_boiling_fraction", "median_peak_surface_K",
]
CI_KEYS = ["e_H", "e_W", "J", "median_H_ratio", "median_W_ratio"]


def _ci_columns(ci: Mapping[str, Any] | None) -> dict[str, Any]:
    out: dict[str, Any] = {"ci_unit": ci["unit"] if ci else None, "ci_replicates": ci["replicates"] if ci else None}
    for key in CI_KEYS:
        lo, hi = (ci["intervals"][key] if ci else (None, None))
        out[f"{key}_ci_lo"] = lo
        out[f"{key}_ci_hi"] = hi
    return out


def coupon_records(analysis: Mapping[str, Any], cis: Mapping[str, Any]) -> list[dict[str, Any]]:
    record = analysis["record"]
    by_member: dict[str, list] = {}
    for t in _track_records(analysis):
        by_member.setdefault(t["member"], []).append(t)
    out = []
    for member, row in analysis["coupons"].items():
        proc = record[member]
        tracks = [t for t in by_member[member] if t["scored_frames"]]
        excluded = sum(t["first_last_excluded_by_rule"] for t in by_member[member])
        undefined = sum(1 for f in analysis["frames"] if f["member"] == member and f["record_status"] == "UNDEFINED")
        eligible = sum(t["eligible"] for t in by_member[member])
        h_ratios = sorted(t["median_H_ratio"] for t in tracks)
        w_ratios = sorted(t["median_W_ratio"] for t in tracks)
        q = np.percentile
        out.append(
            {
                "member": member, "acquisition_set": proc["acquisition_set"], "acquisition_date": proc["acquisition_date"],
                "part": proc["part"], "condition": proc["condition"], "power_W": proc["power_W"], "speed_mm_s": proc["speed_mm_s"],
                "ved_J_mm3": proc["ved_J_mm3"], "role": C.ROLE[member], "a8_role": "held_out" if member in C.A8_HELD_OUT else "calibration",
                "eligible_frames": eligible, "excluded_by_rule": excluded, "undefined_frames": undefined,
                "coverage": row["scored_frames"] / (eligible - excluded),
                **{key: row[key] for key in SUMMARY_KEYS},
                "cam_H_um_median": C.UM_PER_PX * row["cam_H_px_median"], "cam_W_um_median": C.UM_PER_PX * row["cam_W_px_median"],
                "sim_H_um_median_pool": C.UM_PER_PX * row["sim_H_px_median_pool"], "sim_W_um_median_pool": C.UM_PER_PX * row["sim_W_px_median_pool"],
                "no_pool_fraction": row["no_pool_frames"] / row["scored_frames"],
                "track_median_H_ratio_p25": float(q(h_ratios, 25)), "track_median_H_ratio_p75": float(q(h_ratios, 75)),
                "track_median_W_ratio_p25": float(q(w_ratios, 25)), "track_median_W_ratio_p75": float(q(w_ratios, 75)),
                **_ci_columns(cis["coupons"].get(member)),
            }
        )
    return out


def condition_group_records(analysis: Mapping[str, Any], cis: Mapping[str, Any]) -> list[dict[str, Any]]:
    record = analysis["record"]
    rows = []
    for cid, row in analysis["conditions"].items():
        members = row["members"]
        rows.append(
            {
                "level": "condition", "name": cid, "role": C.ROLE[members[0]], "members": " ".join(members),
                "coupons": row["coupons"], "conditions": 1, "power_W": record[members[0]]["power_W"],
                "speed_mm_s": record[members[0]]["speed_mm_s"], "ved_J_mm3": record[members[0]]["ved_J_mm3"],
                "weighting": "unweighted mean over replicate coupons of coupon mean-square (coupon = mean over tracks)",
                **{key: row[key] for key in SUMMARY_KEYS},
                **_ci_columns(cis["conditions"].get(cid)),
            }
        )
    for name, row in analysis["groups"].items():
        rows.append(
            {
                "level": "group", "name": name, "role": None, "members": " ".join(row["members"]),
                "coupons": row["coupons"], "conditions": row["conditions"], "power_W": None, "speed_mm_s": None, "ved_J_mm3": None,
                "weighting": "contract 22.4.3.2 hierarchy: track -> coupon -> condition -> group, each an unweighted mean",
                **{key: row[key] for key in SUMMARY_KEYS},
                **_ci_columns(cis["groups"].get(name)),
                "description": row["description"],
            }
        )
    return rows


def exclusion_ledger(analysis: Mapping[str, Any]) -> list[dict[str, Any]]:
    """D7: every frame record that is not a scored frame with a predicted pool, with its reason."""

    out = []
    for row in analysis["frames"]:
        if row["scored"] and not row["no_pool"]:
            continue
        if row["scored"]:
            reason, category = row["production_status"], "scored_no_pool_prediction (D1: scored as H = W = 0)"
        elif row["exclusion_reason"] == "NOT_ELIGIBLE":
            reason, category = f"NOT_ELIGIBLE:{row['observation_status']}", "camera_ineligible (never entered residuals)"
        else:
            reason, category = row["exclusion_reason"], "excluded_by_rule (A22 scored-frame rule)"
        out.append(
            {
                "member": row["member"], "role": row["role"], "condition": row["condition"], "scan_track_id": row["scan_track_id"],
                "frame_index": row["frame_index"], "process_row": row.get("process_row"), "track_position": row["track_position"],
                "track_eligible_frames": row["track_eligible_frames"], "reason": reason, "category": category,
                "scored": row["scored"], "cam_H_px": row["cam_H_px"], "cam_W_px": row["cam_W_px"],
            }
        )
    return out


def write(analysis: Mapping[str, Any], cis: Mapping[str, Any]) -> dict[str, Any]:
    data = C.DATA_DIR
    d1 = []
    for row in analysis["scored"]:
        d1.append({**{k: row.get(k) for k in D1_FIELDS if k not in C.VERSIONS}, **C.VERSIONS})
    paths = {
        "D1": C.write_csv(data / "D1_frames.csv.gz", d1, D1_FIELDS),
        "D2": C.write_csv(data / "D2_tracks.csv", _track_records(analysis)),
        "D3": C.write_csv(data / "D3_coupons.csv", coupon_records(analysis, cis)),
        "D4": C.write_csv(data / "D4_conditions_groups.csv", condition_group_records(analysis, cis)),
        "D7": C.write_csv(data / "D7_exclusion_ledger.csv", exclusion_ledger(analysis)),
    }
    return paths
