# Methods and decisions

This is a condensed version of the decision ledger kept while the model was developed. Entry IDs are unchanged, so
that references elsewhere in this repository (for example "`docs/DECISIONS.md` A21" in the committee tables) resolve
here. Active decisions are given in full; superseded and historical entries are summarized in a line or two. The full
ledger, with its history, stays in the private development repository (see `PROVENANCE.md`).

In the records, "owner" means the thesis author. Patch numbers (22.3.6, 22.4.3.2, ...) name the development steps in
which a decision was made; tags such as `patch-22.4.3.2` refer to the private repository.

## Method in brief

- **Model.** A reduced-order thermal model of a moving laser track, evaluated in a 99 × 99 surface-cell window at
  16 µm spacing (A1). Its numerical core is frozen by SHA-256 (A6).
- **Observable.** The height H (length along travel) and width W of the laser-associated liquidus component (A2,
  A21), compared with the H/W of the thresholded blob in the coaxial camera frame (A12, A24). The two are different
  measurement operators.
- **Scoring.** Every eligible camera frame of a scan track is scored except the first and last (A22). Frames where
  the model cannot form a prediction are excluded and counted; coverage must stay at or above 95 % per coupon (A23).
  The residual is the log ratio of simulated to camera H and W (A26), aggregated frame → track → coupon → replicate
  → condition (A10).
- **Calibration.** 17 frozen design points in three global parameters (A9), run on the 9 calibration coupons inside
  a 65–85 J/mm³ energy-density window, then up to 3 confirmation points; selection by lowest measured objective,
  frozen and committed before any held-out coupon was read (A25).
- **Result.** `confirm_c1` (A27): calibrated at a box edge (C_EDGE), transfers to held-out coupons inside the window
  (V_PASS), extrapolates poorly outside it (X_PARTIAL); a synthetic camera does not follow the real one across
  energy density (S, descriptive).

## A. Active decisions

### Geometry and observable

**A1. Production window.** 99 × 99 surface cells at 16 µm spacing (`WINDOW_CELLS = 99`,
`lpbf.geometry.FROZEN_SPACING_UM = 16.0`).

**A2. Production H/W definition.** The laser-associated liquidus component, measured on the interpolated liquidus
contour (`laser_associated_component_interpolated_liquidus_contour` in `lpbf.model.production_hw`). Remote,
disconnected liquid components do not contribute. Component selection is A21.

**A3–A4.** Earlier association rules; superseded by A21 (see S8). Still active from A4: tied, unenclosed and
geometry-unavailable cases stay invalid (NaN); the largest component is never substituted; the floor is never changed
to make a gate pass.

**A21. Association by beam-power share (policy 22.3.7).**
- For every 4-connected liquid component on the top surface, compute its share of the beam's surface-deposited power,
  using the model's separable Gaussian (realized radius 0.040 mm) at cell centers, normalized over the window.
- Select the component with the largest share if that share is at least **2 %** (`BEAM_SHARE_FLOOR`, decision D3).
  Its H/W is measured as in A2 (`cv2.minAreaRect`, H ≥ W).
- No liquid in the window → `ZERO_FOOTPRINT`. Largest share below 2 % → `NO_LASER_ASSOCIATED_MELT`, scored as
  H = W = 0 (decision D1). Two shares within 1e-6 → `FAIL_CLOSED_TIED_SHARE` (NaN). Selected component touching the
  window edge → unenclosed (NaN). Missing geometry → NaN.
- Why: a census of the earlier one-cell distance rule found it failed 772 of 777 interior near misses although the
  pool boundary was within one cell; the beam-share outcome is identical for any floor from 0.5 % to 10 %.
- Verified on 10,100 scored frames: production equals the offline rule with 0 mismatches.
- Code: `lpbf.model.laser_component_association`, `lpbf.model.production_hw`; tests `tests/test_patch22_3_7_recovery.py`.

### Provenance and integrity

**A5. Semantic changes are versioned.** Any change to component selection or H/W semantics bumps `POLICY_VERSION`,
`PRODUCTION_HW_SEMANTICS_VERSION` and `PRODUCTION_SEMANTICS_ID`; the scoring conventions carry
`SCORED_FRAME_RULE_VERSION` and the objective contract version. Outputs from different versions are never mixed. Gates
that pin `"22.3.7"` fail closed on a bump.

**A6. The numerical core is frozen.** The 8 files of `src/lpbf/model/_accepted_core/` are fixed by SHA-256 in
`PATCH_22_3_4_ACCEPTED_CORE_HASHES.json`; `tests/test_accepted_core_hashes.py` checks them.

**A16. Dependencies are pinned** in `requirements.lock.txt` (Python 3.13). Numerical provenance depends on them.

