# Sensitivity and robustness

How the reported errors and the selection respond to each analysis choice.

## A. Objective choice (19 calibrated candidates, recorded scores)

| Objective | Winner | Winner (t, ck, η) | Rank of c1 / c2 | ρ with the J ranking |
|---|---|---|---|---|
| J (log ratio, contract 22.4.3.2) | confirm_c1 | (-3.00, 2.418, 0.00) | 1 / 2 of 19 | 1.00 |
| H term only (e_H²) | confirm_c1 | (-3.00, 2.418, 0.00) | 1 / 2 of 19 | 1.00 |
| W term only (e_W²) | halton_08 | (0.38, 1.537, 0.84) | 14 / 15 of 19 | 0.21 |
| Pixel residual objective (22.3.7, superseded, S11) | confirm_c1 | (-3.00, 2.418, 0.00) | 1 / 2 of 19 | 1.00 |

## B. Selected versus near-best

| Candidate | Calibration J (e_H, e_W) | Held-out e_H, e_W | V ratios H, W (reading) | part_5 ratios H, W | Out of window e_H, e_W | ρ(VED, median r) H, W | Peak > 3133 K (calibration) |
|---|---|---|---|---|---|---|---|
| confirm_c1 | 0.298 (0.651, 0.416) | 0.672, 0.423 | 1.033, 1.017 (V_PASS) | 1.151, 0.915 | 0.880, 0.637 | 0.98, 0.96 | 3.4 % |
| confirm_c2 | 0.315 (0.675, 0.418) | 0.697, 0.423 | 1.033, 1.010 (V_PASS) | 1.159, 0.908 | 0.899, 0.635 | 0.98, 0.96 | 3.5 % |

## C. Summary statistic of the model/camera ratio

| Group | Q | Median, pooled frames (package) | Geometric mean, hierarchical | Geometric mean, pooled | Arithmetic mean, pooled | Median of coupon medians |
|---|---|---|---|---|---|---|
| Calibration (9) | H | 1.765 | 1.649 | 1.741 | 1.790 | 1.746 |
| Calibration (9) | W | 0.755 | 0.843 | 0.805 | 0.837 | 0.741 |
| In-window held out (5) | H | 1.769 | 1.700 | 1.756 | 1.812 | 1.759 |
| In-window held out (5) | W | 0.754 | 0.865 | 0.806 | 0.844 | 0.743 |
| Out of window, all (10) | H | 1.982 | 1.425 | 1.655 | 2.012 | 1.488 |
| Out of window, all (10) | W | 0.965 | 0.884 | 0.871 | 0.983 | 0.676 |

## D. Weighting

| Group | Variant | e_H | e_W | J | Frames / tracks / coupons |
|---|---|---|---|---|---|
| Calibration (9) | contract: track -> coupon -> condition | 0.651 | 0.416 | 0.298 | 8,943 / 469 / 9 |
| Calibration (9) | every frame equal | 0.610 | 0.342 | 0.245 | 8,943 / 469 / 9 |
| Calibration (9) | every track equal | 0.643 | 0.426 | 0.298 | 8,943 / 469 / 9 |
| Calibration (9) | every coupon equal | 0.643 | 0.426 | 0.297 | 8,943 / 469 / 9 |
| In-window held out (5) | contract: track -> coupon -> condition | 0.672 | 0.423 | 0.315 | 4,796 / 257 / 5 |
| In-window held out (5) | every frame equal | 0.624 | 0.357 | 0.259 | 4,796 / 257 / 5 |
| In-window held out (5) | every track equal | 0.656 | 0.432 | 0.309 | 4,796 / 257 / 5 |
| In-window held out (5) | every coupon equal | 0.655 | 0.431 | 0.308 | 4,796 / 257 / 5 |
| Out of window, all (10) | contract: track -> coupon -> condition | 0.880 | 0.637 | 0.590 | 10,390 / 518 / 10 |
| Out of window, all (10) | every frame equal | 0.915 | 0.564 | 0.578 | 10,390 / 518 / 10 |
| Out of window, all (10) | every track equal | 0.878 | 0.634 | 0.586 | 10,390 / 518 / 10 |
| Out of window, all (10) | every coupon equal | 0.880 | 0.637 | 0.590 | 10,390 / 518 / 10 |
| All 24 coupons | contract: track -> coupon -> condition | 0.789 | 0.551 | 0.463 | 24,129 / 1,244 / 24 |
| All 24 coupons | every frame equal | 0.759 | 0.453 | 0.391 | 24,129 / 1,244 / 24 |
| All 24 coupons | every track equal | 0.752 | 0.524 | 0.420 | 24,129 / 1,244 / 24 |
| All 24 coupons | every coupon equal | 0.753 | 0.525 | 0.421 | 24,129 / 1,244 / 24 |

## E. Pixel floor and no-pool frames

