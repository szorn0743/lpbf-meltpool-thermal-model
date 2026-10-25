# Definitions and conventions

Conventions used by every table and figure in this package. Ledger entries (A*) are in `docs/DECISIONS.md`.

| Term | Definition | Ledger / source |
|---|---|---|
| Camera H, W | Length (along the blob's long axis) and width of the minimum-area rectangle around the coaxial camera's threshold-150 blob, as supplied with the data, in camera pixels (H >= W). | A12, A24 |
| Model H, W | Length and width of the minimum-area rectangle around the interpolated liquidus contour of the liquid component receiving the largest share of the beam's deposited power (floor 2 %), converted to camera pixels. | A2, A21 |
| Units | Pixels are the native unit. Micrometres use the nominal 8 um/px, which no calibration validates; absolute sizes and size ratios depend on it, shapes (H/W), slopes and rank correlations do not. | A24 |
| Log residual | r_H = ln(max(H_model, 1) / max(H_camera, 1)), r_W likewise, per scored frame; ratio = exp(r). The 1 px floor keeps a zero prediction finite. | A26 |
| e_H, e_W | Hierarchical log-RMS error: square root of the hierarchical mean of r^2 (frame -> track -> coupon -> condition -> group). | A26 |
| J | 0.5 e_H^2 + 0.5 e_W^2 over a group's conditions; the calibration objective on the 5 calibration conditions. | A26 |
| Median ratio | Median over the pooled scored frames of exp(r); descriptive, never an objective weight. | log_ratio_objective |
| Hierarchy and weights | Each level is an unweighted mean of the level below: every track counts equally within its coupon, every coupon within its condition, every condition within its group, whatever their frame counts. | A10 |
| Eligible frame | A camera frame that the sync maps to a powered scan-track row and whose camera H/W is finite and non-zero. | A22 |
| Scored frame | An eligible frame that is not the first or last eligible frame of its scan track (and not the only frame of a one-frame track). | A22 (D2) |
| NO_LASER_ASSOCIATED_MELT, ZERO_FOOTPRINT | No liquid component receives >= 2 % of the beam's power, or no liquid exists in the window: a model prediction, scored as H = W = 0 (floored to 1 px). Called 'no-pool' frames here. | A21 (D1) |
| Undefined frame | Tied shares, an unenclosed selected contour or unavailable source geometry: excluded and counted, never fabricated. None occurred for confirm_c1. | A21, A23 |
| Coverage | scored / (eligible - excluded by rule), per coupon; floor 95 %. | A23 (D3) |
| Inferential unit | Coupons (24) and conditions (18), not frames (24,129 scored). Frame and track counts describe precision inside a coupon only. | this package |
| Confidence intervals | 95 % percentile bootstrap, 4,000 replicates. Groups of >= 2 coupons: coupons resampled within the group. Single coupons and conditions: tracks resampled within each coupon (within-coupon uncertainty only). | METHODS_MANIFEST.json |
| VED | P / (v * 0.080 mm * 0.030 mm), J/mm3; calibration window [65, 85]. | A17, A25 |
