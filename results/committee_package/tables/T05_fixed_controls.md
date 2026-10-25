# Fixed model and numerical controls

What the calibration held fixed, so that the numerical framework could not be adjusted opportunistically.

| Group | Control | Value | Varied by the calibration | Source (read at build time) |
|---|---|---|---|---|
| Numerics | Thermal grid | 16 µm cubic cells | no | lpbf.geometry.FROZEN_SPACING_UM; frozen_configuration.json |
| Numerics | Production window | 99 x 99 cells (1.584 mm square), depth 0.336 mm | no | current_framework.PRODUCTION_CALIBRATION_WINDOW_CELLS; resize_xy_window |
| Numerics | Process (DAQ) clock | 200 kHz, 5 µs per row | no | lpbf.model.input_data |
| Numerics | Thermal time step | 2.5 µs, 2 substeps per DAQ row | no | lpbf.runtime.parameters (overrides the legacy 3.33 µs in frozen_configuration.json) |
| Numerics | Explicit stability guard | directional Gershgorin bound <= 0.95 of the safe step (solver limit 1.0) | no | patch21_0 contract coupled_transport_guard; checked for every candidate before any run |
| Numerics | Frozen numerical core | 8 files of src/lpbf/model/_accepted_core match their accepted sha256: True | no | accepted_core_hashes.json (sha256 bc84e0cc7506); checked at the smoke gate |
| Process input | Laser-on rule | Laser Drive > 2.5 V (strict); scan tracks are the laser-on runs | no | lpbf.model.input_data.PRODUCTION_LASER_DRIVE_THRESHOLD |
| Process input | Process conditions | P and v from the read-only A17 record; hatch 0.080 mm, layer 0.030 mm | no | docs/reference/LPBF_Process_Parameters.csv (A17) |
| Heat source | Beam | Gaussian exp(-2r²/R²), R = 0.04 mm (1/e² radius; spot 80 µm diameter), normalised on the grid | no | _accepted_core/heat_source.py; deposition_depth_source.py |
| Heat source | Depth profile | normalized truncated exponential, decay length λ | no | lpbf.model.deposition_depth |
| Heat source | Absorbed power | P x α x m_TED with m_TED = 1 (global alpha times neutral m TED) | no | model/current_execution.py |
| Heat source | Calibrated coordinate t -> (α, λ) | one principal direction (A9): t in [-3, 3] gives α 0.490–0.641, λ 98.3–51.7 µm; c1 (t = −3): α 0.490, λ 98.3 µm | **yes** | calibration_contract._abs_depth_mapping |
| Material | Alloy model | 316L stainless steel, phase-aware first-pass engineering model | no | _accepted_core/parameters.py (not calibrated) |
| Material | Solidus, liquidus, boiling | 1648.15 K, 1673.15 K, 3133.15 K | no | _accepted_core/parameters.py |
| Material | Density, heat capacity | 7950 kg/m³; cp solid / mushy / liquid 500 / 650 / 820 J/kg K | no | _accepted_core/parameters.py |
| Material | Latent heat | 260000 J/kg over 25 K (cp_eff mushy 11050 J/kg K) | no | _accepted_core/parameters.py |
| Material | Conductivity | solid / mushy / liquid 15 / 22 / 30 W/m K; liquid x ck, and x (1 + η) along the scan | **yes** | _accepted_core/parameters.py; directional_transport.py |
| Material | Calibrated ck and η (box) | ck in [1.5, 2.5], η in [0, 1] | **yes** | patch21_3_coarse_global_search_design.json |
| Boiling | Fixed boiling regulator | surface loss flux above T_b = 3133.15 K, strength 0.5, law smoothstep quadratic; no temperature clipping | no | current_configuration.CURRENT_FIXED_CONFIGURATION; _accepted_core/solver.py |
| Boiling | Peak-above-boiling diagnostic | peak top-surface T > 3133 K (diagnostic only, never in the objective) | no | patch22_4_3_2_window_calibration.BOILING_K |
| Observation | Model H/W | liquidus contour of the laser-associated component, linearly interpolated, minAreaRect; 16 µm cells = 2 camera px (semantics 22.3.7) | no | lpbf.model.production_hw (A2, A21) |
| Observation | Association policy | largest share of the beam's deposited power, floor 2% (policy 22.3.7); below the floor: NO_LASER_ASSOCIATED_MELT, scored as H = W = 0 | no | lpbf.model.laser_component_association (A21, D1, D3) |
| Observation | Camera scale | 8 µm/px nominal (reporting 8); not validated | no | frozen_configuration.json comparison (A24) |
| Scoring | Scored-frame rule | exclude first and last eligible frame of each scan track (version 22.3.7) | no | lpbf.scored_frame_rule (A22, D2) |
| Scoring | Coverage floor | 95% per coupon (flag, never a penalty) | no | lpbf.hierarchical_objective.COVERAGE_FLOOR (A23, D3) |
| Scoring | Objective | contract 22.4.3.2: log ratios with a 1 px floor, hierarchical, w_H = w_W = 0.5 | no | lpbf.log_ratio_objective (A26) |
| Governance | Campaign dispatch lock | CAMPAIGN_DISPATCH_AUTHORIZED_BY = None; lock holds: True | no | Patch 22.3.5.2; S10 |

**Notes.**

- Every value is read from the code the Patch 22.4.3.2 runner imported, when the package is built; nothing is copied by hand.
- Only three coordinates were calibrated: t (absorptivity and deposition depth together, A9), ck (liquid conductivity) and η (directional conductivity). Everything else was fixed before the calibration (A25, A26).
- The smoke, calibrate, confirm and evaluate manifests all recorded the same beam-share floor, coverage floor, pixel floor, window, semantic versions, design file, objective module and plan (sha256): yes (T16).
- The runner module changed once between calibrate and confirm (the c2 walk fix, `ec53a55`, T17 deviation); the objective module did not change.
- Boiling: the model has no temperature cap; above the boiling point a surface loss flux grows quadratically (A27 failure mode: peaks above 3133 K remain).