| Group | Variant | e_H | e_W | J | Frames / tracks / coupons |
|---|---|---|---|---|---|
| Calibration (9) | pixel floor 0.5 px | 0.680 | 0.459 | 0.337 | 8,943 / 469 / 9 |
| Calibration (9) | pixel floor 1 px (contract) | 0.651 | 0.416 | 0.298 | 8,943 / 469 / 9 |
| Calibration (9) | pixel floor 2 px | 0.627 | 0.381 | 0.269 | 8,943 / 469 / 9 |
| Calibration (9) | no-pool frames left out (floor 1 px) | 0.604 | 0.345 | 0.242 | 8,927 / 465 / 9 |
| In-window held out (5) | pixel floor 0.5 px | 0.696 | 0.459 | 0.347 | 4,796 / 257 / 5 |
| In-window held out (5) | pixel floor 1 px (contract) | 0.672 | 0.423 | 0.315 | 4,796 / 257 / 5 |
| In-window held out (5) | pixel floor 2 px | 0.653 | 0.394 | 0.291 | 4,796 / 257 / 5 |
| In-window held out (5) | no-pool frames left out (floor 1 px) | 0.634 | 0.364 | 0.267 | 4,785 / 255 / 5 |
| Out of window, all (10) | pixel floor 0.5 px | 0.986 | 0.763 | 0.777 | 10,390 / 518 / 10 |
| Out of window, all (10) | pixel floor 1 px (contract) | 0.880 | 0.637 | 0.590 | 10,390 / 518 / 10 |
| Out of window, all (10) | pixel floor 2 px | 0.793 | 0.531 | 0.455 | 10,390 / 518 / 10 |
| Out of window, all (10) | no-pool frames left out (floor 1 px) | 0.731 | 0.479 | 0.382 | 9,934 / 518 / 10 |
| All 24 coupons | pixel floor 0.5 px | 0.865 | 0.646 | 0.583 | 24,129 / 1,244 / 24 |
| All 24 coupons | pixel floor 1 px (contract) | 0.789 | 0.551 | 0.463 | 24,129 / 1,244 / 24 |
| All 24 coupons | pixel floor 2 px | 0.728 | 0.472 | 0.376 | 24,129 / 1,244 / 24 |
| All 24 coupons | no-pool frames left out (floor 1 px) | 0.682 | 0.427 | 0.324 | 23,646 / 1,238 / 24 |

## F. Short tracks

| Group | Variant | e_H | e_W | J | Frames / tracks / coupons |
|---|---|---|---|---|---|
| Calibration (9) | tracks with >= 1 scored frames (contract) | 0.651 | 0.416 | 0.298 | 8,943 / 469 / 9 |
| Calibration (9) | tracks with >= 3 scored frames | 0.622 | 0.361 | 0.258 | 8,903 / 441 / 9 |
| Calibration (9) | tracks with >= 5 scored frames | 0.616 | 0.347 | 0.250 | 8,814 / 416 / 9 |
| Calibration (9) | tracks with >= 10 scored frames | 0.595 | 0.334 | 0.233 | 8,324 / 345 / 9 |
| Calibration (9) | tracks with >= 20 scored frames | 0.597 | 0.329 | 0.232 | 6,223 / 201 / 9 |
| In-window held out (5) | tracks with >= 1 scored frames (contract) | 0.672 | 0.423 | 0.315 | 4,796 / 257 / 5 |
| In-window held out (5) | tracks with >= 3 scored frames | 0.653 | 0.379 | 0.285 | 4,777 / 244 / 5 |
| In-window held out (5) | tracks with >= 5 scored frames | 0.655 | 0.370 | 0.283 | 4,719 / 227 / 5 |
| In-window held out (5) | tracks with >= 10 scored frames | 0.638 | 0.351 | 0.265 | 4,444 / 186 / 5 |
| In-window held out (5) | tracks with >= 20 scored frames | 0.620 | 0.343 | 0.251 | 3,397 / 114 / 5 |
| Out of window, all (10) | tracks with >= 1 scored frames (contract) | 0.880 | 0.637 | 0.590 | 10,390 / 518 / 10 |
| Out of window, all (10) | tracks with >= 3 scored frames | 0.903 | 0.660 | 0.625 | 10,341 / 487 / 10 |
| Out of window, all (10) | tracks with >= 5 scored frames | 0.912 | 0.667 | 0.638 | 10,239 / 457 / 10 |
| Out of window, all (10) | tracks with >= 10 scored frames | 0.922 | 0.677 | 0.655 | 9,670 / 375 / 10 |
| Out of window, all (10) | tracks with >= 20 scored frames | 0.924 | 0.680 | 0.658 | 7,391 / 218 / 10 |
| All 24 coupons | tracks with >= 1 scored frames (contract) | 0.789 | 0.551 | 0.463 | 24,129 / 1,244 / 24 |
| All 24 coupons | tracks with >= 3 scored frames | 0.795 | 0.550 | 0.467 | 24,021 / 1,172 / 24 |
| All 24 coupons | tracks with >= 5 scored frames | 0.799 | 0.551 | 0.471 | 23,772 / 1,100 / 24 |
| All 24 coupons | tracks with >= 10 scored frames | 0.799 | 0.553 | 0.473 | 22,438 / 906 / 24 |
| All 24 coupons | tracks with >= 20 scored frames | 0.798 | 0.554 | 0.472 | 17,011 / 533 / 24 |

