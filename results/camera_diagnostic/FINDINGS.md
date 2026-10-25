# Patch 22.3.8 findings (aggregated by step)

Plan and predeclared readings: `PATCH_22_3_8_PLAN.md`. Each step adds a section; earlier sections are not rewritten
except to mark a statement superseded by a later step.

## Step 0: camera-side characterization (2026-10-14)

**Run.** `python -m lpbf.patch22_3_8_camera_step0` at commit `df4493a` plus the uncommitted Step-0 files (plan
SHA256 `417f7574…e25b`, recorded in the manifest), 65 s, serial (no thermal work units). 16 calibration members,
`layer53` and `layer52`. Layer 53: 16,308 scored frames, equal to the A22 calibration count (18,020 eligible −
1,712 excluded); for every member the frame set equals the Patch 21.3 rows after the A22 rule. Layer 52: 16,716
scored frames. No held-out member was opened, no other coupon's frame was read, no thermal model was run, nothing
was fitted or selected. Evidence: `evidence/step0/`.

### Predeclared reading: **MIXED** (no contradiction)

| Criterion | Result | Value (layer 53 unless noted) |
|---|---|---|
| S0 coaxial (centroid IQR ≤ 1.5 px) | holds | IQR x 0.64–0.89 px, y 0.48–0.79 px (layer 52 ≤ 1.22) |
| S1 saturated (≥ 90 % frames; ≥ 0.30 of blob) | holds | 99–100 % of frames; 46–59 % of the 150-blob at 255 |
| S2 shape invariant | holds | median H/W at 60–250 within 1.16–1.43; rise 60 vs 150 ≤ 0.02 median |
| S3 no pool-like speed scaling (CI upper < 0.25) | holds | log(H/W)–log v slope 0.03 [−0.15, 0.17] |
| S4 faint wake (≤ 15 % of full scale) | **fails narrowly** | wing at 10–16 px 0.08–0.18; > 0.15 only P180_V700 (0.18), ≈ 0.15 at P190_V1100 |
| C1 not beam-locked | no | 0 members fail S0 |
| C2 unsaturated | no | 0 members < 50 % |
| C3 resolved tail (H/W ≥ 1.8 at 60/100) | no | max 1.42 |
| C4 pool-like speed scaling (CI ∋ 0.5) | no | CI [−0.15, 0.17] |
| C5 image-fixed strong asymmetry | no (borderline) | "fixed" preferred by 13° (trigger 15°); 5 of 16 members closer to "follows" |

### Results

1. **Beam-locked, saturated core.** The blob centroid sits at the same crop position in every frame (coaxial camera;
   a quasi-steady pool is not motion-smeared). Almost every frame is saturated; about half the threshold-150 blob is
   at 255. Only 3 of 16,308 scored frames have no pixel ≥ 150.
2. **Round at every level.** Camera H/W at 150 is 1.18–1.40 per member; across thresholds 30–250 the member medians
   stay at 1.29–1.35. H and W grow together as the threshold falls (threshold 30: 175 × 130 µm; 250: 68 × 54 µm).
3. **The blob responds to power (not predeclared as a criterion).** Member-level regressions at threshold 150,
   95 % bootstrap CIs:
   - log H: P slope **0.93** [0.65, 1.21], v slope −0.16 [−0.35, −0.00]
   - log W: P slope **0.55** [0.33, 0.74], v slope −0.21 [−0.37, −0.07]
   - log(H/W): P slope 0.24 [0.01, 0.54], v slope 0.03 [−0.15, 0.17]
   - Rosenthal liquid-pool reference: H ∝ P¹v⁰, W ∝ P^½ v^−½, H/W ∝ P^½ v^½.
4. **A faint one-sided wake.** Along the blob axis one side decays more slowly: 10–90 % edge width 8.1–12.0 px
   against 6.2–7.7 px on the other side; the slow side holds 8–18 % of full scale at 80–128 µm from the core,
   strongest at 180–190 W.
5. **It follows the scan.** The blob axis rotates with the hatch direction between layers through a mirrored
   machine-to-image mapping (axial resultant 0.89 vs 0.16 for a direct mapping). The predeclared inner-band (5–8 px)
   asymmetry vector was inconclusive (C5 borderline, above). **Post hoc (exploratory, not predeclared):** rotating
   each member's layer-52 mean image onto its layer-53 mean image over levels 8–150, the best rotation is +30° to
   +60° in 13 of 16 members (median +37.5°); scan-following predicts +45°, image-fixed 0°. The exceptions are the two
   V600 members (+10°, +15°). The wake is physical, not an optical ghost. Script and output:
   `evidence/step0/posthoc/`.
6. **Optical blur is bounded.** Across-scan 10–90 % edge widths are 4.8–6.8 px (38–54 µm), which include the
   thermal gradient; for a Gaussian PSF this bounds σ at about 2.6 px (21 µm) or less.
7. **Layer dependence (unexplained).** The same members have H/W 1.10–1.25 on layer 52 (scan along the crop's
   24-px axis) against 1.18–1.40 on layer 53. Either an image-fixed anisotropy (optics) adds to the scan elongation
   on one layer and partly cancels it on the other, or the difference is physical (hatch direction and track length
   relative to the part). Production scores layer 53 only.
8. **Measurement convention.** Recomputing H/W from the frame (`>= 150`, largest 8-connected component, external
   contour, `minAreaRect`) gives a median difference of 0.00 px from the stored values for H and W, but only 52–80 %
   (H) and 61–90 % (W) of frames agree within 0.5 px; 96–100 % of mapped rows map back to the same frame. The stored
   values follow the same convention but are not always computed from exactly the frame at hand. The script that
   produced them is still needed (open question).

### Interpretation

