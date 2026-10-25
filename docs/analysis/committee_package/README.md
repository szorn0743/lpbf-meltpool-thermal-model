# Committee statistical-output package

Status: **descriptive analysis, passes 1 and 2, 2026-10-19. It is not a patch.**
- It re-reads the frozen Patch 22.4.3.2 records of the selected candidate `confirm_c1`. There are no thermal runs,
  no fitting and no selection, and it changes no production code, semantics, frozen core or process record.
- The ledger (`docs/DECISIONS.md`, A25–A27) and `docs/patches/22.4.3.2/PATCH_22_4_3_2_RESULTS.md` stay
  authoritative. Items that were not predeclared are flagged as exploratory, here and in `METHODS_MANIFEST.json`.
- **Held-out status.** The 8 A8 held-out members were opened by the 22.4.3.2 evaluation after its selection freeze
  (A8, A27). This package uses them only descriptively. Any later fitting or selection on them is no longer held-out
  validation.

The package answers four questions a committee asks:
- Was the study controlled? T1, T5, T6, T16, T17 and F4.
- Were calibration and validation independent? T3 with its data-use history, F1, the confound table (T18) and T19.
- Is it reproducible? The hashes, the scripts, D6 (the selection rebuilt from the records), T16 and this README.
- Is it honest about uncertainty? Intervals over coupons, T4/D7 accounting, T13 failure modes, the measurement floor
  (T10), the effective sample size (T12) and the sensitivity checks (T15).

## Contents

Pass 1 (core) and pass 2 (appendix) together cover all 41 items of the proposed list, plus the seven additions of
the plan (T17 register, data-use history, measurement floor, within-coupon power, confound table, synchronization
table, weighting and threshold sensitivity). `TABLES_AND_FIGURES.md` describes every table and figure in one line.

