"""Build the thesis tables and figures (descriptive; no runs, fitting or selection).

    $env:PYTHONPATH = "$PWD\\src"
    .\\.venv-analysis\\Scripts\\python.exe docs\\analysis\\thesis_figures\\scripts\\build.py

Writes figures/ (PNG 300 dpi and SVG), tables/ (CSV and Markdown), source/ (plotted values), TABLES_AND_FIGURES.md
(captions and placement), thesis_tables_and_figures.docx (Word tables, figures and captions in the thesis styles)
and OUTPUT_SHA256SUMS.txt. Caption numbers are computed from the data at build time.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import charts  # noqa: E402
import diagrams  # noqa: E402
import docx_writer  # noqa: E402
import images  # noqa: E402
import style as S  # noqa: E402
import thesis_tables as tables  # noqa: E402

DOCX = S.PACKAGE / "thesis_tables_and_figures.docx"
INDEX = S.PACKAGE / "TABLES_AND_FIGURES.md"
SUMS = S.PACKAGE / "OUTPUT_SHA256SUMS.txt"

# (id, kind, thesis section, placement in the 2026-10-22 draft)
ORDER = [
    ("T1", "table", "3.2.1", "§3.2.1, after the paragraph on hatch spacing and spot diameter (end of the section)"),
    ("T2", "table", "3.2.2", "§3.2.2, first PLACEHOLDER (after the paragraph on the July and September campaigns)"),
    ("F1", "figure", "3.2.2", "§3.2.2, second PLACEHOLDER (after the paragraph on the four data roles)"),
    ("T3", "table", "3.2.3", "§3.2.3, replaces the existing channel table"),
    ("F2", "figure", "3.2.4", "§3.2.4, first PLACEHOLDER (after 'Camera Image and H/W Definition')"),
    ("F3", "figure", "3.2.4–3.2.5", "§3.2.5, PLACEHOLDER at the end of the section (or §3.2.4, after 'Scored Frame "
                                    "Selection')"),
    ("T4", "table", "3.3.4", "§3.3.4, PLACEHOLDER after the phase-dependent conductivity definition"),
    ("F4", "figure", "3.3", "§3.3.1, after the paragraph on the moving local window (or the PLACEHOLDER at the end of "
                            "§3.3.7)"),
    ("T5", "table", "3.3.10", "§3.3.10, PLACEHOLDER (replaces the note describing the intended table)"),
    ("T6", "table", "3.4.1", "§3.4.1, PLACEHOLDER after the bounds of c_k and η"),
    ("F5", "figure", "3.4", "§3.4.4, end of the section (before §3.5)"),
    ("F6", "figure", "4.1", "§4.1, first PLACEHOLDER"),
    ("T7", "table", "4.1", "§4.1, second PLACEHOLDER"),
    ("T8", "table", "4.2", "§4.2, first PLACEHOLDER"),
    ("F7", "figure", "4.2", "§4.2, second PLACEHOLDER"),
    ("F8", "figure", "4.3", "§4.3, first PLACEHOLDER"),
    ("T9", "table", "4.3–4.4", "§4.4, PLACEHOLDER (or §4.3, second PLACEHOLDER)"),
    ("F9", "figure", "4.4", "§4.4, PLACEHOLDER, after the table"),
    ("F10", "figure", "4.5", "§4.5, first PLACEHOLDER"),
    ("T10", "table", "4.5", "§4.5, second PLACEHOLDER"),
    ("F11", "figure", "4.6", "§4.6, first PLACEHOLDER"),
    ("F12", "figure", "4.7", "§4.7, first PLACEHOLDER"),
    ("F13", "figure", "4.7", "§4.7, second PLACEHOLDER"),
]

FIGURE_FILES = {
    "F1": "F1_process_space_map", "F2": "F2_extraction", "F3": "F3_scoring_hierarchy", "F4": "F4_model_schematic",
    "F5": "F5_workflow", "F6": "F6_footprints_over_process_space", "F7": "F7_candidate_ranking",
    "F8": "F8_observed_vs_predicted", "F9": "F9_calibration_vs_held_out", "F10": "F10_ratio_vs_ved",
    "F11": "F11_process_slopes", "F12": "F12_operators", "F13": "F13_thresholds_and_isotherms",
}


def _pct(x: float, nd: int = 1) -> str:
    return f"{100 * x:.{nd}f}%"


def captions(r: dict) -> dict[str, tuple[str, str]]:
    f2, f4, f8 = r["F2"], r["F4"], r["F8"]
    f10, f12 = r["F10"], r["F12"]
    cond = lambda c: c.replace("P", "").replace("_V", " W, ") + " mm/s"  # noqa: E731
    out_cov0 = f12[("out_of_window_all", "lam850_uniform_sig0.0", "coverage")]
    out_cov2 = f12[("out_of_window_all", "lam850_uniform_sig2.0", "coverage")]
    cal_sh0 = f12[("calibration", "lam850_uniform_sig0.0", "shape_ratio")]
    cal_shl = f12[("calibration", "liquidus", "shape_ratio")]
    return {
        "F1": ("Experimental process space and data roles",
               f"Laser power against scan speed for the {r['F1']['conditions']} process conditions "
               f"({r['F1']['coupons']} coupons). Marker shape and fill give the analysis role; ×2 marks the six "
               "conditions built on both July 30 and July 31. The shaded band is the 65–85 J/mm³ calibration window, "
               "thin lines are VED isolines and dotted lines show the campaign designs."),
        "F2": ("Extraction of the experimental melt-pool dimensions",
               f"(a) Coaxial frame {f2['frame']} of coupon {f2['member']} ({cond(f2['condition'])}, "
               f"{f2['ved']:.1f} J/mm³), cropped from the 64 × 24 px image. (b) Pixels at or above 150 counts; the "
               "largest 8-connected component is the camera's melt pool. (c) Its external contour and minimum-area "
               "rectangle. (d) H and W are the rectangle's long and short sides, in µm at the nominal 8 µm/px. "
               "The frame is re-measured with the documented convention; its stored H × W is "
               f"{f2['H_stored']:.1f} × {f2['W_stored']:.1f} px."),
        "F3": ("Observation, scoring and hierarchical aggregation",
               "(a) The path of a camera frame from synchronization to scoring; shaded steps exclude frames, and "
               "excluded frames are recorded rather than deleted. (b) Squared log residuals are averaged from frame "
               "to scan track, coupon, process condition and analysis group, each level as an unweighted mean, so "
               "that densely sampled tracks, coupons or conditions receive no extra weight."),
        "F4": ("Reduced-order thermal model",
               "(a) Schematic of the moving computational window (99 × 99 × 21 cubic cells of 16 µm; depth drawn "
               "twice its scale) with the Gaussian volumetric source, boundary treatments and the liquidus footprint. "
               f"(b) Simulated top-surface temperature of the selected state at frame {f4['frame']} of {f4['member']} "
               f"({f4['ved']:.1f} J/mm³) with the liquidus contour of the laser-associated component (white) and its "
               f"minimum-area rectangle (H = {f4['H_um']:.0f} µm, W = {f4['W_um']:.0f} µm); + marks the beam centre."),
        "F5": ("Calibration, data freeze and evaluation sequence",
               "Calibration-design and held-out coupons were separated by process condition before any fitting. The "
               "held-out coupons were not compared with the model until the selection freeze; the out-of-window "
               "calibration-design coupons had been examined during model development (dashed arrow). The "
               "calibration search combined a predefined design of anchor and Halton points with confirmation "
               "candidates proposed by a quadratic surrogate, and the candidate with the lowest measured objective "
               "was selected."),
        "F6": ("Melt-pool footprints over process space",
               "Each pair of boxes sits at its process condition, with replicate coupons pooled. The orange outline "
               "is the camera's median melt-pool footprint and the blue box the calibrated model's, both drawn to "
               "one size scale with H horizontal and W vertical. The shaded band marks the calibration window and "
               "the thin lines are lines of constant volumetric energy density."),
        "F7": ("Calibration candidates ranked by the measured objective",
               "Measured objective J on the calibration coupons for every directly evaluated parameter state, split "
               "into its H term (dark) and W term (light); the columns give each state's calibration coordinates. "
               "Anchor and Halton points form the predefined search design, and Candidates 1 and 2 are the "
               "confirmation states proposed by the quadratic surrogate. The dashed line marks the predefined "
               "near-best limit relative to the lowest J."),
        "F8": ("Observed and predicted melt-pool dimensions in the calibration window",
               "Condition medians of camera and model H (a) and W (b) for the five calibration conditions; model "
               "medians over frames with a predicted pool. Solid line: 1:1; dashed line: pooled median ratio. "
               f"Condition ratios range from {f8['H_cond_ratio_min']:.2f} to {f8['H_cond_ratio_max']:.2f} for H and "
               f"from {f8['W_cond_ratio_min']:.2f} to {f8['W_cond_ratio_max']:.2f} for W."),
        "F9": ("Calibration and in-window held-out comparison",
               "(a) Pooled model-to-camera size ratios for the calibration and in-window held-out groups, with "
               "bootstrap intervals; tick marks are individual coupons. The model is longer and narrower than the "
               "camera footprint, by nearly the same factor in both groups. (b) Held-out error divided by "
               "calibration error, V, for H and W, with bootstrap intervals. Both pooled values lie close to equal "
               "error and inside the predefined pass criterion V ≤ 1.25. The grey square is the in-window held-out "
               "coupon from the speed-sweep campaign, shown alone."),
        "F10": ("Model-to-camera ratios against volumetric energy density",
                "Coupon median ratios of H (a) and W (b) on a log scale, with 95% track-bootstrap intervals; marker "
                "shape gives the data role and the shaded band the calibration window. Frames without a predicted "
                "pool are scored as H = W = 0 (1 px floor); they make up "
                f"{_pct(f10['low_no_pool'])} of the scored frames at {f10['low_ved']:.1f} J/mm³."),
        "F11": ("Sensitivity of melt-pool size to the process parameters",
                "Fitted percentage change in melt-pool length H, width W and shape H/W for a one-percent increase in "
                "laser power (a), scan speed (b) and volumetric energy density (c), from log-log regressions over the "
                "coupon medians, for the camera (orange) and the calibrated model (blue); lines are coupon-bootstrap "
                "intervals. Camera and model change in the same direction, but the model responds several times more "
                "strongly in both length and width. The camera's shape barely changes with energy density, whereas "
                "the model's elongates. Leaving out the lowest-energy coupon does not change these conclusions."),
        "F12": ("Observation operators compared",
                "(a–c) One scored camera frame per energy-density level, with the camera threshold-150 outline "
                "(orange), the model liquidus outline (blue) and the simulated-camera threshold-150 outline (aqua; "
                f"850 nm, uniform emissivity, PSF 0 px, T150 = {f12['T150'][0]:.0f} K) in camera pixels. (d–f) Group "
                "medians of the H, W and H/W ratios to the camera for the liquidus and the simulated camera (PSF 0 "
                f"and 2 px). In the calibration group the H/W ratio is {cal_shl:.2f} for the liquidus and "
                f"{cal_sh0:.2f} for the simulated camera; simulated-camera coverage outside the window is "
                f"{out_cov0:.0%} (PSF 0) and {out_cov2:.0%} (PSF 2)."),
        "F13": ("Camera thresholds and model isotherms",
                "One scored frame of a calibration coupon, seen by the camera and by the calibrated model. "
                "(a) Camera melt-pool outlines at increasing brightness thresholds; the thick outline is the "
                "150-count threshold used for scoring. (b) Camera H and W at each threshold, with H/W below. "
                "(c) Model outlines at increasing isotherms on the simulated top surface; the thick outline is the "
                "1673 K liquidus used for scoring, the dashed frame marks the camera's field of view, and isotherms "
                "that leave the model window are not drawn. (d) Model H and W at each isotherm. Raising the "
                "threshold shrinks the camera footprint while it stays nearly round, whereas every model isotherm "
                "is more elongated than any camera outline, so changing the level does not bring the two shapes "
                "together."),
    }


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    plt = S.setup()
    results = {}
    for module in (charts, images, diagrams):
        for key, fn in module.ALL.items():
            results[key] = fn(plt)
            print(f"{key} done", flush=True)
    tabs = {}
    for key in tables.ALL:
        t = tables.build(key)
        tables.write(t)
        tabs[key] = t
        print(f"{key} done", flush=True)
    caps = captions(results)
    items, index = [], []
    for key, kind, section, placement in ORDER:
        if kind == "table":
            t = tabs[key]
            items.append({"id": key, "kind": "table", "placement": placement, "title": t["title"],
                          "columns": t["columns"], "rows": t["rows"], "widths": t.get("widths"),
                          "group_rows": t.get("group_rows", False), "group_from": t.get("group_from"),
                          "note": " ".join(t["notes"])})
            index.append((key, "Table", section, t["title"], " ".join(t["notes"]), f"tables/{t['name']}.csv / .md",
                          placement))
        else:
            title, note = caps[key]
            note = tables.clean(note)
            png = S.FIGURES_DIR / f"{FIGURE_FILES[key]}.png"
            items.append({"id": key, "kind": "figure", "placement": placement, "title": title, "note": note,
                          "png": png})
            index.append((key, "Figure", section, title, note, f"figures/{FIGURE_FILES[key]}.png / .svg", placement))
    intro = ["Tables and figures for the thesis draft of 2026-10-22, in the order of the planning list (T1–T10, "
             "F1–F13). Each item begins with a grey placement line (remove it after pasting). Captions use the "
             "thesis styles 'Table Title' and 'Caption' with SEQ fields, so the List of Tables and List of Figures "
             "pick them up; press F9 after pasting to renumber.",
             "All values are read from the frozen Patch 22.4.3.2 records of the selected state (Candidate 1) and the "
             "committee package. Sizes in µm use the nominal, unvalidated 8 µm/px camera scale."]
    docx_writer.write_docx(DOCX, "Thesis tables and figures", intro, items)
    lines = ["# Thesis tables and figures", "",
             "Generated by `scripts/build.py` from the committee package data and the presentation-figure sources. "
             "Caption numbers are computed from the data at build time. The Word file "
             "`thesis_tables_and_figures.docx` holds the same items, ready to paste.", "",
             "| # | Type | Section | Title | File | Placement |", "|---|---|---|---|---|---|"]
    for key, typ, section, title, _, files, placement in index:
        lines.append(f"| {key} | {typ} | {section} | {title} | `{files}` | {placement} |")
    lines += ["", "## Captions and notes", ""]
    for key, typ, section, title, note, _, _ in index:
        lines.append(f"**{key}. {title}.** {note}")
        lines.append("")
    INDEX.write_bytes("\n".join(lines).encode("utf-8"))
    outputs = sorted(p for d in (S.FIGURES_DIR, S.TABLES_DIR, S.SOURCE_DIR) for p in d.rglob("*") if p.is_file())
    outputs += [DOCX, INDEX]
    rel = [(p.relative_to(S.PACKAGE).as_posix(), sha256(p)) for p in outputs]
    SUMS.write_bytes(("".join(f"{h}  {n}\n" for n, h in sorted(rel))).encode("utf-8"))
    print(f"wrote {len(rel)} hashed files")


if __name__ == "__main__":
    main()
