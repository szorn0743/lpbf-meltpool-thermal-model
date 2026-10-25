"""Pass-1 tables (T1-T4, T6-T8, T11, T13, T17 and the confound table) as Markdown and full-precision CSV."""
from __future__ import annotations

import math
from collections import Counter
from typing import Any, Callable, Mapping, Sequence

import common as C
import confounds
from build_datasets import coupon_records, condition_group_records

Column = tuple[str, str, Callable[[Mapping[str, Any]], Any]]


# ---------------------------------------------------------------------- formatting


def f(value: Any, digits: int = 3) -> str:
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return "–"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:,.{digits}f}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def ci(row: Mapping[str, Any], key: str, digits: int = 3) -> str:
    point = f(row.get(key), digits)
    lo, hi = row.get(f"{key}_ci_lo"), row.get(f"{key}_ci_hi")
    return point if lo is None else f"{point} [{f(lo, digits)}, {f(hi, digits)}]"


def md_table(rows: Sequence[Mapping[str, Any]], columns: Sequence[Column]) -> str:
    head = "| " + " | ".join(c[1] for c in columns) + " |"
    rule = "|" + "|".join("---" for _ in columns) + "|"
    body = ["| " + " | ".join(str(c[2](r)).replace("|", "/") for c in columns) + " |" for r in rows]
    return "\n".join([head, rule, *body])


def write_table(name: str, title: str, intro: Sequence[str], sections: Sequence[tuple[str | None, Sequence[Mapping[str, Any]], Sequence[Column]]], notes: Sequence[str], csv_rows: Sequence[Mapping[str, Any]]) -> list:
    lines = [f"# {title}", "", *intro, ""]
    for heading, rows, columns in sections:
        if heading:
            lines += [f"## {heading}", ""]
        lines += [md_table(rows, columns), ""]
    if notes:
        lines += ["**Notes.**", "", *[f"- {n}" for n in notes], ""]
    md = C.TABLES_DIR / f"{name}.md"
    md.parent.mkdir(parents=True, exist_ok=True)
    md.write_text("\n".join(lines), encoding="utf-8")
    return [md, C.write_csv(C.TABLES_DIR / f"{name}.csv", csv_rows)]


ROLE_SHORT = {"calibration": "calibration", "in_window_held_out": "in-window held out", "out_of_window_examined": "out, examined", "out_of_window_blind": "out, blind"}


# ---------------------------------------------------------------------- T1


def t1() -> list:
    rows = [
        ("Camera H, W", "Length (along the blob's long axis) and width of the minimum-area rectangle around the coaxial camera's threshold-150 blob, as supplied with the data, in camera pixels (H >= W).", "A12, A24"),
        ("Model H, W", "Length and width of the minimum-area rectangle around the interpolated liquidus contour of the liquid component receiving the largest share of the beam's deposited power (floor 2 %), converted to camera pixels.", "A2, A21"),
        ("Units", "Pixels are the native unit. Micrometres use the nominal 8 um/px, which no calibration validates; absolute sizes and size ratios depend on it, shapes (H/W), slopes and rank correlations do not.", "A24"),
        ("Log residual", "r_H = ln(max(H_model, 1) / max(H_camera, 1)), r_W likewise, per scored frame; ratio = exp(r). The 1 px floor keeps a zero prediction finite.", "A26"),
        ("e_H, e_W", "Hierarchical log-RMS error: square root of the hierarchical mean of r^2 (frame -> track -> coupon -> condition -> group).", "A26"),
        ("J", "0.5 e_H^2 + 0.5 e_W^2 over a group's conditions; the calibration objective on the 5 calibration conditions.", "A26"),
        ("Median ratio", "Median over the pooled scored frames of exp(r); descriptive, never an objective weight.", "log_ratio_objective"),
        ("Hierarchy and weights", "Each level is an unweighted mean of the level below: every track counts equally within its coupon, every coupon within its condition, every condition within its group, whatever their frame counts.", "A10"),
        ("Eligible frame", "A camera frame that the sync maps to a powered scan-track row and whose camera H/W is finite and non-zero.", "A22"),
        ("Scored frame", "An eligible frame that is not the first or last eligible frame of its scan track (and not the only frame of a one-frame track).", "A22 (D2)"),
        ("NO_LASER_ASSOCIATED_MELT, ZERO_FOOTPRINT", "No liquid component receives >= 2 % of the beam's power, or no liquid exists in the window: a model prediction, scored as H = W = 0 (floored to 1 px). Called 'no-pool' frames here.", "A21 (D1)"),
        ("Undefined frame", "Tied shares, an unenclosed selected contour or unavailable source geometry: excluded and counted, never fabricated. None occurred for confirm_c1.", "A21, A23"),
        ("Coverage", "scored / (eligible - excluded by rule), per coupon; floor 95 %.", "A23 (D3)"),
        ("Inferential unit", "Coupons (24) and conditions (18), not frames (24,129 scored). Frame and track counts describe precision inside a coupon only.", "this package"),
        ("Confidence intervals", "95 % percentile bootstrap, 4,000 replicates. Groups of >= 2 coupons: coupons resampled within the group. Single coupons and conditions: tracks resampled within each coupon (within-coupon uncertainty only).", "METHODS_MANIFEST.json"),
        ("VED", "P / (v * 0.080 mm * 0.030 mm), J/mm3; calibration window [65, 85].", "A17, A25"),
    ]
    data = [{"term": a, "definition": b, "source": c} for a, b, c in rows]
    cols = [("term", "Term", lambda r: r["term"]), ("definition", "Definition", lambda r: r["definition"]), ("source", "Ledger / source", lambda r: r["source"])]
    return write_table("T01_definitions", "Definitions and conventions", ["Conventions used by every table and figure in this package. Ledger entries (A*) are in `docs/DECISIONS.md`."], [(None, data, cols)], [], data)


