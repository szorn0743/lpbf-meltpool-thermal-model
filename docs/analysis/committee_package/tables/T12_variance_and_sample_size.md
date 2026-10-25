# Variance and effective sample size

Where the data vary, why the frame count is not the sample size, and whether the model follows the camera inside a coupon.

## A. Where the variation sits (share of the frame-level sum of squares)

| Scope | Quantity | Frames / tracks / coupons / conditions | Within track | Between tracks (in coupon) | Between coupons (in condition) | Between conditions | Total variance |
|---|---|---|---|---|---|---|---|
| All 24 coupons | r_H (log residual) | 24,129 / 1,244 / 24 / 18 | 37.6 % | 8.9 % | 0.0 % | 53.4 % | 0.2907 |
| All 24 coupons | r_W (log residual) | 24,129 / 1,244 / 24 / 18 | 58.2 % | 10.4 % | 0.2 % | 31.3 % | 0.1722 |
| All 24 coupons | ln camera H | 24,129 / 1,244 / 24 / 18 | 31.1 % | 34.7 % | 0.0 % | 34.2 % | 0.0278 |
| All 24 coupons | ln camera W | 24,129 / 1,244 / 24 / 18 | 39.1 % | 24.7 % | 0.0 % | 36.2 % | 0.0187 |
| All 24 coupons | ln model H (pool frames) | 23,646 / 1,238 / 24 / 18 | 36.0 % | 4.9 % | 0.0 % | 59.1 % | 0.1525 |
| All 24 coupons | ln model W (pool frames) | 23,646 / 1,238 / 24 / 18 | 55.1 % | 11.6 % | 0.3 % | 33.1 % | 0.1215 |
| Calibration (9) | r_H (log residual) | 8,943 / 469 / 9 / 5 | 66.5 % | 29.6 % | 0.1 % | 3.7 % | 0.0648 |
| Calibration (9) | r_W (log residual) | 8,943 / 469 / 9 / 5 | 76.7 % | 15.0 % | 0.8 % | 7.5 % | 0.0701 |
| Calibration (9) | ln camera H | 8,943 / 469 / 9 / 5 | 35.9 % | 25.3 % | 0.1 % | 38.8 % | 0.0221 |
| Calibration (9) | ln camera W | 8,943 / 469 / 9 / 5 | 60.8 % | 29.0 % | 0.1 % | 10.1 % | 0.0104 |
| Calibration (9) | ln model H (pool frames) | 8,927 / 465 / 9 / 5 | 61.4 % | 14.1 % | 0.0 % | 24.4 % | 0.0447 |
| Calibration (9) | ln model W (pool frames) | 8,927 / 465 / 9 / 5 | 73.6 % | 15.1 % | 1.2 % | 10.2 % | 0.0575 |

## B. Effective sample size

| Group | Frames / tracks / coupons / conditions | ICC coupon r_H / r_W | Design effect r_H / r_W | Effective n (frames) r_H / r_W | ICC track r_H / r_W | Inferential unit |
|---|---|---|---|---|---|---|
| Calibration (9) | 8,943 / 469 / 9 / 5 | 0.042 / 0.091 | 43 / 92 | 209 / 97 | 0.298 / 0.191 | 9 coupons, 5 conditions |
| In-window held out (5) | 4,796 / 257 / 5 / 3 | 0.090 / 0.084 | 87 / 82 | 55 / 59 | 0.316 / 0.174 | 5 coupons, 3 conditions |
| Out of window, all (10) | 10,390 / 518 / 10 / 10 | 0.634 / 0.412 | 659 / 428 | 16 / 24 | 0.649 / 0.447 | 10 coupons, 10 conditions |
| All 24 coupons | 24,129 / 1,244 / 24 / 18 | 0.545 / 0.324 | 548 / 326 | 44 / 74 | 0.604 / 0.387 | 24 coupons, 18 conditions |

## C. Within-coupon explanatory power, by group

| Group | Median frame ρ(model, camera) H / W | Median track ρ H / W | Median e(actual) / e(shuffled) H / W | Coupons with p < 0.05, H / W |
|---|---|---|---|---|
| Calibration (9) | -0.03 / +0.06 | +0.06 / +0.10 | 0.992 / 1.024 | 3 / 0 of 9 |
| In-window held out (5) | -0.03 / +0.02 | -0.16 / +0.06 | 0.989 / 1.038 | 2 / 1 of 5 |
| Out of window, all (10) | -0.11 / +0.19 | -0.09 / +0.23 | 1.002 / 0.963 | 3 / 10 of 10 |
| All 24 coupons | -0.06 / +0.08 | -0.01 / +0.11 | 0.994 / 0.996 | 8 / 11 of 24 |

## C. Within-coupon explanatory power, by coupon

