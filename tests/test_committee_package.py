"""Committee statistical-output package (results/committee_package): consistency with the frozen records.

The recomputation tests need the gitignored Patch 22.4.3.2 evaluate unit files and skip without them. The
committed-output tests compare the package's own CSVs with each other and need nothing outside the repo.
"""
from __future__ import annotations

import csv
import gzip
import json
import math
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pytest

PACKAGE = Path(__file__).resolve().parents[1] / "results" / "committee_package"
sys.path.insert(0, str(PACKAGE / "scripts"))

import common as C  # noqa: E402

needs_units = pytest.mark.skipif(not C.units_available(), reason="c1 evaluate unit files (data bundle) not present")


def _csv(path: Path) -> list[dict[str, str]]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


@pytest.fixture(scope="module")
def analysis():
    import build_datasets

    return build_datasets.build(process_rows=False)


@needs_units
def test_hierarchy_recomputation_equals_the_evaluate_manifest(analysis):
    import build_datasets

    result = build_datasets.verify(analysis)
    assert result["status"] == "PASS"
    assert result["max_abs_difference_vs_manifest"] <= 1e-12
    assert result["production_aggregator_max_abs_difference_calibration"] <= 1e-12
    assert result["values_checked"] >= 150


@needs_units
def test_roles_follow_the_a25_partition(analysis):
    assert {m: len(v) for m, v in C.ROLE_MEMBERS.items()} == {"calibration": 9, "in_window_held_out": 5, "out_of_window_examined": 7, "out_of_window_blind": 3}
    for member, row in analysis["record"].items():
        inside = C.VED_WINDOW_J_MM3[0] <= row["ved_J_mm3"] <= C.VED_WINDOW_J_MM3[1]
        assert inside == (C.ROLE[member] in ("calibration", "in_window_held_out"))


@needs_units
def test_bootstrap_is_deterministic_and_unit_counts_reproduce_the_point(analysis):
    import bootstrap

    first = bootstrap.group_coupon_draws(analysis, 50)
    second = bootstrap.group_coupon_draws(analysis, 50)
    for name in first:
        for key in ("e_H", "e_W", "median_H_ratio", "counts"):
            assert np.array_equal(first[name][key], second[name][key])
    a = bootstrap.coupon_track_draws(analysis, 20)
    b = bootstrap.coupon_track_draws(analysis, 20)
    assert all(np.array_equal(a[m]["msq_H"], b[m]["msq_H"]) for m in a)

    coupons = analysis["coupons"]
    for name in ("calibration", "in_window_held_out", "out_of_window_all"):
        group = analysis["groups"][name]
        members = list(group["members"])
        conditions = sorted({coupons[m]["condition"] for m in members})
        index = np.array([conditions.index(coupons[m]["condition"]) for m in members])
        ones = np.ones((1, len(members)), dtype=np.int64)
        h, w = C.weighted_group_components(np.array([coupons[m]["H_mean_sq_log"] for m in members]), np.array([coupons[m]["W_mean_sq_log"] for m in members]), index, ones)
        assert math.sqrt(h[0]) == pytest.approx(group["e_H"], abs=1e-14)
        assert math.sqrt(w[0]) == pytest.approx(group["e_W"], abs=1e-14)
        frames = [f for m in members for f in analysis["frames_by_member"][m]]
        values = np.array([math.exp(f["r_H"]) for f in frames])
        unit = np.array([k for k, m in enumerate(members) for _ in analysis["frames_by_member"][m]])
        assert bootstrap.weighted_median(values, unit, ones)[0] == group["median_H_ratio"]


def test_weighted_median_matches_numpy_on_the_expanded_sample():
    import bootstrap

    rng = np.random.default_rng(0)
    values = rng.normal(size=40)
    unit = rng.integers(0, 7, size=40)
    counts = rng.integers(0, 4, size=(25, 7))
    counts[:, 0] += 1  # never an empty draw
    got = bootstrap.weighted_median(values, unit, counts)
    for r, row in enumerate(counts):
        expanded = np.concatenate([np.repeat(values[unit == u], c) for u, c in enumerate(row)])
        assert got[r] == np.median(expanded)