# ---------------------------------------------------------------------- T2, T3


def t2(analysis: Mapping[str, Any], d3: Sequence[Mapping[str, Any]]) -> list:
    set_roles = C.acquisition_set_roles()
    conditions = Counter(r["condition"] for r in analysis["record"].values())
    rows = []
    for r in d3:
        rows.append(
            {
                "member": r["member"], "acquisition_date": r["acquisition_date"], "set_design": set_roles[r["acquisition_set"]],
                "part": r["part"], "power_W": r["power_W"], "speed_mm_s": r["speed_mm_s"], "ved_J_mm3": r["ved_J_mm3"],
                "condition": r["condition"], "replicate_pair": "0730/0731 pair" if conditions[r["condition"]] == 2 else "single",
                "a8_role": r["a8_role"], "a25_role": r["role"], "tracks_scored": r["tracks_scored"], "scored_frames": r["scored_frames"],
            }
        )
    cols = [
        ("member", "Coupon", lambda r: r["member"]), ("date", "Acquired", lambda r: r["acquisition_date"]),
        ("P", "P (W)", lambda r: f(r["power_W"], 0)), ("v", "v (mm/s)", lambda r: f(r["speed_mm_s"], 0)),
        ("VED", "VED (J/mm3)", lambda r: f(r["ved_J_mm3"], 1)), ("rep", "Replicate", lambda r: r["replicate_pair"]),
        ("a8", "A8 role", lambda r: r["a8_role"]), ("a25", "Analysis role (A25)", lambda r: ROLE_SHORT[r["a25_role"]]),
        ("tracks", "Tracks scored", lambda r: r["tracks_scored"]), ("frames", "Scored frames", lambda r: f(r["scored_frames"])),
    ]
    notes = [
        "P, v and spot size (0.08 mm for all) are the read-only A17 record; VED is computed with hatch 0.080 mm and layer 0.030 mm and reproduces the record's rounded values.",
        "Set designs (dataset manifest): " + "; ".join(f"{k} {v}" for k, v in sorted(set_roles.items())) + ".",
        "All observations are from layer 53. Each coupon has 54 scan tracks in the layer.",
    ]
    return write_table("T02_coupon_roster", "Coupon roster", ["Every coupon, its process condition, and its role in the calibration study."], [(None, rows, cols)], notes, rows)


def t3(analysis: Mapping[str, Any]) -> list:
    record = analysis["record"]
    register = C.load_json(C.REGISTERS_DIR / "data_use_history.json")
    stages = register["stages"]
    roles = []
    status = {
        "calibration": "Compared with the model by 22.3.8 (all 9) and used for selection (22.4.3.2 calibrate/confirm).",
        "in_window_held_out": "Not read by any stage from 22.4.3 to the freeze; first compared at evaluate, after the committed freeze. Now opened (A8, A27).",
        "out_of_window_examined": "Compared with the model by 22.3.8 (A8 calibration members); not used for 22.4.3.2 selection.",
        "out_of_window_blind": "Not read by any stage from 22.4.3 to the freeze; first compared at evaluate. Now opened (A8, A27).",
    }
    for role, members in C.ROLE_MEMBERS.items():
        conds = sorted({record[m]["condition"] for m in members}, key=lambda c: next(record[m]["ved_J_mm3"] for m in members if record[m]["condition"] == c))
        veds = [record[m]["ved_J_mm3"] for m in members]
        roles.append(
            {
                "role": C.ROLE_LABEL[role], "coupons": len(members), "conditions": len(conds), "members": ", ".join(members),
                "condition_ids": ", ".join(conds), "ved_min": min(veds), "ved_max": max(veds),
                "a8_origin": "held out" if members[0] in C.A8_HELD_OUT else "calibration", "status_at_freeze": status[role],
            }
        )
    cols = [
        ("role", "Group", lambda r: r["role"]), ("n", "Coupons", lambda r: r["coupons"]), ("c", "Conditions", lambda r: r["conditions"]),
        ("ved", "VED (J/mm3)", lambda r: f"{r['ved_min']:.1f}–{r['ved_max']:.1f}"), ("a8", "A8 origin", lambda r: r["a8_origin"]),
        ("members", "Coupons", lambda r: r["members"]), ("status", "Data status at the selection freeze (d01ac72)", lambda r: r["status_at_freeze"]),
    ]
    freeze_stages = {"S01", "S02", "S03", "S04", "S05", "S06", "S08", "S09", "S11", "S12", "S13", "S14", "S16", "S18", "S19"}
    window_stages = {"S12", "S13", "S14", "S16"}
    history = []
    for member in sorted(C.ROLE, key=C.member_key):
        ids = register["members"][member]
        compared_before = [s for s in ids if s in freeze_stages and stages[s]["compared"]]
        history.append(
            {
                "member": member, "a25_role": ROLE_SHORT[C.ROLE[member]], "stages": " ".join(ids),
                "descriptive_camera_summary_2026_10_12": "S01" in ids,
                "examined_by_22_3_8_before_window_choice": any(s in window_stages for s in ids),
                "model_compared_before_freeze": bool(compared_before),
                "first_model_comparison": next((f"{stages[s]['patch']} {stages[s]['stage']} ({stages[s]['date'][:10]})" for s in ids if stages[s]["compared"]), None),
                "used_for_22_4_3_2_selection": "S19" in ids,
            }
        )
    hcols = [
        ("member", "Coupon", lambda r: r["member"]), ("role", "Role", lambda r: r["a25_role"]),
        ("s01", "21.3 summary", lambda r: f(r["descriptive_camera_summary_2026_10_12"])),
        ("w", "Examined by 22.3.8 before window", lambda r: f(r["examined_by_22_3_8_before_window_choice"])),
        ("c", "Model-compared before freeze", lambda r: f(r["model_compared_before_freeze"])),
        ("sel", "Used in selection", lambda r: f(r["used_for_22_4_3_2_selection"])),
        ("first", "First model comparison", lambda r: r["first_model_comparison"]), ("stages", "Stages (register)", lambda r: r["stages"]),
    ]
    stage_rows = [{"id": k, **v} for k, v in stages.items()]
    scols = [
        ("id", "Stage", lambda r: r["id"]), ("patch", "Patch", lambda r: r["patch"]), ("stage", "What", lambda r: r["stage"]),
        ("date", "Date", lambda r: r["date"] or "not recorded"), ("cmp", "Model compared", lambda r: f(r["compared"])),
        ("purpose", "Purpose", lambda r: r["purpose"]), ("commit", "Commit", lambda r: r["commit"]),
    ]
    notes = [
        "**All eight A8 held-out members (in-window held out and blind) were opened by the Patch 22.4.3.2 evaluation after its selection freeze. They must not be reused for fitting or selection; any later use is no longer held-out validation (A8, A27).**",
        *register["findings"],
        "Source: `registers/data_use_history.json` (compiled from the stage manifests and git history).",
    ]
    files = write_table(
        "T03_partition_and_data_use",
        "Partition and data-use history",
        ["The A25 partition and, per coupon, which stage read its experimental data and when. This makes the 'examined' versus 'blind' distinction auditable."],
        [("Partition", roles, cols), ("Data use per coupon", history, hcols), ("Stage catalogue", stage_rows, scols)],
        notes,
        history,
    )
    files.append(C.write_csv(C.TABLES_DIR / "T03_partition.csv", roles))
    return files


