# Reduced-order thermal simulation for laser powder bed fusion

Code and records for the master's thesis *Reduced Order Thermal Simulation for Laser Powder Bed Fusion* (Samuel Henry
Zorn, M.S. Mechanical Engineering, San Diego State University, 2026).

A reduced-order thermal model of single laser tracks is calibrated against melt-pool dimensions measured by a coaxial
near-infrared camera during laser powder bed fusion of 24 coupons. The model's observable is the height H (length
along travel) and width W of the liquidus contour of the melt pool that receives the laser's power; the camera's is
the H/W of the thresholded bright blob in each frame. The thesis reports how well a calibrated model reproduces the
camera inside and outside the calibration window, and where it fails.

## Results in brief

The calibrated parameter set is `confirm_c1` (absorptivity coordinate t = −3, liquid-conductivity factor ck = 2.418,
directional factor η = 0), selected on 9 coupons in the 65–85 J/mm³ energy-density window.

| Reading | Finding |
|---|---|
| **C_EDGE** (calibration) | Objective J = 0.298. The optimum lies on the edge of the parameter box. In the window, H is 1.7–2.0× and W 0.73–0.88× the camera's. |
| **V_PASS** (held out, in window) | Errors on the held-out coupons are within 3 % of the calibration errors. |
| **X_PARTIAL** (out of window) | Errors grow with distance in energy density; the model's speed response is 4× (W) to 9× (H) steeper than the camera's. |
| **S** (descriptive) | No fixed synthetic-camera operator follows the real camera across energy density. |

The camera's dimensions are not validated against an independent measurement, so these are agreements with the
camera's H/W definition, not with the true melt-pool size. Details and failure modes:
[`docs/patches/22.4.3.2/PATCH_22_4_3_2_RESULTS.md`](docs/patches/22.4.3.2/PATCH_22_4_3_2_RESULTS.md). Methods and
every convention: [`docs/DECISIONS.md`](docs/DECISIONS.md).

## Repository layout

| Path | Contents |
|---|---|
| `src/lpbf/` | The model and calibration code (Python package, run from source). |
| `src/lpbf/model/_accepted_core/` | The frozen numerical core: heat source, moving window, solver. Fixed by SHA-256 in `PATCH_22_3_4_ACCEPTED_CORE_HASHES.json`. |
| `src/lpbf/data/` | Frozen contracts: the coupon manifest, calibration/held-out partition, calibration design, runtime configuration. |
| `tests/` | The pytest suite. |
| `docs/DECISIONS.md` | Methods and decisions: every scoring and calibration convention, with the reasons. |
| `docs/reference/` | The experimental process parameters of the 24 coupons (read-only record). |
| `docs/patches/22.4.3.2/` | The calibration: predeclared plan, results, and the evidence of every stage (manifests, selection freeze). |
| `docs/patches/22.3.8/` | The diagnostic of the H mismatch (camera-side checks, synthetic camera, design-box scan): plan, findings, evidence. |
| `docs/patches/22.3.6/`, `22.3.7/` | The evidence files that the code above reads (association census, scored-frame verification, synchronization audit). |
| `docs/analysis/committee_package/` | Statistical outputs for the thesis committee: tables, figures, datasets, registers. |
| `docs/analysis/thesis_figures/` | The tables and figures of thesis Chapters 3–4, and a Word file of them. |
| `docs/analysis/presentation_figures/` | Only the image sources that the thesis figures read, and the scripts that extract them. |
| `data/` | Where the data bundle unpacks (not tracked; see below). |

Module names carry the development step that introduced them (`patch22_4_3_2_window_calibration` is the calibration
runner of step 22.4.3.2). They were kept, unchanged, because the run records name them and pin their hashes. The ones
that matter most:

| Module | Role |
|---|---|
| `lpbf.patch22_4_3_2_window_calibration` | The calibration runner: stages `smoke`, `calibrate`, `confirm`, `freeze`, `evaluate`. |
| `lpbf.patch22_4_3_2_synthetic_camera` | Reading S: the synthetic camera applied to the selected model's fields. |
| `lpbf.model.production_hw`, `lpbf.model.laser_component_association` | The model's H/W: beam-power-share association and liquidus-contour measurement. |
| `lpbf.scored_frame_rule`, `lpbf.hierarchical_objective`, `lpbf.log_ratio_objective` | Which frames are scored, coverage, and the objective. |
| `lpbf.patch22_3_8_camera_step0`, `lpbf.patch22_3_8_field_capture`, `lpbf.patch22_3_8_synthetic_camera` | Camera blob measurement, capture of model temperature fields, the synthetic camera. |
| `lpbf.patch22_3_7_stage_a`, `lpbf.patch22_4_3_parallel_coarse_calibration_execution` | Frame-level evaluation of a candidate on a coupon (reused by the runner). |
| `lpbf.execution` | Serial and parallel (Windows spawn) execution of work units. |