**A17. The process parameters are a fixed, read-only record:** `docs/reference/LPBF_Process_Parameters.csv`
(SHA-256 `15faa033…f304`): power, speed, spot size and both energy densities for all 24 coupons. Code-side copies must
match it; `tests/test_process_parameter_record.py` enforces the hash and the cross-checks. Hatch spacing 0.080 mm and
layer thickness 0.030 mm for all coupons. See `docs/reference/README.md`.

**A19. Execution.** Runs with more than one thermal work unit use 4 Windows-spawn worker processes by default
(`--workers`); each thermal evaluation is single-core. Worker count and completion order carry no meaning; parallel
results equal serial results.

**A20. The model must always produce a comparison.** The model may disagree with the data, but it must not fail in a
way that prevents a comparison. "Undefined" is reserved for genuine inability to form a prediction; no H/W is
fabricated; every convention is predeclared, applied identically to calibration and held-out coupons, and versioned.
Decisions taken under this rule:
- **D1.** No liquid receiving meaningful beam power → `NO_LASER_ASSOCIATED_MELT`, scored as H = W = 0.
- **D2.** The first and last eligible camera frame of every scan track are not scored.
- **D3.** Beam-share floor 2 %; coverage floor 95 % of eligible interior frames per coupon; no heating-position
  correction.

### Data, partition and calibration

**A7. Coupon roster.** 24 coupons: 4 acquisition sets × 6 parts. `20260730` and `20260731` are replicate sets
(140 W / 850 mm/s to 190 W / 1100 mm/s); `20260904` is a speed sweep (140 and 180 W at 600, 1000, 1400 mm/s);
`20260910` a power sweep (140, 160, 180 W at 700 and 1200 mm/s). Canonical list:
`src/lpbf/data/full_coupon_dataset_manifest.json`.

**A8. Calibration and held-out partition.** The unit is the nominal power/speed condition. Calibration: 16 members,
12 conditions. Held out: 8 members, 6 conditions (`20260730`, `20260731` parts 2 and 4; `20260904`, `20260910`
parts 2 and 5). Held-out members never enter ranking, selection or fitting. In Patch 22.4.3.2 they were read only by
the evaluation stage, after the selection freeze was committed (`d01ac72`). **They have now been opened:** any later
fitting or selection that used them would no longer be held-out validation.

**A9. Frozen calibration design.** Three global coordinates: `abs_depth_identifiable_coordinate` t ∈ [−3, 3],
`liquid_conductivity_enhancement_factor` ck ∈ [1.5, 2.5], `eta_directional` η ∈ [0, 1], with the guard
`directional.selected_over_safe_limit` ≤ 0.95 checked before any thermal run. 17 candidates: 5 anchors and 12 Halton
points (`src/lpbf/data/patch21_3_coarse_global_search_design.json`). The original 17 × 16 = 272-unit campaign scope
is superseded (S10); its code is locked and never dispatched.

**A10. Hierarchical objective.** Aggregation frame → track → coupon → exact-condition replicate → unique condition,
H and W weighted 0.5 each. The residual form is now A26; failure handling is A23. The original pixel residuals
(scales 0.90 px for H, 0.65 px for W) stay in `lpbf.hierarchical_objective` and are reported as a sensitivity.

**A11.** A review threshold of the superseded full campaign; not used by Patch 22.4.3.2 (S12).

**A22. Scored-frame rule 22.3.7.** The first and last eligible frame of each scan track (and the only frame of a
single-frame track) are not scored. They keep identity and provenance, are not requested from the model, and are
removed from the coverage denominator. Why: 524 of 525 track-first frames were not comparable, and both laser edges
are synchronization anchors with a campaign-dependent timing offset (O11). Cost on the 16 calibration members: 1,712 of
18,020 eligible frames (9.5 %). Code: `lpbf.scored_frame_rule`.

**A23. Frame-level scoring with coverage.** Each frame is `SCORED` or `UNDEFINED_<reason>`. The objective uses scored
frames only; coverage = scored / (eligible − excluded by rule), reported per track, coupon and overall. A coupon below
**95 %** (`COVERAGE_FLOOR`) flags the candidate. The 1e12 penalty applies only to infrastructure failures and to a
coupon with no scored frames. Undefined frames are never set to zero; `NO_LASER_ASSOCIATED_MELT` is scored as zero
because it is a prediction (D1).

**A25. Window calibration contract (Patch 22.4.3.2).**
- Window: VED = P / (v · 0.080 mm · 0.030 mm) in **[65, 85] J/mm³**.
- Data roles: **calibration**, 9 members, 5 conditions (`20260730`, `20260731` parts 1, 3, 5, 6; `20260910` part 1;
  68.6–83.3 J/mm³); **in-window held out**, 5 members (`20260730`, `20260731` parts 2, 4; `20260904` part 5);
  **out of window, examined**, 7 members (`20260904` parts 1, 3, 4, 6; `20260910` parts 3, 4, 6); **out of window,
  blind**, 3 members (`20260904` part 2; `20260910` parts 2, 5).
