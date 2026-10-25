# Patch 22.4.3.2 plan: narrow-window calibration (65–85 J/mm³)

Status: **APPROVED by the owner, 2026-10-15.** The ledger changes in "Governance" are applied in the approval commit
(A25, A26, the A8 amendment, S10–S12, O8 closed).

## Context

- **Patch 22.3.8 closed O13** (tag `patch-22.3.8`) as a documented limitation:
  - no synthetic-camera setting and no point of the A9 box reproduces the camera;
  - the excess is the model's speed response;
  - the camera's dimensions are unvalidated (A24).
- **Owner, 2026-10-15:** the project is now a scientific analysis of the current model and a report of its results.
  - Calibrate inside a narrow, typical energy-density window.
  - Validate on held-out coupons in the window, then quantify error outside it.
  - It is acceptable if H does not fit; failure modes go into the thesis conclusion, not into production fixes.
- **Owner decisions at plan review (2026-10-15):**
  - a log-ratio objective with equal H and W weights;
  - the production liquidus operator, with the synthetic camera as a secondary result;
  - the full A9 box, with edge optima reported as limitations;
  - the 17-point design plus a quadratic surrogate and 1–3 confirmation candidates.

**What changes:**
- the calibration member scope (9 members);
- the objective's residual form (objective contract `22.4.3.2`);
- a new runner.

**What does not change:**
- association policy and H/W semantics `22.3.7` (liquidus, beam-power share);
- scored-frame rule `22.3.7`;
- the 95 % coverage floor and D1–D3;
- the A9 box, guard and 17-point design;
- the frozen core;
- the dispatch lock. `CAMPAIGN_DISPATCH_AUTHORIZED_BY` stays `None`, and the 272-unit `run_search` campaign stays
  locked and is superseded.

## Data roles (record A17, partition A8; VED = P / (v · 0.080 · 0.030))

| Role | Members | Conditions (VED, J/mm³) |
|---|---|---|
| **Calibration** (A8 calibration, in window), 9 | 20260730 and 20260731 parts 1, 3, 5, 6; 20260910 part 1 | P140 V850 (68.6), P160 V950 (70.2), P180 V1050 (71.4), P190 V1100 (72.0), P140 V700 (83.3) |
| **In-window held-out** (A8 held out, never opened), 5 | 20260730 and 20260731 parts 2, 4; 20260904 part 5 | P150 V900 (69.4), P170 V1000 (70.8), P180 V1000 (75.0) |
| **Out of window, examined** (A8 calibration, used in 22.3.8), 7 | 20260904 parts 1, 3, 4, 6; 20260910 parts 3, 4, 6 | 97.2, 41.7, 125.0, 53.6; 107.1, 48.6, 62.5 |
| **Out of window, blind** (A8 held out, never opened), 3 | 20260904 part 2; 20260910 parts 2, 5 | 58.3; 95.2, 55.6 |

The calibration members hold 8,943 scored frames, and none of their camera frames has zero size.

Caveats, stated in the results:
- Eight of the nine calibration members lie on one P/v line (68.6–72.0). In-window validation of P150 V900 and
  P170 V1000 is therefore close to interpolation.
- 20260904 part 5 comes from the other campaign (sync convention O11). It is the informative in-window test.
- The window was chosen after the O13 diagnostic, with the rationale that 75 J/mm³ sits in the typical LPBF operating
  range.

## Objective (contract `22.4.3.2`)

- **Per scored frame:**
  - r_H = ln(max(H_sim, 1) / max(H_exp, 1)) and r_W = ln(max(W_sim, 1) / max(W_exp, 1)), with H and W in camera pixels;
  - f = 0.5·r_H² + 0.5·r_W².
- **The 1 px floor (one camera pixel)** keeps `NO_LASER_ASSOCIATED_MELT` (D1, H = W = 0) finite and heavily
  penalized. Floored frames are counted and reported.
- **Aggregation:** the A10 hierarchy unchanged (frame → track → coupon → exact-condition replicate → unique
  condition). J is the value over the 5 calibration conditions. A23 coverage and flags are unchanged.