# ---------------------------------------------------------------------- committed outputs


def test_figure_sources_equal_the_tables_and_datasets():
    d3 = {r["member"]: r for r in _csv(PACKAGE / "data" / "D3_coupons.csv")}
    for r in _csv(PACKAGE / "figures" / "source" / "F6_ratio_vs_ved_points.csv"):
        assert float(r["median_ratio"]) == float(d3[r["member"]][f"median_{r['quantity']}_ratio"])
    for r in _csv(PACKAGE / "figures" / "source" / "F5_observed_vs_predicted.csv"):
        assert float(r["camera_um_median"]) == float(d3[r["member"]][f"cam_{r['quantity']}_um_median"])
    t7 = {r["member"]: r for r in _csv(PACKAGE / "tables" / "T07_calibration_performance.csv") if r["level"] == "coupon"}
    t8 = {r["member"]: r for r in _csv(PACKAGE / "tables" / "T08_held_out_performance.csv") if r["level"] == "coupon"}
    assert len(t7) == 9 and len(t8) == 5
    for member, row in {**t7, **t8}.items():
        for key in ("e_H", "e_W", "J", "median_H_ratio", "median_W_ratio", "e_H_ci_lo", "e_H_ci_hi"):
            assert row[key] == d3[member][key]
    t11 = {(r["subset"], r["design"], r["term"], r["source"], r["quantity"]): r["estimate"] for r in _csv(PACKAGE / "tables" / "T11_process_slopes.csv")}
    for r in _csv(PACKAGE / "figures" / "source" / "F11_slopes.csv"):
        assert r["estimate"] == t11[(r["subset"], r["design"], r["term"], r["source"], r["quantity"])]


def test_pooled_groups_in_the_tables_equal_the_evaluate_manifest():
    manifest = json.loads((Path(__file__).resolve().parents[1] / "results/calibration/evaluate/stage_manifest.json").read_text(encoding="utf-8"))
    groups = {r["name"]: r for r in _csv(PACKAGE / "data" / "D4_conditions_groups.csv") if r["level"] == "group"}
    cal = manifest["calibration_score_selected"]
    held = manifest["readings"]["V"]["confirm_c1"]["held_out"]
    for name, ref in (("calibration", cal), ("in_window_held_out", held)):
        assert float(groups[name]["e_H"]) == ref["e_H"]
        assert float(groups[name]["e_W"]) == ref["e_W"]
        assert float(groups[name]["J"]) == pytest.approx(ref["J"], abs=1e-15)
        assert int(groups[name]["scored_frames"]) == ref["scored_frame_count"]


def test_exclusion_ledger_reconciles_with_the_accounting_table():
    t4 = {r["member"]: r for r in _csv(PACKAGE / "tables" / "T04_data_accounting.csv") if r["member"].startswith("2026")}
    ledger = Counter((r["member"], r["category"].split(" ")[0]) for r in _csv(PACKAGE / "data" / "D7_exclusion_ledger.csv"))
    assert len(t4) == 24
    for member, row in t4.items():
        assert ledger[(member, "excluded_by_rule")] == int(row["excluded_by_rule"])
        assert ledger[(member, "camera_ineligible")] == int(row["camera_ineligible_frames"])
        assert ledger[(member, "scored_no_pool_prediction")] == int(row["no_pool_frames"])
        assert int(row["eligible_frames"]) - int(row["excluded_by_rule"]) - int(row["undefined_frames"]) == int(row["scored_frames"])
    frames = _csv(PACKAGE / "data" / "D1_frames.csv.gz")
    assert len(frames) == sum(int(r["scored_frames"]) for r in t4.values()) == 24129


needs_characterization = pytest.mark.skipif(not C.CHARACTERIZATION.is_dir(), reason="Patch 21.3 characterization (data bundle) not present")


# ---------------------------------------------------------------------- pass 2: recomputation


