# Process-response slopes

How camera and model H, W and H/W scale with power, speed and VED, coupon by coupon.

## All 24 coupons

| Response | Regressor | Camera (threshold 150) | Model liquidus (c1) | Model − camera | Rosenthal point source |
|---|---|---|---|---|---|
| ln H | ln P (with ln v) | 0.84 [0.66, 1.06] | 2.46 [1.76, 3.10] | 1.62 [1.00, 2.19] | 1 |
| ln W | ln P (with ln v) | 0.56 [0.38, 0.72] | 1.20 [1.07, 1.35] | 0.63 [0.45, 0.83] | 0.5 |
| ln H/W | ln P (with ln v) | 0.25 [0.06, 0.49] | 1.45 [0.72, 2.27] | 1.20 [0.38, 2.11] | 0.5 |
| ln H | ln v (with ln P) | -0.16 [-0.29, -0.05] | -1.44 [-1.88, -1.06] | -1.29 [-1.66, -0.97] | 0 |
| ln W | ln v (with ln P) | -0.22 [-0.35, -0.10] | -0.96 [-1.05, -0.90] | -0.74 [-0.88, -0.63] | −0.5 |
| ln H/W | ln v (with ln P) | 0.03 [-0.11, 0.15] | -0.58 [-1.09, -0.16] | -0.61 [-1.21, -0.15] | 0.5 |
| ln H | ln VED (alone) | 0.25 [0.10, 0.42] | 1.58 [1.08, 2.09] | 1.33 [0.97, 1.73] | – |
| ln W | ln VED (alone) | 0.26 [0.10, 0.41] | 0.99 [0.91, 1.10] | 0.73 [0.63, 0.87] | – |
| ln H/W | ln VED (alone) | 0.00 [-0.07, 0.11] | 0.69 [0.18, 1.27] | 0.69 [0.14, 1.30] | – |

## Without 20260904:part_3 (no pool on 54 % of frames)

| Response | Regressor | Camera (threshold 150) | Model liquidus (c1) | Model − camera | Rosenthal point source |
|---|---|---|---|---|---|
| ln H | ln P (with ln v) | 0.83 [0.63, 1.10] | 2.10 [1.70, 2.64] | 1.27 [0.95, 1.61] | 1 |
| ln W | ln P (with ln v) | 0.49 [0.33, 0.62] | 1.19 [1.05, 1.37] | 0.70 [0.54, 0.87] | 0.5 |
| ln H/W | ln P (with ln v) | 0.32 [0.13, 0.55] | 0.96 [0.68, 1.33] | 0.64 [0.29, 0.93] | 0.5 |
| ln H | ln v (with ln P) | -0.15 [-0.32, -0.03] | -1.23 [-1.57, -1.01] | -1.08 [-1.29, -0.94] | 0 |
| ln W | ln v (with ln P) | -0.17 [-0.29, -0.08] | -0.96 [-1.07, -0.89] | -0.78 [-0.92, -0.68] | −0.5 |
| ln H/W | ln v (with ln P) | -0.01 [-0.15, 0.09] | -0.29 [-0.55, -0.12] | -0.28 [-0.54, -0.10] | 0.5 |
| ln H | ln VED (alone) | 0.22 [0.06, 0.43] | 1.32 [1.02, 1.75] | 1.10 [0.94, 1.32] | – |
| ln W | ln VED (alone) | 0.20 [0.05, 0.34] | 0.98 [0.89, 1.11] | 0.78 [0.68, 0.92] | – |
| ln H/W | ln VED (alone) | 0.04 [-0.05, 0.15] | 0.36 [0.13, 0.67] | 0.32 [0.08, 0.58] | – |

## Out of window (10 coupons)

| Response | Regressor | Camera (threshold 150) | Model liquidus (c1) | Model − camera | Rosenthal point source |
|---|---|---|---|---|---|
| ln H | ln P (with ln v) | 0.69 [0.43, 0.98] | 2.62 [1.59, 3.78] | 1.92 [1.14, 2.99] | 1 |
| ln W | ln P (with ln v) | 0.74 [0.44, 0.98] | 1.24 [0.99, 1.52] | 0.50 [0.13, 0.96] | 0.5 |
| ln H/W | ln P (with ln v) | -0.05 [-0.34, 0.35] | 1.59 [0.55, 3.07] | 1.64 [0.52, 3.19] | 0.5 |
| ln H | ln v (with ln P) | -0.17 [-0.26, -0.07] | -1.41 [-1.84, -1.08] | -1.24 [-1.64, -0.98] | 0 |
| ln W | ln v (with ln P) | -0.19 [-0.32, -0.09] | -0.95 [-1.05, -0.87] | -0.76 [-0.91, -0.62] | −0.5 |
| ln H/W | ln v (with ln P) | -0.01 [-0.13, 0.11] | -0.55 [-1.10, -0.20] | -0.54 [-1.10, -0.16] | 0.5 |
| ln H | ln VED (alone) | 0.24 [0.12, 0.35] | 1.57 [1.13, 1.94] | 1.33 [1.01, 1.65] | – |
| ln W | ln VED (alone) | 0.26 [0.11, 0.39] | 0.99 [0.90, 1.07] | 0.73 [0.63, 0.88] | – |
| ln H/W | ln VED (alone) | -0.00 [-0.09, 0.10] | 0.69 [0.24, 1.16] | 0.69 [0.21, 1.20] | – |

**Notes.**

- Least squares of the log coupon median on [1, ln P, ln v] (or [1, ln VED]); 95 % percentile intervals from 4,000 coupon resamples; camera and model share the draws, so the difference is paired. Descriptive, not predeclared.
- Coupon medians: camera over all scored frames; model over frames with a predicted pool. H/W is the median of the per-frame ratio (as in 22.3.8 Step 0).
- The results report §4 gave H/W slopes as ln(median H) − ln(median W): model 1.26 (P) and -0.48 (v), camera 0.28 and 0.06. Both conventions agree on sign and on the model − camera gap.
- Check against 22.3.8 Step 0 (camera, the 16 A8 calibration members): the largest slope difference is 0.080, well inside the intervals (Step 0 measured the images itself; this package uses the supplied H/W).
- In-window subset: 8 of 9 calibration coupons lie on one P/v line, so P and v slopes there are not identified (very wide intervals); see the CSV.
- Scale-free: slopes do not depend on the 8 µm/px scale (A24).
