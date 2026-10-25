# Measurement operators

The same frames under different measurement operators, and which conclusions depend on the unvalidated 8 µm/px scale.

## A. Operators by group

| Group | Operator (model side) | Camera side | Frames (coverage) | H ratio | W ratio | Model H/W / camera H/W | Shape ratio | e_H | e_W |
|---|---|---|---|---|---|---|---|---|---|
| Calibration (9) | Model liquidus (production H/W) | camera, supplied H/W (threshold 150) | 8,943 (1.000) | 1.76 | 0.75 | 3.01 / 1.29 | 2.34 | 0.651 | 0.416 |
| Calibration (9) | Synthetic camera, PSF 0 px, T150 1950 K | camera re-measured at threshold 150 | 8,770 (0.981) | 0.36 | 0.33 | 1.33 / 1.30 | 1.03 | 1.103 | 1.159 |
| Calibration (9) | Synthetic camera, PSF 2 px, T150 1950 K | camera re-measured at threshold 150 | 8,685 (0.971) | 0.53 | 0.50 | 1.33 / 1.30 | 1.03 | 0.834 | 0.908 |
| In-window held out (5) | Model liquidus (production H/W) | camera, supplied H/W (threshold 150) | 4,796 (1.000) | 1.77 | 0.75 | 3.07 / 1.28 | 2.40 | 0.672 | 0.423 |
| In-window held out (5) | Synthetic camera, PSF 0 px, T150 1950 K | camera re-measured at threshold 150 | 4,793 (0.999) | 0.33 | 0.31 | 1.33 / 1.28 | 1.05 | 1.072 | 1.170 |
| In-window held out (5) | Synthetic camera, PSF 2 px, T150 1950 K | camera re-measured at threshold 150 | 4,758 (0.992) | 0.47 | 0.44 | 1.33 / 1.29 | 1.04 | 0.784 | 0.868 |
| 20260904:part_5 | Model liquidus (production H/W) | camera, supplied H/W (threshold 150) | 884 (1.000) | 2.03 | 0.81 | 3.34 / 1.30 | 2.57 | 0.749 | 0.380 |
| 20260904:part_5 | Synthetic camera, PSF 0 px, T150 1950 K | camera re-measured at threshold 150 | 882 (0.998) | 0.48 | 0.44 | 1.50 / 1.30 | 1.15 | 0.694 | 0.802 |
| 20260904:part_5 | Synthetic camera, PSF 2 px, T150 1950 K | camera re-measured at threshold 150 | 878 (0.993) | 0.70 | 0.63 | 1.40 / 1.30 | 1.08 | 0.462 | 0.527 |
| Out of window, examined (7) | Model liquidus (production H/W) | camera, supplied H/W (threshold 150) | 7,365 (1.000) | 2.12 | 1.01 | 3.00 / 1.30 | 2.30 | 0.968 | 0.707 |
| Out of window, examined (7) | Synthetic camera, PSF 0 px, T150 1950 K | camera re-measured at threshold 150 | 5,638 (0.766) | 0.80 | 0.75 | 1.43 / 1.30 | 1.10 | 0.785 | 0.770 |
| Out of window, examined (7) | Synthetic camera, PSF 2 px, T150 1950 K | camera re-measured at threshold 150 | 5,484 (0.745) | 1.13 | 1.06 | 1.40 / 1.30 | 1.08 | 0.604 | 0.611 |
| Out of window, blind (3) | Model liquidus (production H/W) | camera, supplied H/W (threshold 150) | 3,025 (1.000) | 1.60 | 0.84 | 2.88 / 1.25 | 2.30 | 0.629 | 0.430 |
| Out of window, blind (3) | Synthetic camera, PSF 0 px, T150 1950 K | camera re-measured at threshold 150 | 1,806 (0.597) | 0.69 | 0.64 | 1.33 / 1.25 | 1.07 | 1.026 | 0.953 |
| Out of window, blind (3) | Synthetic camera, PSF 2 px, T150 1950 K | camera re-measured at threshold 150 | 1,646 (0.544) | 1.03 | 0.89 | 1.38 / 1.25 | 1.10 | 0.472 | 0.492 |
| Out of window, all (10) | Model liquidus (production H/W) | camera, supplied H/W (threshold 150) | 10,390 (1.000) | 1.98 | 0.97 | 2.98 / 1.28 | 2.32 | 0.880 | 0.637 |
| Out of window, all (10) | Synthetic camera, PSF 0 px, T150 1950 K | camera re-measured at threshold 150 | 7,444 (0.716) | 0.77 | 0.71 | 1.40 / 1.29 | 1.09 | 0.864 | 0.829 |
| Out of window, all (10) | Synthetic camera, PSF 2 px, T150 1950 K | camera re-measured at threshold 150 | 7,130 (0.686) | 1.11 | 1.00 | 1.38 / 1.29 | 1.07 | 0.567 | 0.578 |

