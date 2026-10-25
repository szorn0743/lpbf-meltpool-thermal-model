# Patch 22.4.3.2 results: narrow-window calibration (65–85 J/mm³)

Status: **complete, 2026-10-16.** The owner reviewed readings V, X and S at plan stop 3 and said "Proceed."

- Plan: `PATCH_22_4_3_2_PLAN.md` (approved 2026-10-15), with the predeclared readings.
- Implementation, calibration, confirmation, the freeze and the owner's stop-2 decisions: `PATCH_22_4_3_2_IMPLEMENTATION.md`.
- Ledger: A25 (window contract), A26 (objective contract `22.4.3.2`), A27 (this result), A8 (held-out use).

**What the comparison means.** Every number below compares the model's liquidus H/W (or its synthetic-camera image)
with the coaxial camera's threshold-150 blob. The camera's dimensions are unvalidated (A24). "Calibrated" therefore
means calibrated to the camera's H/W definition, not to a measured melt-pool size. Ratios are simulated/camera.
Sizes in µm use the camera's nominal 8 µm/px.

## Summary

| Reading | Result | In one line |
|---|---|---|
| **C**, calibration | **C_EDGE** | Selected `confirm_c1` (t = −3, ck = 2.418, η = 0): J 0.298, e_H 0.651, e_W 0.416. H 1.7–2.0×, W 0.73–0.88×. The optimum sits on the box edge. |
| **V**, in-window validation | **V_PASS** | Held-out e_H and e_W are 1.03× and 1.02× their calibration values. The cross-campaign coupon alone also passes (1.15×, 0.92×). |
| **X**, outside the window | **X_PARTIAL** | Both residuals rise with VED (Spearman 0.976 for H, 0.964 for W). W's predeclared sign pattern fails at high VED, where W is close to 1 on two of four coupons. |
| **S**, synthetic camera | descriptive | Fixing T₁₅₀ by shape makes the synthetic pool 0.2–0.7× the camera's in the window. No fixed operator follows the camera across VED. |

**For the thesis.**
- Inside 65–85 J/mm³ the calibrated model predicts the camera's W at 0.73–0.88× and its H at 1.7–2.0×. This holds equally on held-out coupons and on the other campaign's coupon.
- Outside the window the error grows with distance in VED. The direction is set by the model's process response,
  which is steeper than the camera's:
  - at 41.7 J/mm³ the model loses its pool on 54 % of frames (H 0.14×);
  - at 125 J/mm³ H is 3.0× and W 1.2×.