- **Supported.** The threshold-150 blob is a beam-locked, saturated hot zone. It shows no elongated tail at any
  threshold the camera offers, and its aspect ratio does not scale with speed.
- **Revised.** Two statements in the original plan and review do not hold:
  - "The blob is about spot sized and nearly independent of process conditions" / "the camera probably cannot see
    the trailing liquid at all": camera H scales as P^0.93 and W as P^0.55, and a faint scan-following wake is
    visible at low levels. The blob is a thermal signal that responds to the process; it is not the laser spot.
    This weakens the Gate-2 option "declare camera H uninformative".
  - The review said a pool-resolving camera would show H/W rising strongly at low thresholds. With NIR radiance
    rising roughly as T⁸–T¹⁰ near these temperatures (Wien, ~850 nm), thresholds 30–250 span only about ±12 % in
    temperature, over which a Rosenthal isotherm's H/W changes by only ~10–15 %. S2 is therefore weak evidence either way.
- **Not decided by Step 0.** The alternative H-pool (the 150 contour is close to the liquidus and the real pool is
  short and round) is not excluded: without a radiometric calibration the temperature at the 150 contour is unknown.
  What does discriminate is (i) the absolute aspect ratio (model liquidus 3.4 vs camera ≈ 1.3 at every level) and
  (ii) the speed scaling (a high-Péclet isotherm has H/W ∝ √v; the camera shows none). Whether the model's hotter
  isotherms, or a synthetic-camera image of the model, reproduce H/W ≈ 1.3, H ∝ P^0.9 and flat speed scaling is the
  Step-3 question, and Step 0 now supplies its targets.

### Consequences for the plan (for owner discussion)

- Step 3 targets: per-member camera family (11 thresholds) and the slopes above, with their CIs.
- Synthetic camera: start with an isotropic PSF of σ ≤ 2.6 px; carry an anisotropic PSF as a sensitivity case
  because of the layer difference.
- Step 2 sample: all 12 calibration conditions are needed to compare slopes (camera slope CIs are about ±0.3).
  Optional: replay layer 52 for a few members to test whether the model reproduces the layer difference (physical)
  or not (optical); this needs runner support for a second layer.
- Gate 2: "camera H is uninformative" is no longer the likely outcome; the comparison should move to a matched
  observable rather than drop H.

Owner decisions (2026-10-14): proceed to Step 1; commit at each step boundary (Step 0 = `669f2fd`); layer-52 replay
deferred until after Step 3.

## Step 1: field capture and regression gate (2026-10-14)

**What was built.** `src/lpbf/patch22_3_8_field_capture.py` runs the unchanged Patch 22.3.7 Stage-A unit job inside
`field_capture_instrumentation` (entered outside the production wrapper, as the 22.3.6 census was). At every scored
frame it stores the full 99 × 99 top-surface temperature field (float64), the beam cell, the source and heating
centres and the production association outcome. Workers write nothing; the parent writes one deterministic,
compressed `.npz` per unit (27 MB for this unit). 19 synthetic tests cover nesting, copying, seam restoration,
fail-closed keying, held-out refusal, deterministic storage, parallel = serial and the round trip. Suite: 184 passed.

**Live gate: `PASS_PATCH_22_3_8_FIELD_CAPTURE_GATE`.** Unit `anchor_center × 20260730:part_1`, serial, 603 s, code
`3f57e8f5…` on commit `669f2fd` + Step-1 files, plan SHA256 `9ac559c0…3254` (gate predeclared there before it was
evaluated).

| Gate | Result |
|---|---|
| G1 counts | 1,056 requested = returned = captured; no Stage-A or capture failures |
| G2 vs Stage-A evidence | 1,162 of 1,162 rows (1,056 scored + 106 rule-excluded) bit-identical; 0 mismatches |
| G3 round trip | 1,056 of 1,056 SELECTED frames re-measure bit for bit from the saved fields |
| G4 vs 22.3.6 census | 1,056 source and heating centres identical (max difference 0.0 mm) |
| G5 integrity | frozen core 8 of 8 hashes match; `CAMPAIGN_DISPATCH_AUTHORIZED_BY` = `None`; suite passes |

The capture changes nothing in production, and the saved fields are the fields production measured. Evidence:
`evidence/step1/` (gate, manifest, console log); the field file stays in the gitignored
`patch22_3_8_capture_output/step1/`.

## Step 2: replay on the calibration members (2026-10-14)

**Run.** `python -m lpbf.patch22_3_8_field_capture --preset step2 --workers 4`, 4 spawn workers, 6,029 s. Capture
module SHA256 `3f57e8f5…`, the bytes committed in `f430906` (unchanged since Step 1). The manifest records the commit
`2d45b0d` and plan SHA256 `c40e1bbf…` because it is written when the run ends. The Step-3 code and the plan
clarifications were committed while the replay ran; neither touches the capture path. 24 units:
- `anchor_center` on all 16 calibration members;
- `anchor_t_min` and `anchor_t_max` on the four corners (20260904 parts 1, 3, 4, 6).

No held-out member, no `run_search` / `_thermal_worker`, dispatch lock unchanged.

**Gate: `PASS_PATCH_22_3_8_FIELD_CAPTURE_GATE`** on every unit.

| Gate | Result |
|---|---|
| G1 counts | 25,176 frames requested = returned = captured; no Stage-A or capture failures. `anchor_center` holds 16,308 frames, equal to the A22 calibration count |
| G2 vs Stage-A evidence (where it exists) | `anchor_center × 20260730:part_1`: 1,162 of 1,162 rows bit-identical; `× 20260730:part_3`: 1,071 of 1,071 |
| G3 round trip | 24,802 of 24,802 SELECTED frames re-measure bit for bit; status reproduced on the other 374; 0 mismatches |
| G4 vs 22.3.6 census (where it exists) | the same two units: 1,056 and 964 source centres identical (max difference 0.0 mm) |
| G5 integrity | frozen core 8 of 8; `CAMPAIGN_DISPATCH_AUTHORIZED_BY` = `None`; suite 211 passed |

