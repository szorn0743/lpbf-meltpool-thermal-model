# Committee statistical outputs: tables and figures

The outputs of the committee statistical package, in
`docs/analysis/committee_package/`. All of them describe the frozen Patch 22.4.3.2 candidate `confirm_c1`. The
package re-reads the recorded runs only: no new thermal runs, no fitting and no selection.

- **Tables** are in `tables/`, each as Markdown (rounded, for reading) and CSV (full precision).
- **Figures** are in `figures/` as PNG (300 dpi) and SVG. Every plotted value is in `figures/source/`.
- **Status** says whether a result was fixed before its data were read (*predeclared*) or added afterwards
  (*exploratory*). `METHODS_MANIFEST.json` gives the status of every item.
- **Sources of truth.** The decision ledger (`docs/DECISIONS.md`) and
  `docs/patches/22.4.3.2/PATCH_22_4_3_2_RESULTS.md` remain authoritative.

The package README (`docs/analysis/committee_package/README.md`) gives the method, the checks run on every build
and how to reproduce the package.

## Tables

| # | Title | What it shows | Status | File |
|---|---|---|---|---|
| T1 | Definitions and conventions | The terms used throughout: camera and model H/W, units, the log residual, e_H, e_W, J, the weighting hierarchy, scored and undefined frames, coverage and the interval method. | conventions | `T01_definitions` |
| T2 | Coupon roster | Each of the 24 coupons: acquisition date, power, speed, VED, replicate pair, role, tracks and scored frames. | record | `T02_coupon_roster` |
| T3 | Partition and data-use history | The four groups (calibration, in-window held out, out-of-window examined, out-of-window blind), and which stage read each coupon's data and when. | record | `T03_partition_and_data_use` |
| T4 | Data accounting | Frame counts per coupon from the camera stream down to the scored frames, so that nothing is removed silently. | record | `T04_data_accounting` |
| T5 | Fixed model and numerical controls | Grid, window, time step, laser-on rule, beam, material, boiling regulator, association policy and scoring rules. Only t, ck and η were calibrated. | record | `T05_fixed_controls` |
| T6 | Calibration candidate search | All 19 calibrated candidates ranked by measured J, with coordinates, guard value, coverage and errors. | predeclared rule | `T06_candidate_search` |
| T7 | Calibration performance | c1 on its 9 calibration coupons: sizes, ratios, e_H, e_W and J, pooled and by condition and coupon. | reading C; intervals exploratory | `T07_calibration_performance` |
| T8 | In-window held-out performance | The same for the 5 in-window held-out coupons, with the held-out / calibration error ratios and their intervals. | reading V; intervals exploratory | `T08_held_out_performance` |
| T9 | Out-of-window performance | The 10 coupons outside 65–85 J/mm³, sorted by VED, with the rank correlations of reading X. | reading X; intervals exploratory | `T09_out_of_window_performance` |
| T10 | Replicates and measurement floor | How closely the coupons built on 20260730 and 20260731 agree, and the error that a perfect track- or coupon-level predictor would still score. | exploratory | `T10_replicates_and_measurement_floor` |
| T11 | Process-response slopes | How camera and model H, W and H/W scale with power, speed and VED. | exploratory | `T11_process_slopes` |
| T12 | Variance and effective sample size | Where the data vary (frame, track, coupon or condition), what the ~24,000 frames are worth as independent observations, and a permutation test of whether the model follows the camera within a coupon. | exploratory | `T12_variance_and_sample_size` |
| T13 | Failure modes and coverage | Counts of no-pool frames, timing exclusions, camera-invalid frames, crop contact and peaks above boiling. The undefined classes are listed as zero. | descriptive | `T13_failure_modes` |
| T14 | Measurement operators | The model liquidus, the synthetic camera, the width-matched isotherm and the camera's own threshold family compared, and which conclusions depend on the 8 µm/px scale. | reading S and 22.3.8 readings; slopes exploratory | `T14_measurement_operators` |
| T15 | Sensitivity and robustness | How the selection and the errors respond to the objective, the choice of c1 or c2, the summary statistic, the weighting, the pixel floor, short tracks, dropping one coupon, and the camera threshold. | exploratory | `T15_sensitivity` |
| T16 | Provenance | For each 22.4.3.2 stage: code commit, workers, runtime and held-out access; and the reproducibility facts for this package. | record | `T16_provenance` |
| T17 | Predeclared criteria | Every gate and reading that was fixed before its data were read: when it was written, what had been seen, and the outcome. | register | `T17_predeclared_criteria` |
| T18 | Confounds | Design features that cannot be separated from the reported effects: part number, scan order, campaign, collinearity of the calibration design and track order. | exploratory | `T18_confounds` |
| T19 | Synchronization quality | Per coupon: sync method, frame counts, where the track ends map, and the July and September anchor conventions. | record | `T19_synchronization` |