@needs_units
def test_contract_errors_equal_the_hierarchy_for_every_group(analysis):
    for name, group in analysis["groups"].items():
        frames = [f for f in analysis["scored"] if f["member"] in set(group["members"])]
        mine = C.contract_errors(frames)
        for key in ("e_H", "e_W", "J"):
            assert mine[key] == pytest.approx(group[key], abs=1e-15), (name, key)


@needs_units
def test_synthetic_operator_scores_equal_the_synthetic_manifest(analysis):
    import operators

    synth, _ = operators.synthetic_frames(analysis)
    check = operators.verify_synthetic(analysis, synth)
    assert check["status"] == "PASS" and check["max_abs_difference"] <= 1e-12 and check["values_checked"] >= 100


@needs_units
def test_within_coupon_permutation_reproduces_the_coupon_errors(analysis):
    import variance

    rows = variance.explanatory_rows(analysis, permutations=20)
    assert len(rows) == 24
    for row in rows:
        assert row["e_H_actual"] == pytest.approx(analysis["coupons"][row["member"]]["e_H"], rel=1e-12)
        assert 0.0 < row["p_H_shuffled_at_or_below_actual"] <= 1.0


@needs_units
def test_replicate_bootstrap_is_deterministic(analysis):
    import replicates

    tracks = [t for t in analysis["tracks"] if t["member"] == "20260730:part_1"]
    a = replicates.coupon_draws(tracks, 0, 30)
    b = replicates.coupon_draws(tracks, 0, 30)
    assert all(np.array_equal(a[k], b[k], equal_nan=True) for k in a)


@needs_characterization
def test_sync_mapping_reproduces_the_22_3_6_audit():
    import sync

    audit ={m["member_identity"]: m["summary"] for m in json.loads(C.SYNC_AUDIT_22_3_6.read_text(encoding="utf-8"))["members"]}
    for member, ref in audit.items():
        mine = sync.track_mapping(member)
        assert mine["first_maps_to_track_start_fraction"] == ref["first_maps_to_track_start_fraction"]
        assert mine["last_maps_to_track_end_fraction"] == ref["last_maps_to_track_end_fraction"]
        assert mine["single_frame_tracks"] == ref["single_frame_track_count"]
        assert mine["tracks_with_eligible_frames"] == ref["track_count"]


def test_stage_manifests_record_the_same_fixed_controls():
    import controls

    rows, consistency = controls.stage_rows()
    assert consistency["all_constant"]
    assert [r["stage"] for r in rows] == ["smoke", "calibrate", "confirm", "freeze", "evaluate", "synthetic"]
    assert all(not r["campaign_dispatched"] and not r["production_semantics_changed"] for r in rows)
    assert {r["stage"]: r["held_out_members_read"] for r in rows if r["stage"] in ("smoke", "calibrate", "confirm", "freeze")} == {"smoke": 0, "calibrate": 0, "confirm": 0, "freeze": 0}


# ---------------------------------------------------------------------- pass 2: committed outputs


def test_selection_is_reconstructed_from_the_committed_archive():
    from lpbf.calibration import fit_quadratic

    recon = json.loads((PACKAGE / "data" / "D6_candidate_search" / "D6_selection_reconstruction.json").read_text(encoding="utf-8"))
    assert recon["status"] == "PASS" and recon["selected_reconstructed"] == recon["selected_recorded"] == C.CANDIDATE
    cands = _csv(PACKAGE / "data" / "D6_candidate_search" / "D6_candidates.csv")
    assert len(cands) == 19
    eligible = [r for r in cands if r["coverage_flag"] == "false" and r["status"] == "PASS"]
    assert min(eligible, key=lambda r: float(r["J"]))["candidate"] == C.CANDIDATE
    design = [r for r in cands if r["origin"] == "frozen_design"]
    fit = fit_quadratic([[float(r[f"coded_x{k}"]) for k in (1, 2, 3)] for r in design], [float(r["J"]) for r in design])
    recorded = json.loads((Path(__file__).resolve().parents[1] / "results/calibration/calibration_reading.json").read_text(encoding="utf-8"))["surrogate"]["fit"]
    assert max(abs(a - b) for a, b in zip(fit["coefficients"], recorded["coefficients"])) < 1e-9


