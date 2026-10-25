# In-window held-out performance

Transfer of the frozen calibration to the 5 in-window held-out coupons, with the predeclared reading V.

## Reading V: held-out error relative to calibration

| Comparison | Error | Ratio [95 % CI] | Predeclared limit | Bootstrap share ≤ 1.25 | Resampling |
|---|---|---|---|---|---|
| Held out / calibration | e_H | 1.033 [0.879, 1.155] | ≤ 1.25 | 1.000 | coupon (both groups, independent) |
| 20260904:part_5 / calibration | e_H | 1.151 [1.069, 1.272] | ≤ 1.25 | 0.945 | track within 20260904:part_5; coupon within calibration |
| Held out / calibration | e_W | 1.017 [0.772, 1.328] | ≤ 1.25 | 0.928 | coupon (both groups, independent) |
| 20260904:part_5 / calibration | e_W | 0.915 [0.760, 1.100] | ≤ 1.25 | 1.000 | track within 20260904:part_5; coupon within calibration |

## Performance

| Level / unit | VED | Coupons / tracks / frames | Camera H × W (µm) | Model H × W (µm, pool frames) | H ratio | W ratio | e_H | e_W | J | No-pool frames | CI unit |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **Pooled in-window held out** | – | 5 / 257 / 4,796 | 91 × 72 | 161 × 53 | 1.77 [1.71, 1.89] | 0.75 [0.74, 0.79] | 0.672 [0.575, 0.719] | 0.423 [0.353, 0.517] | 0.315 [0.228, 0.370] | 11 | coupons |
| set 20260730 | – | 2 / 101 / 1,914 | 91 × 72 | 156 × 52 | 1.73 [1.71, 1.76] | 0.74 [0.73, 0.74] | 0.572 [0.549, 0.594] | 0.343 [0.343, 0.344] | 0.223 [0.210, 0.235] | 0 | coupons |
| set 20260731 | – | 2 / 104 / 1,998 | 91 × 72 | 156 × 53 | 1.72 [1.68, 1.76] | 0.74 [0.74, 0.75] | 0.683 [0.612, 0.747] | 0.523 [0.397, 0.624] | 0.370 [0.266, 0.474] | 11 | coupons |
| 20260904_part_5 | – | 1 / 52 / 884 | 93 × 72 | 191 × 57 | 2.03 [1.95, 2.11] | 0.81 [0.80, 0.83] | 0.749 [0.712, 0.782] | 0.380 [0.351, 0.417] | 0.353 [0.322, 0.384] | 0 | tracks |
| P150_V900 (2 coupons) | 69.4 | 2 / 104 / 2,052 | 85 × 71 | 153 × 51 | 1.76 [1.71, 1.82] | 0.74 [0.73, 0.76] | 0.603 [0.566, 0.642] | 0.371 [0.352, 0.396] | 0.251 [0.226, 0.279] | 6 | tracks |
| P170_V1000 (2 coupons) | 70.8 | 2 / 101 / 1,860 | 98 × 73 | 170 × 54 | 1.70 [1.66, 1.74] | 0.74 [0.73, 0.75] | 0.656 [0.544, 0.787] | 0.504 [0.367, 0.657] | 0.342 [0.218, 0.523] | 5 | tracks |
| P180_V1000 (1 coupon) | 75.0 | 1 / 52 / 884 | 93 × 72 | 191 × 57 | 2.03 [1.95, 2.11] | 0.81 [0.80, 0.83] | 0.749 [0.712, 0.782] | 0.380 [0.351, 0.417] | 0.353 [0.322, 0.384] | 0 | tracks |
| 20260730:part_2 | 69.4 | 1 / 52 / 1,000 | 85 × 71 | 153 × 51 | 1.76 [1.69, 1.84] | 0.74 [0.72, 0.76] | 0.594 [0.539, 0.657] | 0.343 [0.330, 0.357] | 0.235 [0.205, 0.275] | 0 | tracks |
| 20260730:part_4 | 70.8 | 1 / 49 / 914 | 98 × 73 | 170 × 54 | 1.71 [1.66, 1.76] | 0.73 [0.72, 0.75] | 0.549 [0.504, 0.602] | 0.344 [0.327, 0.361] | 0.210 [0.187, 0.240] | 0 | tracks |
| 20260731:part_2 | 69.4 | 1 / 52 / 1,052 | 85 × 70 | 152 × 51 | 1.76 [1.70, 1.83] | 0.75 [0.73, 0.76] | 0.612 [0.561, 0.665] | 0.397 [0.361, 0.442] | 0.266 [0.228, 0.310] | 6 | tracks |
| 20260731:part_4 | 70.8 | 1 / 52 / 946 | 98 × 73 | 170 × 54 | 1.68 [1.63, 1.76] | 0.74 [0.73, 0.76] | 0.747 [0.546, 0.960] | 0.624 [0.390, 0.861] | 0.474 [0.228, 0.828] | 5 | tracks |
| 20260904:part_5 | 75.0 | 1 / 52 / 884 | 93 × 72 | 191 × 57 | 2.03 [1.95, 2.11] | 0.81 [0.80, 0.83] | 0.749 [0.712, 0.782] | 0.380 [0.351, 0.417] | 0.353 [0.322, 0.384] | 0 | tracks |

**Notes.**

- Pooled held-out values equal the evaluate manifest (`readings.V.confirm_c1.held_out`) exactly; reading V_PASS was declared on the point ratios (plan, A27). The intervals and bootstrap shares are added here and were not part of the predeclared rule.
- P150_V900 and P170_V1000 lie on the calibration P/v line, so their validation is close to interpolation; 20260904:part_5 is off that line and from the other campaign (sync convention O11), the informative test (A25).
- The held-out/calibration interval resamples coupons in both groups independently (5 and 9 coupons). The part_5 interval combines a track bootstrap within part_5 with a coupon bootstrap of calibration.
- These coupons were opened after the selection freeze and are now spent as held-out data (A8, A27).
