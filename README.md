# Reduced-order thermal simulation for laser powder bed fusion

**What this is.** The research software of a master's thesis: a reduced-order thermal model of single laser tracks
in laser powder bed fusion (LPBF), calibrated against melt-pool dimensions measured by a coaxial near-infrared camera,
together with the frozen configuration, the recorded calibration results and the scripts that produced the thesis's
tables and figures.

**Thesis.** *Reduced Order Thermal Simulation for Laser Powder Bed Fusion*, Samuel Henry Zorn, M.S. Mechanical
Engineering, San Diego State University, 2026. Release `v1.0.0` of this repository is the code package submitted
with it.

## The scientific problem

In LPBF a coaxial camera records the bright melt pool behind the laser at 8000 frames per second. The experiment
provides, for each of 24 coupons (4 acquisition sets × 6 parts, one observed layer each), the synchronized process
data and the camera's melt-pool length H and width W per frame. The model simulates the temperature field of the
moving laser track and extracts the length and width of the liquidus contour of the melt pool that receives the
laser's power. The question of the thesis is how well a calibrated reduced-order model reproduces the camera's H/W
inside its calibration window of volumetric energy density, how it transfers to held-out coupons, and how it
extrapolates outside the window.

## What the model claims, and what it does not

- The model, calibrated on 9 coupons at 65–85 J/mm³, reproduces its own calibration error on 5 held-out coupons in
  the same window (held-out errors within 3 % of the calibration errors). **It demonstrated transfer of its error
  behaviour within the calibrated domain.**
- **It did not demonstrate absolute melt-pool-size accuracy**: at the selected parameters the model's pool is
  1.7–2.0× longer and 0.73–0.88× as wide as the camera's blob, and the camera's own dimensions are not validated
  against an independent measurement (its pixel scale is a nominal 8 µm/px). Agreement here means agreement with the
  camera's H/W definition, not with the true melt-pool size.
- **It did not demonstrate reliable extrapolation outside that domain**: the error grows with the distance in energy
  density, and the model's response to scan speed is 4× (W) to 9× (H) steeper than the camera's.
- The selected parameters lie on the edge of the predeclared parameter box; the optimum is outside it.

The recorded readings are: C_EDGE (calibration), V_PASS (held out, in window), X_PARTIAL (out of window), S (a
synthetic camera does not follow the real one across energy density; descriptive). The full results and failure
modes are in [`results/calibration/RESULTS.md`](results/calibration/RESULTS.md); the methods and every convention
are in [`docs/DECISIONS.md`](docs/DECISIONS.md).

## Installation

