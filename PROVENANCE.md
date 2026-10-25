# Provenance

## Origin

The thesis was developed in a private repository whose history is not published. Its final commit `f15cce9`
(2026-10-24) was exported byte-for-byte into this repository (commit `27a83ea`, release of 2026-10-24); the present
release `v1.0.0` restructures that export into a canonical research-software package: patch-numbered modules were
consolidated under descriptive names, development-only code and records were removed, the evidence was moved to
`results/`, the package became installable, and the one check that needed git metadata was replaced by a
release-internal hash record. **No numerical statement, parameter, scoring definition or result was changed**, and
the restructuring was validated against the recorded run (below).

## Which code produced the results

Every stage of the calibration recorded the private commit it ran at, a clean worktree, and the SHA-256 of the module
that ran it (`provenance.git_commit`, `git_worktree_dirty`, `module_sha256`, `objective_module_sha256`,
`plan_sha256`, `design_sha256` in the manifests under `results/calibration/`).

| Stage | Private commit | Recorded `module_sha256` | That module, at the export `27a83ea` | Now |
|---|---|---|---|---|
| smoke, calibrate | `bebec6d`, `78dc07d` (2026-10-15) | `d31422f1…76a1` | `patch22_4_3_2_window_calibration.py`, one revision earlier (see below) | `src/lpbf/calibration.py` |
| confirm, evaluate | `ec53a55`, `2fdc58c` (2026-10-16) | `34373f4a…371a` | `patch22_4_3_2_window_calibration.py` = `34373f4a…371a` (identical) | `src/lpbf/calibration.py` |
| synthetic | `2fdc58c` | `89c0b29d…a396` | `patch22_4_3_2_synthetic_camera.py` = `89c0b29d…a396` (identical) | `src/lpbf/observation_operators.py` |
| all | | `objective_module_sha256` `fa7c356f…efcfb` | `log_ratio_objective.py` = `fa7c356f…efcfb` | `src/lpbf/log_ratio_objective.py`, **unchanged** |
| all | | `plan_sha256` `ac103ea2…ce0d` | `PATCH_22_4_3_2_PLAN.md` | `results/calibration/PREDECLARED_PLAN.md`, **unchanged bytes** |
| all | | `design_sha256` `2fa0b8bc…` | `patch21_3_coarse_global_search_design.json` | `src/lpbf/data/calibration_design.json`, **unchanged bytes** |