## Setup

Python 3.13 on Windows (the runs used 3.13.15 and the spawn start method). The package is not installed; it runs from
`src/`.

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
$env:PYTHONPATH = "$PWD\src"
.\.venv\Scripts\python.exe -m pytest -q
```

The figures need matplotlib, which is kept out of the model environment because the model's numerical provenance
depends on the pinned versions. Build them in a second environment:

```powershell
py -3.13 -m venv .venv-analysis
.\.venv-analysis\Scripts\python.exe -m pip install -r docs\analysis\committee_package\requirements.analysis.txt
```

On Linux or macOS use `python3.13 -m venv`, `.venv/bin/python` and `export PYTHONPATH="$PWD/src"`.

## Data

The experimental data and the recorded run outputs are **not public yet**; they are available from the author on
request. They come as three zip archives that unpack into the repository root:

| Archive | Unpacks to | Size (zipped) | Contents |
|---|---|---|---|
| `lpbf_coupon_hdf5.zip` | `data/coupons/` | 1.1 GB | The 24 coupon HDF5 files: synchronized process data and coaxial camera frames. |
| `lpbf_characterization_patch21_3.zip` | `data/characterization/` | 5 MB | Per-coupon frame and track index of the eligible camera observations (Patch 21.3). |
| `lpbf_run_outputs_22_4_3_2.zip` | `patch22_4_3_2_output/` | 0.7 GB | Every unit file and temperature field of the recorded calibration run. |

`data/SHA256SUMS.txt` lists the SHA-256 of every unpacked file; check it from the repository root with
`sha256sum -c data/SHA256SUMS.txt` (Git Bash, Linux) or `shasum -a 256 -c data/SHA256SUMS.txt` (macOS). Without the
data, the tests that need it are skipped and everything else in this repository can still be read.

## Reproducing the results

Set `$env:PYTHONPATH = "$PWD\src"` first. Times are for 4 worker processes on the original machine.

**Analysis outputs** (no thermal runs; need the data bundle):

```powershell
.\.venv-analysis\Scripts\python.exe docs\analysis\presentation_figures\scripts\build_sources.py   # image sources
.\.venv-analysis\Scripts\python.exe docs\analysis\committee_package\scripts\run_all.py           # about 1 min
.\.venv-analysis\Scripts\python.exe docs\analysis\thesis_figures\scripts\build.py                # about 10 s
```

The builds are deterministic: compare each package's `OUTPUT_SHA256SUMS.txt` with the committed copy (`git diff`).

**The calibration** (thermal runs). Use a new output directory, so that the recorded run in `patch22_4_3_2_output/`
is not reused or overwritten:

```powershell
$run = "rerun_22_4_3_2"
$common = "--data-dir", "data\coupons", "--characterization-dir", "data\characterization\patch21_3_full_characterization_20261012_011936", "--output-dir", $run
$freeze = "--freeze-file", "docs\patches\22.4.3.2\evidence\selection_freeze.json", "--freeze-sha256", "43184dff94c9d3b75cee1c8924abf7b195b72fbb5b32d301733fc21dad4292a8"

.\.venv\Scripts\python.exe -m lpbf.patch22_4_3_2_window_calibration smoke @common              # 1 unit, about 6 min
.\.venv\Scripts\python.exe -m lpbf.patch22_4_3_2_window_calibration calibrate @common          # 153 units, about 6 h
.\.venv\Scripts\python.exe -m lpbf.patch22_4_3_2_window_calibration confirm @common            # 18 units, about 1 h
.\.venv\Scripts\python.exe -m lpbf.patch22_4_3_2_window_calibration freeze --output-dir $run   # selection, seconds
.\.venv\Scripts\python.exe -m lpbf.patch22_4_3_2_window_calibration evaluate @common @freeze   # 39 units, about 2.5 h
.\.venv\Scripts\python.exe -m lpbf.patch22_4_3_2_synthetic_camera --data-dir data\coupons --output-dir $run @freeze   # about 5 min
```

`evaluate` accepts only a selection freeze that is committed in this repository, so it uses the recorded one; compare
it with the `selection_freeze.json` that your `freeze` stage writes. The smoke gate's result can be compared directly
with `docs/patches/22.4.3.2/evidence/smoke/smoke_gate.json`.

The code also contains the locked dispatcher of an earlier 272-unit coarse campaign that was superseded before it ran
(`docs/DECISIONS.md` S10). It refuses to run and is kept only because the calibration runner reuses functions from
its module.

## Provenance

This repository is a curated export of the private development repository; its history is not published. The code
that produced the results is included byte for byte. `PROVENANCE.md` says which files were changed, how to check
the code against the hashes in the run records, and what was left out.

## License and citation

Code: MIT License (see `LICENSE`). Citation metadata: `CITATION.cff`. The data, when released, will carry their own
license.