## B. Width-matched model isotherm (Patch 22.3.8; frozen design candidates)

| Candidate | Coupons | Width-matched H ratio (median of coupons) | Pooled median [IQR] | Matched isotherm (median K) | Below liquidus | Note |
|---|---|---|---|---|---|---|
| anchor_center | 16 A8 calibration members | 3.62 | 1.99 [1.27, 4.94] | 1,745 | 41 % |  |
| anchor_t_min | 4 corner coupons (20260904 parts 1, 3, 4, 6) | 2.45 | 1.94 [1.25, 3.66] | 1,698 | 43 % |  |
| anchor_center | 4 corner coupons (20260904 parts 1, 3, 4, 6) | 2.62 | 1.25 [1.04, 1.67] | 2,062 | 18 % |  |
| anchor_t_max | 4 corner coupons (20260904 parts 1, 3, 4, 6) | 1.38 | 1.14 [0.99, 1.45] | 2,534 | 2 % |  |
| 17 frozen design candidates | 4 corner coupons | 1.38–2.77 | – | – | – | 0 of 17 within [0.87, 1.15] |
| halton_02 | 4 corner coupons; nearest design candidate to c1 | 2.40 | – | 1,863 | – | coded distance to c1 1.07 |

## C. The camera's own threshold family (16 A8 calibration members, layer 53)

| Threshold | Camera H (px) | Camera W (px) | Camera H/W | H / H(150) | W / W(150) | Blob at crop edge |
|---|---|---|---|---|---|---|
| 30 | 21.9 | 16.2 | 1.35 | 1.96 | 1.81 | 19.1 % |
| 45 | 18.4 | 14.1 | 1.32 | 1.65 | 1.59 | 6.5 % |
| 60 | 16.6 | 13.0 | 1.31 | 1.47 | 1.44 | 2.8 % |
| 80 | 14.9 | 12.0 | 1.29 | 1.32 | 1.32 | 1.0 % |
| 100 | 13.4 | 11.0 | 1.29 | 1.19 | 1.20 | 0.2 % |
| 125 | 12.0 | 10.0 | 1.29 | 1.09 | 1.10 | 0.1 % |
| **150** | 11.3 | 9.0 | 1.30 | 1.00 | 1.00 | 0.0 % |
| 175 | 10.6 | 8.2 | 1.30 | 0.94 | 0.92 | 0.0 % |
| 200 | 9.9 | 7.9 | 1.29 | 0.88 | 0.86 | 0.0 % |
| 225 | 9.0 | 7.0 | 1.31 | 0.81 | 0.78 | 0.0 % |
| 250 | 8.5 | 6.7 | 1.32 | 0.75 | 0.75 | 0.0 % |

## D. Process slopes by operator (24 coupons)