# ---------------------------------------------------------------------- T4, T13


def accounting_rows(analysis: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = []
    frames_by = {}
    for r in analysis["frames"]:
        frames_by.setdefault(r["member"], []).append(r)
    for member in sorted(C.ROLE, key=C.member_key):
        audit = C.characterization_audit(member)
        sync = audit["camera_sync"]
        fr = frames_by[member]
        reasons = Counter(r["exclusion_reason"] for r in fr)
        eligible = sum(1 for r in fr if r["exclusion_reason"] != "NOT_ELIGIBLE")
        excluded = reasons["EXCLUDED_TRACK_FIRST"] + reasons["EXCLUDED_TRACK_LAST"] + reasons["EXCLUDED_TRACK_SINGLE_FRAME"]
        undefined = sum(1 for r in fr if r["record_status"] == "UNDEFINED")
        scored = sum(1 for r in fr if r["scored"])
        if eligible != sync["eligible_melt_pool_frame_count"]:
            raise RuntimeError(f"{member}: eligible {eligible} != characterization {sync['eligible_melt_pool_frame_count']}")
        if eligible - excluded - undefined != scored:
            raise RuntimeError(f"{member}: eligible - excluded - undefined != scored")
        no_pool = sum(1 for r in fr if r["scored"] and r["no_pool"])
        tracks_scored = len({r["scan_track_id"] for r in fr if r["scored"]})
        rows.append(
            {
                "member": member, "role": C.ROLE[member], "condition": analysis["record"][member]["condition"],
                "raw_camera_frames_layer": sync["raw_camera_frame_count"], "sync_mapped_frames": sync["synchronization_valid_frame_count"],
                "laser_on_mapped_frames": sync["laser_on_mapped_frame_count"],
                "camera_ineligible_frames": sync["laser_on_mapped_frame_count"] - eligible, "eligible_frames": eligible,
                "excluded_track_first": reasons["EXCLUDED_TRACK_FIRST"], "excluded_track_last": reasons["EXCLUDED_TRACK_LAST"],
                "excluded_single_frame_track": reasons["EXCLUDED_TRACK_SINGLE_FRAME"], "excluded_by_rule": excluded,
                "undefined_frames": undefined, "scored_frames": scored, "no_pool_frames": no_pool,
                "coverage": scored / (eligible - excluded), "scan_tracks_layer": audit["laser_state"]["scan_track_count"],
                "observation_bearing_tracks": audit["laser_state"]["observation_bearing_track_count"], "tracks_scored": tracks_scored,
                "conditions": 1,
            }
        )
    return rows


def _total(rows: Sequence[Mapping[str, Any]], name: str, keys: Sequence[str]) -> dict[str, Any]:
    out = {"member": name, "role": "", "condition": ""}
    for k in keys:
        out[k] = sum(r[k] for r in rows)
    return out


def t4(analysis: Mapping[str, Any]) -> list:
    rows = accounting_rows(analysis)
    keys = ["sync_mapped_frames", "laser_on_mapped_frames", "camera_ineligible_frames", "eligible_frames", "excluded_track_first", "excluded_track_last", "excluded_single_frame_track", "excluded_by_rule", "undefined_frames", "scored_frames", "no_pool_frames", "tracks_scored"]
    total = _total(rows, "All 24 coupons", keys)
    total["coverage"] = total["scored_frames"] / (total["eligible_frames"] - total["excluded_by_rule"])
    total["conditions"] = 18
    total["raw_camera_frames_layer"] = None
    cols = [
        ("member", "Coupon", lambda r: r["member"]), ("role", "Role", lambda r: ROLE_SHORT.get(r["role"], "")),
        ("raw", "Raw frames (layer)", lambda r: f(r["raw_camera_frames_layer"])), ("map", "Sync-mapped", lambda r: f(r["sync_mapped_frames"])),
        ("on", "Laser-on mapped", lambda r: f(r["laser_on_mapped_frames"])), ("inel", "Camera-invalid", lambda r: f(r["camera_ineligible_frames"])),
        ("el", "Eligible", lambda r: f(r["eligible_frames"])), ("ex", "Excluded first / last / single", lambda r: f"{r['excluded_track_first']} / {r['excluded_track_last']} / {r['excluded_single_frame_track']}"),
        ("und", "Undefined", lambda r: f(r["undefined_frames"])), ("sc", "Scored", lambda r: f(r["scored_frames"])),
        ("np", "No-pool (scored as 0)", lambda r: f(r["no_pool_frames"])), ("cov", "Coverage", lambda r: f(r["coverage"], 3)),
        ("tr", "Tracks scored", lambda r: f(r["tracks_scored"])),
    ]
    notes = [
        "Identity checked for every coupon: eligible − excluded by rule − undefined = scored; eligible equals the Patch 21.3 characterization count.",
        "Raw frames are the whole layer's camera stream, shared by the six coupons of a set; sync-mapped frames are those the sync maps to this coupon's process rows (laser on or off).",
        "Camera-invalid: laser-on mapped frames whose camera H/W is non-finite (3 frames, track 54 of 20260904:part_6 and 20260910:part_6); they never enter residuals.",
        "No-pool frames are scored model predictions (D1), not exclusions; they are listed in D7 with the excluded frames.",
        "Frame-level ledger: `data/D7_exclusion_ledger.csv` (reconciles exactly with this table; test `test_committee_package.py`).",
    ]
    return write_table("T04_data_accounting", "Data accounting", ["Every camera frame from the layer stream down to the scored frames, per coupon. Nothing is removed silently."], [(None, rows + [total], cols)], notes, rows + [total])


def crop_contact_counts() -> dict[str, int]:
    counts: Counter = Counter()
    for row in C.read_csv(C.SYNTHETIC_FRAMES):
        if row["case_id"] == "lam850_uniform_sig0.0" and row["synthetic_status"] == "CAMERA_BLOB_150_ABSENT_OR_EDGE":
            counts[row["member_identity"]] += 1
    return counts


def t13(analysis: Mapping[str, Any]) -> list:
    acc = {r["member"]: r for r in accounting_rows(analysis)}
    crop = crop_contact_counts()
    rows = []
    for member in sorted(C.ROLE, key=C.member_key):
        fr = analysis["frames_by_member"][member]
        a = acc[member]
        n = a["scored_frames"]
        statuses = Counter(r["production_status"] for r in fr)
        unexpected = set(statuses) - {"SELECTED", *C.NO_POOL_STATUSES}
        if unexpected:
            raise RuntimeError(f"{member}: unexpected production statuses {unexpected}")
        rows.append(
            {
                "member": member, "role": C.ROLE[member], "condition": a["condition"], "ved_J_mm3": analysis["record"][member]["ved_J_mm3"],
                "eligible_frames": a["eligible_frames"], "scored_frames": n,
                "no_laser_associated_melt": statuses["NO_LASER_ASSOCIATED_MELT"], "zero_footprint": statuses["ZERO_FOOTPRINT"],
                "no_pool_pct": 100.0 * (statuses["NO_LASER_ASSOCIATED_MELT"] + statuses["ZERO_FOOTPRINT"]) / n,
                "tied_or_ambiguous_share": 0, "unenclosed_contour": 0, "boundary_contact": 0, "geometry_unavailable": 0,
                "timing_exclusion_first_last": a["excluded_by_rule"], "timing_exclusion_pct_of_eligible": 100.0 * a["excluded_by_rule"] / a["eligible_frames"],
                "camera_invalid_hw": a["camera_ineligible_frames"], "camera_crop_contact_or_absent_150": crop[member],
                "peak_above_boiling": sum(1 for r in fr if r["peak_above_boiling"]),
                "peak_above_boiling_pct": 100.0 * sum(1 for r in fr if r["peak_above_boiling"]) / n,
            }
        )
    keys = ["eligible_frames", "scored_frames", "no_laser_associated_melt", "zero_footprint", "tied_or_ambiguous_share", "unenclosed_contour", "boundary_contact", "geometry_unavailable", "timing_exclusion_first_last", "camera_invalid_hw", "camera_crop_contact_or_absent_150", "peak_above_boiling"]
    totals = []
    for role, members in [*C.ROLE_MEMBERS.items(), ("all", tuple(C.ROLE))]:
        sub = [r for r in rows if r["member"] in members]
        t = _total(sub, C.ROLE_LABEL.get(role, "All 24 coupons"), keys)
        t["no_pool_pct"] = 100.0 * (t["no_laser_associated_melt"] + t["zero_footprint"]) / t["scored_frames"]
        t["timing_exclusion_pct_of_eligible"] = 100.0 * t["timing_exclusion_first_last"] / t["eligible_frames"]
        t["peak_above_boiling_pct"] = 100.0 * t["peak_above_boiling"] / t["scored_frames"]
        t["ved_J_mm3"] = None
        totals.append(t)
    cols = [
        ("member", "Coupon / group", lambda r: r["member"]), ("ved", "VED", lambda r: f(r["ved_J_mm3"], 1)),
        ("sc", "Scored", lambda r: f(r["scored_frames"])),
        ("nlam", "No laser-assoc. melt", lambda r: f(r["no_laser_associated_melt"])), ("zf", "Zero footprint", lambda r: f(r["zero_footprint"])),
        ("np", "No-pool %", lambda r: f(r["no_pool_pct"], 1)),
        ("und", "Tied / unenclosed / boundary / geometry", lambda r: f"{r['tied_or_ambiguous_share']} / {r['unenclosed_contour']} / {r['boundary_contact']} / {r['geometry_unavailable']}"),
        ("tim", "Timing exclusion (first/last)", lambda r: f"{r['timing_exclusion_first_last']} ({r['timing_exclusion_pct_of_eligible']:.1f} %)"),
        ("cam", "Camera invalid H/W", lambda r: f(r["camera_invalid_hw"])), ("crop", "Camera blob absent or at crop edge", lambda r: f(r["camera_crop_contact_or_absent_150"])),
        ("boil", "Peak > 3133 K", lambda r: f"{r['peak_above_boiling']} ({r['peak_above_boiling_pct']:.1f} %)"),
    ]
    notes = [
        "Undefined classes (tied or ambiguous share, unenclosed contour, boundary contact, unavailable geometry) never occurred for confirm_c1: every scored frame is SELECTED, NO_LASER_ASSOCIATED_MELT or ZERO_FOOTPRINT. They are shown as zero counts, not omitted.",
        "No-pool frames (no laser-associated melt, zero footprint) are model predictions scored as H = W = 0 (D1), floored to 1 px; percentages are of scored frames.",
        "Timing exclusion is the A22 rule (first and last eligible frame of each track); percentages are of eligible frames.",
        "Camera blob absent or at crop edge: the Patch 22.4.3.2 reading-S re-measurement of the camera image at threshold 150 on scored frames (`synthetic_frames.csv.gz`, case 850 nm, sigma 0). It is a camera-side diagnostic; the supplied camera H/W are still scored on these frames.",
        "Peak above boiling: frames whose model peak surface temperature exceeds 3133 K (fixed boiling regulator, A27 failure mode).",
    ]
    data = rows + totals
    return write_table("T13_failure_modes", "Failure modes and coverage", ["Every non-ideal observation of confirm_c1, by coupon and by group."], [("By coupon", rows, cols), ("By group", totals, cols)], notes, data)


# ---------------------------------------------------------------------- T6


def t6() -> list:
    from lpbf.calibration_contract import _abs_depth_mapping

    reading = C.load_json(C.CALIBRATION_READING)
    calibrate = C.load_json(C.CALIBRATE_MANIFEST)["scores"]
    confirm = C.load_json(C.CONFIRM_MANIFEST)["scores"]
    for cid, score in reading["scores"].items():
        ref = calibrate.get(cid) or confirm[cid]
        if any(score[k] != ref[k] for k in ("J", "e_H", "e_W")):
            raise RuntimeError(f"{cid}: calibration reading disagrees with its stage manifest")
    rank = {r["candidate_id"]: i + 1 for i, r in enumerate(reading["selection"]["ranking"])}
    near = {c["candidate_id"] for c in C.load_json(C.SELECTION_FREEZE)["near_best"]}
    predicted = {c["candidate_id"]: c["predicted_J"] for c in reading["surrogate"]["confirmation_candidates"]}
    rows = []
    for cand in reading["candidates"]:
        cid = cand["candidate_id"]
        s = reading["scores"][cid]
        t = cand["coordinates"]["abs_depth_identifiable_coordinate"]
        absorptivity, depth = _abs_depth_mapping(t)
        rows.append(
            {
                "rank": rank[cid], "candidate": cid, "origin": cand["origin"], "t": t,
                "ck": cand["coordinates"]["liquid_conductivity_enhancement_factor"], "eta": cand["coordinates"]["eta_directional"],
                "coded_x1": cand["coded"][0], "coded_x2": cand["coded"][1], "coded_x3": cand["coded"][2],
                "absorptivity": absorptivity, "deposition_depth_mm": depth, "guard_value": cand["guard_value"],
                "coverage": s["coverage"], "coverage_flag": s["coverage_flag"], "no_pool_frames": s["zero_prediction_frame_count"],
                "floored_frames": s["floored_frame_count"], "peak_above_boiling_fraction": s["fraction_peak_above_boiling"],
                "median_peak_surface_K": s["median_peak_surface_K"], "e_H": s["e_H"], "e_W": s["e_W"], "J": s["J"],
                "J_pixel_objective_22_3_7": s["sensitivity"]["pixel_22_3_7"], "surrogate_predicted_J": predicted.get(cid),
                "near_best": cid in near, "selected": cid == C.CANDIDATE,
            }
        )
    rows.sort(key=lambda r: r["rank"])
    cols = [
        ("rank", "Rank", lambda r: r["rank"]), ("cand", "Candidate", lambda r: ("**" + r["candidate"] + "**") if r["selected"] else r["candidate"]),
        ("t", "t", lambda r: f(r["t"], 2)), ("ck", "ck", lambda r: f(r["ck"], 3)), ("eta", "η", lambda r: f(r["eta"], 2)),
        ("abs", "Absorptivity", lambda r: f(r["absorptivity"], 3)), ("dep", "Depth (mm)", lambda r: f(r["deposition_depth_mm"], 3)),
        ("g", "Guard", lambda r: f(r["guard_value"], 3)), ("cov", "Coverage", lambda r: f(r["coverage"], 3)),
        ("np", "No-pool frames", lambda r: r["no_pool_frames"]), ("boil", "Peak > boiling", lambda r: f"{100 * r['peak_above_boiling_fraction']:.1f} %"),
        ("eh", "e_H", lambda r: f(r["e_H"])), ("ew", "e_W", lambda r: f(r["e_W"])), ("j", "J", lambda r: f(r["J"])),
        ("jp", "J (pixel 22.3.7)", lambda r: f(r["J_pixel_objective_22_3_7"], 1)), ("nb", "Near-best", lambda r: f(r["near_best"])),
    ]
    sel = next(r for r in rows if r["selected"])
    surrogate = C.load_json(C.SELECTION_FREEZE)["surrogate"]
    notes = [
        f"Selected: {C.CANDIDATE} by the lowest measured J ({sel['J']:.4f}); near-best set J <= 1.10 J_min. Quadratic surrogate over the 17 design points: R² {surrogate['r_squared']:.5f}, leave-one-out RMSE {surrogate['loo_rmse']:.4f}; it predicted J {predicted['confirm_c1']:.4f} at c1 and {predicted['confirm_c2']:.4f} at c2. The surrogate proposes; it never selects.",
        "Reading C_EDGE: t and η are at their bounds (coded |x| >= 0.9); the guard value 0.724 is below the 0.9025 edge threshold. The box was not widened (A9, A25).",
        "Absorptivity and deposition depth are derived from t by `_abs_depth_mapping` (`src/lpbf/calibration_contract.py:124-140`); they are not stored in the manifests. ck is the liquid-conductivity enhancement factor; η the directional factor.",
        "Each candidate is scored on the 9 calibration members (8,943 scored frames). J (pixel 22.3.7) is the superseded A10 objective, reported as a sensitivity only (S11).",
        "Values equal `calibrate/stage_manifest.json` (17 design candidates) and `confirm/stage_manifest.json` (2 confirmation candidates) exactly; checked at build time.",
    ]
    return write_table("T06_candidate_search", "Calibration candidate search", ["All 17 frozen design candidates and the 2 confirmation candidates, ranked by measured J."], [(None, rows, cols)], notes, rows)


# ---------------------------------------------------------------------- T7, T8


PERF_COLS: list[Column] = [
    ("name", "Level / unit", lambda r: r["_label"]), ("ved", "VED", lambda r: f(r.get("ved_J_mm3"), 1)),
    ("n", "Coupons / tracks / frames", lambda r: f"{r.get('coupons', 1)} / {r['tracks_scored']} / {r['scored_frames']:,}"),
    ("cam", "Camera H × W (µm)", lambda r: f"{C.UM_PER_PX * r['cam_H_px_median']:.0f} × {C.UM_PER_PX * r['cam_W_px_median']:.0f}"),
    ("sim", "Model H × W (µm, pool frames)", lambda r: f"{C.UM_PER_PX * r['sim_H_px_median_pool']:.0f} × {C.UM_PER_PX * r['sim_W_px_median_pool']:.0f}"),
    ("hr", "H ratio", lambda r: ci(r, "median_H_ratio", 2)), ("wr", "W ratio", lambda r: ci(r, "median_W_ratio", 2)),
    ("eh", "e_H", lambda r: ci(r, "e_H")), ("ew", "e_W", lambda r: ci(r, "e_W")), ("j", "J", lambda r: ci(r, "J")),
    ("np", "No-pool frames", lambda r: r["no_pool_frames"]), ("u", "CI unit", lambda r: {"coupon": "coupons", "track_within_coupon": "tracks"}.get(r.get("ci_unit"), "–")),
]


def _perf_rows(role: str, d3, d4, extra_groups: Sequence[str]) -> list[dict[str, Any]]:
    group_rows = {r["name"]: r for r in d4 if r["level"] == "group"}
    cond_rows = [r for r in d4 if r["level"] == "condition" and r["role"] == role]
    rows = [{**group_rows[role], "_label": f"**Pooled {C.ROLE_LABEL[role].lower()}**", "_level": "group"}]
    for name in extra_groups:
        rows.append({**group_rows[name], "_label": name.split("__")[-1].replace("set_", "set ").replace("cross_campaign_", ""), "_level": "group"})
    for r in cond_rows:
        rows.append({**r, "_label": f"{r['name']} ({r['coupons']} coupon{'s' if r['coupons'] > 1 else ''})", "_level": "condition"})
    for r in d3:
        if r["role"] == role:
            rows.append({**r, "coupons": 1, "_label": r["member"], "_level": "coupon"})
    return rows


def t7(d3, d4) -> list:
    rows = _perf_rows("calibration", d3, d4, ["calibration__set_20260730", "calibration__set_20260731", "calibration__set_20260910"])
    notes = [
        "Pooled values equal the evaluate manifest (`calibration_score_selected`) exactly: J 0.298, e_H 0.651, e_W 0.416.",
        "Ratios are model/camera medians over pooled scored frames (no-pool frames included as floored zeros); µm sizes are medians at the nominal 8 µm/px (A24), model sizes over frames with a predicted pool.",
        "CI unit 'coupons': coupons resampled within the group (9 coupons; with 4 or fewer coupons the interval is coarse). 'tracks': tracks resampled within each coupon, so the interval reflects within-coupon sampling only. 95 % percentile, 4,000 replicates.",
        "Acquisition-set rows apply the same hierarchy to that set's calibration coupons (replicate groups 0730, 0731; 0910 is the off-line P140_V700 coupon).",
        "Coverage is 1.000 for every coupon (T4).",
    ]
    return write_table("T07_calibration_performance", "Calibration performance", ["Calibration fit of the selected candidate on its 9 calibration coupons."], [(None, rows, PERF_COLS)], notes, [{k: v for k, v in r.items() if not k.startswith("_")} | {"level": r["_level"]} for r in rows])


def t8(d3, d4, ratios: Mapping[str, Any]) -> list:
    rows = _perf_rows("in_window_held_out", d3, d4, ["in_window_held_out__set_20260730", "in_window_held_out__set_20260731", "cross_campaign_20260904_part_5"])
    vrows = []
    for key, item in ratios.items():
        name, q = key.split("__")
        vrows.append(
            {
                "comparison": {"held_out_over_calibration": "Held out / calibration", "part_5_over_calibration": "20260904:part_5 / calibration"}[name],
                "quantity": q, "ratio": item["point"], "ci_lo": item["ci"][0], "ci_hi": item["ci"][1],
                "share_of_draws_at_or_below_1_25": item["share_at_or_below_1_25"], "resampling_unit": item["unit"],
                "predeclared_threshold": 1.25, "reading": "pass" if item["point"] <= 1.25 else "fail",
            }
        )
    vcols = [
        ("cmp", "Comparison", lambda r: r["comparison"]), ("q", "Error", lambda r: r["quantity"]),
        ("ratio", "Ratio [95 % CI]", lambda r: f"{r['ratio']:.3f} [{r['ci_lo']:.3f}, {r['ci_hi']:.3f}]"),
        ("thr", "Predeclared limit", lambda r: "≤ 1.25"), ("p", "Bootstrap share ≤ 1.25", lambda r: f"{r['share_of_draws_at_or_below_1_25']:.3f}"),
        ("unit", "Resampling", lambda r: r["resampling_unit"]),
    ]
    notes = [
        "Pooled held-out values equal the evaluate manifest (`readings.V.confirm_c1.held_out`) exactly; reading V_PASS was declared on the point ratios (plan, A27). The intervals and bootstrap shares are added here and were not part of the predeclared rule.",
        "P150_V900 and P170_V1000 lie on the calibration P/v line, so their validation is close to interpolation; 20260904:part_5 is off that line and from the other campaign (sync convention O11), the informative test (A25).",
        "The held-out/calibration interval resamples coupons in both groups independently (5 and 9 coupons). The part_5 interval combines a track bootstrap within part_5 with a coupon bootstrap of calibration.",
        "These coupons were opened after the selection freeze and are now spent as held-out data (A8, A27).",
    ]
    return write_table(
        "T08_held_out_performance",
        "In-window held-out performance",
        ["Transfer of the frozen calibration to the 5 in-window held-out coupons, with the predeclared reading V."],
        [("Reading V: held-out error relative to calibration", vrows, vcols), ("Performance", rows, PERF_COLS)],
        notes,
        [{k: v for k, v in r.items() if not k.startswith("_")} | {"level": r["_level"]} for r in rows] + [{"level": "v_ratio", **r} for r in vrows],
    )


# ---------------------------------------------------------------------- T11


def t11(slope_rows: Sequence[Mapping[str, Any]], step0: Mapping[str, Any]) -> list:
    def cell(subset, design, term, source, q):
        r = next(x for x in slope_rows if (x["subset"], x["design"], x["term"], x["source"], x["quantity"]) == (subset, design, term, source, q))
        return f"{r['estimate']:.2f} [{r['ci_lo']:.2f}, {r['ci_hi']:.2f}]"

    def panel(subset):
        rows = []
        for design, term, label in (("P_v", "ln_P", "ln P (with ln v)"), ("P_v", "ln_v", "ln v (with ln P)"), ("VED", "ln_VED", "ln VED (alone)")):
            for q, qlabel in (("H", "ln H"), ("W", "ln W"), ("HW", "ln H/W")):
                ref = {"H": {"ln_P": "1", "ln_v": "0"}, "W": {"ln_P": "0.5", "ln_v": "−0.5"}, "HW": {"ln_P": "0.5", "ln_v": "0.5"}}[q].get(term, "–")
                rows.append(
                    {
                        "response": qlabel, "regressor": label, "camera": cell(subset, design, term, "camera", q), "model": cell(subset, design, term, "model", q),
                        "difference": cell(subset, design, term, "model_minus_camera", q), "rosenthal": ref,
                    }
                )
        return rows

    cols = [
        ("resp", "Response", lambda r: r["response"]), ("reg", "Regressor", lambda r: r["regressor"]),
        ("cam", "Camera (threshold 150)", lambda r: r["camera"]), ("mod", "Model liquidus (c1)", lambda r: r["model"]),
        ("diff", "Model − camera", lambda r: r["difference"]), ("ros", "Rosenthal point source", lambda r: r["rosenthal"]),
    ]
    by = {(r["subset"], r["design"], r["term"], r["source"], r["quantity"]): r for r in slope_rows}
    hw_report = {
        source: {term: by[("all_24", "P_v", term, source, "H")]["estimate"] - by[("all_24", "P_v", term, source, "W")]["estimate"] for term in ("ln_P", "ln_v")}
        for source in ("camera", "model")
    }
    notes = [
        "Least squares of the log coupon median on [1, ln P, ln v] (or [1, ln VED]); 95 % percentile intervals from 4,000 coupon resamples; camera and model share the draws, so the difference is paired. Descriptive, not predeclared.",
        "Coupon medians: camera over all scored frames; model over frames with a predicted pool. H/W is the median of the per-frame ratio (as in 22.3.8 Step 0).",
        f"The results report §4 gave H/W slopes as ln(median H) − ln(median W): model {hw_report['model']['ln_P']:.2f} (P) and {hw_report['model']['ln_v']:.2f} (v), camera {hw_report['camera']['ln_P']:.2f} and {hw_report['camera']['ln_v']:.2f}. Both conventions agree on sign and on the model − camera gap.",
        f"Check against 22.3.8 Step 0 (camera, the 16 A8 calibration members): the largest slope difference is {step0['max_abs_difference']:.3f}, well inside the intervals (Step 0 measured the images itself; this package uses the supplied H/W).",
        "In-window subset: 8 of 9 calibration coupons lie on one P/v line, so P and v slopes there are not identified (very wide intervals); see the CSV.",
        "Scale-free: slopes do not depend on the 8 µm/px scale (A24).",
    ]
    sections = [
        ("All 24 coupons", panel("all_24"), cols),
        ("Without 20260904:part_3 (no pool on 54 % of frames)", panel("all_but_20260904_part_3"), cols),
        ("Out of window (10 coupons)", panel("out_of_window_10"), cols),
    ]
    return write_table("T11_process_slopes", "Process-response slopes", ["How camera and model H, W and H/W scale with power, speed and VED, coupon by coupon."], sections, notes, slope_rows)


# ---------------------------------------------------------------------- T17, confounds


def t17() -> list:
    register = C.load_json(C.REGISTERS_DIR / "predeclared_criteria.json")
    rows = register["rows"]
    cols = [
        ("id", "ID", lambda r: r["id"]), ("kind", "Kind", lambda r: r["kind"]), ("crit", "Criterion", lambda r: r["criterion"]),
        ("thr", "Threshold", lambda r: r["threshold"]),
        ("w", "Written (commit, date)", lambda r: f"`{r['written']['commit']}` {r['written']['date']}"),
        ("ord", "Ordering evidence", lambda r: r["ordering_evidence"]), ("seen", "Data seen when written", lambda r: r["data_seen_at_writing"]),
        ("ev", "Evaluated", lambda r: f"`{r['evaluated']['commit']}` {r['evaluated']['date']}" if r["evaluated"] else "–"),
        ("out", "Outcome", lambda r: r["outcome"]), ("st", "Status", lambda r: r["status"]),
    ]
    flat = [
        {
            **{k: v for k, v in r.items() if k not in ("written", "approved", "evaluated", "sources")},
            "written_commit": r["written"]["commit"], "written_date": r["written"]["date"],
            "approved_commit": (r["approved"] or {}).get("commit"), "approved_date": (r["approved"] or {}).get("date"),
            "evaluated_commit": (r["evaluated"] or {}).get("commit"), "evaluated_date": (r["evaluated"] or {}).get("date"),
            "sources": "; ".join(r["sources"]),
        }
        for r in rows
    ]
    status = Counter(r["status"] for r in rows)
    notes = [*register["how_to_read"], "Counts: " + ", ".join(f"{k} {v}" for k, v in sorted(status.items())) + ".", "Source: `registers/predeclared_criteria.json` (each row cites file and line)."]
    return write_table("T17_predeclared_criteria", "Predeclared criteria", ["Every gate and reading that was fixed before its data were read, with when it was written, what had been seen, and what it found."], [(None, rows, cols)], notes, flat)


def t18(analysis: Mapping[str, Any]) -> tuple[list, dict[str, Any]]:
    checks = confounds.checks(analysis)
    rows = confounds.table_rows(checks)
    cols = [
        ("c", "Confound", lambda r: r["confound"]), ("w", "What is confounded", lambda r: r["what_is_confounded"]),
        ("k", "Check (computed)", lambda r: r["check"]), ("q", "Consequence for the readings", lambda r: r["consequence"]), ("s", "Source", lambda r: r["source"]),
    ]
    notes = ["Listed, not resolved. None of these changes a predeclared reading; they bound how the readings can be interpreted.", "Computed checks: `data/confound_checks.json`."]
    files = write_table("T18_confounds", "Confounds", ["Design features that cannot be separated from the effects reported."], [(None, rows, cols)], notes, rows)
    files.append(C.write_json(C.DATA_DIR / "confound_checks.json", checks))
    return files, checks


def run(analysis: Mapping[str, Any], cis: Mapping[str, Any], slopes_result: Mapping[str, Any]) -> list:
    d3 = coupon_records(analysis, cis)
    d4 = condition_group_records(analysis, cis)
    files = []
    files += t1()
    files += t2(analysis, d3)
    files += t3(analysis)
    files += t4(analysis)
    files += t6()
    files += t7(d3, d4)
    files += t8(d3, d4, cis["ratios"])
    files += t11(slopes_result["rows"], slopes_result["step0_check"])
    files += t13(analysis)
    files += t17()
    f18, _ = t18(analysis)
    files += f18
    return files