## G. Leave one coupon out

| Group | Statistic | All coupons | Lowest (dropping) | Highest (dropping) |
|---|---|---|---|---|
| Calibration (9) | e_H | 0.651 | 0.631 (20260731:part_1) | 0.670 (20260730:part_1) |
| Calibration (9) | e_W | 0.416 | 0.388 (20260731:part_1) | 0.442 (20260730:part_1) |
| Calibration (9) | J | 0.298 | 0.274 (20260731:part_1) | 0.322 (20260730:part_1) |
| In-window held out (5) | e_H | 0.672 | 0.630 (20260904:part_5) | 0.703 (20260730:part_4) |
| In-window held out (5) | e_W | 0.423 | 0.365 (20260731:part_4) | 0.473 (20260730:part_4) |
| In-window held out (5) | J | 0.315 | 0.271 (20260731:part_4) | 0.359 (20260730:part_4) |
| Out of window, all (10) | e_H | 0.880 | 0.767 (20260904:part_3) | 0.914 (20260904:part_2) |
| Out of window, all (10) | e_W | 0.637 | 0.493 (20260904:part_3) | 0.666 (20260904:part_1) |
| Out of window, all (10) | J | 0.590 | 0.416 (20260904:part_3) | 0.631 (20260904:part_2) |

## H. Camera threshold (coupon medians; 9 calibration and 7 examined coupons)

| Camera threshold | Coupons | Model/camera H (median of coupon ratios) | W | Shape ratio |
|---|---|---|---|---|
| 30 | Calibration | 0.94 | 0.41 | 2.29 |
| 30 | Out of window, examined | 0.89 | 0.36 | 2.08 |
| 45 | Calibration | 1.13 | 0.47 | 2.39 |
| 45 | Out of window, examined | 1.06 | 0.41 | 2.10 |
| 60 | Calibration | 1.25 | 0.52 | 2.43 |
| 60 | Out of window, examined | 1.15 | 0.45 | 2.13 |
| 80 | Calibration | 1.41 | 0.57 | 2.45 |
| 80 | Out of window, examined | 1.30 | 0.50 | 2.13 |
| 100 | Calibration | 1.51 | 0.62 | 2.46 |
| 100 | Out of window, examined | 1.39 | 0.55 | 2.13 |
| 125 | Calibration | 1.68 | 0.68 | 2.45 |
| 125 | Out of window, examined | 1.53 | 0.61 | 2.11 |
| **150** | Calibration | 1.78 | 0.74 | 2.45 |
| **150** | Out of window, examined | 1.62 | 0.66 | 2.11 |
| 175 | Calibration | 1.88 | 0.78 | 2.41 |
| 175 | Out of window, examined | 1.77 | 0.71 | 2.11 |
| 200 | Calibration | 2.04 | 0.87 | 2.40 |
| 200 | Out of window, examined | 1.89 | 0.76 | 2.11 |
| 225 | Calibration | 2.25 | 0.93 | 2.39 |
| 225 | Out of window, examined | 1.97 | 0.86 | 2.11 |
| 250 | Calibration | 2.38 | 0.99 | 2.38 |
| 250 | Out of window, examined | 2.16 | 0.89 | 2.18 |

**Notes.**

- Descriptive checks on the frozen records, not new searches: no candidate was run or re-selected. A, B and H use recorded candidate scores and committed 22.3.8 camera measurements; C-G re-aggregate the c1 frames.
- A. 3 of 4 objectives select c1: J (log ratio, contract 22.4.3.2); H term only (e_H²); Pixel residual objective (22.3.7, superseded, S11). The w term only (e_W²) would select halton_08 and rank c1 14 of 19. The selection is driven by H, the quantity the model cannot match (A27).
- B. c2, the other near-best point, gives the same reading (V_PASS) with V and part_5 ratios within 0.008 of c1's, the same rank correlations with VED, and calibration J 0.315 against 0.298. The conclusions do not hinge on the choice between them.
- C. Across these summaries the model's H is 1.42–2.01 times the camera's and its W 0.68–0.98 times; the package reports the pooled-frame median, as the manifests do.
- D. Weighting every frame equally changes e by up to 0.07 (large coupons dominate); weighting every track or every coupon equally stays within 0.016 of the contract.
- E. The 1 px floor matters only through the no-pool frames: leaving them out changes e_W by -0.07 for calibration and -0.16 out of window; a 0.5 or 2 px floor moves e in opposite directions by similar amounts. F. Keeping only tracks with at least 10 or 20 scored frames lowers e by up to 0.09.
- G. Dropping any one calibration coupon moves J within 0.274–0.322 (full 0.298); the held-out J ranges from 0.271 (without 20260731:part_4) to 0.359 (without 20260730:part_4), full 0.315.
- H. With the camera thresholded lower its blob grows and the model's H ratio falls; the shape ratio stays within 2.08–2.46 at every threshold from 30 to 250, so no camera threshold reconciles the model's elongation (22.3.8 reading R-b).
- Sources: `data/T15_*.csv`.
