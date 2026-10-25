# 316L material properties used by the model

| Property | Symbol | Value | Units | Remark |
|---|---|---|---|---|
| Density | ρ | 7950 | kg/m³ | constant |
| Solidus temperature | T_s | 1648.15 | K | 1375 °C |
| Liquidus temperature | T_l | 1673.15 | K | 1400 °C |
| Boiling temperature | T_b | 3133.15 | K | threshold of the boiling regulator |
| Latent heat of fusion | L | 260,000 | J/kg | spread over the 25 K mushy interval |
| Specific heat, solid | c_p,s | 500 | J/(kg·K) | T ≤ T_s |
| Specific heat, mushy (sensible) | c_p,m | 650 | J/(kg·K) | T_s < T < T_l |
| Specific heat, mushy (effective) | c_p,eff | 11,050 | J/(kg·K) | c_p,m + L / (T_l − T_s) |
| Specific heat, liquid | c_p,l | 820 | J/(kg·K) | T ≥ T_l |
| Conductivity, solid | k_s | 15 | W/(m·K) | T ≤ T_s |
| Conductivity, mushy | k_m | 22 | W/(m·K) | T_s < T < T_l |
| Conductivity, liquid | k_l | 30 | W/(m·K) | multiplied by c_k (calibrated; 2.418 × 30 = 72.5 W/(m·K) in the selected state) |

- Phase-dependent first-pass engineering values; they were fixed and not calibrated. The directional term (η) multiplies the liquid conductivity along the scan by (1 + η); η = 0 in the selected state.
- Read at build time from lpbf.model.parameters.get_model_parameters().material (_accepted_core/parameters.py).
