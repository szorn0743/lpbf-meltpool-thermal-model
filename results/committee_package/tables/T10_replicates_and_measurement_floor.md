# Replicates and measurement floor

How well the experiment repeats between the two July days, and how small an error is attainable at all, so that the model's e_H and e_W are read against a floor rather than against zero.

## Replicate pairs (20260730 / 20260731)

| Condition | Role | VED | Camera H, px (0730 / 0731, Δ) | Camera W, px | Camera H/W | Model H, px | Model W, px | e_H (0730 / 0731, Δ [95 % CI]) | e_W |
|---|---|---|---|---|---|---|---|---|---|
| P140_V850 | calibration | 68.6 | 10.29 / 10.24 (-0.5 %) | 8.79 / 8.65 (-1.5 %) | 1.18 / 1.19 (+0.6 %) | 17.90 / 17.87 (-0.2 %) | 6.24 / 6.25 (+0.1 %) | 0.554 / 0.747 (+0.193 [+0.012, +0.388]) | 0.356 / 0.594 (+0.238 [+0.023, +0.457]) |
| P150_V900 | in-window held out | 69.4 | 10.63 / 10.59 (-0.4 %) | 8.87 / 8.80 (-0.8 %) | 1.21 / 1.22 (+0.9 %) | 19.12 / 19.04 (-0.4 %) | 6.38 / 6.42 (+0.5 %) | 0.594 / 0.612 (+0.018 [-0.059, +0.095]) | 0.343 / 0.397 (+0.054 [+0.015, +0.104]) |
| P160_V950 | calibration | 70.2 | 11.22 / 11.23 (+0.1 %) | 9.00 / 9.00 (+0.0 %) | 1.24 / 1.26 (+1.3 %) | 20.23 / 20.32 (+0.4 %) | 6.53 / 6.56 (+0.4 %) | 0.588 / 0.684 (+0.096 [-0.039, +0.269]) | 0.341 / 0.506 (+0.165 [+0.010, +0.357]) |
| P170_V1000 | in-window held out | 70.8 | 12.20 / 12.28 (+0.7 %) | 9.14 / 9.09 (-0.5 %) | 1.33 / 1.34 (+0.9 %) | 21.25 / 21.22 (-0.1 %) | 6.71 / 6.73 (+0.3 %) | 0.549 / 0.747 (+0.197 [-0.013, +0.420]) | 0.344 / 0.624 (+0.281 [+0.047, +0.515]) |
| P180_V1050 | calibration | 71.4 | 12.63 / 12.56 (-0.5 %) | 9.19 / 9.15 (-0.5 %) | 1.36 / 1.35 (-0.5 %) | 22.54 / 22.54 (-0.0 %) | 6.84 / 6.85 (+0.2 %) | 0.585 / 0.609 (+0.024 [-0.052, +0.102]) | 0.339 / 0.400 (+0.061 [+0.010, +0.131]) |
| P190_V1100 | calibration | 72.0 | 13.34 / 13.44 (+0.7 %) | 9.37 / 9.42 (+0.6 %) | 1.41 / 1.41 (+0.4 %) | 23.91 / 23.89 (-0.0 %) | 6.94 / 6.94 (+0.0 %) | 0.566 / 0.700 (+0.134 [-0.038, +0.345]) | 0.351 / 0.538 (+0.187 [+0.011, +0.408]) |

## Day-to-day agreement of coupon medians

| Coupon median | Mean absolute ln(0731/0730), 6 pairs | Largest | Pairs whose CI excludes 0 |
|---|---|---|---|
| Camera H | 0.0049 (0.5 %) | 0.0073 | 0 of 6 |
| Camera W | 0.0066 (0.7 %) | 0.0154 | 0 of 6 |
| Model H | 0.0021 (0.2 %) | 0.0045 | 0 of 6 |
| Model W | 0.0027 (0.3 %) | 0.0052 | 0 of 6 |

## Measurement floor

| Group | Camera median H / W (px) | 1 px is up to | Re-measurement, median absolute Δln, H / W | Track oracle e_H / e_W | Coupon oracle e_H / e_W | Replicate oracle e_H / e_W | Model e_H / e_W |
|---|---|---|---|---|---|---|---|
| Calibration (9) | 10.2–13.4 / 8.7–9.4 | 12 % | 0.017 / 0.013 | 0.087 / 0.082 | 0.137 / 0.121 | 0.126 / 0.109 (8 coupons) | **0.651 / 0.416** |
| In-window held out (5) | 10.6–12.3 / 8.8–9.1 | 11 % | 0.021 / 0.017 | 0.097 / 0.088 | 0.140 / 0.112 | 0.133 / 0.108 (4 coupons) | **0.672 / 0.423** |
| Out of window, all (10) | 9.1–12.7 / 6.9–10.1 | 15 % | 0.034 / 0.027 | 0.101 / 0.100 | 0.162 / 0.138 | – | **0.880 / 0.637** |
| All 24 coupons | 9.1–13.4 / 6.9–10.1 | 15 % | 0.023 / 0.019 | 0.097 / 0.093 | 0.152 / 0.129 | 0.128 / 0.109 (12 coupons) | **0.789 / 0.551** |

## Within-coupon spread (log scale)

