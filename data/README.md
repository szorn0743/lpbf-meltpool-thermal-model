# Data

The data are distributed separately from the code and are **not public yet**; they are available from the author on
request. They come as three zip archives whose paths are relative to the repository root, so each one unpacks in
place:

| Archive | Unpacks to | Files | Contents |
|---|---|---|---|
| `lpbf_coupon_hdf5.zip` (1.1 GB) | `data/coupons/` | 24 | One HDF5 file per coupon (`part_<n>_<date>.h5`): the synchronized process data and the coaxial camera frames of the observed layer. Read only. |
| `lpbf_characterization_patch21_3.zip` (5 MB) | `data/characterization/patch21_3_full_characterization_20261012_011936/` | 129 | Per-coupon index of the eligible camera observations (`frame_observations.csv`, `scan_tracks.csv`, `member_audit.json`) and the synchronization audit, produced from the HDF5 files by `lpbf.characterization`. |
| `lpbf_recorded_calibration_run.zip` (0.7 GB) | `runs/recorded_calibration/` | 250 | The recorded calibration run: every unit file (frame-level model and camera H/W) of the smoke, calibrate, confirm and evaluate stages, the temperature fields captured in the evaluate stage, the selection freeze, the synthetic-camera stage and the console logs. |

`SHA256SUMS.txt` lists the SHA-256 of all 403 unpacked files, with paths relative to the repository root:

```bash
sha256sum -c data/SHA256SUMS.txt          # Git Bash or Linux, from the repository root
shasum -a 256 -c data/SHA256SUMS.txt      # macOS
```

`python -m lpbf.reproduce check-data` reports which of the expected files are present. The code also checks its
inputs: the coupon files against `src/lpbf/data/full_coupon_dataset_manifest.json`, and the unit and field files
against the SHA-256 values in the stage manifests under `results/calibration/`.

## Why the data are not in the repository

The coupon files belong to the laboratory's experimental campaign and have not been released; the run outputs and
the characterization are derived from them. The process parameters of the 24 coupons (power, speed, spot size,
energy densities) are public and in the repository: `docs/reference/LPBF_Process_Parameters.csv`.

## What can be reproduced without them

Installation, the test suite (the tests that read the recorded run are skipped), the synthetic example, and every
table, figure and dataset can be read. Rebuilding the tables and figures needs the characterization and the recorded
run; re-executing the model needs the coupon files and the characterization.

## Expected layout of the HDF5 files

One group per layer (`layer53` is the observed layer) with `data` (channels × rows, 5 µs per row), `names` (channel
names as bytes; the model reads `Laser Drive`, `On-Axis TED`, `X-Machine`, `Y-Machine`, `H`, `W`), `gige_time`
(camera timestamps), `gige_image` (frames × 24 × 64, uint8) and a `sync` group with `gige_image_to_data_index`
(process row of each camera frame, −1 if unmapped) and `data_to_gige_image_index`. `lpbf.synthetic_example` writes a
small file in exactly this layout.