## Figures

| # | Title | What it shows | Status | File |
|---|---|---|---|---|
| F1 | Coupons by acquisition set and part | The 24 coupons laid out by acquisition set and part, marked by role. | descriptive | `F1_partition` |
| F2 | Analysis hierarchy | The averaging chain frame → track → coupon → condition → group, with where exclusions and bootstrap resampling happen. | descriptive | `F2_hierarchy` |
| F3 | Process space and calibration window | Power against speed, with VED isolines and the calibration window shaded. | descriptive | `F3_process_space` |
| F4 | Calibration response surface | The surrogate J on three slices through c1, with all the candidates, the parameter box, the guard boundary and the edge band. | recorded surrogate; slices descriptive | `F4_response_surface` |
| F5 | Camera and model melt pool size by coupon | Camera against model H and W per coupon, with a 1:1 line. | descriptive | `F5_observed_vs_predicted` |
| F6 | Model-to-camera ratio against VED | Model / camera H and W ratios per coupon against VED, with a fitted trend and band. | points: reading X; trend exploratory | `F6_ratio_vs_ved` |
| F7 | Frame residuals by group | Violins of the frame residuals by group, with the coupon medians. | descriptive | `F7_residual_distributions` |
| F8 | Bland–Altman agreement | Agreement on the log scale: the in-window bias and limits, and the proportional trend outside the window. | exploratory | `F8_bland_altman` |
| F9 | Replicate agreement | 20260730 against 20260731 for camera H and W, model H and W, e_H and e_W. | exploratory | `F9_replicate_agreement` |
| F10 | Frames without a predicted pool | The share of frames without a predicted pool against VED and against speed. Coverage is 1.000 for every coupon. | descriptive | `F10_no_pool_coverage` |
| F11 | Process-response slopes | Camera and model slopes on power and speed, with intervals and the Rosenthal point-source reference. | exploratory | `F11_process_slopes` |
| F12 | Track medians in scan order | Track medians in scan order for a low-VED, an in-window and a high-VED coupon. The camera's H grows through the layer; the model's stays flat. | exploratory | `F12_within_layer` |
| F13 | Melt pool boundaries on one camera frame | One camera frame per condition with four boundaries drawn on it: the camera blob, the model liquidus, the synthetic camera and the width-matched isotherm. | descriptive illustration | `F13_measurement_operators` |
| F14 | Peak surface temperature | The share of frames above boiling against VED and against t, and the H mismatch against peak temperature. The best H agreement comes at the coolest peaks. | descriptive | `F14_peak_temperature` |
| F15 | Agreement over process space | H ratio, W ratio, e_H, e_W and no-pool fraction for each of the 18 conditions. | descriptive | `F15_process_space_heatmaps` |

## Supporting data

The data files D1–D10 back the tables and figures. They are:
- the frame, track, coupon and condition datasets;
- the bootstrap draws;
- the candidate-search archive;
- the exclusion ledger;
- the figure sources;
- the methods manifest;
- the reproduction files.

They are in `data/`, `figures/source/` and the package root, and the package README lists each one.

## Caveats that apply throughout

- Every comparison sets the model's liquidus contour against the camera's threshold-150 blob. These are different
  physical boundaries (ledger A12).
- The camera scale of 8 µm/px is nominal and unvalidated (A24). Shapes, slopes and rank correlations do not depend on
  it.
- The 8 held-out coupons were opened by the 22.4.3.2 evaluation after the selection freeze. Any later fitting or
  selection on them is no longer held-out validation (A8, A27).
- Intervals over coupons are coarse where a group has only a few coupons. Single-coupon intervals show within-coupon
  sampling only.
