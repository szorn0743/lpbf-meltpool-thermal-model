# Architecture

One trial of the model is one candidate parameter set on one coupon. The data flow, and the module that implements
each step:

```
coupon HDF5 (process channels, camera frames, synchronization)
   │  data/full_coupon_manifest.py      identity and SHA-256 of the 24 coupons
   │  characterization.py               HDF5 -> per-coupon camera observation tables (frame_observations.csv, scan_tracks.csv)
   ▼
camera observations per frame (H, W in px; laser-on, synchronized, eligible)
   │  frame_records.py                  reads the coupon's table, classifies each observation
   │  scored_frame_rule.py              drops the first and last eligible frame of every scan track
   ▼
numerical solver                        runtime/parameters.py, geometry.py: the frozen 99 x 99 x 21 window, 16 um, 2.5 us
   │  model/_accepted_core/             heat source, moving window, explicit solver (frozen, hash-pinned)
   │  model/current_execution.py        the four physical parameters -> solver inputs; energy accounting
   │  experiments/current_framework.py  evaluate_calibration_trial: preflights, solve, per-frame observations
   ▼
temperature field at each scored frame
   │  model/laser_component_association.py   the liquid component receiving >= 2 % of the beam's power
   │  model/production_hw.py                 H and W of its interpolated liquidus contour (minAreaRect)
   │  field_capture.py                       keeps the top-surface field for the synthetic camera (evaluate stage)
   ▼
model H/W per frame, or UNDEFINED
   │  frame_records.py                  PASS / UNDEFINED / EXCLUDED / FAIL records with the camera's H/W
   ▼
scoring
   │  log_ratio_objective.py            r = ln(max(sim,1)/max(exp,1)) for H and W; f = 0.5 r_H^2 + 0.5 r_W^2
   │  hierarchical_objective.py         frame -> track -> coupon -> replicate condition -> condition, unweighted means;
   │                                    coverage per coupon, 95 % floor; infrastructure penalty
   ▼
calibration and evaluation             calibration.py: smoke, calibrate (17 design points x 9 coupons), confirm (quadratic
   │                                    surrogate -> <= 3 candidates), freeze (lowest measured J), evaluate (all roles)
   │  calibration_design.py             the frozen 17-point design and bounds
   │  dataset_split.py                  the four coupon roles and the 65-85 J/mm3 window
   │  configuration.py                  the one record of the frozen configuration (data/final_model.json)
   ▼
results/                                stage manifests, selection freeze, readings C / V / X
   │  camera_observations.py            camera-side measurement of the raw frames (threshold 150 blob)
   │  synthetic_camera.py               renders the model's field as the camera would see it
   │  observation_operators.py          reading S: synthetic camera on the evaluate stage's fields
   ▼
results/committee_package, results/thesis_figures        tables and figures, rebuilt from the recorded run
```

Execution: every thermal evaluation is one single-core process; `execution/parallel.py` runs independent units on
Windows-spawn worker processes (4 by default) and `execution/work_units.py` serially; parallel results equal serial
results. Workers write nothing; the parent writes one unit file per candidate × coupon and a stage manifest with the
SHA-256 of every input and output.

Frozen state: the numerical core is pinned by `data/accepted_core_hashes.json`; the model configuration by
`data/frozen_configuration.json` (with an integrity hash); the calibration contract and design by
`data/calibration_contract.json` and `data/calibration_design.json`; the coupon identities by
`data/full_coupon_dataset_manifest.json`; the selected parameters by `results/calibration/selection_freeze.json`.
`data/final_model.json` gathers all of it in one place and is checked against the code by the tests.