The smoke and calibrate stages ran one revision before `ec53a55`, which added 17 lines to the walk that places the
confirmation candidates (and changed the file's line endings); the thermal evaluation of a candidate on a coupon did
not change. The fix and its reason are recorded in `results/calibration/pre_fix/README.md`.

The 8 files of the frozen numerical core (`src/lpbf/model/_accepted_core/`) are byte-identical to the code that ran
and are pinned by `src/lpbf/data/accepted_core_hashes.json` (`tests/test_accepted_core_hashes.py`; the smoke gate
checks the same hashes). The thesis's results were produced with Python 3.13.15, numpy 2.5.4, numba 0.68.0,
h5py 3.16.0 and opencv-python 5.0.0.93 on Windows (`requirements.lock.txt`; the manifests record the runtime).

## What the restructuring changed

Modules were moved and consolidated with their function bodies intact (cut and paste, imports rewritten). The only
function bodies that changed are listed here:

| Change | Where | Why |
|---|---|---|
| `verify_committed_freeze` no longer runs `git show HEAD:`; it checks the freeze's SHA-256 against the value recorded in `src/lpbf/data/final_model.json` (and its own content hash, as before). A comparison with HEAD is still made in a git clone, as an aid that never fails the check. | `calibration.py` | the package must pass its tests from a source ZIP without `.git` |
| Four copies of a `_git` helper became `infrastructure.git_metadata`, which records `None` for the commit and the worktree state when git is unavailable (the old helper recorded the string `"unavailable"` and then, by mistake, `worktree_dirty = True`). | `calibration.py`, `observation_operators.py`, committee `run_all.py`, `controls.py` | same; and a correctness fix in a provenance field |
| The data roles, the energy-density window, hatch and layer thickness, the boiling temperature used for reporting and the camera definition are imported from `dataset_split.py` / `configuration.py` instead of being literals repeated in several files. The values are identical and `tests/test_configuration.py` asserts the stored split equals its derivation. | `calibration.py`, `synthetic_camera.py`, committee `common.py` | one source of truth |
| Path constants point at `results/…` and `src/lpbf/data/…` instead of `docs/patches/…` and the repository root. | all movers | the relocation |
| `run_evaluate` records `calibration_records_reproduced: null` instead of raising when the output directory holds no calibration stage (a standalone rerun of the evaluate stage); with the stages present it compares frame records as before and records `true`/`false`. The field is informational. | `calibration.py` | `reproduce evaluate` into a fresh directory must complete |
| `dispatch_lock_check` reports the same record (`CAMPAIGN_DISPATCH_AUTHORIZED_BY = None`, "locked") but no longer imports the removed campaign dispatcher. | `field_capture.py` | the dispatcher is gone |

Consolidation map (old file at `27a83ea` → new module):

| Old module | New module | Kept |
|---|---|---|
| `patch22_4_3_2_window_calibration.py` | `calibration.py` | all stages, surrogate, readings |
| `patch22_4_3_2_synthetic_camera.py` | `observation_operators.py` | all |
| `patch22_3_8_synthetic_camera.py` | `synthetic_camera.py` | radiometry, PSF, mapping, measurement, `evaluate_scope`; the Step-3 runner and readings removed |
| `patch22_3_8_camera_step0.py` | `camera_observations.py` | frame reading, blob measurement, camera-side frame selection, trends; the Step-0 analysis and verdict removed |
| `patch22_3_8_field_capture.py` | `field_capture.py` | instrumentation, capture storage, smoke-reference comparison, core-hash check; Step-2/4 units, round trip, gate and runner removed |
| `patch22_4_3_parallel_coarse_calibration_execution.py` | `frame_records.py` (11 functions) | the frame-table reader, member context, trial gate, frame-record conversion; the 272-unit campaign dispatcher (17 functions, never run; ledger S10) removed |
| `patch22_3_7_stage_a.py` | `frame_records.py` (2 functions) | `_annotate_frame_records`, `_csv_value`; the Stage-A runner removed |
| `patch22_4_2_parallel_coarse_calibration.py`, `patch22_3_5_1_frozen_revalidation.py` | `calibration_design.py` | the design loader and candidate coordinates; everything else removed |
| `observational_characterization.py` | `characterization.py` | all (the HDF5 → observation-table tool) |
| — | `dataset_split.py`, `configuration.py`, `synthetic_example.py`, `reproduce.py` | new |

Removed entirely (reached by no live code): `patch22_3_6_association_census.py`, `patch22_4_1_calibration_readiness.py`,
`calibration_evaluation.py`, `execution/api.py`, `execution/campaign_provenance.py`, `experiments/execution.py`,
`provenance/artifacts.py`; and inside kept modules the functions that nothing referenced (listed in the release
notes). The superseded 22.3.5 distance selector `select_laser_associated_component` is kept in
`laser_component_association.py` because the association tests exercise it as the reference the beam-share rule
replaced; it is not on any production path.

Package data were renamed without changing their bytes: `patch21_0_calibration_contract.json` →
`calibration_contract.json`, `patch21_3_coarse_global_search_design.json` → `calibration_design.json`,
`PATCH_22_3_4_ACCEPTED_CORE_HASHES.json` → `src/lpbf/data/accepted_core_hashes.json`.

Version strings (`"22.4.3.2"` objective contract, `"22.3.7"` association policy and H/W semantics, work-unit ids
`22.4.3.2:<candidate>@<member>`) are the semantic identifiers recorded in every unit file and manifest and are kept.

## How numerical equivalence was verified

Before the restructuring, the export `27a83ea` with the data bundle gave: 260 tests passed; committee, thesis-figure
and figure-source rebuilds byte-identical to the committed outputs; a smoke-stage rerun bit-identical to the
recorded gate. After the restructuring, on the same machine and data:

1. **Tests.** 168 tests pass in the git clone; the same 168 pass from a source ZIP without `.git` (`git archive`)
   in a fresh virtual environment installed with `pip install -e .[test]` and the data mounted; without any data,
   160 pass and the 8 tests that read the recorded run skip. No test needs git.
2. **Analysis rebuild.** `reproduce analysis` regenerates the committee package, the thesis tables and figures and
   the figure sources. Against the pre-restructuring outputs, every CSV, CSV.GZ, NPZ, JSON dataset, PNG, SVG and the
   `.docx` are byte-identical. Exactly eight text files differ, all in provenance text: committee `T05` (the
   core-hash file is now named `accepted_core_hashes.json`), `T16` (the evidence paths are now under `results/`),
   `METHODS_MANIFEST.json`, `PROVENANCE.json` and `OUTPUT_SHA256SUMS.txt` (package path and build record),
   `registers/private_git_history.json` (its keys are the new paths), and thesis `T6` (one source line names
   `lpbf.calibration` instead of the old module).
3. **Characterization.** `reproduce characterize` on the 24 coupon files reproduces the bundle's characterization:
   all 48 `frame_observations.csv` / `scan_tracks.csv` files and all 24 `member_audit.json` files are identical, as
   are the aggregate track and coupon tables.
4. **Smoke stage.** `reproduce smoke` into a scratch directory: gate status, checks, log-ratio score, pixel objective
   and the comparison with the frozen reference equal the recorded `results/calibration/smoke/smoke_gate.json`; the
   unit file is byte-identical to the recorded one (all 26 fields, 1,162 frame records; J = 0.6227886949003064).
   Only the `provenance` block differs (this repository's commit and the new module's hash).
5. **Evaluate stage.** `reproduce evaluate` into a scratch directory, 39 units on 4 workers (2.4 h): all 39 unit
   files and all 24 temperature-field files are byte-identical to the recorded ones (their SHA-256 equal the values
   in `results/calibration/evaluate/stage_manifest.json`), and the rerun's manifest equals the recorded one in its
   `units` and `readings` blocks (V_PASS, X_PARTIAL, the same group scores and per-coupon rows). Only `execution`
   (timing), `provenance` (this repository's commit, the new module's hash) and `calibration_records_reproduced`
   differ; the last is `null` in a standalone rerun (see the table above) where the recorded run has `true`.
6. **Headline metrics**, read from the moved results files, equal the thesis's: `confirm_c1` at t = −3,
   ck = 2.41774, η = 0; J 0.298, e_H 0.651, e_W 0.416; held-out ratios 1.03 / 1.02; Spearman 0.976 / 0.964;
   24,129 scored frames.

## Historical material kept on purpose

- `results/calibration/pre_fix/`: the first confirmation stage and freeze, superseded by a documented code fix before
  the real freeze; cited by the committee registers (T17) and `RESULTS.md` as a recorded post-data deviation.
- `results/calibration/PREDECLARED_PLAN.md` and `results/camera_diagnostic/PREDECLARED_PLAN.md`: the protocols fixed
  before the runs; predeclaration is a reported integrity property and the plans' hashes are in the manifests. They
  still name development files and tools in their closing checklists; they are kept byte-identical.
- `results/smoke_reference/`: the frame records every smoke stage must reproduce bit for bit.
- `results/committee_package/registers/private_git_history.json`: the private commits and dates that table T16
  reports, which cannot be looked up in this repository.
- The recorded synchronization audit (`results/synchronization_audit/track_start_audit.json`) names the output folder
  of the development machine it was written to, and the stage manifests name private commits; they are run records
  whose SHA-256 the analysis verifies, and were left unchanged.

## Not included

The private repository's history and tags; its decision ledger in full (condensed into `docs/DECISIONS.md` with the
same entry IDs); the runners, launchers and records of the development steps that preceded the calibration, except
the evidence files the code and the tables read; the talk figures and animations of the defense (their image
sources stay); the thesis document; the development tooling configuration; a third-party dissertation draft used as a
method reference; and the data (`data/README.md`).