No Step-2 field was analysed before the Step-3 reading was approved (`b9a69da`) and the Step-3 code was committed
(`2d45b0d`). Evidence: `evidence/step2/` (gate, manifest, console log). The 24 field files (667 MB) stay in the
gitignored `patch22_3_8_capture_output/step2/fields/`, with their SHA256 in the manifest.

## Step 3: synthetic camera, physics and level-free check (2026-10-14)

**Run.** `python -m lpbf.patch22_3_8_synthetic_camera --workers 4`, 4 spawn workers, 3,353 s, clean worktree at
`421fe34` (module SHA256 `35a54825…` = commit `2d45b0d`; plan SHA256 `c40e1bbf…`, the approved reading plus the
implementation clarifications). Inputs: the 24 Step-2 field files (hashes checked against the Step-2 manifest) and the
Step-0 frame table, which reproduced the committed Step-0 member summaries for all 16 members. Offline only: no
thermal model, no held-out member, no parameter adopted. Evidence: `evidence/step3/` (verdict, grid of all 1,752
`anchor_center` points plus the three corner scopes, physics, level-free summary and frames, manifest, console log).

### Predeclared reading: **R-b, stop and reconsider**

For `anchor_center` on 16 members, no case (3 wavelengths × 2 emissivity models × 4 PSFs) and no T₁₅₀ in
1400–3200 K satisfies M1 at threshold 150 together with M2.

| Criterion | Grid points passing (of 1,752) |
|---|---|
| M1 at 150 (shape) | 0 |
| M1 at all five thresholds | 0 |
| M2 (sizes, ≥ 12 of 16 members) | 0 |
| M3 (family spacing) | 0 |
| M4 (saturation) | 111 |
| M5 (P and v trends) | 0 |

None of the three candidates on the four corners has a point that meets the core criteria.

**Robustness to the coverage floor** (an implementation clarification, not part of the approved text). Without any
coverage requirement, only 4 of 1,752 points meet M1 at 150 and M2. At those points (σ = 2 px, T₁₅₀ = 2500–2550 K)
the synthetic camera sees a blob in only 34–38 % of the frames where the camera sees one. The reading does not
depend on the floor.

### Results

1. **Where the synthetic camera sees the frames, the model's hot zone is too elongated.**
   - Synthetic coverage at threshold 150 is ≥ 95 % only for T₁₅₀ ≈ 1800–2150 K (maximum 0.98).
   - Below that, the synthetic blobs run off the camera's 64 × 24 crop. At T₁₅₀ = 1400–1600 K only 10–18 % of frames
     are usable, whereas the camera's own blobs touch the crop edge in ≤ 9 % of frames even at threshold 60.
   - Above that, the cooler frames show nothing (coverage 0.58 at 2600 K).
   - Inside the usable window, with σ ≤ 1 px, the median model/camera H/W at 150 is ≥ 1.27 in every case; the closest
     approach is 1.27–1.30 at T₁₅₀ = 2000–2100 K. The ratio falls toward 1 only where coverage collapses.
2. **Blur helps the shape but not the sizes.**
   - With σ = 2.0–2.6 px (the Step-0 upper bound), at T₁₅₀ ≈ 2000 K the median model/camera H/W is 1.03–1.12 at 150
     and the family spacing matches (M3 W ratios 0.86–1.10).
   - But coverage is only 0.90–0.93, and only 7 of 16 members have both H and W within ±25 % (M2 needs 12).
3. **The process response differs.** No grid point has the model's P and v slopes within the camera's (M5). Camera-free
   (P, production liquidus values, member medians, 95 % bootstrap CIs):

   | | model P slope | model v slope | camera P / v (Step 0) | Rosenthal P / v |
   |---|---|---|---|---|
   | log H | 1.66 [1.39, 1.89] | −0.79 [−0.96, −0.65] | 0.93 / −0.16 | 1 / 0 |
   | log W | 0.85 [0.79, 0.90] | −0.76 [−0.78, −0.72] | 0.55 / −0.21 | 0.5 / −0.5 |
   | log H/W | 0.82 [0.60, 1.04] | −0.05 [−0.21, 0.07] | 0.24 / 0.03 | 0.5 / 0.5 |

   - Model liquidus: H 156–475 µm, W 47–112 µm, H/W 3.2–4.8.
   - Camera at threshold 150: H 72–107 µm, W 56–80 µm, H/W 1.18–1.40.
   - The model's width spans a range 2.4× wider than the camera's.
4. **Level-free check (L, no free scalar).** At the model isotherm whose width equals the camera's threshold-150
   width:
   - model H is **2.0×** camera H (pooled median; quartiles 1.27 and 4.94; 16,244 of 16,299 frames defined);
   - the median over members is **3.6×**.
   - For the 12 members with v ≥ 850 mm/s or P = 140 W at V1200–1400, the width-matched isotherm sits at 1560–1670 K,
     at or just below the liquidus (1673 K), and the model is 2.7–5.3× too long there.
   - For the four V600/V700 members it sits at 1830–2190 K, and the excess is 1.1–1.7×.
   - On the corners the median member ratio is 2.45 (`anchor_t_min`), 2.62 (`anchor_center`) and 1.38
     (`anchor_t_max`). The absorptivity/depth coordinate t moves the excess, but the corners alone do not remove it.