- **Also reported per candidate:**
  - the hierarchical log-RMS errors e_H = √(hierarchical mean of r_H²) and e_W, computed separately;
  - median H and W ratios per condition;
  - coverage, floored-frame count, and the fraction of frames peaking above boiling (3133 K).
- **Sensitivity (post-processing of the same runs; it never changes the selection):** H-only weights (1, 0), W-only
  weights (0, 1), and the 22.3.7 pixel objective (A10 scales 0.90 and 0.65 px).

## Search and selection

1. **Coarse.** The 17 frozen candidates (A9 design) × 9 members: 153 units, 4 spawn workers. At Step 4's throughput
   (about 7 frames/s) that is about 6 h.
2. **Surrogate.**
   - Least-squares quadratic of J in coded coordinates x = (t/3, (ck − 2)/0.5, (η − 0.5)/0.5): 10 coefficients from 17
     points. Report R² and the leave-one-out RMSE.
   - Minimize it over the box under the coupled guard, which is checked with `patch21_candidate_admissibility`. Use
     multi-start; the minimum may lie on the boundary.
3. **Confirmation** (at most 3 candidates × 9 members = 27 units):
   - c1 is the surrogate minimizer. It is not run if it lies within 0.05 coded units of a design point.
   - If the surrogate's Hessian has an eigenvalue ≤ 10 % of its largest (a flat valley), c2 and c3 lie along that
     eigenvector at the predicted 1.10 · J_min level. Both are clipped to the box and guard.
4. **Selection.** The lowest *measured* J among all evaluated candidates; the surrogate never selects by prediction.
   - **Near-best set:** measured J ≤ 1.10 · J_min.
   - **Ties:** the lower peak-above-boiling fraction wins.
5. **Edge rule.** The selected point is **edge** if any |x_i| ≥ 0.9 or the guard value is ≥ 0.9025 (95 % of the 0.95
   limit). That is reported as a model limitation, and the box is never widened.

## Freeze, then evaluation

- **Freeze.** After reading C, commit `selection_freeze.json`: the selected candidate, near-best set, J values,
  coordinates, git commit and input hashes. Then stop for the owner.
  - The runner refuses every held-out member unless the evaluation stage is requested *and* a committed freeze file
    with a matching hash exists.
  - The manifest records that no held-out member was read before the freeze.
- **Evaluation (after the owner's go-ahead):**
  - **E-set:** the selected candidate plus up to 2 further near-best candidates (lowest J, at least 0.2 coded units
    from the selected).
  - Each E-set candidate on the 5 in-window held-out and 10 out-of-window coupons (15 units each).
  - The selected candidate also re-runs on the 9 calibration members with field capture, for the secondary operator.
  - Field capture applies to the selected candidate only (24 units).
  - Estimated 2–3 h in total.

## Predeclared readings

**C, calibration** (descriptive; there is no pass or fail, since H misfit is accepted):
- Report J_min, the selected coordinates, the near-best set, the surrogate fit, and per-condition H and W ratios.
- Also report e_H, e_W, coverage, floored frames and peak-above-boiling for the selected candidate.
- The reading is **C-interior** or **C-edge**.

**V, in-window validation** (selected candidate):
- e_Q(held-out) is compared with e_Q(calibration) for Q ∈ {H, W}, each over its own conditions with the same hierarchy.
- **V-pass:** both ratios ≤ 1.25. **V-partial:** exactly one. **V-fail:** neither.
- 20260904 part 5 is also reported on its own (cross-campaign). The near-best candidates' V is descriptive.

**X, outside the window** (selected candidate, 10 coupons):
- Per coupon: the median signed r_H and r_W, and e_H and e_W. The blind (3) and examined (7) coupons are reported
  separately. The data are shown against P, v and VED.
- **Expectation, written before any 22.4.3.2 run, from the 22.3.8 Step 3 `anchor_center` liquidus ratios:**
  - On the seven examined coupons, H rises monotonically with VED, from 2.17 at 41.7 J/mm³ to 4.95 at 125.
  - W is 0.84–0.95 below the window and 1.26–1.44 above it.
  - Hence the expectation is that **the model over-responds to energy input**:
    - **X1:** median r_W rises with VED across the 10 coupons (Spearman ρ ≥ 0.6). W is over-predicted at ≥ 95 J/mm³
      and under-predicted at ≤ 62.5 J/mm³.
    - **X2:** median r_H rises with VED (Spearman ρ ≥ 0.6).
- **X-confirmed:** both hold. **X-partial:** one holds. **X-contradicted:** neither holds.

**S, secondary synthetic camera** (descriptive):
- Fixed settings: 850 nm, uniform ε, σ ∈ {0, 2.0} px.
- T₁₅₀ is fixed once, at the selected candidate's closest approach on the 9 calibration members (M1 at threshold 150
  with coverage ≥ 95 %). It is then applied unchanged to the held-out and out-of-window coupons.