| Item | File(s) | Status |
|---|---|---|
| T1 definitions and conventions | `tables/T01_definitions.*` | conventions (A10, A20–A26) |
| T2 coupon roster | `tables/T02_coupon_roster.*` | record |
| T3 partition and per-coupon data-use history | `tables/T03_partition_and_data_use.*`, `tables/T03_partition.csv`, `registers/data_use_history.json` | record |
| T4 data accounting | `tables/T04_data_accounting.*` | record |
| T5 fixed model and numerical controls | `tables/T05_fixed_controls.*` | record, read from the code at build time |
| T6 candidate search | `tables/T06_candidate_search.*` | predeclared rule; committed values |
| T7 calibration performance | `tables/T07_calibration_performance.*` | point values: reading C; intervals exploratory |
| T8 held-out performance and reading V | `tables/T08_held_out_performance.*` | point ratios: reading V; intervals exploratory |
| T9 out-of-window performance and reading X | `tables/T09_out_of_window_performance.*` | Spearman values: reading X; intervals exploratory |
| T10 replicates and measurement floor | `tables/T10_replicates_and_measurement_floor.*`, `data/T10_*.csv` | exploratory |
| T11 process-response slopes | `tables/T11_process_slopes.*`, `data/T11_process_slopes.csv` | exploratory |
| T12 variance, effective sample size, within-coupon power | `tables/T12_variance_and_sample_size.*`, `data/T12_*.csv` | exploratory |
| T13 failure modes | `tables/T13_failure_modes.*` | descriptive |
| T14 measurement operators | `tables/T14_measurement_operators.*`, `data/T14_*.csv` | reading S and 22.3.8 readings; slopes exploratory |
| T15 sensitivity and robustness | `tables/T15_sensitivity.*`, `data/T15_*.csv` | exploratory |
| T16 provenance | `tables/T16_provenance.*` | record |
| T17 predeclared-criteria register | `tables/T17_predeclared_criteria.*`, `registers/predeclared_criteria.json` | register |
| T18 confound table | `tables/T18_confounds.*`, `data/confound_checks.json` | exploratory |
| T19 synchronization quality | `tables/T19_synchronization.*`, `data/T19_synchronization.csv` | record (checked against the 22.3.6 audit) |
| F1 partition, F2 hierarchy, F3 process space | `figures/F1_partition.*`, `figures/F2_hierarchy.*`, `figures/F3_process_space.*` | descriptive |
| F4 calibration response surface | `figures/F4_response_surface.*` | recorded surrogate; slices descriptive |
| F5 observed vs predicted | `figures/F5_observed_vs_predicted.*` | descriptive |
| F6 ratio vs VED | `figures/F6_ratio_vs_ved.*` | points: reading-X inputs; fitted trend exploratory |
| F7 residual distributions | `figures/F7_residual_distributions.*` | descriptive |
| F8 Bland–Altman | `figures/F8_bland_altman.*` | exploratory |
| F9 replicate agreement | `figures/F9_replicate_agreement.*` | exploratory |
| F10 no-pool frames and coverage | `figures/F10_no_pool_coverage.*` | descriptive |
| F11 slope comparison | `figures/F11_process_slopes.*` | exploratory |
| F12 within-layer evolution | `figures/F12_within_layer.*` | exploratory |
| F13 measurement operators on one frame | `figures/F13_measurement_operators.*` | descriptive illustration |
| F14 peak temperature | `figures/F14_peak_temperature.*` | descriptive |
| F15 heat maps over process space | `figures/F15_process_space_heatmaps.*` | descriptive |
| D1 frames (one row per scored frame) | `data/D1_frames.csv.gz` | data |
| D2 tracks, D3 coupons | `data/D2_tracks.csv`, `data/D3_coupons.csv` | data |
| D4 conditions and groups, with intervals | `data/D4_conditions_groups.csv` | data |
| D5 bootstrap distributions | `data/bootstrap/D5_*.npz`, `data/bootstrap/D5_bootstrap_summary.csv` | exploratory |
| D6 candidate-search archive | `data/D6_candidate_search/` (candidates, coupons, conditions, unit hashes, `D6_selection_reconstruction.json`) | record + reconstruction |
| D7 exclusion and failure ledger | `data/D7_exclusion_ledger.csv` | data |
| D8 figure sources | `figures/source/F*.csv` (and `F4_surface_meta.json`) | data |
| D9 methods manifest | `METHODS_MANIFEST.json` | |
| D10 reproduction | this README, `PROVENANCE.json`, `OUTPUT_SHA256SUMS.txt`, `requirements.analysis.txt`, `scripts/` | |

Tables come as Markdown (rounded, for reading) and CSV (full precision, for reuse). Figures come as PNG (300 dpi) and
SVG with text kept as text. Every plotted value is in `figures/source/`; the F7 violins are drawn from D1. Numbers in
table notes and figure captions are computed from the data at build time, not typed in.

## What pass 2 adds, in brief

- **Controls (T5, T16, D6, F4).** Only t, ck and η were calibrated; every other control was identical in all six
  stage manifests. The selection is rebuilt from the recorded scores: the same winner, J_min, near-best set and
  reading C; the surrogate refit matches the recorded coefficients to 4e-16.
- **Measurement floor (T10, F9).** The camera repeats between the two July days to within 1.5 % and the model to
  within 0.5 %. A predictor that knew each coupon's camera median exactly would still score e_H about 0.14; the
  model's e_H is about five times that.
- **Within-coupon power (T12, F12).** Inside a coupon the model does not follow the camera: shuffling the camera's
  frames changes the coupon e by about 1 % (H). The camera's H grows through the layer while the model's stays flat.
  With about 1,000 frames per coupon, the frames are worth tens to a few hundred independent observations per group.
- **Operators (T14, F13).** The reading-S synthetic camera reproduces the camera's shape but not its size. A model
  contour matched to the camera's width is still 1.4–3.6 times too long for every frozen design candidate. The
  camera's own size changes 2.6-fold between thresholds 30 and 250 while its shape barely moves.
- **Sensitivity (T15).** The selection is driven by H: a W-only objective would pick another candidate. c2 gives the
  same readings as c1. The reported errors move by at most 0.02 under track or coupon weighting, and by up to 0.09
  when the shortest tracks are dropped.