| Coupon | Role | VED | Frame ρ H | Track ρ H | e_H actual / shuffled | p (H) | Frame ρ W | Track ρ W | e_W actual / shuffled | p (W) |
|---|---|---|---|---|---|---|---|---|---|---|
| 20260730:part_1 | calibration | 68.6 | -0.03 | +0.09 | 0.554 / 0.547 | 0.961 | -0.01 | +0.10 | 0.356 / 0.343 | 1.000 |
| 20260730:part_2 | in-window held out | 69.4 | -0.12 | -0.23 | 0.594 / 0.593 | 0.587 | -0.02 | +0.04 | 0.343 / 0.331 | 0.998 |
| 20260730:part_3 | calibration | 70.2 | -0.06 | +0.03 | 0.588 / 0.596 | 0.030 | +0.02 | -0.06 | 0.341 / 0.337 | 0.792 |
| 20260730:part_4 | in-window held out | 70.8 | -0.03 | -0.24 | 0.549 / 0.555 | 0.047 | +0.05 | +0.06 | 0.344 / 0.327 | 1.000 |
| 20260730:part_5 | calibration | 71.4 | -0.06 | -0.24 | 0.585 / 0.590 | 0.142 | +0.08 | -0.01 | 0.339 / 0.337 | 0.701 |
| 20260730:part_6 | calibration | 72.0 | -0.03 | -0.23 | 0.566 / 0.569 | 0.212 | +0.08 | +0.04 | 0.351 / 0.342 | 0.970 |
| 20260731:part_1 | calibration | 68.6 | -0.06 | +0.11 | 0.747 / 0.743 | 0.625 | +0.06 | +0.21 | 0.594 / 0.568 | 0.994 |
| 20260731:part_2 | in-window held out | 69.4 | -0.11 | +0.08 | 0.612 / 0.612 | 0.469 | +0.02 | -0.01 | 0.397 / 0.390 | 0.950 |
| 20260731:part_3 | calibration | 70.2 | -0.01 | +0.06 | 0.684 / 0.698 | 0.040 | +0.05 | +0.30 | 0.506 / 0.492 | 0.939 |
| 20260731:part_4 | in-window held out | 70.8 | -0.03 | -0.16 | 0.747 / 0.755 | 0.216 | -0.05 | +0.13 | 0.624 / 0.585 | 1.000 |
| 20260731:part_5 | calibration | 71.4 | -0.02 | +0.20 | 0.609 / 0.616 | 0.042 | +0.03 | +0.12 | 0.400 / 0.394 | 0.908 |
| 20260731:part_6 | calibration | 72.0 | +0.00 | +0.09 | 0.700 / 0.706 | 0.244 | +0.08 | +0.09 | 0.538 / 0.516 | 0.991 |
| 20260904:part_1 | out, examined | 97.2 | -0.16 | +0.04 | 0.804 / 0.820 | 0.001 | +0.24 | +0.34 | 0.260 / 0.307 | 0.001 |
| 20260904:part_2 | out, blind | 58.3 | -0.11 | -0.40 | 0.472 / 0.464 | 0.935 | +0.08 | +0.22 | 0.463 / 0.483 | 0.001 |
| 20260904:part_3 | out, examined | 41.7 | +0.07 | +0.08 | 1.563 / 1.574 | 0.013 | +0.08 | +0.05 | 1.368 / 1.387 | 0.001 |
| 20260904:part_4 | out, examined | 125.0 | -0.16 | -0.23 | 1.031 / 1.045 | 0.001 | +0.25 | +0.36 | 0.290 / 0.342 | 0.001 |
| 20260904:part_5 | in-window held out | 75.0 | +0.04 | -0.07 | 0.749 / 0.759 | 0.014 | +0.16 | +0.21 | 0.380 / 0.393 | 0.007 |
| 20260904:part_6 | out, examined | 53.6 | -0.01 | +0.07 | 0.637 / 0.637 | 0.536 | +0.13 | +0.49 | 0.646 / 0.666 | 0.001 |
| 20260910:part_1 | calibration | 83.3 | -0.19 | -0.01 | 0.718 / 0.706 | 0.993 | +0.21 | +0.10 | 0.309 / 0.314 | 0.256 |
| 20260910:part_2 | out, blind | 95.2 | -0.11 | -0.16 | 0.845 / 0.841 | 0.898 | +0.22 | +0.25 | 0.265 / 0.297 | 0.001 |
| 20260910:part_3 | out, examined | 107.1 | -0.13 | -0.18 | 0.950 / 0.947 | 0.777 | +0.27 | -0.05 | 0.296 / 0.328 | 0.001 |
| 20260910:part_4 | out, examined | 48.6 | +0.10 | +0.26 | 0.847 / 0.856 | 0.086 | +0.22 | +0.51 | 0.869 / 0.892 | 0.001 |
| 20260910:part_5 | out, blind | 55.6 | -0.13 | -0.02 | 0.498 / 0.496 | 0.704 | +0.14 | -0.02 | 0.520 / 0.534 | 0.004 |
| 20260910:part_6 | out, examined | 62.5 | -0.08 | -0.59 | 0.613 / 0.605 | 0.930 | +0.16 | +0.12 | 0.465 / 0.481 | 0.002 |

**Notes.**

- A. Exact frame-weighted sum-of-squares partition (within-track + between-track + between-coupon + between-condition = total). Between coupons within a condition is the 0730/0731 day difference (6 July conditions; September conditions have one coupon each). Over all 24 coupons the camera H varies 35 % between tracks of a coupon and 34 % between conditions; the model's H varies 5 % between tracks and 59 % between conditions.
- B. One-way random-effects ICC (ANOVA estimator, unbalanced n0) with coupons as clusters; design effect 1 + (m̄ − 1) ICC with m̄ ≈ 1,000 frames per coupon. Even a small coupon ICC shrinks the frames to an effective 16–209 independent ones per group (against 4,796–24,129 scored); the package therefore infers over coupons and conditions, never frames (T1).
- C. Within-coupon explanatory power (exploratory, plan Part 1, item 4). ρ: Spearman over frames with a predicted pool, and over track medians (tracks with ≥ 3 such frames). Permutation control: the camera values are shuffled across the coupon's scored frames 1,000 times (family 6) and the coupon e is recomputed through the track hierarchy; p is the share of shuffles with e at or below the actual e. A ratio near 1 means the pairing of model and camera frames inside a coupon carries no information: the model explains differences between conditions, not the variation within a coupon (cf. the track-order confound).
- Sources: `data/T12_variance_partition.csv`, `data/T12_effective_sample_size.csv`, `data/T12_within_coupon_power.csv`, `data/T12_within_coupon_power_summary.csv`.
