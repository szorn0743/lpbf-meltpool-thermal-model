# Calibration parameters and bounds

| Quantity | Symbol | Bounds | Unit | Definition | Physical interpretation | Selected |
|---|---|---|---|---|---|---|
| Absorptivity–depth coordinate | t | [−3, 3] | – | calibration coordinate | One identifiable direction that moves α and δ together | −3 (lower bound) |
| Absorptivity | α(t) | 0.490–0.641 | – | α = 0.565625 + 0.0252194 t | Fraction of incident power absorbed | 0.490 |
| Deposition depth | δ(t) | 0.0517–0.0983 | mm | δ = 0.075000 − 0.00776201 t | Decay length of the exponential depth profile | 0.0983 |
| Liquid conductivity factor | c_k | [1.5, 2.5] | – | calibration coordinate | Multiplies the liquid conductivity (unresolved melt flow) | 2.418 |
| Directional transport | η | [0, 1] | – | calibration coordinate | Extra liquid conductivity along the local scan direction, × (1 + η) | 0 (lower bound) |
| Stability guard | Δt / Δt_safe | ≤ 0.95 | – | constraint on (c_k, η) | Rejects numerically marginal states before any run | 0.724 |

- Selected: Candidate 1, the calibrated state. Increasing t raises α and shortens δ. The boiling-regulator strength (b = 0.5) and all other quantities were fixed and are not calibration coordinates.
- Bounds from lpbf.calibration.coordinate_bounds(); the mapping from lpbf.calibration_contract._abs_depth_mapping; selected state from committee D6.