def test_pass2_tables_and_sources_agree_with_the_datasets():
    d4 = {(r["level"], r["name"]): r for r in _csv(PACKAGE / "data" / "D4_conditions_groups.csv")}
    t9 = [r for r in _csv(PACKAGE / "tables" / "T09_out_of_window_performance.csv") if r["level"] == "coupon"]
    d3 = {r["member"]: r for r in _csv(PACKAGE / "data" / "D3_coupons.csv")}
    assert len(t9) == 10
    for r in t9:
        assert r["e_H"] == d3[r["member"]]["e_H"] and r["e_W"] == d3[r["member"]]["e_W"]
    weighting = [r for r in _csv(PACKAGE / "data" / "T15_weighting_floor_tracks_loo.csv") if r["section"] == "D_weighting" and r["variant"].startswith("contract")]
    for r in weighting:
        assert float(r["e_H"]) == pytest.approx(float(d4[("group", r["group"])]["e_H"]), abs=1e-15)
    for r in _csv(PACKAGE / "figures" / "source" / "F15_process_space.csv"):
        assert float(r["e_H"]) == float(d4[("condition", r["condition"])]["e_H"])
    pairs = {(r["condition"], r["quantity"]): r for r in _csv(PACKAGE / "data" / "T10_replicate_pairs.csv")}
    for r in _csv(PACKAGE / "figures" / "source" / "F9_replicates.csv"):
        assert r["difference"] == pairs[(r["condition"], r["quantity"])]["difference"]
    lines = {r["quantity"]: r for r in _csv(PACKAGE / "figures" / "source" / "F8_bland_altman_lines.csv")}
    for q in ("H", "W"):
        inside = [float(r[f"median_r_{q}"]) for r in d3.values() if r["role"] in ("calibration", "in_window_held_out")]
        assert float(lines[q]["bias"]) == pytest.approx(sum(inside) / len(inside), abs=1e-12)
    t4 = {r["member"]: r for r in _csv(PACKAGE / "tables" / "T04_data_accounting.csv")}
    for r in _csv(PACKAGE / "tables" / "T19_synchronization.csv"):
        assert r["eligible_frames"] == t4[r["member"]]["eligible_frames"]
    f2 = {r["level"]: int(r["count"]) for r in _csv(PACKAGE / "figures" / "source" / "F2_hierarchy.csv")}
    assert f2["scored_frames"] == int(t4["All 24 coupons"]["scored_frames"]) == 24129
    assert f2["eligible_frames"] - f2["excluded_by_rule"] - f2["undefined_frames"] == f2["scored_frames"]


def test_f13_sources_are_complete():
    frames = _csv(PACKAGE / "figures" / "source" / "F13_frames.csv")
    outlines = _csv(PACKAGE / "figures" / "source" / "F13_outlines.csv")
    pixels = _csv(PACKAGE / "figures" / "source" / "F13_camera_pixels.csv")
    assert len(frames) == 3 and len(pixels) == 3 * 24 * 64
    for f in frames:
        assert C.ROLE[f["member"]] in ("calibration", "out_of_window_examined")  # never a held-out coupon
        assert {r["operator"] for r in outlines if r["member"] == f["member"]} == {"camera_150", "liquidus", "synthetic_150", "width_matched"}


def test_registers_are_complete():
    register = json.loads((PACKAGE / "registers" / "predeclared_criteria.json").read_text(encoding="utf-8"))
    for row in register["rows"]:
        assert row["status"] in {"pass", "not_met", "partial", "descriptive", "convention", "deviation"}
        assert row["written"]["commit"] and row["sources"]
    history = json.loads((PACKAGE / "registers" / "data_use_history.json").read_text(encoding="utf-8"))
    assert len(history["members"]) == 24
    for member, stages in history["members"].items():
        assert set(stages) <= set(history["stages"])
        assert ("S19" in stages) == (member in C.ROLE_MEMBERS["calibration"])  # only calibration members entered selection