- Search: the 17 A9 candidates × 9 members (153 units), a quadratic surrogate in coded coordinates, and at most 3
  guard-checked confirmation candidates. Selection is by lowest *measured* J, never by surrogate prediction.
- A selection at the box or guard edge is reported as a model limitation; the box is never widened.
- Caveats: eight of the nine calibration members lie on one P/v line (68.6–72.0 J/mm³), and the window was chosen
  after the O13 diagnostic.
- Plan: `docs/patches/22.4.3.2/PATCH_22_4_3_2_PLAN.md`.

**A26. Objective contract 22.4.3.2: log-ratio residuals.** Per scored frame, in camera pixels,
r_H = ln(max(H_sim, 1) / max(H_exp, 1)), r_W likewise, and f = 0.5·r_H² + 0.5·r_W². The 1 px floor keeps
`NO_LASER_ASSOCIATED_MELT` finite and heavily penalized; floored frames are counted. Aggregation is A10; coverage and
penalty rules are A23. Code: `lpbf.log_ratio_objective`.

**A27. The calibrated parameter set and its readings (Patch 22.4.3.2).**
- **Selected:** `confirm_c1`: t = −3 (absorptivity 0.490, deposition depth 0.098 mm), ck = 2.418, η = 0. Freeze:
  `docs/patches/22.4.3.2/evidence/selection_freeze.json` (SHA-256 `43184dff…92a8`). No code default was changed.
- **C_EDGE.** J 0.298, e_H 0.651, e_W 0.416. In the window, H is 1.7–2.0× and W 0.73–0.88× the camera's. t and η are
  at their bounds; the box was not widened. A probe below t = −3 was not run; the descriptive extrapolation
  (t ≈ −4.6, J ≈ 0.24, shape still about 2× too long) is a limitation.
- **V_PASS.** Held-out e_H and e_W are 1.03× and 1.02× their calibration values (`20260904:part_5`, from the other
  campaign, 1.15× and 0.92×).
- **X_PARTIAL.** Outside the window, Spearman(VED, median r_H) = 0.976 and Spearman(VED, median r_W) = 0.964; the W
  sign rule fails. Errors run from H 0.14× and W 0.18× at 41.7 J/mm³ (no pool on 54 % of frames) to H 2.98× and W
  1.20× at 125 J/mm³. The model's speed response is about 4× (W) and 9× (H) steeper than the camera's.
- **S (descriptive).** T₁₅₀ fixed on calibration at 1950 K (σ = 0) and 1825 K (σ = 2). In the window the synthetic
  pool is 0.2–0.7× the camera's; at low VED it falls below the coverage floor. No fixed operator follows the camera
  across VED.
- **Failure modes** (reported, not fixed): the speed response; the liquidus length excess; boiling-regulator overrun
  at high t; the unvalidated camera (A24); narrow-window identifiability; an optimum outside the box.
- Results: `docs/patches/22.4.3.2/PATCH_22_4_3_2_RESULTS.md`.

### Measurement interpretation

**A12. Experimental and simulated H/W are different measurement operators.** The camera's H/W comes from thresholding
coaxial optical intensity; the model's from the thermal liquidus contour. Synchronization matches image intensity to
laser activity, with manufacturer delays XY 0.000208 s and LDS 0.000103 s; residual timing error is possible,
especially at track starts and ends. The experimental system is described in the Satterlee dissertation (committee
draft, 2026; not distributed here).

**A24. The camera's H/W is an unvalidated optical measure.** Teledyne DALSA Genie Nano M640-NIR, coaxial, Mono8, 8000
fps, 40 µs exposure, threshold 150 on a 64 × 24 px crop. The scale of about 8 µm/px is a nominal optics value with no
calibration, and no independent width measurement exists. Calibration results therefore mean "calibrated to the
camera's H/W definition", not to the true melt-pool size. Scale-free results (ratios, process slopes) do not depend
on the 8 µm/px question. Evidence: `docs/patches/22.3.8/PATCH_22_3_8_FINDINGS.md`.

**A18. The Satterlee dissertation is a method reference**, not this project's process record. Its Table 4.1 process
matrix is a different, earlier campaign; this project's 24 coupons come only from A17.

**A15. Process-condition caveats.** Nominal spot diameter 0.08 mm. Process conditions are supplied from the record
(A17), not read from the HDF5 files.

### Historical entries (development steps; records not included here)

**A13.** Patch 22.3.5.1 diagnostic contract: all 568 observed fail-closed rows of an interrupted earlier campaign were
kept, never relabeled to an earlier count of 516.