- The calibration cannot remove the shape mismatch (H/W about 2.2–2.5× the camera's). That mismatch is what holds J
  at 0.30.

## 1. Runs and integrity

| Stage | Commit | Units | Wall time | Evidence |
|---|---|---|---|---|
| smoke | `78dc07d` | 1 | 354 s | `evidence/smoke/` |
| calibrate (17 A9 candidates × 9 members) | `78dc07d` | 153 | 21,364 s | `evidence/calibrate/` |
| confirm (c1, c2) | `ec53a55` | 18 | — | `evidence/confirm/` |
| freeze | `d01ac72` | — | — | `evidence/selection_freeze.json` |
| evaluate (E-set {c1, c2} × 15, c1 × 9 with fields) | `2fdc58c` | 39 | 8,318 s | `evidence/evaluate/` |
| synthetic camera (reading S, c1 fields) | `2fdc58c` (module `b2fd78a`) | 24 | 269 s | `evidence/synthetic/` |

All multi-unit stages ran on 4 Windows-spawn workers, on a clean worktree.

- **Evaluate.**
  - Rescoring c1 on the 9 calibration members reproduces the confirm units' frame records exactly
    (`calibration_records_reproduced: true`).
  - The 8 held-out members were read only in this stage, after the committed freeze and the owner's go-ahead
    (`held_out_used_after_committed_freeze_only: true`).
  - Semantics `22.3.7`, scored-frame rule `22.3.7`, objective contract `22.4.3.2`, beam-share floor 2 %, coverage
    floor 95 %, window 99 cells.
- **Synthetic camera.**
  - Its inputs are the evaluate manifest (sha256 `d4408c94…`), the coupon hashes the evaluate units read, and the
    field-file hashes, all checked.
  - Its camera measurements reproduce the committed Step-0 record for all 16 members that have one.
  - T₁₅₀ was fixed on the 9 calibration members only. The evaluation members were rendered at that T₁₅₀ alone.
    No thermal model run, no fitting.
- **Unchanged:** the frozen core and `docs/reference/LPBF_Process_Parameters.csv` (no diff since `patch-22.3.8`);
  production semantics. `CAMPAIGN_DISPATCH_AUTHORIZED_BY` is `None`, and the 272-unit campaign was not dispatched.
- The unit and field files (83 MB and 616 MB) stay in the gitignored `patch22_4_3_2_output/`. Their sha256 values
  are in the manifests.

## 2. Reading C: calibration (summary)

Details: implementation report §3–5.

- **Response surface.** Across the 17 design points, t dominates J. ck and η move it by a few per cent.
  - J falls with t, from 1.208 at t = +3 to 0.332 at t = −3, with small departures where ck and η differ.
  - Simulated H is too long everywhere, and lower t shortens it.
  - W falls below the camera's as t falls.
- **Surrogate.** R² 0.99948, leave-one-out RMSE 0.0299. The valley is flat along η (Hessian eigenvalue −0.0102;
  eigenvector almost pure η).
- **Selected `confirm_c1`.** t = −3 (absorptivity 0.490, deposition depth 0.098 mm), ck = 2.418, η = 0.
  - J 0.2981, e_H 0.651, e_W 0.416.
  - Coverage 1.0; 16 of 8,943 frames floored.
  - 3.4 % of frames peak above boiling.
- **Near-best and E-set:** {c1, `confirm_c2`}. c2 is at t = −3, ck = 2.370, η = 0.40, with J 0.3154.
- **C_EDGE.** t and η are at their bounds. The box was not widened (A9).
  - The owner declined a probe below t = −3; the extrapolation is in §6.6.

## 3. Reading V: in-window validation — **V_PASS**

Selected candidate c1. Each group is scored over its own conditions with the same hierarchy.

| Group | Coupons | Scored frames | Coverage | Frames without a predicted pool | e_H | e_W | J |
|---|---|---|---|---|---|---|---|
| Calibration | 9 | 8,943 | 1.000 | 16 | 0.651 | 0.416 | 0.298 |
| In-window held out | 5 | 4,796 | 1.000 | 11 | 0.672 | 0.423 | 0.315 |
| **Ratio, held out / calibration** | | | | | **1.03** | **1.02** | |
| `20260904:part_5` alone (other campaign) | 1 | 884 | 1.000 | 0 | 0.749 | 0.380 | 0.353 |
| **Ratio, part_5 / calibration** | | | | | **1.15** | **0.92** | |

Both ratios are ≤ 1.25, so **V_PASS**. `20260904:part_5` alone also passes.

Per held-out coupon (c1):

| Coupon | Condition | VED (J/mm³) | H ratio | W ratio | e_H | e_W | Frames without a pool |
|---|---|---|---|---|---|---|---|
| 20260730:part_2 | P150_V900 | 69.4 | 1.76 | 0.74 | 0.594 | 0.343 | 0 |
| 20260731:part_2 | P150_V900 | 69.4 | 1.76 | 0.75 | 0.612 | 0.397 | 6 |
| 20260730:part_4 | P170_V1000 | 70.8 | 1.71 | 0.73 | 0.549 | 0.344 | 0 |
| 20260731:part_4 | P170_V1000 | 70.8 | 1.68 | 0.74 | 0.747 | 0.624 | 5 |
| 20260904:part_5 | P180_V1000 | 75.0 | 2.03 | 0.81 | 0.749 | 0.380 | 0 |

**Near-best candidate c2 (descriptive).**
- Held-out e_H 0.697 and e_W 0.423, J 0.333; ratios 1.03 and 1.01 to its own calibration values. V_PASS.
- `20260904:part_5` alone: ratios 1.16 and 0.91.

**Reading.**
- The calibration transfers to held-out coupons in the window almost unchanged, and so does its bias.
- **Caveat (plan).** P150_V900 and P170_V1000 lie on the same P/v line as eight of the nine calibration members
  (68.6–72.0 J/mm³). Their validation is close to interpolation.
- `20260904:part_5` is off that line and comes from the other campaign (sync convention O11), so it is the
  informative test.
  - Its H is longer (2.03×) and its e_H 15 % higher, in line with the H ratio's rise with VED (§4).
- **Spread versus median.** `20260731:part_4` has an e_W of 0.624, against 0.344 for its replicate `20260730:part_4`,
  although the two have the same median W ratio. The difference is in the spread of W, not its median.

## 4. Reading X: outside the window — **X_PARTIAL**

Selected candidate c1 on the 10 out-of-window coupons, each at 100 % coverage. A frame without a predicted pool
(`NO_LASER_ASSOCIATED_MELT` or `ZERO_FOOTPRINT`) is scored as H = W = 0 (D1), floored at 1 px.

| Coupon | Group | P (W) | v (mm/s) | VED (J/mm³) | H ratio | W ratio | e_H | e_W | Frames without a pool | Peak > boiling |
|---|---|---|---|---|---|---|---|---|---|---|
| 20260904:part_3 | examined | 140 | 1400 | 41.7 | 0.14 | 0.18 | 1.563 | 1.368 | 347 of 648 | 0 % |
| 20260910:part_4 | examined | 140 | 1200 | 48.6 | 0.96 | 0.53 | 0.847 | 0.869 | 85 of 776 | 0 % |
| 20260904:part_6 | examined | 180 | 1400 | 53.6 | 1.28 | 0.64 | 0.637 | 0.646 | 22 of 657 | 11.3 % |
| 20260910:part_5 | blind | 160 | 1200 | 55.6 | 1.36 | 0.62 | 0.498 | 0.520 | 0 of 776 | 5.4 % |
| 20260904:part_2 | blind | 140 | 1000 | 58.3 | 1.35 | 0.68 | 0.472 | 0.463 | 1 of 936 | 0 % |
| 20260910:part_6 | examined | 180 | 1200 | 62.5 | 1.61 | 0.67 | 0.613 | 0.465 | 1 of 779 | 9.2 % |
| *calibration window* | | | | *65–85* | *1.69–1.96* | *0.72–0.88* | | | | |
| 20260910:part_2 | blind | 160 | 700 | 95.2 | 2.31 | 0.95 | 0.845 | 0.265 | 0 of 1,313 | 4.3 % |
| 20260904:part_1 | examined | 140 | 600 | 97.2 | 2.30 | 1.10 | 0.804 | 0.260 | 0 of 1,518 | 0.1 % |
| 20260910:part_3 | examined | 180 | 700 | 107.1 | 2.62 | 0.99 | 0.950 | 0.296 | 0 of 1,376 | 8.4 % |
| 20260904:part_4 | examined | 180 | 600 | 125.0 | 2.98 | 1.20 | 1.031 | 0.290 | 0 of 1,611 | 7.6 % |

| Group | Coupons | Scored frames | e_H | e_W | J | Spearman (VED, median r_H) | Spearman (VED, median r_W) |
|---|---|---|---|---|---|---|---|
| Examined | 7 | 7,365 | 0.968 | 0.707 | 0.718 | 1.00 | 0.96 |
| Blind | 3 | 3,025 | 0.629 | 0.430 | 0.290 | 0.5 | 1.0 |
| All 10 (predeclared) | 10 | 10,390 | | | | **0.976** | **0.964** |

The blind coupons sit at 55.6–95.2 J/mm³, nearer the window than most examined ones, which explains their lower
error. With n = 3 their rank correlations carry little information.

**Error map** (c1; H ratio / W ratio; VED in J/mm³ and role in brackets):

| 20260904 set | V600 | V1000 | V1400 |
|---|---|---|---|
| **P140** | 2.30 / 1.10 (97.2) | 1.35 / 0.68 (58.3, blind) | 0.14 / 0.18 (41.7) |
| **P180** | 2.98 / 1.20 (125.0) | 2.03 / 0.81 (75.0, in-window held out) | 1.28 / 0.64 (53.6) |

| 20260910 set | V700 | V1200 |
|---|---|---|
| **P140** | 1.96 / 0.88 (83.3, calibration) | 0.96 / 0.53 (48.6) |
| **P160** | 2.31 / 0.95 (95.2, blind) | 1.36 / 0.62 (55.6, blind) |
| **P180** | 2.62 / 0.99 (107.1) | 1.61 / 0.67 (62.5) |

The error is mostly a speed effect. At fixed power, going from the slowest to the fastest scan lowers the H ratio
by a factor of 1.6 (P180, 20260910) to 16 (P140, 20260904), and the W ratio by a factor of 1.5–6.

**Against the predeclared expectation.** The expectation was written from the 22.3.8 `anchor_center` liquidus
ratios: H rising from 2.17 to 4.95, W 0.84–0.95 below the window and 1.26–1.44 above it.

- **X2 (H rises with VED): holds.** ρ = 0.976. With c1, H runs from 0.14 at 41.7 J/mm³ to 2.98 at 125. That is
  lower than `anchor_center`'s 2.17–4.95, and steeper at the low end, where the pool vanishes.
- **X1 (W rises with VED, with a sign pattern): fails on the sign rule only.**
  - The rank correlation holds: ρ = 0.964.
  - All six coupons at ≤ 62.5 J/mm³ are under-predicted (W 0.18–0.68), as required.
  - Of the four at ≥ 95 J/mm³, two are over-predicted (`20260904:part_1` +10 %, `20260904:part_4` +20 %). Two are
    slightly under (`20260910:part_3` −1 %, `20260910:part_2` −5 %).
  - The trend is as expected, but the level is not. Calibrating to t = −3 lowered W by about a quarter compared
    with `anchor_center`, so the W ratio now crosses 1 inside the high-VED group instead of below it.
- **c2 (descriptive)** gives the same reading: identical ρ, and the same two sign failures (−2.5 % and −6.4 %).
  Its H ratios are up to 5 % higher.

**Process response** (descriptive, not predeclared).
- Method: least squares of log member medians on log P and log v over all 24 coupons, with 95 % bootstrap
  intervals over coupons (4,000 resamples). Model sizes use frames with a predicted pool.

| | log H on P | log H on v | log W on P | log W on v | log H/W on P | log H/W on v |
|---|---|---|---|---|---|---|
| Model liquidus, c1 | 2.46 [1.76, 3.09] | −1.44 [−1.87, −1.05] | 1.20 [1.07, 1.33] | −0.96 [−1.05, −0.90] | 1.26 [0.68, 1.86] | −0.48 [−0.88, −0.15] |
| Camera, threshold 150 | 0.84 [0.66, 1.05] | −0.16 [−0.28, −0.05] | 0.56 [0.38, 0.72] | −0.22 [−0.35, −0.10] | 0.28 [0.08, 0.53] | 0.06 [−0.10, 0.18] |
| Rosenthal point source (reference) | 1 | 0 | 0.5 | −0.5 | 0.5 | 0.5 |

- Without `20260904:part_3`, the model gives 2.10 and −1.23 for H and 1.19 and −0.96 for W. The camera gives 0.83
  and −0.15 for H and 0.49 and −0.17 for W.
- The model's width falls with speed about 4× faster than the camera's, and its length about 9× faster. This
  agrees with 22.3.8 Steps 3–4: the camera slopes match Step 0's 16-member values, and the speed excess is of the
  same size.
- **Ranges.** Model sizes: H 41–300 µm, W 30–88 µm. Camera sizes: H 72–107 µm, W 55–80 µm.

## 5. Reading S: synthetic camera (descriptive)

**T₁₅₀, fixed once on the 9 calibration members.** The rule is the 22.3.8 closest approach: the median
model/camera H/W at threshold 150 closest to 1, with coverage ≥ 95 %.

| Case | T₁₅₀ | Model/camera H/W at 150 | Coverage at 150 |
|---|---|---|---|
| 850 nm, uniform ε, σ = 0 | 1950 K | 1.03 | 0.981 |
| 850 nm, uniform ε, σ = 2.0 px | 1825 K | 1.07 | 0.971 |

These are lower than the dry run's 2375 K and 2175 K on `anchor_center` fields (implementation report §7), because
c1 is cooler.

**Scores, synthetic beside liquidus,** on the same c1 units. Each cell gives J, then e_H / e_W, then coverage.
⚑ = at least one coupon in the group is below the 95 % coverage floor. Those scores are reported but not
interpreted.

| Group | Liquidus | Synthetic, σ = 0 | Synthetic, σ = 2 |
|---|---|---|---|
| Calibration | 0.298 (0.651 / 0.416; 1.000) | 1.280 (1.103 / 1.159; 0.981) ⚑ | 0.760 (0.834 / 0.908; 0.971) ⚑ |
| In-window held out | 0.315 (0.672 / 0.423; 1.000) | 1.259 (1.072 / 1.170; 1.000) | 0.684 (0.784 / 0.868; 0.992) |
| 20260904:part_5 | 0.353 (0.749 / 0.380; 1.000) | 0.563 (0.694 / 0.802; 1.000) | 0.246 (0.462 / 0.527; 0.995) |
| Out of window, examined | 0.718 (0.968 / 0.707; 1.000) | 0.604 (0.785 / 0.770; 0.766) ⚑ | 0.369 (0.604 / 0.611; 0.745) ⚑ |
| Out of window, blind | 0.290 (0.629 / 0.430; 1.000) | 0.981 (1.026 / 0.953; 0.597) ⚑ | 0.233 (0.472 / 0.492; 0.544) ⚑ |

The calibration group is flagged only because the two P140_V850 coupons reach 88–92 % coverage. Pooled, it is at
97–98 %.

**In the window, the synthetic camera has the right shape but the wrong size.**
- Synthetic/camera H is 0.19–0.48 at σ = 0 and 0.27–0.71 at σ = 2; W is 0.18–0.46 and 0.24–0.70.
- The ratios rise with VED within the window, too: lowest at P140_V850 (68.6 J/mm³), highest at P180_V1000 and
  P140_V700 (75.0 and 83.3).
- The calibration-only dry run predicted this. Here the synthetic camera scores worse than the liquidus operator.

**Out of the window,** per coupon (synthetic H ratio / W ratio, coverage):

| Coupon | VED | σ = 0 | σ = 2 | Median frame peak | Frames with peak ≥ 1950 K |
|---|---|---|---|---|---|
| 20260904:part_3 | 41.7 | 1.08 / 1.31, 0.19 | 1.38 / 1.71, 0.21 | 1748 K | 19 % |
| 20260910:part_4 | 48.6 | 1.11 / 1.23, 0.19 | 1.46 / 1.62, 0.20 | 1832 K | 19 % |
| 20260904:part_6 | 53.6 | 0.20 / 0.20, 0.47 | 1.44 / 1.70, 0.25 | 1964 K | 53 % |
| 20260910:part_5 | 55.6 | 0.71 / 0.75, 0.35 | 1.44 / 1.52, 0.22 | 1949 K | 50 % |
| 20260904:part_2 | 58.3 | 0.90 / 1.00, 0.23 | 1.39 / 1.56, 0.18 | 1936 K | 40 % |
| 20260910:part_6 | 62.5 | 0.27 / 0.24, 0.72 | 0.35 / 0.33, 0.72 | 2060 K | 85 % |
| 20260910:part_2 | 95.2 | 0.67 / 0.63, 1.00 | 1.00 / 0.89, 1.00 | 2328 K | 100 % |
| 20260904:part_1 | 97.2 | 0.64 / 0.71, 1.00 | 0.93 / 1.00, 1.00 | 2274 K | 100 % |
| 20260910:part_3 | 107.1 | 0.83 / 0.70, 1.00 | 1.17 / 1.00, 0.99 | 2495 K | 100 % |
| 20260904:part_4 | 125.0 | 1.00 / 0.88, 1.00 | 1.42 / 1.22, 0.99 | 2643 K | 100 % |

**Low VED (≤ 62.5 J/mm³): the model's peak stays near or below T₁₅₀.**
- The synthetic camera then sees no blob, whereas the camera sees one in essentially every frame (1–6 camera-invalid
  frames per group).
- At σ = 0 the coverage stays at or below the share of frames whose peak reaches 1950 K. Blur lowers it further.
- The paired frames are the hottest subset, so their ratios are biased and not interpreted.

**High VED (≥ 95 J/mm³):** coverage is about 100 %, and the synthetic sizes come close to the camera's. They are
0.63–1.00 at σ = 0 and 0.89–1.42 at σ = 2.

**Rank correlations (descriptive).** Across the 10 out-of-window coupons the synthetic residuals correlate
negatively with VED: −0.21 (H) and −0.35 (W) at σ = 0, and −0.47 and −0.74 at σ = 2. The liquidus values are +0.98
and +0.96. The low-coverage coupons drive this, so it is not read as a trend.

**Reading.**
- A fixed T₁₅₀ can match the camera's shape at one energy density, or its size at another, but not both.
- Because the model's hot zone grows faster with VED than the camera's blob, the synthetic sizes cross the camera's
  near 95–125 J/mm³, just as the liquidus W does.
- An observation operator moves where the crossing lies; it does not change the process response.
- This agrees with 22.3.8's R-b: no synthetic-camera setting reproduces the camera's shape, sizes and trends.

**Sync diagnostic (descriptive).**
- For 7 of the 24 members, a few scored frames do not map back exactly to their process row through
  `data_to_gige_image_index`. The lowest shares are 95.8 % (`20260904:part_3`) and 97.3 % (`20260910:part_4`); the
  other five are ≥ 99.6 %.
- 22.3.8 Step 0 found the same 96–100 % on the calibration members.
- The liquidus scoring uses the same pairing, so this affects both operators equally.

## 6. Failure modes (for the thesis conclusion)

Each failure mode is drawn from existing evidence. The remedies are possibilities only; none is implemented
(owner's aim, 2026-10-15).

### 6.1 The model's speed response is steeper than the camera's

**Evidence.**
- The error map (§4): at fixed power, the H ratio falls by a factor of 1.6–16 from the slowest to the fastest scan.
- The process slopes (§4): the model's W falls with speed about 4× faster than the camera's, and its H about 9×
  faster.
- At 41.7 J/mm³ the model has no pool on 347 of 648 frames, while the camera sees a blob in every frame.
- 22.3.8 Step 4 (Q-b): no point of the A9 box comes within L = 1.59 at 1400 mm/s. Absorptivity, deposition depth
  and liquid conductivity do not change how the pool scales with speed.

**Unresolved.** The camera's width also scales unusually weakly: −0.22 with speed, against −0.5 for a Rosenthal
point source. It sits at or below the 80 µm spot (A24). The data cannot tell whether the model over-responds or the
camera under-responds.

**Possible remedies.**
- Data side, decisive: independent melt-pool widths at the corner conditions (20260904 parts 1, 3, 4, 6), from
  cross-sections or top-surface bead widths.
- Model side: if those widths follow the camera, the model needs an element whose effect depends on speed, which
  none of t, ck and η supplies.

### 6.2 Too long for its width: the liquidus tail against the camera's hot core

**Evidence.**
- In the window, c1 has H 1.7–2.0× and W 0.73–0.88×, so the simulated H/W is 2.2–2.5× the camera's.
- 22.3.8 Step 3: model liquidus H/W 3.2–4.8 against the camera's 1.18–1.40. At the width-matched isotherm, the
  model is 2.0× too long (pooled).
- Reading S (§5): matching the shape needs a T₁₅₀ where the synthetic pool is 0.2–0.7× the camera's size.
- This is the part of J the calibration cannot remove. Every design point is too long, and lowering t trades H
  against W without fixing the shape (§6.6).

**Possible remedies.**
- A radiometric calibration of the coaxial camera (a known-temperature target through the same optics), so that
  T₁₅₀ is measured rather than chosen.
- A measured pool length, for example from off-axis high-speed imaging, to show whether the liquidus tail exists.

### 6.3 Peaks overrun the fixed boiling regulator at high absorptivity

**Evidence.**
- Frames peaking above 3133 K: 5 % at t = −3 and 99 % at t = +3 (calibrate table).
- 22.3.8 Step 4: the candidates closest to the camera on the slow corners have median peaks 540–970 K above
  boiling.
- With c1: 3.4 % in calibration, 3.6 % in-window held out, and 0–11 % outside the window, highest at P = 180 W
  (7.6–11.3 %).
- The regulator is fixed (`quadratic_boiling_strength` = 0.5, `smoothstep_quadratic`, Patch 19.8.6) and is not
  calibratable.

**Consequence.** The high-t part of the box matches the camera at slow scans only at unphysical peak temperatures.
The calibration avoids it for its H error alone, but that region could not be read as physical in any case.

**Possible remedy.** A physically based evaporative and recoil-pressure heat loss in place of the fixed regulator,
validated against peak temperatures.

### 6.4 The camera's scale and definition are unvalidated (A24)

**Evidence.**
- 22.3.8 Gate 2 follow-up:
  - the nominal 8 µm/px has no calibration;
  - the H/W extraction script is not available;
  - the camera's author used the blob's minor axis as a spot-size proxy;
  - no independent widths exist locally.
- Here, camera W stays at 55–80 µm across 41.7–125 J/mm³.

**Consequence.**
- All readings are relative to the camera's definition.
- The scale-free results (shape, slopes, V ratios, rank correlations) do not depend on the pixel scale.
- Absolute size ratios do.

**Possible remedies:** an image of a scale target through the coaxial path, the extraction script and camera
configuration, and the independent widths of §6.1.

### 6.5 A narrow window limits identifiability

**Evidence.**
- Eight of the nine calibration members lie on one P/v line (68.6–72.0 J/mm³), so V is close to interpolation (§3).
- Only t is identified:
  - the surrogate is flat along η (eigenvalue −0.0102);
  - ck moves J by a few per cent.
- t couples absorptivity and deposition depth, so the window cannot separate them.
- The calibration does not transfer to other energy densities: e_H and e_W are 0.97 and 0.71 on the examined
  coupons, against 0.65 and 0.42 in calibration. The blind coupons, nearer the window, stay at 0.63 and 0.43.

**Possible remedies.**
- A calibration design that varies P and v independently, as the 20260904 and 20260910 grids do.
- A depth observable, such as cross-section depth, to separate absorptivity from deposition depth.
- Both are useful only together with §6.1.

### 6.6 The optimum lies outside the box

**Evidence.**
- C_EDGE: t and η are at their bounds, and J falls steadily as t falls.
- A descriptive extrapolation (implementation report §6) puts the best compromise near t ≈ −4.6 (absorptivity
  0.45, depth 0.111 mm). There, H ≈ 1.3×, W ≈ 0.63× and J ≈ 0.24.
- The shape stays about 2× too long there.
- Low-energy coupons would lose more of their pool. At t = −3, 20260904:part_3 already has none on 54 % of frames.

**Owner decision (2026-10-16).** "Keep as planned. No probe." The box was not widened, and no candidate outside it
was run.

**Consequence.** Lowering t further trades H error for W error and pool loss. It does not address §6.2, which limits
J.

## 7. Other limitations of this patch

- **Window choice.** The window was chosen after the O13 diagnostic, on the rationale that 75 J/mm³ is a typical
  LPBF operating point.
- **Small held-out groups.** Only `20260904:part_5` tests the window off the calibration line. The blind
  out-of-window group has 3 coupons.
- **Calibration members reused.** The 7 examined out-of-window coupons are A8 calibration members that Patch 22.3.8
  had already used. Only the 3 blind coupons are new outside the window.
- **Held-out data are now opened.** The 8 A8 held-out members have now been used in evaluation (A8). Any later
  fitting or selection that uses them would no longer be held-out validation.
- **Means and medians differ.** The objective uses means of squared log ratios. Condition-level mean and median log
  ratios can differ where the frame distribution has heavy tails. For example, on `20260904:part_5` the mean log W
  ratio is +0.03 while the median is −0.21.

## 8. Evidence

- `evidence/evaluate/`: `stage_manifest.json` (readings V and X, unit hashes, provenance) and `evaluate_console.log`.
- `evidence/synthetic/`:
  - `stage_manifest.json` (reading S, T₁₅₀, per-group and per-coupon scores, camera checks, provenance);
  - `synthetic_frames.csv.gz` (per-frame synthetic and camera H/W at the fixed T₁₅₀);
  - `synthetic_console.log`.
- Earlier stages: `evidence/smoke/`, `evidence/calibrate/`, `evidence/confirm/`, `evidence/pre_fix/`,
  `evidence/selection_freeze.json`, `evidence/calibration_reading.json`.
- The §4 process slopes, the c2 descriptive X values and the §5 peak-temperature columns come from the evaluate
  unit files, which stay in `patch22_4_3_2_output/evaluate/units/` with their hashes in the evaluate manifest.