- **Temperature (F14).** Across the 19 candidates and 9 calibration coupons, |r_H| rises with the peak temperature
  (Spearman ρ 0.97): the best H agreement comes at the coolest peaks, not above boiling.

## Method in brief

- **Unit of inference.** Coupons (24) and conditions (18), not frames. Each level of the contract-22.4.3.2 hierarchy is
  an unweighted mean of the level below: frame → track → coupon → condition → group (F2).
- **Intervals.** 95 % percentile bootstrap, 4,000 replicates, seed 20261019, with one generator per unit
  (`METHODS_MANIFEST.json` lists every key and families 1–8).
  - For groups of 2 or more coupons, coupons are resampled within the group.
  - For single coupons and conditions, tracks are resampled within each coupon, so those intervals show
    within-coupon sampling only.
  - With 2–5 coupons the coupon intervals are coarse, and the tables give the coupon count beside every interval.
- **Model sizes** are medians over frames with a predicted pool. Ratios and errors include the no-pool frames,
  scored as H = W = 0 with the 1 px floor (D1).
- **Units.** µm use the nominal 8 µm/px, which no calibration validates (A24). Shapes (H/W), slopes, error ratios and
  rank correlations are scale-free; T14 E lists which quantities depend on the scale.

## Verification (run on every build)

- **Manifest.** Every coupon and group e_H, e_W, J, median ratio and count recomputed from the unit files equals the
  committed evaluate manifest (174 values, maximum difference 0.0). The production aggregator
  (`aggregate_log_ratio_records`) gives the same calibration score.
- **Synthetic operator.** The reading-S scores recomputed from `synthetic_frames.csv.gz` equal the synthetic stage
  manifest (108 values, maximum difference 0.0).
- **Synchronization.** The track-start and track-end mapping recomputed for all 24 coupons equals the Patch 22.3.6
  audit for its 16 members (96 values).
- **Selection.** D6 re-applies the selection rule and refits the surrogate; any disagreement with the freeze stops the
  build. The 171 calibrate and confirm unit files are checked against their manifest sha256.
- **Inputs.** The unit files and field files match their sha256 values in the evaluate manifest; the three coupon
  HDF5 files F13 reads match the characterization record. T6 equals the calibrate and confirm manifests.
- **Accounting.** For every coupon, eligible − excluded by rule − undefined = scored, and eligible equals the
  Patch 21.3 count. D7 reconciles with T4.
- **Step 0.** The camera slopes on the 16 A8 calibration members agree with 22.3.8 Step 0 within 0.08, well inside
  the intervals.
- **Repeatability.** Two consecutive builds give byte-identical outputs, PNG and SVG included (155 files). A build in
  `.venv` (without matplotlib) reproduces every table, data file and figure source byte for byte (107 files).
- **Tests.** `tests/test_committee_package.py` (17 tests) checks the manifest equality, the bootstrap's determinism and
  point reproduction, the synthetic-operator and sync recomputations, the selection reconstruction, the fixed
  controls across stages, the figure sources against the tables, D7 against T4, and that the registers are complete.
  The full suite passed at the pass-2 commit (273 tests).

## How to reproduce

From the repo root, in PowerShell. Inputs, all from the data bundle (see the top-level README):
- the gitignored c1 unit and field files in `patch22_4_3_2_output/evaluate/`, and the calibrate and confirm unit
  files beside them (D6, F14);
- the Patch 21.3 characterization in `data/characterization/`;
- for F13 only, the coupon HDF5 files (`LPBF_COUPON_DATA_DIR`, default `data/coupons/`). Without them the committed
  F13 sources are kept and the figure is still rendered from them.

```powershell
# one-time: the analysis environment = the lock + matplotlib (never install into .venv)
py -3.13 -m venv .venv-analysis
.\.venv-analysis\Scripts\python.exe -m pip install -r docs\analysis\committee_package\requirements.analysis.txt

$env:PYTHONPATH = "$PWD\src"
.\.venv-analysis\Scripts\python.exe docs\analysis\committee_package\scripts\run_all.py   # about 55 s
.\.venv\Scripts\python.exe -m pytest -q tests\test_committee_package.py
```