Python 3.13 (the results were produced with 3.13.15 on Windows; the parallel stages use the `spawn` start method).

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .            # model + tests' dependencies, pinned to the recorded versions
.\.venv\Scripts\python.exe -m pip install -e ".[test]"    # adds pytest
```

The thesis figures need matplotlib. Keep it in a second environment, because the numerical provenance of the model
depends on the exact versions in the first one:

```powershell
py -3.13 -m venv .venv-analysis
.\.venv-analysis\Scripts\python.exe -m pip install -e ".[analysis,test]"
```

`requirements.lock.txt` and `requirements.analysis.lock.txt` are the exact environments of the recorded run and of
the figure builds. On Linux or macOS use `python3.13 -m venv` and `.venv/bin/python`.

## Data

| | Included in this repository | Not included |
|---|---|---|
| **Experimental data** | The process parameters of the 24 coupons (`docs/reference/LPBF_Process_Parameters.csv`); the camera-side frame counts, synchronization audit and per-coupon summaries used by the tables (`results/`). | The 24 coupon HDF5 files (1.1 GB zipped): process channels and camera frames. |
| **Derived data** | Every table, dataset and figure source of the thesis and of the committee package (`results/committee_package/data`, `results/thesis_figures`), the stage manifests, the selection freeze and the synthetic-camera frames of the recorded calibration. | The per-unit files and temperature fields of the recorded calibration run (0.7 GB zipped); the characterization tables (5 MB zipped). |

The data are not public yet; they are available from the author on request as three zip archives that unpack into
`data/coupons/`, `data/characterization/` and `runs/recorded_calibration/`. [`data/README.md`](data/README.md)
gives the layout, the file list and the SHA-256 of every file (`data/SHA256SUMS.txt`), and
`python -m lpbf.reproduce check-data` reports what is present.

Without the data you can install and test the package, run the synthetic example, read every result, and inspect
the frozen configuration. With the data you can rebuild every table and figure from the recorded run (minutes),
re-execute the calibration's smoke gate (6 min) or its evaluation stage (2.5 h), and re-run the whole calibration
(about 10 h).

## The minimal example

```powershell
python -m lpbf.reproduce example
```

writes a small **synthetic** coupon (two straight tracks, a constant "camera" melt pool), runs the frozen model on it
at the thesis's parameters, extracts the melt pool, scores it, and writes `examples/synthetic/output/`. It takes about
ten seconds and shows that installation, input parsing, the solver, melt-pool extraction and scoring work. Its numbers
have no scientific meaning; see [`examples/synthetic/README.md`](examples/synthetic/README.md).

## Reproducing the thesis analysis

All commands run from the repository root; `python -m lpbf.reproduce --help` lists them.

```powershell
python -m lpbf.reproduce check-data              # which data files are present
python -m lpbf.reproduce analysis                # figure sources -> committee package -> thesis tables/figures (.venv-analysis, ~2 min)
python -m lpbf.reproduce smoke                   # the calibration's gate unit, bit-identical to the recorded one (~6 min)
python -m lpbf.reproduce evaluate                # the selected candidate on all 24 coupons, 39 units (~2.5 h, 4 workers)
python -m lpbf.reproduce calibrate               # the 17 design candidates on the 9 calibration coupons, 153 units (~6 h)
python -m lpbf.reproduce confirm                 # the confirmation candidates (~1 h)
python -m lpbf.reproduce freeze                  # selection by lowest measured objective (seconds)
python -m lpbf.reproduce synthetic-camera        # reading S on the evaluate stage's fields (~5 min)
python -m lpbf.reproduce characterize --data-dir data/coupons --output-dir <dir>   # HDF5 -> camera observation tables
```

The thermal stages write to `runs/calibration/` by default (`--output-dir` changes it); the recorded run of the thesis
lives in `runs/recorded_calibration/` and is never overwritten. `evaluate` and `synthetic-camera` run against the
recorded selection freeze (`results/calibration/selection_freeze.json`), whose SHA-256 is pinned in the frozen
configuration; this check uses no git metadata, so it passes in a clone and in a source ZIP alike. The analysis
builds are deterministic: `git diff` after `reproduce analysis` shows no change to the committed outputs.

## Where the frozen configuration is

[`src/lpbf/data/final_model.json`](src/lpbf/data/final_model.json) is the one readable record of the final model:
numerics (99 × 99 window at 16 µm, 2.5 µs time step, 21 depth cells), material constants, boundary conditions, the
laser source, the moving window, the fixed boiling regulator, the observation definitions on both sides (beam-share
association with its 2 % floor; camera threshold 150 on 64 × 24 px frames), the scoring rules (scored-frame rule,
95 % coverage floor, log-ratio residuals with a 1 px floor, the aggregation hierarchy), the calibration contract
(bounds, guard, design, 65–85 J/mm³ window) and the selected parameters (`confirm_c1`: t = −3, ck = 2.418, η = 0,
hence absorptivity 0.490 and deposition depth 0.098 mm) with the SHA-256 of the selection freeze they come from.

It is assembled by `lpbf.configuration.final_configuration()` from the code's own constants and the recorded freeze,
and `tests/test_configuration.py` fails if the committed file and the assembly ever differ. The data split is stored
in [`src/lpbf/data/dataset_split.json`](src/lpbf/data/dataset_split.json) (calibration; held out, in window; out of
window, examined; out of window, blind) and checked against its derivation from the partition and the window.

## Running the tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

The suite passes from a git clone and from a source ZIP without `.git`. Without the data bundle the tests that read
the recorded run are skipped; with it they also re-derive the thesis's hierarchy from the recorded unit files and
compare it with the stage manifests. The suite includes focused tests of the scoring hierarchy
(`tests/test_scoring_hierarchy.py`: frames do not weight tracks, tracks do not weight coupons, replicates do not
weight conditions, log-ratio residuals, the pixel floor, edge-frame exclusion, undefined predictions, coverage),
of the melt-pool association, of the frozen numerical core's hashes, of the frozen configuration, and the synthetic
end-to-end example.

## Expected outputs

| Command | Output |
|---|---|
| `example` | `examples/synthetic/output/{synthetic_coupon.h5, example_result.json, frame_records.csv}` |
| `smoke` | `runs/calibration/smoke/smoke_gate.json` with `status: PASS_PATCH_22_4_3_2_SMOKE_GATE`; equal to `results/calibration/smoke/smoke_gate.json` in every field except `execution` and `provenance` |
| `calibrate`, `confirm`, `evaluate` | `runs/calibration/<stage>/{stage_manifest.json, units/*.json}` (+ `fields/*.npz` for `evaluate`); the unit files equal the recorded ones in `runs/recorded_calibration/` (compare their SHA-256 with `results/calibration/<stage>/stage_manifest.json`). `evaluate` alone, in a directory without the `confirm` stage, records `calibration_records_reproduced: null`. |
| `freeze` | `runs/calibration/freeze/{selection_freeze.json, calibration_reading.json}`; `selected.candidate_id == "confirm_c1"` |
| `analysis` | regenerates `results/figure_sources/source`, `results/committee_package/{data,tables,figures}` and `results/thesis_figures/{tables,figures,thesis_tables_and_figures.docx}` byte for byte |

## Known limitations of the model

Reported, not fixed (details in `results/calibration/RESULTS.md` and `results/camera_diagnostic/FINDINGS.md`):

- the liquidus length excess: the modelled pool is 1.7–2.0× longer than the camera's blob in the window, and no fixed
  synthetic-camera operator reconciles the two across energy density;
- the speed response: the model's H and W fall with scan speed 4–9× faster than the camera's;
- the optimum lies outside the predeclared box (t and η at their bounds); the box was not widened;
- narrow-window identifiability: eight of the nine calibration coupons lie on one power/speed line;
- the boiling regulator is overrun at high absorptivity;
- the camera is unvalidated: its 8 µm/px scale is nominal and no independent width measurement exists, so the H
  mismatch cannot be attributed to the model alone;
- the two acquisition campaigns differ in their synchronization-anchor convention (about 50 µs at track edges), which
  is why the first and last frame of every track are not scored.

## Repository layout

| Path | Contents |
|---|---|
| `src/lpbf/` | The package. `model/_accepted_core/` is the frozen numerical core (hash-pinned); `model/` the production melt-pool association and H/W extraction; `calibration.py` the calibration stages; `frame_records.py`, `scored_frame_rule.py`, `hierarchical_objective.py`, `log_ratio_objective.py` the observation records and scoring; `camera_observations.py`, `synthetic_camera.py`, `observation_operators.py` the camera side; `characterization.py` the HDF5 → observation tables tool; `configuration.py`, `dataset_split.py`, `calibration_design.py` the frozen configuration; `synthetic_example.py`, `reproduce.py` the entry points. See [`docs/architecture.md`](docs/architecture.md). |
| `src/lpbf/data/` | Frozen inputs: `final_model.json`, `dataset_split.json`, `calibration_contract.json`, `calibration_design.json`, `frozen_configuration.json`, `full_coupon_dataset_manifest.json`, `accepted_core_hashes.json`. |
| `results/` | The thesis's results: the calibration (plan, results, stage manifests, freeze), the camera diagnostic, the synchronization audit, the smoke reference, the committee statistical package, the thesis tables and figures, and the figure image sources. See `results/README.md`. |
| `docs/` | `DECISIONS.md` (methods and decisions), `architecture.md`, `reference/` (the process-parameter record). |
| `tests/`, `examples/` | The test suite and the synthetic example. |
| `data/`, `runs/` | Where the data bundle unpacks (gitignored). |

`PROVENANCE.md` records how this repository relates to the development repository that produced the results, which
code is byte-identical to the code that ran, and how numerical equivalence was verified after the restructuring.

## Citation and license

Code: MIT License (`LICENSE`). Please cite the thesis; `CITATION.cff` holds the metadata. The data, when released,
will carry their own license.
