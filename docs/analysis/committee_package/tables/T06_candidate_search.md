# Calibration candidate search

All 17 frozen design candidates and the 2 confirmation candidates, ranked by measured J.

| Rank | Candidate | t | ck | η | Absorptivity | Depth (mm) | Guard | Coverage | No-pool frames | Peak > boiling | e_H | e_W | J | J (pixel 22.3.7) | Near-best |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | **confirm_c1** | -3.00 | 2.418 | 0.00 | 0.490 | 0.098 | 0.724 | 1.000 | 16 | 3.4 % | 0.651 | 0.416 | 0.298 | 79.9 | yes |
| 2 | confirm_c2 | -3.00 | 2.370 | 0.40 | 0.490 | 0.098 | 0.900 | 1.000 | 15 | 3.5 % | 0.675 | 0.418 | 0.315 | 87.9 | yes |
| 3 | anchor_t_min | -3.00 | 2.000 | 0.50 | 0.490 | 0.098 | 0.799 | 1.000 | 16 | 5.0 % | 0.699 | 0.419 | 0.332 | 95.7 | no |
| 4 | halton_04 | -2.25 | 1.944 | 0.80 | 0.509 | 0.092 | 0.893 | 1.000 | 12 | 6.6 % | 0.825 | 0.383 | 0.413 | 151.5 | no |
| 5 | halton_11 | -1.88 | 1.648 | 0.48 | 0.518 | 0.090 | 0.652 | 1.000 | 10 | 8.5 % | 0.886 | 0.371 | 0.461 | 187.9 | no |
| 6 | halton_02 | -1.50 | 2.167 | 0.40 | 0.528 | 0.087 | 0.822 | 1.000 | 7 | 7.5 % | 0.901 | 0.359 | 0.471 | 198.2 | no |
| 7 | halton_09 | -1.12 | 1.870 | 0.08 | 0.537 | 0.084 | 0.590 | 1.000 | 6 | 9.1 % | 0.957 | 0.358 | 0.522 | 240.6 | no |
| 8 | halton_06 | -0.75 | 1.722 | 0.24 | 0.547 | 0.081 | 0.599 | 1.000 | 5 | 9.9 % | 1.032 | 0.357 | 0.596 | 307.6 | no |
| 9 | anchor_transport_guard_edge | 0.00 | 2.500 | 0.40 | 0.566 | 0.075 | 0.949 | 1.000 | 5 | 9.1 % | 1.095 | 0.375 | 0.669 | 372.8 | no |
| 10 | halton_01 | 0.00 | 1.833 | 0.20 | 0.566 | 0.075 | 0.623 | 1.000 | 5 | 10.9 % | 1.125 | 0.372 | 0.702 | 412.0 | no |
| 11 | anchor_center | 0.00 | 2.000 | 0.50 | 0.566 | 0.075 | 0.799 | 1.000 | 5 | 10.2 % | 1.126 | 0.372 | 0.703 | 412.3 | no |
| 12 | halton_05 | 0.75 | 2.278 | 0.04 | 0.585 | 0.069 | 0.701 | 1.000 | 3 | 11.3 % | 1.173 | 0.380 | 0.760 | 487.6 | no |
| 13 | anchor_low_ck_high_eta | 0.00 | 1.500 | 1.00 | 0.566 | 0.075 | 0.749 | 1.000 | 5 | 11.6 % | 1.182 | 0.364 | 0.765 | 490.2 | no |
| 14 | halton_08 | 0.38 | 1.537 | 0.84 | 0.575 | 0.072 | 0.718 | 1.000 | 3 | 12.3 % | 1.217 | 0.353 | 0.803 | 555.6 | no |
| 15 | halton_12 | 1.12 | 1.981 | 0.68 | 0.594 | 0.066 | 0.863 | 1.000 | 3 | 13.8 % | 1.269 | 0.384 | 0.879 | 648.9 | no |
| 16 | halton_10 | 1.88 | 2.204 | 0.28 | 0.613 | 0.060 | 0.783 | 1.000 | 3 | 35.8 % | 1.329 | 0.428 | 0.975 | 774.4 | no |
| 17 | halton_03 | 1.50 | 1.611 | 0.60 | 0.603 | 0.063 | 0.676 | 1.000 | 3 | 49.2 % | 1.343 | 0.395 | 0.980 | 806.2 | no |
| 18 | halton_07 | 2.25 | 2.056 | 0.44 | 0.622 | 0.058 | 0.797 | 1.000 | 3 | 68.2 % | 1.390 | 0.445 | 1.065 | 921.3 | no |
| 19 | anchor_t_max | 3.00 | 2.000 | 0.50 | 0.641 | 0.052 | 0.799 | 1.000 | 3 | 99.1 % | 1.476 | 0.486 | 1.208 | 1,173.2 | no |

**Notes.**

- Selected: confirm_c1 by the lowest measured J (0.2981); near-best set J <= 1.10 J_min. Quadratic surrogate over the 17 design points: R² 0.99948, leave-one-out RMSE 0.0299; it predicted J 0.2835 at c1 and 0.3118 at c2. The surrogate proposes; it never selects.
- Reading C_EDGE: t and η are at their bounds (coded |x| >= 0.9); the guard value 0.724 is below the 0.9025 edge threshold. The box was not widened (A9, A25).
- Absorptivity and deposition depth are derived from t by `_abs_depth_mapping` (`src/lpbf/calibration_contract.py:124-140`); they are not stored in the manifests. ck is the liquid-conductivity enhancement factor; η the directional factor.
- Each candidate is scored on the 9 calibration members (8,943 scored frames). J (pixel 22.3.7) is the superseded A10 objective, reported as a sensitivity only (S11).
- Values equal `calibrate/stage_manifest.json` (17 design candidates) and `confirm/stage_manifest.json` (2 confirmation candidates) exactly; checked at build time.
