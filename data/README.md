# Data

The data are distributed separately from the code and are **not public yet**; they are available from the author on
request. They come as three zip archives whose paths are relative to the repository root, so each one unpacks in
place:

| Archive | Unpacks to | Files | Contents |
|---|---|---|---|
| `lpbf_coupon_hdf5.zip` | `data/coupons/` | 24 | One HDF5 file per coupon (`part_<n>_<date>.h5`): the synchronized process data and the coaxial camera frames of the observed layer. Read only. |
| `lpbf_characterization_patch21_3.zip` | `data/characterization/patch21_3_full_characterization_20261012_011936/` | 129 | Per-coupon index of the eligible camera observations (frames and scan tracks) and the synchronization audit, produced by the Patch 21.3 characterization of the HDF5 files. |
| `lpbf_run_outputs_22_4_3_2.zip` | `patch22_4_3_2_output/` | 250 | The recorded calibration run: every unit file (frame-level model and camera H/W) of the smoke, calibrate, confirm and evaluate stages, the temperature fields captured in the evaluate stage, the selection freeze, the synthetic-camera stage and the console logs. |

`SHA256SUMS.txt` lists the SHA-256 of all 403 unpacked files, with paths relative to the repository root:

```bash
sha256sum -c data/SHA256SUMS.txt          # Git Bash or Linux, from the repository root
shasum -a 256 -c data/SHA256SUMS.txt      # macOS
```

The code also checks its inputs: the coupon files against `src/lpbf/data/full_coupon_dataset_manifest.json`, and
the unit and field files against the SHA-256 values in the stage manifests under
`docs/patches/22.4.3.2/evidence/`.

The process parameters of the 24 coupons (power, speed, spot size, energy densities) are in the repository itself:
`docs/reference/LPBF_Process_Parameters.csv`.
