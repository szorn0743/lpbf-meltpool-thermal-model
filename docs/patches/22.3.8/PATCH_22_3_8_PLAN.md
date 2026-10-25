# Patch 22.3.8 plan: why simulated H is 2–5× the camera's (ledger O13)

Status: **diagnostic only.** Step 0 authorized by the owner on 2026-10-14. Later steps are provisional and are
revisited after each step; if a step contradicts the working hypothesis, work stops and the plan is reconsidered
with the owner. Findings are aggregated step by step in `PATCH_22_3_8_FINDINGS.md`.

This patch changes no association policy, H/W semantics, floor, scored-frame rule, objective, constant or version.
It fits and selects nothing, opens no held-out member's camera images, and dispatches no campaign. Step 0 runs no
thermal model.

Origin: the plan drafted after Patch 22.3.7 closed, revised after an Opus review on 2026-10-14 (outline-temperature
sweep replaced by a camera-first sequence and a synthetic-camera operator).

## Context

Patch 22.3.7 is closed. Median simulated H is 1.8–5.1× the camera's while W agrees (0.72–1.35×) (O13, re-measured
under 22.3.7). Remote melt is not the cause (A2; 91 % of Stage-A frames have a single liquid component and show the
same H ratio). The model's liquidus pool is a median 204 × 59 µm (H/W 3.4); the camera blob is a median 86 × 72 µm
(H/W 1.16–1.36 across conditions). The material is 316L (liquidus 1400 °C, boiling 2860 °C; the solver does not cap
temperature).

## Working hypothesis

**H-core.** The camera's threshold-150 blob images a saturated, optically blurred, beam-centred hot core. The camera
does not resolve the trailing liquid pool, so camera H is not a pool-length measurement.

**Alternative H-pool.** The camera does resolve the pool at some radiance level, and the model's tail is too long.

Physics prior (conduction-mode moving source, Rosenthal): trailing liquidus length ≈ AP/(2πkΔT), nearly independent
of speed; width ∝ √(P/v); so a resolved liquid pool has H/W rising with speed (log-log slope ≈ +0.5). For 316L at
140–190 W this length is roughly 150–800 µm depending on the conductivity taken; the model's 204 µm is plausible.

### What is already known (the Step-0 reading is not blind)