5. **Peak temperatures.** 27 % of `anchor_center` frames peak above boiling (3133 K). Most members are at 5–17 %, but
   20260910:part_3 (P180_V700) is at 89 % and 20260904:part_4 (P180_V600) at 100 %, with median peaks of 3208 K and
   3391 K. *Corrected 2026-10-14 (superseded wording: "the model has no evaporation limit"):* the model has a
   fixed quadratic boiling regulator (`quadratic_boiling_strength` = 0.5, `smoothstep_quadratic`, Patch 19.8.6, not
   calibratable). It does not hold the peak at or below 3133 K at these conditions.

### Interpretation

- **Ruled out:** a measurement-definition mismatch with adequate model physics (R-a). One global camera gain, under
  any of the 24 optics cases, does not turn the model's fields into the camera's blobs. Adopting a synthetic-camera
  operator would therefore not close O13 on its own.
- **Not explained by the pixel scale.** The shape mismatch (H/W) and the slope mismatch are scale-free, so the open
  8 µm/px question cannot explain them; it could only shift sizes.
- **Points to the model's hot zone.** It is longer for its width and grows more steeply with power and slower scans
  than anything the camera shows. The L result locates the excess near the liquidus for most conditions. This is the
  plan's "model physics (tail too long) or unmodelled optics" branch. The optics side is constrained:
  - Step 0 bounds an isotropic PSF at σ ≤ 2.6 px, and the camera's across-scan edges include the thermal gradient.
  - An image-fixed anisotropic PSF was not among the approved cases. It could not fix the trend mismatch (M5), which
    no PSF changes.
- **Open on the camera side:** the script that produced the stored H/W, the 8 µm/px provenance, and any independent
  width or length data. Layer 52 (deferred) is less informative now that R-b holds on layer 53.

Per the plan, Step 3 stops here for the owner (Gate 2). Nothing is adopted and no parameter is selected.

## Step 4: sensitivity map over the A9 box (2026-10-14)

### Replay and capture gate

**Run.** `python -m lpbf.patch22_3_8_field_capture --preset step4 --workers 4`, 4 spawn workers, 8,711 s. Capture
module SHA256 `116a82ab…`, the bytes committed in `a0703ef` (the `step4` preset; capture path unchanged since Step 1).
The manifest records commit `09327ef` (Step-4 reading approved) and a clean worktree. 56 units: the 14 frozen-design
candidates not replayed in Step 2 (`anchor_low_ck_high_eta`, `anchor_transport_guard_edge`, `halton_01` … `halton_12`)
on the four corners (20260904 parts 1, 3, 4, 6). No held-out member, no `run_search` / `_thermal_worker`, dispatch lock
unchanged.

**Gate: `PASS_PATCH_22_3_8_FIELD_CAPTURE_GATE`** on every unit.

| Gate | Result |
|---|---|
| G1 counts | 62,076 frames requested = returned = captured; no Stage-A or capture failures |
| G2, G4 | not applicable (no Stage-A or census evidence exists for these units) |
| G3 round trip | 61,540 of 61,540 SELECTED frames re-measure bit for bit; status reproduced on the other 536; 0 mismatches |
| G5 integrity | frozen core 8 of 8; `CAMPAIGN_DISPATCH_AUTHORIZED_BY` = `None`; suite 224 passed |

The 536 non-selected frames are all on 20260904:part_3 (P140_V1400, the lowest-energy corner) and all belong to
candidates with t < 0 (lower absorptivity, deeper deposition). They are model predictions, not failures:
`NO_LASER_ASSOCIATED_MELT`, scored H = W = 0 under decision D1, plus one `ZERO_FOOTPRINT`.

| Candidate | t | ck | η | Scored part_3 frames without laser-associated melt |
|---|---|---|---|---|
| `halton_04` | −2.25 | 1.94 | 0.80 | 250 + 1 zero footprint of 648 |
| `halton_11` | −1.875 | 1.65 | 0.48 | 165 of 648 |
| `halton_02` | −1.5 | 2.17 | 0.40 | 86 of 648 |
| `halton_09` | −1.125 | 1.87 | 0.08 | 27 of 648 |
| `halton_06` | −0.75 | 1.72 | 0.24 | 7 of 648 |

The console shows 18 unenclosed-contour warnings (NaN, never zero), against 11 in Step 2. Evidence: `evidence/step4/`
(gate, manifest, console log). The 56 field files (1.7 GB) stay in the gitignored
`patch22_3_8_capture_output/step4/fields/`, with their SHA256 in the manifest.

### Analysis run

