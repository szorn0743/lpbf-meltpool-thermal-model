# Thesis tables and figures

Status: **descriptive analysis for the thesis document, 2026-10-22. It is not a patch.**
- It builds the tables and figures of Chapters 3 and 4 of the thesis, numbered as in the planning list: tables T1–T10
  and figures F1–F13.
- It re-reads the committee package data (`docs/analysis/committee_package/`, D1–D7 and the T-table data), the
  presentation-figure image sources and the recorded 22.3.8 step-4 candidates, plus the model constants from the code the
  22.4.3.2 runner imported. There are no thermal runs, no fitting and no selection, and no production code, semantics,
  frozen core or process record changes.
- The ledger (`docs/DECISIONS.md`, A25–A27), `docs/patches/22.4.3.2/PATCH_22_4_3_2_RESULTS.md` and the committee package
  stay authoritative.
- **Held-out status.** The 8 A8 held-out coupons appear in the all-coupon items. They were opened by the 22.4.3.2
  evaluation after its freeze (A8, A27) and are used here only descriptively.

## Outputs

| File | What it holds |
|---|---|
| `thesis_tables_and_figures.docx` | All 23 items in list order, ready to paste: Word tables, figures and captions. |
| `TABLES_AND_FIGURES.md` | Index: section, title, file and placement for every item, with the full caption and note text. |
| `figures/` | F1–F13 as PNG (300 dpi) and SVG, 6.25 in wide (the thesis text width), Times New Roman. |
| `tables/` | T1–T10 as CSV (full precision) and Markdown (rounded, as printed). The Markdown also gives each table's sources. |
| `source/` | Every plotted value, one CSV per figure. |
| `OUTPUT_SHA256SUMS.txt` | Hashes of all outputs; two builds are byte-identical. |

## Using the Word file

- Each item starts with a grey placement line, which names the placeholder in the thesis draft it was made for.
  Delete the line after pasting.
- Table captions use the thesis style *Table Title* (above the table) and figure captions the style *Caption* (below the
  figure), with `SEQ Table` / `SEQ Figure` fields. The thesis's List of Tables (`TOC \t "Table Title" \c "Table"`)
  and List of Figures (`TOC \t "Caption"`) therefore pick them up. After pasting, select all and press F9 to
  renumber, then update the two lists.
- Figure captions are a bold title followed by the explanatory note in regular weight, in one paragraph. The List of
  Figures shows the whole paragraph; shorten the note if the list gets long.
- Symbols written as `x_y` in the CSV and Markdown (`c_k`, `e_H`, `Δt_safe`) are real subscripts in the Word file.

## Design

- Type and size match the thesis: Times New Roman (STIX for mathematics), figures 6.25 in wide, white background,
  no titles inside the images. Panel letters (a), (b) are kept because the captions refer to them.
- Colour code: orange = camera (experiment), blue = model (`confirm_c1`),
  aqua = simulated camera. Data roles are shown by marker shape and fill in ink and grey (filled circle =
  calibration, open square = held out in window, grey triangle = out of window examined, open diamond = out of
  window blind), so they survive a greyscale print.
- Table and figure titles are short, descriptive and unnumbered; Word numbers them.

## Provenance of the values

- **Data values** (sizes, ratios, errors, intervals, counts, slopes) come from the committee package datasets; the
  intervals are its 4,000-replicate percentile bootstraps (coupon level within a group, track level within a single
  coupon).
- **Model and numerical values** (T4, T5, T6) are read at build time from
  `lpbf.model.parameters`, `current_configuration`, `experiments.current_framework`, `runtime.parameters`, `geometry`,
  `calibration_contract`, `laser_component_association`, `hierarchical_objective` and `log_ratio_objective`, as
  committee T5 does.
- **Setup facts that the repository does not record** come from thesis section 3.2.1, the author's experimental record:
  machine, laser wavelength, feedstock, build plate, atmosphere and O₂ level, fume extraction, coupon height and layer
  count, and camera exposure. They are marked `owner` in `tables/T1_lpbf_setup.csv`. The repository and the coupon
  files confirm the rest: spot, hatch, layer, footprint, observed layer 53, 54 tracks per layer, the 45° hatch
  rotation, and the camera model in ledger A24.
- **F2** re-measures one stored camera frame with the documented convention (`measure_blob`: ≥ 150 counts, largest
  8-connected component, external contour, minimum-area rectangle). The canonical camera H/W are the values stored
  with the dataset. The frame was chosen by the presentation package's fixed rule, so its re-measurement agrees with
  the stored value within half a pixel.
- **F12** draws the committee package's recorded outlines (its F13 sources) and its operator group table (T14).
- **F6** and **F13** are thesis-style versions of the defense-talk figures "Melt pool footprints over process space"
  and "Camera thresholds and model isotherms", from their stored sources (`presentation_figures/source/condition_sizes.csv`,
  `levels_feature_frame.csv`, `levels_feature_outlines.npz`; see `presentation_figures/README.md`).
- **Captions** are qualitative: no counts or results, except a named threshold (V ≤ 1.25, the
  150-count camera threshold, the 1673 K liquidus). Where a caption states a finding, the build asserts it holds in the
  data (F11, F13).

## Notes on conventions

- **Laser state.** The code treats the laser as on above 2.5 V (strict). T3 reproduces the setup table as written
  ("≥ 2.5 V"). The signal is binary (0 or 5 V), so both wordings select the same frames.
- **Image size.** The stored camera array is 24 rows × 64 columns, that is 64 px wide × 24 px tall. T1 uses
  "64 × 24 px"; T3 uses "24 × 64 pixels".
- **Sync Pulse.** The channel is zero throughout layer 53 of all 24 files. Synchronization is by edge matching of the
  laser state and image intensity.

## How to rebuild

From the repo root, in PowerShell, with the analysis environment (`.venv-analysis`, see the top-level README):

```powershell
$env:PYTHONPATH = "$PWD\src"
.\.venv-analysis\Scripts\python.exe docs\analysis\thesis_figures\scripts\build.py   # about 10 s
.\.venv\Scripts\python.exe -m pytest -q tests\test_thesis_figures.py
```

| Script | Role |
|---|---|
| `style.py` | thesis type and sizes, colours, role markers, save helpers |
| `data.py` | readers for the committee data and the presentation sources |
| `charts.py` | F1, F6–F11 |
| `images.py` | F2 (camera extraction steps), F12 (observation operators), F13 (camera thresholds and model isotherms) |
| `diagrams.py` | F3 (scoring and aggregation), F4 (model schematic), F5 (calibration workflow) |
| `thesis_tables.py` | T1–T10 (CSV and Markdown) |
| `docx_writer.py` | the Word file (thesis styles, SEQ captions, fixed zip timestamps) |
| `build.py` | orchestration, captions with computed numbers, placement, index and hash list |

## Caveats to state with these items

- The camera's threshold-150 blob and the model's liquidus are different physical boundaries (A12). The camera's
  dimensions are unvalidated (A24): sizes in µm use the nominal 8 µm/px. Ratios, shapes and slopes do not depend on
  that scale.
- Intervals over coupons are coarse where a group has few coupons. Single-coupon intervals show within-coupon
  sampling only.
- The bootstrap intervals, process-response slopes, replicate comparison and robustness items are exploratory. Only
  the V and X readings were predeclared (committee T17).