- Plan review spot check, 2026-10-14, `20260730` part 1 only (P140_V850, calibration), layers 52 and 53, the part's
  own ~1,200 frames per layer:
  - 99–100 % of lit frames contain saturated (255) pixels; ~55 % of the threshold-150 blob is saturated.
  - Thresholds 250 → 30 grow the blob from ~60 × 50 to ~150 × 128 µm; H/W stays 1.09–1.26.
  - The blob axis rotates with the hatch direction between layers (mirrored mapping), so camera H is along-scan.
  - The blob centroid is fixed in the crop: the camera is coaxial (its view moves with the beam), so a quasi-steady
    pool is not motion-smeared by the 40 µs exposure. (This corrects the review's proposed "smear vs v·τ" check.)
  - Stored H/W agree with a pixel-centre `findContours` + `minAreaRect` at ≥ 150 to a median 0.15 px.
- Disclosure: a first, discarded pass of that spot check pooled every lit frame of the 20260730 layer-53 file, which
  includes frames of held-out parts 2 and 4 (each file's `gige_image` covers the whole layer). It was descriptive
  only; nothing was fitted, selected or retained. The Patch 21.3 "all 18 conditions" camera summary quoted in the
  original plan likewise includes the six held-out conditions. From Step 0 on, only calibration members are used.

## Step 0: camera-side characterization (no thermal runs)

**Scope.** The 16 calibration members (12 conditions; Patch 21.0 contract `data_partition.calibration_members`).
`layer53` (production layer) for every criterion; `layer52` (adjacent layer, different hatch direction) only for the
direction test and as supplementary context. Held-out members are refused by code.

**Frames.** Scored frames under the production rules: synchronization-valid, laser-on, finite non-negative H/W, in a
scan track (Patch 21.3 eligibility), minus the first and last eligible frame of each track (A22). Frames are reached
only through the member's own `sync/gige_image_to_data_index`; other coupons' frames are never read. For `layer53`
the frame set must equal the Patch 21.3 characterization rows after the A22 rule, or the run fails closed.

**Measurements per scored frame** (camera convention: threshold `>=`, largest 8-connected component, its external
contour, `cv2.minAreaRect`, H ≥ W):
- peak value, saturated (255) pixel count, saturated fraction of the threshold-150 blob, background level;
- blob H, W, area and crop-edge contact at thresholds 30, 45, 60, 80, 100, 125, 150, 175, 200, 225, 250;
- threshold-150 blob centroid and principal-axis angle; scan direction from `X-Machine`/`Y-Machine`;
- recomputed vs stored H/W at 150 (convention check).

**Per member-layer:** medians and track-clustered bootstrap CIs; centroid spread; mean image; profiles through the
core along and across the blob axis (10–90 % edge widths, wing levels at 10–16 px); a pairwise radial asymmetry vector
(only directions whose opposite also lies inside the crop, so crop placement cannot bias it).

**Across members (layer53, threshold 150):** member-level regressions of log H, log W and log(H/W) on log P and
log v, with 95 % bootstrap CIs over members (2,000 replicates, seed 22038).

### Predeclared reading (fixed 2026-10-14, before the 16-member run)

Supports H-core (all on layer53):
- **S0 coaxial:** threshold-150 centroid IQR ≤ 1.5 px in x and in y, in every member.
- **S1 saturated:** in every member ≥ 90 % of blob-bearing scored frames contain a 255 pixel, and the median
  saturated fraction of the threshold-150 blob is ≥ 0.30.
- **S2 shape invariant:** in every member the median H/W at thresholds 60, 100, 150, 200 and 250 lies in [1.0, 1.5],
  and median H/W at 60 exceeds that at 150 by less than 0.25 (frames where neither blob touches the crop edge).
- **S3 no pool-like speed scaling:** the 95 % CI upper bound of the log(H/W)–log v slope (log P as covariate) is
  < 0.25.
- **S4 at most a faint wake:** the brighter-side wing level at 10–16 px is ≤ 15 % of full scale in every member.

Contradicts H-core (any one → stop and reconsider the plan with the owner):
- **C1:** S0 fails in ≥ 2 members (the camera is not beam-locked; motion smear matters).
- **C2:** ≥ 3 members have < 50 % of blob-bearing scored frames saturated (the blob edge is a genuine radiance level).
- **C3:** in any member, median H/W ≥ 1.8 at threshold 60 or 100 on frames without crop-edge contact (the camera
  resolves an elongated tail).
- **C4:** the 95 % CI of the log(H/W)–log v slope contains +0.5 (the blob scales like a liquid pool).
- **C5:** the radial asymmetry is fixed in image coordinates regardless of scan direction **and** its brighter-side
  wing exceeds 15 % of full scale (an optical ghost or flare the synthetic camera would have to model). Test (amended
  2026-10-14 before the 16-member run, see below): the machine-to-image mapping (mirrored or direct) is fitted on the
  blob axes; per member, the observed layer52 → layer53 rotation of the inner-band (5–8 px) asymmetry direction is
  compared with the mapped scan rotation ("follows") and with zero ("fixed"). C5 needs a median |scan rotation|
  ≥ 30° (otherwise not discriminating) and a median residual for "follows" that exceeds the one for "fixed" by
  > 15°.
  - Amendment: the first draft compared pooled resultant lengths ("fixed" exceeding "follows" by > 0.2). A unit test
    showed this cannot separate the hypotheses when the hatch rotates only ~45° between layers (both resultants
    ≈ 0.9), which is the case here. The paired per-member rotation test replaces it. No 16-member data had been
    run when it was changed.

Neither all-S nor any-C → **mixed**: reported as such, discussed with the owner before Step 1.

**Outputs.** `patch22_3_8_step0_output/` (gitignored); summary evidence copied to `evidence/step0/`.
Code: `src/lpbf/patch22_3_8_camera_step0.py`, tests `tests/test_patch22_3_8_camera_step0.py`.

## Later steps (provisional; revisited after Step 0)

Owner decisions after Step 0 (2026-10-14): proceed to Step 1; commit at every step boundary (Step 0 is commit
`669f2fd`); the layer-52 replay is deferred until after Step 3.

1. **Field capture + regression gate** (`src/lpbf/patch22_3_8_field_capture.py`, tests
   `tests/test_patch22_3_8_field_capture.py`). The unchanged Stage-A unit job (`_stage_a_unit_job`) runs inside
   `field_capture_instrumentation`, entered outside the production wrapper. At every scored frame it stores the full
   99 × 99 top-surface temperature field in **float64** (the liquid and selected-component masks are derived from it
   and the saved selected label), the beam cell, the source and heating centres, and the production status. Workers
   write nothing; the parent writes one deterministic compressed `.npz` per unit. Frozen core untouched.
   **Predeclared regression gate** (one real unit, `anchor_center × 20260730:part_1`, serial):
   - G1: requested = returned = captured frames, keyed 1:1 by the core's own frame→row mapping.
   - G2: frame statuses and simulated H/W bit-identical (repr) to that unit's rows in
     `docs/patches/22.3.7/evidence/PATCH_22_3_7_STAGE_A_FRAMES.csv`.
   - G3: re-measuring the saved fields (selector labelling + pristine contour measure) reproduces H/W bit for bit on
     every SELECTED frame, and the status on every other frame.
   - G4: captured source and heating centres equal the 22.3.6 census telemetry
     (`PATCH_22_3_6_ASSOCIATION_CENSUS_FRAMES.csv`) at the same process row.
   - G5: frozen-core hashes unchanged, `CAMPAIGN_DISPATCH_AUTHORIZED_BY` still `None`, full test suite passes.
   Any failure stops the patch for a report.
2. **Replay (calibration members only; A19, 4 workers), only after the Step-1 gate passes.** 24 units:
   `anchor_center` on all 16 calibration members (member-level slopes, as in Step 0); `anchor_t_min` and
   `anchor_t_max` on the four corners (20260904 parts 1, 3, 4, 6 = P140/P180 × V600/V1400). G1 and G3 on every unit;
   G2/G4 where references exist. Built on the Stage-A runner path (never `run_search` / `_thermal_worker`; dispatch
   lock unchanged). The Step-3 predeclared reading is written and approved by the owner before any Step-2 data is
   analysed.
3. **Offline analysis on the captured fields.** Predeclared reading below (written 2026-10-14 while the Step-2
   replay ran and before any of its data was opened; **approved by the owner 2026-10-14**, unchanged from the draft).
4. **Reading and records.** Findings section per step; O13 updated at patch close.

### Step 3 predeclared reading (approved by the owner 2026-10-14, before any Step-2 data was opened)

**Inputs.** Step-2 fields (layer 53, scored frames) matched frame by frame (`frame_index`) to the Step-0 camera
measurements of the same frames. Primary candidate `anchor_center` on 16 members; `anchor_t_min` / `anchor_t_max`
on the four corners are secondary (feasible sets reported, no criterion).

**P. Camera-free model physics (descriptive).** Per member: model liquidus H, W, H/W (production values), peak
surface temperature, fraction of frames whose peak exceeds boiling (3133 K). Member-level slopes of log H, log W,
log(H/W) on log P and log v (bootstrap over members), set against the Rosenthal reference (H ∝ P¹v⁰, W ∝ P^½v^−½,
H/W ∝ P^½v^½) and the Step-0 camera slopes.

**S. Synthetic camera.** Per frame:
1. Interpolate the model top-surface temperature bilinearly to a 4 µm grid and compute in-band radiance
   L = ε · B_λ(T) (Planck).
2. Average 2 × 2 to 8 µm pixels, rendered at the camera's orientation relative to the scan (Step-0 mirrored
   mapping).
3. Blur with a Gaussian PSF of σ (the optics blur radiance before the sensor saturates).
4. Scale so that the 150 level sits at temperature T₁₅₀, i.e. counts = 150 · (PSF ⊛ L) / (ε B_λ(T₁₅₀)), and clip at
   255.
5. Measure with the camera convention (`>=` threshold, largest 8-connected component, external contour,
   `minAreaRect`).

The one free scalar is T₁₅₀ (equivalent to the unknown gain). It is scanned over 1400–3200 K in 25 K steps and is
**global**: one value for all members of a candidate. Sensitivity cases:
- λ_eff ∈ {750, 850, 950} nm;
- σ ∈ {0, 1.0, 2.0, 2.6} px (2.6 px is the Step-0 bound);
- emissivity uniform, or ε_liquid/ε_solid = 0.5.

**Match criteria** (one case and one T₁₅₀, `anchor_center`; all must hold):
- **M1 shape.** At each threshold 60, 100, 150, 200, 250, the median over members of (model H/W ÷ camera H/W) lies
  in [0.87, 1.15].
- **M2 size.** At threshold 150, model/camera H and W (member medians) lie in [0.8, 1.25] for ≥ 12 of 16 members.
  T₁₅₀ alone can always set the pooled size at one threshold, so M2 is weak by construction; M3–M5 are not free.
- **M3 family spacing.** At thresholds 60 and 250, the pooled median model/camera W lies in [0.8, 1.25]. The
  spacing between levels is fixed by Planck, not by T₁₅₀.
- **M4 saturation.** The median saturated fraction of the synthetic threshold-150 blob is within ±0.15 of the
  camera's.
- **M5 trends.** At threshold 150, the paired member-bootstrap CI of (model − camera) slope contains 0 for log H and
  log W on both log P and log v.

**Reading.**
- **R-a: the synthetic camera reproduces the camera** (supports H-core, with model physics adequate near the beam).
  M1–M5 hold for some case and some T₁₅₀. O13 is then a measurement-definition mismatch: liquidus H is not comparable
  to camera H, and the synthetic camera is a candidate operator for a separate, versioned adoption patch.
- **R-b: the model's hot zone is too elongated → stop and reconsider with the owner.** No case and T₁₅₀ satisfies
  M1 at threshold 150 together with M2. This points to model physics (tail too long) or to unmodelled optics; it
  leads to Gate 2.
- **R-c: partial.** M1–M2 can be met but some of M3–M5 cannot. Report which, and discuss.
- Always reported:
  - the feasible T₁₅₀ interval per case and per candidate (if the camera's 150 contour has to sit below the liquidus,
    that is flagged);
  - how the feasible T₁₅₀ shifts between `anchor_t_min`, `anchor_center` and `anchor_t_max` (the trade-off against
    absorptivity);
  - no point estimate of T₁₅₀ is adopted.

**L. Level-free diagnostic (no free scalar).** Per frame, find the model isotherm whose W equals the camera's
threshold-150 W, and report the model H at that level ÷ camera H (member medians and the pooled distribution).

**Implementation clarifications** (`src/lpbf/patch22_3_8_synthetic_camera.py`, fixed 2026-10-14 after approval and
before any Step-2 data was opened; no criterion, band or grid changed):
- *Orientation.* Step-0 mirrored mapping, image angle = 29.68° − machine angle. The full-circle sign is set by the wake
  (212° from the mapped motion), so the tail points opposite the motion. The beam sits at a pixel centre of a
  192 × 192 px render, which leaves room for the crop when the hot zone extends far behind the beam.
- *Crop.* The camera convention includes the camera's 64 × 24 crop. Per frame and T₁₅₀, the crop is placed so that the
  synthetic threshold-150 centroid sits at that frame's camera centroid (the member median if the camera has none).
  A synthetic blob that touches the crop edge, or contains a pixel sampled outside the model window, is "edge" and
  excluded, exactly as camera edge frames are. A blob whose crop cannot be placed inside the render also counts as
  edge.
- *Pairing and coverage.* At each threshold, a frame is paired when the camera blob exists without touching the crop
  edge and the synthetic blob exists without edge. A criterion at a threshold holds only if the synthetic coverage at
  that threshold (paired ÷ camera-valid frames, pooled over the candidate's members) is ≥ 95 %. This applies the A23
  floor to the synthetic observable.
- *Statistics.*
  - Member values are medians over paired frames, and member ratios are ratios of member medians (model ÷ camera,
    same frames).
  - M1 and M4 take the median over members.
  - M3's pooled value is the median, over all paired frames, of the per-frame ratio model W ÷ camera W.
  - M5 regresses log(model member median) − log(camera member median) on [1, log P, log v], with 2000 member-bootstrap
    replicates, seed 22038 (the Step-0 draws), and percentile CIs.
- *M4.* The synthetic saturated fraction is the fraction of the threshold-150 blob's pixels at or above the 255 level.
- *Emissivity case.* ε = 0.5 above the liquidus and 1 below; T₁₅₀ is defined with ε(T₁₅₀).
- *PSF.* Gaussian, truncated at 4σ, zero outside the render, applied to the 8 µm radiance image before the 150 and 255
  levels are applied.
- *Reading logic.*
  - R-a: some grid point passes M1 (all five thresholds), M2, M3, M4 and M5.
  - R-b: no grid point passes M1 at 150 together with M2 (each with coverage).
  - R-c: otherwise.
  - Per case, the T₁₅₀ at which the median model/camera H/W at 150 is closest to 1 is reported as descriptive only,
    never adopted.
- *Corners (secondary).* "Core" there means M1 at 150 and M2 with ≥ 3 of 4 members. M1 at the other thresholds, M3 and
  M4 are reported; M5 is not computed (4 members).
- *L.* Temperature image (sub-sample mean, camera orientation, no PSF, no crop) on frames whose camera threshold-150
  blob does not touch the crop edge. Bisection (30 iterations, floor 800 K) finds the highest isotherm whose
  camera-convention W reaches the camera's threshold-150 W. Reported: model H there ÷ camera H, and that isotherm's
  temperature against the liquidus.
- *P.* Production liquidus H/W from the Step-2 unit records (SELECTED frames, member medians); peak = maximum of the
  captured top-surface field.
- *Inputs.*
  - The Step-0 frame table (`patch22_3_8_step0_output/step0_frames.csv.gz`, gitignored; its SHA256 goes into the Step-3
    manifest) must reproduce the committed Step-0 member summaries (frame counts, median H and W at 150), or the run
    stops.
  - The Step-2 capture gate must be PASS, and every field file must match its manifest SHA256.

**Gate 2 (if needed, decided before any search).** Keep the A9 box; flag winners at a bound; report H, W, H/W
separately; options include declaring camera H uninformative and scoring on W or a synthetic-camera observable, as a
versioned owner decision.

**If an operator is ever adopted (separate patch):** bump `PRODUCTION_HW_SEMANTICS_VERSION` and
`PRODUCTION_SEMANTICS_ID` (`POLICY_VERSION` only if selection changes); move the `"22.3.7"` pins in the 22.4.1 / 22.4.3
gates and tests; define the new outcomes (nothing above the camera level, several hot sub-components, enclosure);
repeat the Stage-A gate with a new output root; regenerate the frame-13768 and 99-cell references. A free gain is a
fourth calibration coordinate: add it to the design (changes A9) or fix it by a declared procedure before 22.4.3.2.

## Step 4: sensitivity map over the frozen design (owner decision 2026-10-14)

Step 3 read R-b. At Gate 2 the owner chose option 1: test whether settings inside the A9 box reproduce the camera's
shape and process response before any change to what calibration compares.

**Question.** Does any point of the A9 box (t ∈ [−3, 3], ck ∈ [1.5, 2.5], η ∈ [0, 1], coupled guard) bring the model's
hot zone to the camera's shape, or does the excess persist across the box?

**Replay** (`python -m lpbf.patch22_3_8_field_capture --preset step4`, 4 workers, about 4 h):
- Units: the 14 frozen-design candidates not yet replayed (`anchor_low_ck_high_eta`, `anchor_transport_guard_edge` and
  `halton_01`–`halton_12`), each on the four corners, 56 units. The corners are 20260904 parts 1, 3, 4 and 6 (P140_V600,
  P140_V1400, P180_V600, P180_V1400), a 2 × 2 factorial in P and v.
- With Step 2's three candidates on the corners, all 17 design points are covered (68 units). The design points are
  used as fixed probes: nothing is ranked for calibration, fitted or selected, and no point outside the frozen design
  is run.
- Same capture and gate: G1, G3 and G5 on every unit (no Stage-A or census reference exists for these units). Output
  root `patch22_3_8_capture_output/step4/`.

### Step 4 predeclared reading (written 2026-10-14 before the replay; approved by the owner 2026-10-14 before any Step-4 data was opened)

**Per candidate, on the four corners:**
- **L** (level-free, as in Step 3): member-median H ratio at the width-matched isotherm, then the median of the four
  members. The isotherm temperature is also reported.
- **S-core** (synthetic camera, as in Step 3):
  - Cases: 850 nm, uniform ε, σ ∈ {0, 1.0, 2.0, 2.6} px. In Step 3, wavelength and emissivity moved the closest approach
    by at most 0.02 in H/W ratio.
  - T₁₅₀ grid: 1400–3200 K in 25 K steps.
  - "Core" means: M1 at threshold 150 in [0.87, 1.15], M2 for ≥ 3 of 4 members, and synthetic coverage ≥ 95 % at 150.
  - Also reported: M1 at all five thresholds, M3, M4, and the closest approach per case.
- **Trends** (2 × 2, descriptive): least-squares slopes of log H and log W on log P and log v from the four members, for
  - the model liquidus (production values),
  - the synthetic camera at threshold 150 at each case's closest-approach T₁₅₀,
  - the camera on the same corners (Step-0 frame table, member medians at 150).
- **Peaks:** the fraction of frames above 3133 K.

**Reading.**
- **Q-a: the box reaches the camera.** At least one candidate meets S-core (some case, some T₁₅₀) and has an L median in
  [0.87, 1.15]. Next, as an owner decision: check that candidate on all 16 members against the full Step-3 criteria.
  That is evidence that camera H is matchable inside the box, not a selection.
- **Q-b: the box does not reach the camera.** No candidate meets S-core, and every candidate's L median lies outside
  [0.87, 1.15]. The A9 box cannot reproduce the camera's shape, which goes to the owner at Gate 2: score W only, or a
  model-structure question beyond the box.
- **Q-c: partial.** Exactly one of the two holds; report it and discuss.
- **Always reported** (descriptive, no selection):
  - how log(L median) responds to t, ck and η across the 17 candidates (least squares on the three coordinates);
  - the closest candidates;
  - peak temperatures.
- **Consistency check:** the three Step-2 candidates must reproduce their Step-3 corner L medians (2.45, 2.62 and 1.38)
  to within 0.01; otherwise the analysis stops.
- **Owner addition at approval (descriptive, from existing outputs):** per candidate, the corner "shape gap" before and
  after the synthetic camera: liquidus H/W ÷ camera H/W, and synthetic H/W ÷ camera H/W at each case's closest
  approach.

**Implementation** (`src/lpbf/patch22_3_8_sensitivity.py`, committed before the replay finished; it reuses the Step-3
functions unchanged, with a case subset):
- `python -m lpbf.patch22_3_8_sensitivity --workers 4` reads the Step-2 and Step-4 capture roots. It refuses a failed
  gate, a duplicate or missing unit, a field-file hash mismatch, or a camera table that disagrees with the Step-0
  evidence.
- "Core" is counted per candidate over 4 cases × 73 T₁₅₀.
- The L median is the median of the four member medians.
- Q-a requires both conditions on the same candidate.

## Open questions for the owner

- Independent width or length measurements (XCT, cross-sections, track images) for these coupons? Model W (59 µm)
  and camera W (72 µm) are both below the 80 µm hatch.
- The data_processing script that produced the stored camera H/W (exact convention).
- Provenance of 8 µm/px (object-plane calibration, not sensor pitch).

**Status 2026-10-15 (Gate 2 after Step 4, the owner chose option (c), camera-side evidence first).** See the findings,
"Gate 2 follow-up".
- No independent widths exist locally. The Basler post-scan images do not resolve tracks, and XCT does not show fusion
  boundaries.
- The H/W script is not on this PC; the source archive `E:/Past_prints/xctv16/` is not attached.
- The draft gives 8 µm/px as a nominal optics value with no calibration, and it does not validate the camera's
  dimensions.

All three questions above remain open and need the lab: corner cross-sections or top-surface microscopy, the script,
and the camera configuration.