**Run.** `python -m lpbf.patch22_3_8_sensitivity --workers 4`, 4 spawn workers, 2,198 s, clean worktree at `0b20bad`
(module SHA256 `a6a64320…` and synthetic-camera module `854c8011…`, both the bytes of `f823d8b`; plan SHA256
`1488b85b…`, the approved reading of `09327ef`). Inputs: the 68 corner field files (Step 2's three candidates and
Step 4's fourteen), with hashes checked against both capture manifests, and the Step-0 frame table, checked against the
Step-0 evidence. Offline only: no thermal model, no held-out member, nothing fitted, ranked for calibration or selected.
Evidence: `evidence/step4/` (verdict, candidates, candidate detail, grid of 4,964 points, level-free frames, manifest,
console log).

**Consistency check: pass.** The three Step-2 candidates reproduce their Step-3 corner L medians exactly: `anchor_center`
2.6159, `anchor_t_min` 2.4524, `anchor_t_max` 1.3788 (difference 0.0; tolerance 0.01).

### Predeclared reading: **Q-b, the box does not reach the camera**

- **S-core:** no candidate meets it. That is 0 of 4,964 grid points (17 candidates × 4 cases × 73 T₁₅₀).
- **L:** no candidate's L median lies in [0.87, 1.15]; the medians range from 1.38 to 2.77.

| S-core condition (each with synthetic coverage ≥ 95 % at threshold 150) | Grid points (of 4,964) |
|---|---|
| Coverage ≥ 95 % at 150 | 103, on 9 candidates (none with t < 0) |
| M1 at 150 in [0.87, 1.15] (shape) | 8 (`anchor_t_max` 7, `halton_07` 1) |
| M2, ≥ 3 of 4 members with H and W within ±25 % (sizes) | 0 |
| S-core (M1 at 150 and M2) | 0 |

**Robustness to the coverage floor** (descriptive, the same check as Step 3).
- Without any coverage requirement, 43 of 4,964 points meet M1 at 150 and M2. They are spread over all 17 candidates,
  at coverage 0.76–0.91.
- Four candidates come closest. At these points the synthetic camera sees a blob in 89–91 % of the frames where the
  camera does:

  | Candidate | σ (px) | T₁₅₀ (K) | M1 at 150 |
  |---|---|---|---|
  | `anchor_t_max` | 0 and 1 | 2575–2725 | 1.02–1.07 |
  | `halton_07` | 0 | 2500–2525 | 1.08 |
  | `halton_10` | 0 | 2400–2425 | 1.03–1.05 |
  | `halton_05` | 0 | 2200 | 0.95 |

- None of the 43 points also meets M3 (family spacing) or M4 (saturation).
- So the floor decides between Q-b and Q-c: without it, S-core would be met while every L median stays outside the band.
  It does not decide Q-a, which neither version reaches.

### Results

1. **The excess is a speed effect.** Per-corner L is the member-median H ratio at the width-matched isotherm, with the
   isotherm's median temperature in brackets:

   | Candidate | t | ck | η | L part_1 (P140 V600) | L part_4 (P180 V600) | L part_3 (P140 V1400) | L part_6 (P180 V1400) | L median | Isotherm median (K) | Frames > 3133 K |
   |---|---|---|---|---|---|---|---|---|---|---|
   | `anchor_t_max` | 3 | 2.00 | 0.50 | 1.00 (2579 K) | 1.17 (2617 K) | 1.59 (1950 K) | 2.00 (1988 K) | **1.38** | 2534 | 82 % |
   | `halton_10` | 1.875 | 2.20 | 0.28 | 0.99 (2373 K) | 1.12 (2444 K) | 1.75 (1775 K) | 2.09 (1802 K) | **1.44** | 2350 | 76 % |
   | `halton_07` | 2.25 | 2.06 | 0.44 | 1.00 (2443 K) | 1.17 (2501 K) | 1.75 (1823 K) | 2.10 (1857 K) | **1.46** | 2412 | 76 % |
   | `halton_03` | 1.5 | 1.61 | 0.60 | 1.13 (2340 K) | 1.41 (2378 K) | 1.95 (1744 K) | 2.68 (1741 K) | **1.68** | 2306 | 76 % |
   | `halton_12` | 1.125 | 1.98 | 0.68 | 1.07 (2247 K) | 1.27 (2333 K) | 2.10 (1699 K) | 2.87 (1694 K) | **1.69** | 2220 | 59 % |
   | `halton_05` | 0.75 | 2.28 | 0.04 | 0.93 (2199 K) | 1.10 (2305 K) | 2.28 (1677 K) | 3.67 (1670 K) | **1.69** | 2188 | 45 % |
   | `halton_02` | −1.5 | 2.17 | 0.40 | 1.22 (1864 K) | 1.31 (1976 K) | 3.48 (1474 K) | 4.73 (1439 K) | **2.40** | 1863 | 10 % |
   | `halton_04` | −2.25 | 1.94 | 0.80 | 1.58 (1768 K) | 1.65 (1881 K) | 3.23 (1404 K) | 4.57 (1375 K) | **2.44** | 1770 | 8 % |
   | `anchor_t_min` | −3 | 2.00 | 0.50 | 1.90 (1696 K) | 1.82 (1796 K) | 3.01 (1343 K) | 4.41 (1326 K) | **2.45** | 1698 | 6 % |
   | `halton_09` | −1.125 | 1.87 | 0.08 | 1.18 (1930 K) | 1.33 (2046 K) | 3.65 (1506 K) | 4.82 (1472 K) | **2.49** | 1931 | 39 % |
   | `halton_11` | −1.875 | 1.65 | 0.48 | 1.50 (1823 K) | 1.65 (1944 K) | 3.40 (1438 K) | 4.69 (1406 K) | **2.53** | 1823 | 12 % |
   | `anchor_transport_guard_edge` | 0 | 2.50 | 0.40 | 1.00 (2064 K) | 1.14 (2174 K) | 3.93 (1606 K) | 4.90 (1613 K) | **2.54** | 2055 | 43 % |
   | `halton_06` | −0.75 | 1.72 | 0.24 | 1.20 (1979 K) | 1.41 (2094 K) | 3.79 (1536 K) | 4.97 (1527 K) | **2.60** | 1979 | 44 % |
   | `anchor_center` | 0 | 2.00 | 0.50 | 1.09 (2073 K) | 1.29 (2191 K) | 3.95 (1604 K) | 5.02 (1620 K) | **2.62** | 2062 | 44 % |
   | `halton_01` | 0 | 1.83 | 0.20 | 1.10 (2090 K) | 1.31 (2214 K) | 3.93 (1606 K) | 5.01 (1618 K) | **2.62** | 2082 | 45 % |
   | `halton_08` | 0.375 | 1.54 | 0.84 | 1.23 (2134 K) | 1.54 (2227 K) | 3.77 (1647 K) | 4.73 (1662 K) | **2.65** | 2122 | 51 % |
   | `anchor_low_ck_high_eta` | 0 | 1.50 | 1.00 | 1.31 (2070 K) | 1.58 (2178 K) | 3.96 (1601 K) | 5.16 (1627 K) | **2.77** | 2062 | 46 % |

   - **Slow corners (600 mm/s).** Much of the box comes close: 9 of 17 candidates have L ≤ 1.31 on both slow corners.
     Three of them (`halton_05`, `halton_10`, `anchor_transport_guard_edge`) have both in [0.87, 1.15].
   - **Fast corners (1400 mm/s).** No candidate gets below L = 1.59 (`anchor_t_max`, part_3). For t ≤ 0 the values are
     3.0–5.2.
   - **Why the fast corners fail.** For t ≤ 0.75, the model's hot zone at 1400 mm/s is narrower than the camera's blob at
     every temperature above about the liquidus. The width-matched isotherm therefore sits at 1326–1677 K, where the
     model's tail is long.
   - **The L median mixes the two regimes.** It is the mean of the second and third member values, so one slow and one
     fast corner. This is why it is not monotonic in t:
     - lowering t worsens the slow corners (`anchor_t_min`: 1.82–1.90);
     - lowering t also shrinks the fast-corner excess (3.01–4.41, against 3.95–5.02 at t = 0);
     - the result is `anchor_t_min` 2.45 < `anchor_center` 2.62.
2. **Response of the excess to t, ck and η** (descriptive least squares across the 17 candidates):
   log L = 1.145 − 0.114 t − 0.208 ck + 0.042 η, R² = 0.66.
   - Across the box, t moves L by a factor of 0.50 over its 6 units, ck by 0.81 over its range, and η by 1.04.
   - The fitted surface is lowest at the unsampled corner t = +3, ck = 2.5, η = 0, where it gives L ≈ 1.33. That is still
     outside the band.
   - This is an extrapolation of a linear fit with R² 0.66, not a prediction. The corner's admissibility under the
     coupled guard was not checked.
   - The closest candidates by L median: `anchor_t_max` 1.38, `halton_10` 1.44, `halton_07` 1.46, `halton_03` 1.68,
     `halton_12` 1.69. All have t ≥ 1.1.
3. **Synthetic camera: shape and size need different calibrations.**
   - Only candidates with t ≥ 0 ever reach 95 % coverage (9 of the 11). With t < 0, coverage at 150 peaks at 0.89–0.93.
     Their part_3 frames without laser-associated melt (see the gate section) and small fast-corner hot spots show no
     synthetic blob.
   - Blur shrinks the usable window further. At σ = 2 px only `anchor_t_max` reaches 95 % coverage, and at σ = 2.6 px no
     candidate does.
   - Wherever coverage reaches 95 %, at most 1 of 4 members matches in size, so no covered point meets M2. M1 at 150
     passes at 8 covered points (T₁₅₀ 2150–2525 K).
   - Sizes on 3 of 4 members need a different T₁₅₀ (2200–2725 K for the four closest candidates). There coverage falls to
     ≤ 0.91, consistent with the coolest corner's peak falling below the level. For `anchor_t_max`, the median peak on
     part_3 is 2666 K against T₁₅₀ = 2700 K.
4. **Shape gap before and after the synthetic camera** (owner's addition, descriptive).
   - The comparison values:
     - Camera H/W at 150 (Step 0, member medians): part_1 1.375, part_4 1.30, part_3 1.375, part_6 1.333.
     - "Liquidus ÷ camera": the member-median production liquidus H/W divided by the camera's, per corner. On part_3 of the
       t < 0 candidates it covers only the frames with a laser-associated melt.
     - "Synthetic ÷ camera": M1 at threshold 150 at each case's closest approach, the pooled median of the per-frame ratio.
       "—" means no T₁₅₀ reaches 95 % coverage in that case.
   - "Share removed" = 1 − ln(synthetic ratio) / ln(liquidus median ratio).

   | Candidate | Liquidus ÷ camera H/W: part_1 / part_4 / part_3 / part_6 | median | Synthetic ÷ camera at closest approach, σ = 0 (T₁₅₀) | σ = 1 | σ = 2 | Share of the log gap removed (σ = 0) |
   |---|---|---|---|---|---|---|
   | `anchor_t_max` | 3.04 / 3.54 / 3.40 / 4.22 | **3.47** | 1.12 (2525 K) | 1.13 (2350 K) | 1.12 (2200 K) | 91 % |
   | `halton_10` | 2.82 / 3.33 / 2.95 / 3.74 | **3.14** | 1.19 (2200 K) | 1.17 (2150 K) | — | 85 % |
   | `halton_07` | 2.94 / 3.46 / 3.13 / 3.97 | **3.30** | 1.15 (2350 K) | 1.17 (2200 K) | — | 89 % |
   | `halton_03` | 3.05 / 3.64 / 3.09 / 4.00 | **3.37** | 1.33 (2200 K) | 1.43 (2075 K) | — | 77 % |
   | `halton_12` | 2.91 / 3.48 / 2.84 / 3.67 | **3.19** | 1.32 (2075 K) | 1.41 (1975 K) | — | 76 % |
   | `halton_05` | 2.61 / 3.12 / 2.53 / 3.28 | **2.86** | 1.18 (2025 K) | 1.28 (1925 K) | — | 84 % |
   | `halton_02` | 2.45 / 3.02 / 1.65 / 2.69 | **2.57** | — | — | — | — |
   | `halton_04` | 2.49 / 3.09 / 1.00 / 2.43 | **2.46** | — | — | — | — |
   | `anchor_t_min` | 2.31 / 2.86 / 0.78 / 2.10 | **2.20** | — | — | — | — |
   | `halton_09` | 2.47 / 3.04 / 1.85 / 2.84 | **2.66** | — | — | — | — |
   | `halton_11` | 2.53 / 3.16 / 1.26 / 2.64 | **2.59** | — | — | — | — |
   | `anchor_transport_guard_edge` | 2.61 / 3.12 / 2.25 / 3.06 | **2.84** | 1.28 (1900 K) | — | — | 76 % |
   | `halton_06` | 2.62 / 3.21 / 2.06 / 3.06 | **2.84** | — | — | — | — |
   | `anchor_center` | 2.73 / 3.29 / 2.35 / 3.25 | **2.99** | 1.47 (1875 K) | — | — | 65 % |
   | `halton_01` | 2.68 / 3.26 / 2.34 / 3.25 | **2.97** | 1.50 (1875 K) | — | — | 63 % |
   | `halton_08` | 2.99 / 3.62 / 2.67 / 3.63 | **3.31** | — | — | — | — |
   | `anchor_low_ck_high_eta` | 2.98 / 3.63 / 2.50 / 3.54 | **3.26** | — | — | — | — |

   - **Liquidus.** The liquidus gap is 2.2–3.5×. It is largest for the high-t candidates, which are the ones closest
     to the camera by L: more absorbed power lengthens the liquidus tail even as it brings the hot core closer to the
     camera's shape.
   - **Synthetic camera.** Where it applies (9 candidates), it removes 63–91 % of the log gap. `anchor_t_max` falls from
     3.47 to 1.12, `anchor_center` from 2.99 to 1.47.
5. **Process response across the box** (2 × 2 slopes on log P and log v, descriptive):

   | | log H on P | log H on v | log W on P | log W on v |
   |---|---|---|---|---|
   | Camera, corners (Step 0, threshold 150) | 0.57 | −0.17 | 0.70 | −0.20 |
   | Model liquidus, 17 candidates | 1.22 to 2.91 | −0.44 to −1.56 | 0.64 to 1.12 | −0.63 to −0.91 |
   | Synthetic camera at closest approach (16 candidate-cases) | 2.11 to 2.81 | −1.01 to −1.31 | 1.19 to 2.29 | −0.83 to −1.23 |
   | Rosenthal point source (reference) | 1 | 0 | 0.5 | −0.5 |

   - No point in the box brings the speed response near the camera's. The model's width falls 3.2–4.6× faster with speed,
     and its liquidus length 2.6–9× faster.
   - Only the liquidus W-on-P slope of the high-t candidates (0.64–0.73) is near the camera's.
6. **Peaks.** The share of frames peaking above boiling (3133 K) ranges from 6 % (`anchor_t_min`) to 82 %
   (`anchor_t_max`).
   - On part_4 (P180 V600), every candidate with t ≥ −0.75 peaks above boiling on 98–100 % of frames.
   - With t ≥ 1.5 the same holds on part_1 (P140 V600). `anchor_t_max` has median peaks of 3669 K (part_1) and
     4107 K (part_4).
   - So the candidates closest to the camera are those where the fixed boiling regulator is overrun the most: median
     peaks 540–970 K above boiling. That weighs against reading their closeness as physical.

### Interpretation

- **Answer to the Step-4 question.** Within the A9 box and the approved optics cases, no setting reproduces the
  camera on the four corners. The H excess persists across the box (Q-b). Together with Step 3 (R-b), the O13 mismatch is
  not a matter of where calibration lands inside the box.
- **What the box can and cannot do.**
  - Much of it matches the camera at 600 mm/s, and the high-t end of the box nearly matches shape and size jointly on about 90 %
    of frames.
  - None of it matches at 1400 mm/s.
  - The residual is the model's speed response. Its pool narrows and shortens with speed several times faster than the
    camera's blob.
  - The camera's width falls with speed more slowly (−0.20) than even a Rosenthal point source (−0.5). Absorptivity,
    deposition depth and liquid conductivity, the knobs this box offers, do not change that kind of scaling. Only t
    reduces the excess appreciably, and at the cost of peaks far above boiling.
- **Open, and decisive:** does the camera's threshold-150 blob width track the melt-pool width at 1400 mm/s? One
  camera-side mechanism was not tested: sensor blooming. 99–100 % of the corner frames saturate, with 46–56 % of the
  blob saturated, and M4 tests the fraction only.
  - *Corrected 2026-10-15.* The superseded wording also listed motion blur along the scan during the 40 µs exposure.
    That does not apply: the camera is coaxial, so a quasi-steady pool is not motion-smeared. Step 0 established this
    (plan, Step 0 design).

  Independent widths at the corners (cross-sections, XCT, track images; see "Open questions" in the plan) would settle
  it more directly than any further model run.
- **Options for the owner at Gate 2**, in the plan's terms, plus the open-question route. None is taken:
  - (a) score W only, keeping H as a reported diagnostic;
  - (b) a model-structure question beyond the box, such as the speed response of the source or regulator;
  - (c) camera-side evidence first: corner widths, the camera's H/W script, exposure time.

  Changing the coverage floor is not an option here. It would move the reading only from Q-b to Q-c, and the closest
  points fail M3 and M4 regardless.

Per the plan, Step 4 stops here for the owner. Nothing is adopted, ranked or selected.

## Gate 2 follow-up: camera-side evidence, option (c) (2026-10-15)

**Owner decision (2026-10-15):** check option (c), camera-side evidence, before (a) or (b). This is a source and
provenance check, not a predeclared analysis.

Sources checked:
- the corner coupon HDF5 files (attributes and channel names, layer 53);
- the local `data_processing/` and `code_updates/` trees;
- the Satterlee committee draft (ledger A18: a method reference for the shared system; its Table 4.1 process matrix
  was not used);
- the Basler post-scan images stored in the coupon files.

Nothing was run on the thermal model and no held-out member was opened.

### Results

1. **The camera H/W script is not available here.**
   - H and W are stored as ready-made channels (`H`, `W`) in each layer's `data` array.
   - The files' provenance points to `E:/Past_prints/xctv16/session0/…` (`gigE_nano/layer53/`, `pyro/`, `basler/`). That
     drive is not attached.
   - The metadata names the part-split, synchronization and segmentation scripts (`segment_parts_and_write_bounds_v4.py`
     v5.1, `sync_xct_to_process_3d_v3.py`, sync version 3.2.0), but no H/W script.
   - The draft states threshold 150 (Fig. 3.2, p. 37) but not the contour, component or rectangle convention.
   - Step 0's reconstruction (8-connected external contour, `minAreaRect`) remains the only evidence of the convention.
2. **The camera, from the draft:**
   - Teledyne DALSA Genie Nano M640-NIR on the coaxial path, with a Kowa LM100FC24M lens and a 4× focal-length extender
     (pp. 57, 63).
   - Mono8 (8-bit), free-running at 8000 fps, 40 µs exposure (p. 63). Frames are matched to laser activity afterwards
     (pp. 86–87).
   - **"About 8 µm" per pixel is a nominal optics value. No scale calibration of the coaxial camera is described.** Only
     the Basler camera was calibrated.
   - The filter is described as a "400–700 nm cutoff filter … to reject reflected laser light" (p. 63). The wording does
     not settle whether the camera images a visible band or the NIR.
   - Not stated: gain, sensor type, radiometric calibration, any handling of saturation, and blooming. Saturation, plume,
     exposure, thresholding and alignment are listed only as limitations (p. 17). Genie Nano cameras are CMOS, where
     blooming is usually weak; the M640-NIR datasheet would confirm it.
3. **No validation of camera dimensions.**
   - No cross-sections, single tracks, high-speed imaging or comparison with literature; melt-pool depth was "not
     measured" (pp. 37, 134, 146).
   - No trend of camera length, width or area with power or speed is reported.
   - The draft uses the blob's minor axis as the *laser spot size* in a regression (p. 38), not as the melt-pool width.
4. **The beam spot.** Our record (A17) gives a spot size of 0.08 mm for these coupons. The camera's corner widths
   (56–79 µm at threshold 150) sit at or below the spot diameter and change little with speed (W ∝ v^−0.20).
5. **The Basler post-scan images cannot give track widths** (quick screen, not a predeclared analysis).
   - They are photometric-stereo albedo and a relative height map, calibrated at 5 µm/px in x and 6 µm/px in y
     (draft pp. 75–77).
   - On layer 53 of the four corners, neither image type shows a spectral peak at the 80 µm hatch period, which is
     12–15 px here.
   - The dominant structure is at 25–38 px (about 150–250 µm), and only 1–14 % of the power between 5 and 40 px lies at
     periods below 10 px. Individual tracks are not resolved.
6. **XCT** (NSI X5000, 7.6 µm voxels) was used for pores and exterior geometry (draft pp. 55–56, 93). Absorption
   contrast in dense, remelted metal does not show fusion boundaries, so it is not a width source.
7. **Motion blur does not apply** (coaxial camera, Step 0); see the correction in the Step 4 interpretation.

### Interpretation

- **Nothing available validates the threshold-150 blob as the melt-pool outline.**
  - Its author read the minor axis as a spot-size proxy.
  - Its pixel scale is nominal.
  - Its width stays near the 80 µm spot and responds weakly to speed.
  - The data fit a hot-core optical signal, not a fixed-temperature contour. They do not show what the blob measures.
- **What still holds regardless:** the scale-free Step 3 and Step 4 results (H/W ratios and process slopes) do not depend
  on the 8 µm/px question.
- **What cannot be settled:** whether O13 is a model error or a camera-definition effect. The available evidence does
  not decide it.
- **The decisive data does not exist locally.** In order of decisiveness:
  1. **Corner melt pools measured directly** on 20260904 parts 1, 3, 4 and 6, at P140/P180 × V600/V1400:
     - metallographic cross-sections across the final layer's tracks (width and depth); or
     - non-destructively, optical microscopy or profilometry of the final layer's top surface (bead widths).

     Either directly tests the speed response that separates model and camera.
  2. **From the lab or the `E:` archive:**
     - the H/W extraction script;
     - the camera configuration (gain, filter part number);
     - any image of a scale target taken through the coaxial path.
  3. **The camera datasheet**, to confirm the sensor and its spectral response.
- **This bears on option (a) too.** Camera W has the same unvalidated status as H, and its speed response is the
  part the model misses most. Scoring W only would not escape the question.
- **Options (a) and (b) from Gate 2 remain open.** None is taken.

## Patch close (2026-10-15)

**Summary of the O13 diagnostic:**
- **Step 0.** The camera is beam-locked and saturated. Its H/W is about 1.3 at every threshold, and the blob is a
  thermal signal.
- **Step 3 (R-b).** No synthetic-camera setting reproduces the camera's shape, sizes and process trends.
- **Step 4 (Q-b).** No point of the A9 box reproduces the camera on the corners. The excess is the model's speed
  response (1400 mm/s).
- **Option (c).** The camera's dimensions are unvalidated (A24).

**Owner decision (2026-10-15):**
- Accept the H mismatch as a documented limitation, and report failure modes in the thesis conclusion rather than fix
  them.
- Proceed with Patch 22.4.3.2 as a narrow-window calibration: 65–85 J/mm³, log-ratio H/W objective with equal weights,
  liquidus operator, synthetic camera as a secondary result.

**Ledger:** O13 closed and A24 added. Tag `patch-22.3.8`. No production code, semantics or frozen core changed in this
patch. The dispatch lock is unchanged.