| Coupon | Role | Camera H: track SD | frame SD | Camera W: track SD | frame SD | Model H: track SD | frame SD | Model W: track SD | frame SD |
|---|---|---|---|---|---|---|---|---|---|
| 20260730:part_1 | calibration | 0.107 | 0.084 | 0.076 | 0.081 | 0.141 | 0.170 | 0.155 | 0.177 |
| 20260730:part_2 | in-window held out | 0.124 | 0.088 | 0.081 | 0.085 | 0.182 | 0.179 | 0.179 | 0.185 |
| 20260730:part_3 | calibration | 0.091 | 0.094 | 0.074 | 0.098 | 0.155 | 0.183 | 0.179 | 0.191 |
| 20260730:part_4 | in-window held out | 0.101 | 0.087 | 0.061 | 0.072 | 0.152 | 0.186 | 0.118 | 0.183 |
| 20260730:part_5 | calibration | 0.097 | 0.097 | 0.070 | 0.084 | 0.158 | 0.181 | 0.204 | 0.201 |
| 20260730:part_6 | calibration | 0.084 | 0.090 | 0.084 | 0.085 | 0.194 | 0.171 | 0.211 | 0.229 |
| 20260731:part_1 | calibration | 0.098 | 0.083 | 0.070 | 0.074 | 0.195 | 0.198 | 0.172 | 0.267 |
| 20260731:part_2 | in-window held out | 0.110 | 0.092 | 0.072 | 0.091 | 0.223 | 0.191 | 0.172 | 0.281 |
| 20260731:part_3 | calibration | 0.089 | 0.093 | 0.072 | 0.084 | 0.220 | 0.195 | 0.181 | 0.288 |
| 20260731:part_4 | in-window held out | 0.099 | 0.090 | 0.085 | 0.083 | 0.180 | 0.197 | 0.178 | 0.295 |
| 20260731:part_5 | calibration | 0.105 | 0.092 | 0.086 | 0.075 | 0.215 | 0.202 | 0.191 | 0.302 |
| 20260731:part_6 | calibration | 0.093 | 0.087 | 0.068 | 0.073 | 0.256 | 0.202 | 0.184 | 0.314 |
| 20260904:part_1 | out, examined | 0.152 | 0.081 | 0.112 | 0.093 | 0.136 | 0.275 | 0.157 | 0.181 |
| 20260904:part_2 | out, blind | 0.094 | 0.097 | 0.081 | 0.102 | 0.059 | 0.272 | 0.381 | 0.387 |
| 20260904:part_3 | out, examined | 0.086 | 0.158 | 0.099 | 0.151 | 0.521 | 0.717 | 0.597 | 0.727 |
| 20260904:part_4 | out, examined | 0.233 | 0.082 | 0.147 | 0.079 | 0.224 | 0.344 | 0.150 | 0.169 |
| 20260904:part_5 | in-window held out | 0.114 | 0.120 | 0.077 | 0.108 | 0.135 | 0.299 | 0.314 | 0.331 |
| 20260904:part_6 | out, examined | 0.095 | 0.111 | 0.080 | 0.098 | 0.117 | 0.364 | 0.421 | 0.507 |
| 20260910:part_1 | calibration | 0.157 | 0.087 | 0.133 | 0.093 | 0.135 | 0.294 | 0.235 | 0.235 |
| 20260910:part_2 | out, blind | 0.144 | 0.079 | 0.091 | 0.080 | 0.157 | 0.308 | 0.210 | 0.215 |
| 20260910:part_3 | out, examined | 0.175 | 0.083 | 0.120 | 0.079 | 0.132 | 0.352 | 0.231 | 0.214 |
| 20260910:part_4 | out, examined | 0.073 | 0.135 | 0.073 | 0.141 | 0.195 | 0.501 | 0.489 | 0.555 |
| 20260910:part_5 | out, blind | 0.078 | 0.099 | 0.064 | 0.099 | 0.090 | 0.304 | 0.418 | 0.440 |
| 20260910:part_6 | out, examined | 0.076 | 0.088 | 0.072 | 0.080 | 0.091 | 0.303 | 0.372 | 0.402 |

**Notes.**

- Replicates. The six July conditions were built on 20260730 and again on 20260731 by the same part number (confound table), so a pair differs by day only. Δ for sizes is the relative difference of the coupon medians, for e the plain difference; intervals: tracks resampled within each coupon independently (family 5, 4,000 replicates), i.e. within-coupon sampling only.
- The camera's coupon medians repeat between days to within 1.5 % and the model's to within 0.5 %; 0 of 24 size differences have an interval excluding zero. The day difference sits in e: 0731 has the larger e_H in 6 of 6 pairs and the larger e_W in 6 of 6, consistent with the 0731-only end-of-track frames without a predicted pool (confound table, T15 E).
- Within-coupon spread is on the log scale (≈ relative spread): SD of the ln track medians, and the pooled SD of ln frame values within tracks.
- Measurement floor. The camera's coupon-median blob is 6.9–13.4 px across, so a 1 px step is up to 15 % of a dimension. Re-measuring the supplied images at threshold 150 (reading S) reproduces the supplied H and W to a median 2.3 % and 1.9 % per frame.
- Oracle floors: the e a predictor would score if it knew the camera exactly and predicted one value per track (track oracle), per coupon (coupon oracle) or the other day's coupon value (replicate oracle). Any model that is constant within a coupon scores at least the coupon oracle. Across the three groups the model's e_H is 4.8–5.4 times the coupon floor and its e_W 3.4–4.6 times.
- Sources: `data/T10_replicate_pairs.csv` (every quantity with intervals), `data/T10_within_coupon_spread.csv`, `data/T10_measurement_floor.csv`, `data/T10_camera_remeasurement.csv`, `data/bootstrap/D5_replicate_bootstrap.npz`.
