# Calibration and held-out performance

| Quantity | Calibration | Held out, in window | Sep 4, 180 W, 1000 mm/s (held out) |
|---|---|---|---|
| Coupons (conditions) | 9 (5) | 5 (3) | 1 (1) |
| Scored frames | 8,943 | 4,796 | 884 |
| e_H | 0.651 [0.594, 0.689] | 0.672 [0.575, 0.719] | 0.749 [0.712, 0.782] |
| e_W | 0.416 [0.353, 0.489] | 0.423 [0.353, 0.517] | 0.380 [0.351, 0.417] |
| J | 0.298 [0.246, 0.351] | 0.315 [0.228, 0.370] | 0.353 [0.322, 0.384] |
| H ratio, model / camera | 1.76 [1.72, 1.83] | 1.77 [1.71, 1.89] | 2.03 [1.95, 2.11] |
| W ratio, model / camera | 0.75 [0.73, 0.81] | 0.75 [0.74, 0.79] | 0.81 [0.80, 0.83] |
| Camera H × W (µm) | 93 × 72 | 91 × 72 | 93 × 72 |
| Model H × W (µm) | 167 × 54 | 161 × 53 | 191 × 57 |
| Coverage (lowest coupon) | 1.000 | 1.000 | 1.000 |
| Frames without a pool | 16 | 11 | 0 |
| V_H = e_H / e_H,cal | – | 1.033 [0.879, 1.155] | 1.151 [1.069, 1.272] |
| V_W = e_W / e_W,cal | – | 1.017 [0.772, 1.328] | 0.915 [0.760, 1.100] |

- Errors are hierarchical log-RMSEs over the group's conditions; ratios are medians of the frame ratios, with frames without a pool scored as H = W = 0 (1 px floor). Brackets: 95% percentile bootstrap over coupons within the group (single coupon: over tracks). Model sizes are medians of the frames with a pool. Predefined criterion V ≤ 1.25 for H and W: met for both.
- Committee D4 group rows, D5 bootstrap summary (v_ratio) and D3 coverage.