Then compare `OUTPUT_SHA256SUMS.txt` with the committed copy. `PROVENANCE.json` records:

- the run time, the git head and the script hashes;
- the runtime;
- every input hash, including the external HDF5 files;
- the verification results.

It changes on every run. The outputs do not.

| Script | Role |
|---|---|
| `common.py` | inputs, frame table, contract hierarchy, bootstrap primitives, analysis groups |
| `build_datasets.py` | D1–D4, D7 and the manifest check |
| `bootstrap.py` | D5 and the intervals |
| `slopes.py` | T11, the F6 trend and the Step-0 check |
| `confounds.py` | the confound checks |
| `controls.py` | T5 values from the code; T16 stage provenance and the cross-stage check |
| `replicates.py` | T10: replicate pairs, within-coupon spread, measurement floor |
| `variance.py` | T12: variance partition, effective sample size, within-coupon power |
| `operators.py` | T14 and the synthetic-manifest check |
| `sensitivity.py` | T15 |
| `candidates.py` | D6, the selection reconstruction and the F4 grids |
| `sync.py` | T19 and the 22.3.6 check |
| `tables.py`, `tables_pass2.py` | the tables |
| `figures.py`, `figures_pass2.py` | figure sources (numpy only) and renders (matplotlib) |
| `field_figures.py` | F13: sources from the HDF5 and field files, and the render |
| `run_all.py` | orchestration, `METHODS_MANIFEST.json`, `PROVENANCE.json`, the hash list |

## Caveats to state with these outputs

- **What is compared.** Every comparison is the model's liquidus H/W against the camera's threshold-150 blob. These
  are different physical boundaries (A12), and the camera's dimensions are unvalidated (A24). F13 shows the
  boundaries on one frame each.
- **Absorptivity and depth** in T6 and D6 are derived from t (`_abs_depth_mapping`). They are not stored in the run
  records.
- **T11 H/W slopes.** The package uses the median of the per-frame H/W, as 22.3.8 Step 0 does. The results report §4
  used ln(median H) − ln(median W): model 1.26 and −0.48, against 1.45 and −0.58 here. The signs agree, and so does
  the gap between model and camera. The H and W slopes match the report to the second decimal.
- **F6 trend.** The log-linear trend is descriptive and curves away from the points at both ends. The predeclared
  statistic is the Spearman correlation (reading X).
- **Width-matched operator.** T14 B and F13 use the Patch 22.3.8 operator. Its table values are for the frozen design
  candidates, not c1; c1 is drawn with it only on the three F13 frames.
- **Oracle floors (T10)** use the camera's own data to define the best a condition-level predictor could do; they are
  reference points, not model results.
- **Held-out data were not entirely unopened.** The Patch 21.3 characterization (2026-10-12) wrote descriptive
  camera summaries for all 24 coupons, held out included. No stage compared them with the model before the freeze
  (T3). The 22.4.3.2 plan's "never opened" holds for model comparison and for every stage from 22.4.3 on.
- **Selection deviation.** One post-data change was made before the freeze: the c2 walk fix, `ec53a55`. It is listed
  in T17, and it did not change the selected candidate.

## Conflicts found while compiling

- **Ledger O11 (resolved 2026-10-19).** O11 said the last eligible frame of every September track is the falling-edge
  anchor, "430 of 430". The committed evidence CSV
  (`docs/patches/22.3.6/evidence/PATCH_22_3_6_SYNC_TRACK_START_AUDIT_TRACKS.csv`) gives 428 of 430. The exceptions
  are `20260904:part_3` track 6 (2 rows before the track end) and `20260910:part_1` track 19 (0 rows). The owner had
  O11 corrected in the ledger; its conclusion is unchanged.
- **Pass 2 found no new conflict** with the ledger or the 22.4.3.2 results report.
