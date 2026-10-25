"""Thesis tables and figures (results/thesis_figures): committed outputs agree with the frozen records.

Runs in the production .venv (no matplotlib): the tables are rebuilt from the committee data and the code the
22.4.3.2 runner imported and compared byte for byte; the figures are checked through their hash list and sources.
"""
from __future__ import annotations

import csv
import hashlib
import re
import sys
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PACKAGE = REPO / "results" / "thesis_figures"
COMMITTEE = REPO / "results" / "committee_package"


@pytest.fixture(scope="module")
def tables():
    scripts = str(PACKAGE / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import thesis_tables

    return thesis_tables


def _rows(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def test_output_hash_list_matches_the_files():
    lines = (PACKAGE / "OUTPUT_SHA256SUMS.txt").read_text(encoding="utf-8").splitlines()
    assert len(lines) > 50
    for line in lines:
        digest, name = line.split("  ", 1)
        assert hashlib.sha256((PACKAGE / name).read_bytes()).hexdigest() == digest, name


@pytest.mark.parametrize("key", [f"T{i}" for i in range(1, 11)])
def test_tables_rebuild_byte_for_byte(tables, key):
    table = tables.build(key)
    for name, data in tables.render(table).items():
        assert (PACKAGE / "tables" / name).read_bytes() == data, name


def test_titles_are_simple_and_unnumbered(tables):
    index = (PACKAGE / "TABLES_AND_FIGURES.md").read_text(encoding="utf-8")
    titles = [line.split("|")[4].strip() for line in index.splitlines() if re.match(r"\| [TF]\d+ \|", line)]
    assert len(titles) == 23
    for title in titles:
        assert not re.match(r"^[TFD]\d", title) and len(title.split()) <= 10, title


def test_held_out_ratios_and_validation_reading_match_the_ledger(tables):
    t9 = tables.build("T9")
    v = {row[0]: row[2] for row in t9["rows"]}
    assert v["V_H = e_H / e_H,cal"].startswith("1.033") and v["V_W = e_W / e_W,cal"].startswith("1.017")
    t10 = tables.build("T10")
    assert round(t10["summary"]["rho_H"], 3) == 0.976 and round(t10["summary"]["rho_W"], 3) == 0.964


def test_channel_table_holds_exactly_the_owner_supplied_rows(tables):
    """T3 is the owner's table as supplied (2026-10-23): these seven channels and nothing else."""

    t3 = tables.build("T3")
    assert t3["columns"] == ["Process Channel", "Description", "Format", "Acquisition Rate", "Unit",
                             "Role in present study"]
    assert [r[0] for r in t3["rows"]] == ["Laser Drive", "Sync Pulse", "X-Machine", "Y-Machine",
                                          "Coaxial GigE camera", "H", "W"]
    assert t3["notes"] == []


def test_figure_sources_agree_with_the_committee_data():
    d3 = {r["member"]: r for r in _rows(COMMITTEE / "data" / "D3_coupons.csv")}
    f10 = _rows(PACKAGE / "source" / "F10_ratio_vs_ved.csv")
    assert {r["coupon"] for r in f10} == set(d3)
    for r in f10:
        assert float(r["median_H_ratio"]) == float(d3[r["coupon"]]["median_H_ratio"])
        assert float(r["median_W_ratio"]) == float(d3[r["coupon"]]["median_W_ratio"])
    f7 = _rows(PACKAGE / "source" / "F7_candidate_ranking.csv")
    assert len(f7) == 19 and f7[0]["candidate"] == "confirm_c1" and f7[0]["selected"] == "True"



def test_scoring_schematic_is_qualitative():
    """F3 is descriptive only (owner, 2026-10-23): no counts or values in its labels, SVG text or caption."""

    labels = [r["label"] for r in _rows(PACKAGE / "source" / "F3_scoring_hierarchy.csv")]
    assert len(labels) == 11 and not any(re.search(r"\d", label) for label in labels)
    svg_text = re.findall(r">([^<>]+)</text>", (PACKAGE / "figures" / "F3_scoring_hierarchy.svg").read_text("utf-8"))
    assert svg_text and not any(re.search(r"\d", t) for t in svg_text[2:]), svg_text
    index = (PACKAGE / "TABLES_AND_FIGURES.md").read_text(encoding="utf-8")
    caption = next(line for line in index.splitlines() if line.startswith("**F3."))
    assert not re.search(r"\d", caption.removeprefix("**F3."))


def test_footprint_figure_matches_the_condition_medians_and_has_a_qualitative_caption():
    """F6 reproduces the presentation 'melt pool footprints' sizes; its caption has no numbers (owner, 2026-10-23)."""

    d4 = {r["name"]: r for r in _rows(COMMITTEE / "data" / "D4_conditions_groups.csv") if r["level"] == "condition"}
    f6 = _rows(PACKAGE / "source" / "F6_footprints_over_process_space.csv")
    assert {r["condition"] for r in f6} == set(d4)
    for r in f6:
        assert abs(float(r["camera_H_um"]) - 8.0 * float(d4[r["condition"]]["cam_H_px_median"])) < 1e-9
        assert abs(float(r["model_W_um"]) - 8.0 * float(d4[r["condition"]]["sim_W_px_median_pool"])) < 1e-9
    index = (PACKAGE / "TABLES_AND_FIGURES.md").read_text(encoding="utf-8")
    caption = next(line for line in index.splitlines() if line.startswith("**F6."))
    assert not re.search(r"\d", caption.removeprefix("**F6."))


def test_candidate_ranking_uses_readable_names_and_a_qualitative_caption():
    """F7 names (owner, 2026-10-23): Candidate 1/2, Halton point n, anchors in words; no result values in the caption."""

    f7 = _rows(PACKAGE / "source" / "F7_candidate_ranking.csv")
    labels = {r["candidate"]: r["label"] for r in f7}
    assert labels["confirm_c1"] == "Candidate 1" and labels["confirm_c2"] == "Candidate 2"
    assert labels["halton_04"] == "Halton point 4"
    assert all("_" not in v.replace("$c_k$", "") for v in labels.values()), labels
    svg = (PACKAGE / "figures" / "F7_candidate_ranking.svg").read_text(encoding="utf-8")
    assert "confirm_c" not in svg and "halton_" not in svg and "anchor_" not in svg
    index = (PACKAGE / "TABLES_AND_FIGURES.md").read_text(encoding="utf-8")
    caption = next(line for line in index.splitlines() if line.startswith("**F7."))
    assert not re.search(r"\d", caption.removeprefix("**F7.").replace("Candidates 1 and 2", ""))
    assert "confirm_c" not in caption


def test_transfer_figure_shows_the_v_ratios_and_a_qualitative_caption():
    """F9 (owner, 2026-10-23): V ratios against the 1.25 criterion; caption qualitative except that threshold."""

    rows = _rows(PACKAGE / "source" / "F9_calibration_vs_held_out.csv")
    v = {(r["quantity"], r["role"]): r for r in rows if r["kind"] == "b_V"}
    assert set(v) == {(q, n) for q in ("H", "W") for n in ("held_out_over_calibration", "part_5_over_calibration")}
    assert round(float(v[("H", "held_out_over_calibration")]["value"]), 3) == 1.033
    assert round(float(v[("W", "held_out_over_calibration")]["value"]), 3) == 1.017
    assert all(r["ci_lo"] and r["ci_hi"] for r in v.values())
    index = (PACKAGE / "TABLES_AND_FIGURES.md").read_text(encoding="utf-8")
    caption = next(line for line in index.splitlines() if line.startswith("**F9."))
    assert re.findall(r"\d+(?:\.\d+)?", caption.removeprefix("**F9.")) == ["1.25"]


def test_threshold_and_isotherm_figure_uses_the_presentation_levels_and_names_only_the_scored_levels():
    """F13 (owner, 2026-10-23): the presentation 'camera thresholds and model isotherms' levels; the caption names only
    the two scored levels (150 counts, 1673 K liquidus)."""

    pres = _rows(REPO / "results" / "figure_sources" / "source" / "levels_feature_frame.csv")
    f13 = _rows(PACKAGE / "source" / "F13_thresholds_and_isotherms.csv")
    assert [(r["source"], float(r["level"])) for r in f13 if r["drawn"] == "True"] == \
        [(r["source"], float(r["level"])) for r in pres if r["touches_edge"] == "false"]
    for a, b in zip([r for r in f13 if r["drawn"] == "True"], [r for r in pres if r["touches_edge"] == "false"]):
        assert abs(float(a["H_um"]) - 8.0 * float(b["H_px"])) < 1e-9
    index = (PACKAGE / "TABLES_AND_FIGURES.md").read_text(encoding="utf-8")
    caption = next(line for line in index.splitlines() if line.startswith("**F13."))
    assert re.findall(r"\d+", caption.removeprefix("**F13.")) == ["150", "1673"]


def test_readers_see_candidate_names_not_record_ids(tables):
    """Owner, 2026-10-23: 'Candidate 1/2' in every table and figure; record IDs only in CSV/Markdown provenance."""

    with zipfile.ZipFile(PACKAGE / "thesis_tables_and_figures.docx") as z:
        doc = z.read("word/document.xml").decode("utf-8")
    assert "confirm_c" not in doc and "Candidate 1" in doc and "Candidate 2" in doc
    assert "confirm_c" not in (PACKAGE / "TABLES_AND_FIGURES.md").read_text(encoding="utf-8")
    for svg in (PACKAGE / "figures").glob("*.svg"):
        assert "confirm_c" not in svg.read_text(encoding="utf-8"), svg.name
    for key in tables.ALL:
        t = tables.build(key)
        shown = " ".join([t["title"], *t["columns"], *t["notes"], *(x for row in t["rows"] for x in row)])
        assert "confirm_c" not in shown, key
    assert tables.build("T8")["columns"][1:] == ["Candidate 1 (selected)", "Candidate 2 (second best)"]


def test_workflow_caption_is_qualitative():
    """F5 (owner, 2026-10-23): simplified box wording; the caption carries no counts or values."""

    index = (PACKAGE / "TABLES_AND_FIGURES.md").read_text(encoding="utf-8")
    caption = next(line for line in index.splitlines() if line.startswith("**F5."))
    assert not re.search(r"\d", caption.removeprefix("**F5.")) and "confirm_c" not in caption


def test_sensitivity_figure_matches_the_committee_slopes_and_has_a_qualitative_caption():
    """F11 (owner, 2026-10-23): bars of the committee T11 slopes, no tick markers, caption without numbers."""

    t11 = {(r["subset"], r["design"], r["term"], r["source"], r["quantity"]): r
           for r in _rows(COMMITTEE / "data" / "T11_process_slopes.csv")}
    f11 = _rows(PACKAGE / "source" / "F11_process_slopes.csv")
    assert len(f11) == 18
    for r in f11:
        ref = t11[(r["subset"], r["design"], r["term"], r["source"], r["quantity"])]
        assert float(r["estimate"]) == float(ref["estimate"]) and float(r["ci_lo"]) == float(ref["ci_lo"])
    index = (PACKAGE / "TABLES_AND_FIGURES.md").read_text(encoding="utf-8")
    caption = next(line for line in index.splitlines() if line.startswith("**F11."))
    assert not re.search(r"\d", caption.removeprefix("**F11.")) and "tick" not in caption


def test_extraction_frame_remeasures_within_half_a_pixel():
    row = _rows(PACKAGE / "source" / "F2_extraction.csv")[0]
    assert abs(float(row["H_px_remeasured"]) - float(row["H_px_stored"])) <= 0.5
    assert abs(float(row["W_px_remeasured"]) - float(row["W_px_stored"])) <= 0.5


def test_word_document_holds_every_item_with_thesis_caption_styles():
    with zipfile.ZipFile(PACKAGE / "thesis_tables_and_figures.docx") as z:
        doc = z.read("word/document.xml").decode("utf-8")
        media = [n for n in z.namelist() if n.startswith("word/media/")]
    assert doc.count("<w:tbl>") == 10 and len(media) == 13
    assert doc.count("SEQ Table") == 10 and doc.count("SEQ Figure") == 13
    assert doc.count('w:val="TableTitle"') == 10 and doc.count('w:val="Caption"') == 13