- Reported: the synthetic H/W ratios and e_H, e_W per group, beside the liquidus operator.

## Results report (`PATCH_22_4_3_2_RESULTS.md`, for the thesis)

- Readings C, V, X and S, with tables and the out-of-window error map.
- **"Failure modes" section** from existing evidence, each with its evidence and a possible remedy (not implemented):
  - the model's speed response, steeper than the camera's (22.3.8 Step 4);
  - the length excess at the liquidus versus the camera's hot core (Steps 3–4);
  - peaks overrunning the fixed boiling regulator at high absorptivity;
  - the camera's unvalidated scale and definition (A24);
  - the identifiability limits of a narrow window.

## Implementation (code before data, after approval)

- **New `src/lpbf/patch22_4_3_2_window_calibration.py`,** modeled on `run_stage_a` (`src/lpbf/patch22_3_7_stage_a.py`)
  and the 22.3.8 runners:
  - `execute_serial_jobs` / `execute_parallel_jobs`, `--workers` default 4, parallel equals serial;
  - constants for the 9 members, 5 conditions and 153 units;
  - a confirmation-candidate schema, with the guard checked on every non-frozen candidate;
  - stages `calibrate`, `confirm`, `freeze`, `evaluate`, with a held-out refusal outside `evaluate`;
  - resume by `work_unit_id`; a manifest with provenance hashes;
  - field capture through the `patch22_3_8_field_capture` instrumentation for the evaluation runs.
- **Objective.** A log-ratio variant beside `src/lpbf/hierarchical_objective.py`, with its own contract version
  `22.4.3.2`. The 22.3.7 path stays bit-identical, and a regression test pins it.
- **Guard gap.** `run_stage_a` gains a held-out refusal (test first).
- **Tests:**
  - member and condition scope;
  - the hand-computed log-ratio objective and the 1 px floor;
  - the surrogate fit and constrained minimizer on a known quadratic;
  - guard rejection;
  - held-out refusal without a valid freeze;
  - parallel equals serial;
  - the existing objective unchanged.
- **Gate before the calibration run:**
  - Smoke unit `anchor_center × 20260730:part_1`: its frame records reproduce the 22.3.7 Stage A records bit for bit,
    and its 22.3.7 pixel objective matches.
  - Full suite; frozen core 8 of 8; lock `None`.

## Governance (ledger changes applied on approval)

- **A25 (new), the window calibration contract:**
  - window [65, 85] J/mm³;
  - the 9 calibration members and 5 conditions, the in-window held-out roles, and the out-of-window roles above.
  - This supersedes A9's "17 × 16 = 272 work units" scope for calibration; the A9 box, guard and design stay active.
- **A26 (new), objective contract `22.4.3.2`:**
  - log-ratio residuals with equal weights and a 1 px floor;
  - it supersedes A10's residual form and scales for calibration, while the A10 hierarchy stays;
  - the A10 pixel form is kept as a reported sensitivity.
- **A8:** held-out use is authorized in this patch only for evaluation after the freeze commit.
- **O8:** closed with [65, 85] J/mm³.
- **S-entries:**
  - the 272-unit campaign is superseded and stays locked;
  - the roadmap's Stage B 16/12/272 checks and A11 do not apply to this patch.
- **CLAUDE.md "Current state"** updated.

## Stops for the owner

1. Approval of this plan.
2. Reading C and the freeze, before any held-out member is opened.
3. Readings V, X and S. The results report follows.