| Operator | Lowest coupon coverage | ln H on ln P | ln H on ln v | ln W on ln P | ln W on ln v | ln H/W on ln P | ln H/W on ln v |
|---|---|---|---|---|---|---|---|
| Camera, supplied (threshold 150) | 1.00 | 0.84 [0.65, 1.05] | -0.16 [-0.29, -0.05] | 0.56 [0.38, 0.72] | -0.22 [-0.35, -0.10] | 0.25 [0.07, 0.48] | 0.03 [-0.11, 0.15] |
| Camera, re-measured (150, synthetic-paired frames) | 0.19 | 0.86 [0.69, 1.09] | -0.14 [-0.29, -0.04] | 0.51 [0.33, 0.68] | -0.20 [-0.33, -0.09] | 0.25 [0.06, 0.49] | 0.02 [-0.13, 0.14] |
| Model liquidus (c1) | 1.00 | 2.46 [1.75, 3.11] | -1.44 [-1.89, -1.05] | 1.20 [1.07, 1.34] | -0.96 [-1.05, -0.90] | 1.45 [0.72, 2.27] | -0.58 [-1.12, -0.15] |
| Synthetic camera, PSF 0 px | 0.19 | 0.17 [-2.13, 3.39] | -0.43 [-1.89, 1.02] | -0.64 [-3.06, 2.71] | -0.31 [-1.86, 1.25] | 0.61 [0.33, 0.83] | -0.26 [-0.44, -0.13] |
| Synthetic camera, PSF 2 px | 0.18 | 0.66 [-1.50, 3.44] | 0.05 [-1.38, 1.64] | 0.05 [-2.33, 3.07] | 0.30 [-1.21, 2.08] | 0.60 [0.34, 0.85] | -0.33 [-0.52, -0.19] |

## E. Scale dependence

| Quantity | Depends on the 8 µm/px scale | Why |
|---|---|---|
| Absolute sizes (µm) | yes | camera µm = px x 8 µm/px; the scale is unvalidated (A24) |
| Model/camera H and W ratios; e_H, e_W, J | yes | the model's µm are converted to camera px with 8 µm/px; a true scale s multiplies both ratios by 8/s and shifts every r by ln(8/s) |
| Synthetic-camera and width-matched comparisons | yes | both render the model field on the 8 µm camera grid |
| Shape ratio (model H/W ÷ camera H/W) | no | a common scale factor cancels |
| H ratio ÷ W ratio | no | a common scale factor cancels |
| Process slopes (T11, this table) | no | a constant factor only shifts the intercept |
| Rank correlations (reading X) | no | a constant shift of r leaves ranks unchanged |

**Notes.**

- Different operators measure different boundaries: the liquidus contour of the laser-associated melt, a rendered brightness threshold, the camera's threshold-150 blob. Agreement under one operator is not agreement under another (A12, A24).
- Synthetic camera (reading S, S_DESCRIPTIVE): T150 = 1950 K was fixed on the 9 calibration coupons (closest H/W shape at threshold 150) and then held for all coupons. Its group e_H, e_W and J were recomputed here from `synthetic_frames.csv.gz` and equal the synthetic manifest (108 values, largest difference 0.0e+00). Coverage counts frames where both the synthetic and the re-measured camera blob exist.
- The synthetic camera reproduces the camera's shape (shape ratio 1.03–1.15, against 2.30–2.57 for the liquidus) but not its size, and its coverage falls to 54–77 % out of window (no blob above the fixed T150 at low VED): no fixed synthetic operator follows the camera across VED (A27).
- Width-matched isotherm (Patch 22.3.8, readings R-b and Q-b): with the model contour chosen per frame to match the camera's W, the model's H is still 1.38–3.62 times the camera's (median over coupons) for every frozen design candidate; c1 itself was not evaluated with this operator.
- The camera's own threshold family: from threshold 30 to 250 the camera H falls by a factor of 2.58 and W by 2.43, while its H/W stays within 1.29–1.35: the camera's size is operator-dependent, its shape much less so.
- Slopes: least squares of ln coupon medians on [1, ln P, ln v], 24 coupons, 95 % coupon bootstrap (family 8; all operators share the draws). Synthetic slopes rest on low coverage at low VED (lowest coupon 19 % at PSF 0) and are descriptive only.
- Sources: `data/T14_operator_groups.csv`, `T14_width_matched.csv`, `T14_camera_threshold_family.csv`, `T14_operator_slopes.csv`, `T14_synthetic_status_by_coupon.csv`.