**A14.** The recovery sequence: the 22.3.6 audit (census of residual association cases), then 22.3.7 (A21–A23).

## B. Superseded

- **S1.** The 22.3.3 integer-grid association rule (a diagonal neighbor at √2 cells was rejected). Replaced by A3.
- **S2.** Policy 22.3.3 and H/W semantics 22.3.4 as current.
- **S3.** The 516-row revalidation contract. Replaced by A13.
- **S4.** The original 272-unit campaign authorization and its resume instructions. Revoked.
- **S5.** An earlier objective wording, replaced by the A10 hierarchy.
- **S6.** The figure "92.1 % of failures at exactly √2", which belonged to the 516-row snapshot (90.0 % of 568).
- **S7.** Stale workflow notes in the development roadmap.
- **S8.** The one-cell continuous-distance association (A3) and the "remote melt is never zero" clause of A4.
  Replaced by A21 and D1.
- **S9.** All-or-nothing candidate failure. Replaced by A23: one undefined frame no longer disqualifies a candidate.
- **S10.** The 272-unit coarse campaign. Replaced by the window calibration (A25); the campaign code stays locked
  (`CAMPAIGN_DISPATCH_AUTHORIZED_BY` is `None`).
- **S11.** The pixel residuals of A10 as the calibration objective (with them the H misfit dominated). Replaced by
  A26; kept as a sensitivity.
- **S12.** The full-campaign checks of the original 22.4.3.2 plan and A11. Replaced by A25.

## C. Open and closed items

- **O1, O2 (open).** A 16-case reference-panel validation from Patch 22.3.4 was never confirmed as run and cannot be
  reached from the current tools. Not needed for the results here.
- **O3 (closed).** The 22.3.5.1 targeted replay of the 568 rows: 233 corrected, 335 still fail closed.
- **O4 (closed).** The frame-13768 regression for the continuous association rule passed.
- **O5 (closed).** The campaign code no longer authorizes itself: `run_search` and `_thermal_worker` raise
  `CampaignDispatchLocked`; `tests/test_patch22_3_5_2_campaign_dispatch_lock.py`.
- **O8 (closed).** The calibration energy-density window is [65, 85] J/mm³ (A25).
- **O11. The two acquisition campaigns use different sync-anchor conventions.** July (`0730`, `0731`): the first
  bright frame is pinned to the first laser-on row (431 of 431 tracks). September (`0904`, `0910`): it is pinned about
  10 rows before laser-on, so the first eligible frame lands a median 12 rows after laser-on, and the last eligible
  frame is pinned exactly 9 rows before the track end on 428 of 430 tracks (exceptions: `20260904:part_3` track 6 and
  `20260910:part_1` track 19). The only differing sync parameter is `selected_resample_factor` (1.1 vs 0.8). A
  campaign-dependent timing offset of about 50 µs (2–3 cells of travel) therefore exists at the anchors; whether it
  persists mid-track is not determined. Evidence: `docs/patches/22.3.6/PATCH_22_3_6_SYNC_AUDIT_FINDINGS.md` and its
  evidence CSV, which this entry corrects (428, not 430, of 430).
- **O12 (closed).** The one-cell rule of Patch 22.3.5 was a net loss (net +179 undefined frames); resolved by A21.
- **O13 (closed as a documented limitation).** The simulated pool length is about 3× the camera's. Patch 22.3.8 found
  that no synthetic-camera setting reproduces the camera's shape, sizes and trends (reading R-b), and that no point of
  the design box reproduces the camera on the four corner coupons (reading Q-b); the model's width and length fall
  with speed 3–9× faster than the camera's. With the camera unvalidated (A24), the mismatch cannot be assigned to the
  model alone. Response: calibrate in the 65–85 J/mm³ window with a balanced log-ratio objective (A25, A26).
  Evidence: `docs/patches/22.3.8/PATCH_22_3_8_FINDINGS.md`.
- **O14 (closed).** D3 decided.

## Changelog (condensed)

- 2026-10-13: Ledger created; process-parameter record fixed (A17); execution policy (A19).
- 2026-10-14: A20 (always compare) with D1–D3; the 22.3.6 census; Patch 22.3.7 implemented A21–A23 and passed its
  Stage A verification (10,100 of 10,100 frames exact).
- 2026-10-15: Patch 22.3.8 closed O13 (A24). The window calibration plan was approved (A25, A26).
- 2026-10-16: Patch 22.4.3.2 closed (A27): C_EDGE, V_PASS, X_PARTIAL, S descriptive. No production code, semantics or
  frozen core changed.
- 2026-10-19: Descriptive analyses added (committee package); O11 corrected to 428 of 430. No decision changes.
