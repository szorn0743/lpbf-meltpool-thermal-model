# Partition and data-use history

The A25 partition and, per coupon, which stage read its experimental data and when. This makes the 'examined' versus 'blind' distinction auditable.

## Partition

| Group | Coupons | Conditions | VED (J/mm3) | A8 origin | Coupons | Data status at the selection freeze (d01ac72) |
|---|---|---|---|---|---|---|
| Calibration | 9 | 5 | 68.6–83.3 | calibration | 20260730:part_1, 20260730:part_3, 20260730:part_5, 20260730:part_6, 20260731:part_1, 20260731:part_3, 20260731:part_5, 20260731:part_6, 20260910:part_1 | Compared with the model by 22.3.8 (all 9) and used for selection (22.4.3.2 calibrate/confirm). |
| In-window held out | 5 | 3 | 69.4–75.0 | held out | 20260730:part_2, 20260730:part_4, 20260731:part_2, 20260731:part_4, 20260904:part_5 | Not read by any stage from 22.4.3 to the freeze; first compared at evaluate, after the committed freeze. Now opened (A8, A27). |
| Out of window, examined | 7 | 7 | 41.7–125.0 | calibration | 20260904:part_1, 20260904:part_3, 20260904:part_4, 20260904:part_6, 20260910:part_3, 20260910:part_4, 20260910:part_6 | Compared with the model by 22.3.8 (A8 calibration members); not used for 22.4.3.2 selection. |
| Out of window, blind | 3 | 3 | 55.6–95.2 | held out | 20260904:part_2, 20260910:part_2, 20260910:part_5 | Not read by any stage from 22.4.3 to the freeze; first compared at evaluate. Now opened (A8, A27). |

## Data use per coupon

| Coupon | Role | 21.3 summary | Examined by 22.3.8 before window | Model-compared before freeze | Used in selection | First model comparison | Stages (register) |
|---|---|---|---|---|---|---|---|
| 20260730:part_1 | calibration | yes | yes | yes | yes | 22.4.3 interrupted 272-unit campaign (2026-10-13) | S01 S03 S04 S05 S06 S08 S09 S11 S12 S13 S14 S18 S19 S22 S24 |
| 20260730:part_2 | in-window held out | yes | no | no | no | 22.4.3.2 evaluate (V, X) and synthetic camera (S) (2026-10-16) | S01 S22 S24 |
| 20260730:part_3 | calibration | yes | yes | yes | yes | 22.4.3 interrupted 272-unit campaign (2026-10-13) | S01 S03 S04 S06 S08 S09 S11 S12 S14 S19 S22 S24 |
| 20260730:part_4 | in-window held out | yes | no | no | no | 22.4.3.2 evaluate (V, X) and synthetic camera (S) (2026-10-16) | S01 S22 S24 |
| 20260730:part_5 | calibration | yes | yes | yes | yes | 22.3.8 Steps 2-3 replay and synthetic camera (2026-10-14) | S01 S03 S08 S12 S14 S19 S22 S24 |
| 20260730:part_6 | calibration | yes | yes | yes | yes | 22.3.8 Steps 2-3 replay and synthetic camera (2026-10-14) | S01 S02 S03 S08 S12 S14 S19 S22 S24 |
| 20260731:part_1 | calibration | yes | yes | yes | yes | 22.3.8 Steps 2-3 replay and synthetic camera (2026-10-14) | S01 S03 S08 S12 S14 S19 S22 S24 |
| 20260731:part_2 | in-window held out | yes | no | no | no | 22.4.3.2 evaluate (V, X) and synthetic camera (S) (2026-10-16) | S01 S22 S24 |
| 20260731:part_3 | calibration | yes | yes | yes | yes | 22.3.8 Steps 2-3 replay and synthetic camera (2026-10-14) | S01 S03 S08 S12 S14 S19 S22 S24 |
| 20260731:part_4 | in-window held out | yes | no | no | no | 22.4.3.2 evaluate (V, X) and synthetic camera (S) (2026-10-16) | S01 S22 S24 |
| 20260731:part_5 | calibration | yes | yes | yes | yes | 22.3.8 Steps 2-3 replay and synthetic camera (2026-10-14) | S01 S03 S08 S12 S14 S19 S22 S24 |
| 20260731:part_6 | calibration | yes | yes | yes | yes | 22.3.8 Steps 2-3 replay and synthetic camera (2026-10-14) | S01 S02 S03 S08 S12 S14 S19 S22 S24 |
| 20260904:part_1 | out, examined | yes | yes | yes | no | 22.3.8 Steps 2-3 replay and synthetic camera (2026-10-14) | S01 S03 S08 S12 S14 S16 S22 S24 |
| 20260904:part_2 | out, blind | yes | no | no | no | 22.4.3.2 evaluate (V, X) and synthetic camera (S) (2026-10-16) | S01 S22 S24 |
| 20260904:part_3 | out, examined | yes | yes | yes | no | 22.3.8 Steps 2-3 replay and synthetic camera (2026-10-14) | S01 S02 S03 S08 S12 S14 S16 S22 S24 |
| 20260904:part_4 | out, examined | yes | yes | yes | no | 22.3.8 Steps 2-3 replay and synthetic camera (2026-10-14) | S01 S02 S03 S08 S12 S14 S16 S22 S24 |
| 20260904:part_5 | in-window held out | yes | no | no | no | 22.4.3.2 evaluate (V, X) and synthetic camera (S) (2026-10-16) | S01 S22 S24 |
| 20260904:part_6 | out, examined | yes | yes | yes | no | 22.3.8 Steps 2-3 replay and synthetic camera (2026-10-14) | S01 S02 S03 S08 S12 S14 S16 S22 S24 |
| 20260910:part_1 | calibration | yes | yes | yes | yes | 22.3.8 Steps 2-3 replay and synthetic camera (2026-10-14) | S01 S03 S08 S12 S14 S19 S22 S24 |
| 20260910:part_2 | out, blind | yes | no | no | no | 22.4.3.2 evaluate (V, X) and synthetic camera (S) (2026-10-16) | S01 S22 S24 |
| 20260910:part_3 | out, examined | yes | yes | yes | no | 22.3.8 Steps 2-3 replay and synthetic camera (2026-10-14) | S01 S03 S08 S12 S14 S22 S24 |
| 20260910:part_4 | out, examined | yes | yes | yes | no | 22.3.8 Steps 2-3 replay and synthetic camera (2026-10-14) | S01 S03 S08 S12 S14 S22 S24 |
| 20260910:part_5 | out, blind | yes | no | no | no | 22.4.3.2 evaluate (V, X) and synthetic camera (S) (2026-10-16) | S01 S22 S24 |
| 20260910:part_6 | out, examined | yes | yes | yes | no | 22.3.8 Steps 2-3 replay and synthetic camera (2026-10-14) | S01 S03 S08 S12 S14 S22 S24 |

## Stage catalogue

| Stage | Patch | What | Date | Model compared | Purpose | Commit |
|---|---|---|---|---|---|---|
| S01 | 21.3.0 | 24-member characterization | 2026-10-12 01:19 | no | descriptive camera H/W and sync inventory; no thermal run, no fitting; validation_used = false | 8b29404 (tag patch-21.3); output gitignored |
| S02 | 22.3.1-22.3.4 (pre-repo) | 99-cell reference panel and 22.3.2 audit | not recorded | no | window-size and association diagnostics at single frames; files hold simulated H/W only | 44fc251 (imported, tag patch-22.4.3.1) |
| S03 | 22.4.3 | real-data preflight | 2026-10-12 01:29 | no | campaign gates; held_out_validation_members_absent = true | 44fc251 |
| S04 | 22.4.3 | interrupted 272-unit campaign | 2026-10-13 11:51-14:34 | yes | coarse calibration under 22.3.4 semantics; 24 units, all failed (A13) | 44fc251; outputs outside the repo |
| S05 | 22.3.5 | frame-13768 regression | 2026-10-13 19:30 | no | O4 | 277cf8d |
| S06 | 22.3.5.1 / 22.3.5.3 | targeted replay of 568 rows (serial and 4-worker) | 2026-10-13 19:36-23:05 | no | association reclassification (O3) | 93f3834, cbac505 |
| S08 | 22.3.6 | sync track-edge audit | 2026-10-14 00:33 | no | anchor convention (O11); held_out_members_opened = false | cd197e5 |
| S09 | 22.3.6 | association census | 2026-10-14 00:33-01:04 | yes | residual-case classes (A14) | cd197e5 |
| S11 | 22.3.7 | Stage A (two attempts) | 2026-10-14 14:06-14:50 | yes | verify A21-A23; O13 re-measured | c2901c3, 9367868 |
| S12 | 22.3.8 | Step 0 camera characterization | 2026-10-14 16:51 | no | what the camera blob measures; raw images of layers 52 and 53; trends against P and v | 669f2fd |
| S13 | 22.3.8 | Step 1 capture gate | 2026-10-14 17:39 | yes | regression against Stage A | f430906 |
| S14 | 22.3.8 | Steps 2-3 replay and synthetic camera | 2026-10-14 19:19-20:17 | yes | anchor_center model vs camera; source of the 22.4.3.2 out-of-window expectation | 421fe34, 16ef975 |
| S16 | 22.3.8 | Step 4 sensitivity map (corners) and Gate 2 (c) | 2026-10-14 22:57 - 2026-10-15 14:48 | yes | A9 box vs camera on the four 20260904 corners; camera provenance (A24) | 0b20bad, 3fb2150, 28a1d51 |
| S18 | 22.4.3.2 | smoke | 2026-10-15 15:54-16:00 | yes | runner check | 78dc07d |
| S19 | 22.4.3.2 | calibrate, confirm and selection freeze | 2026-10-15 16:01 - 2026-10-16 14:33 | yes | window calibration and selection; held_out_members_read = [] | 78dc07d, ec53a55, d01ac72 |
| S22 | 22.4.3.2 | evaluate (V, X) and synthetic camera (S) | 2026-10-16 15:43-18:15 | yes | held-out and out-of-window evaluation after the freeze | 2fdc58c |
| S24 | analysis | per-coupon note and this package | 2026-10-19 | yes | descriptive, post hoc; evaluate unit files only, no HDF5 | a169772 and this package |

**Notes.**

- **All eight A8 held-out members (in-window held out and blind) were opened by the Patch 22.4.3.2 evaluation after its selection freeze. They must not be reused for fitting or selection; any later use is no longer held-out validation (A8, A27).**
- Before the freeze, the camera data of the 16 A8 calibration members (the 9 calibration and 7 examined out-of-window coupons) had been read and compared with the model; 20260730 parts 1 and 3 from 2026-10-13, all 16 by 2026-10-14.
- The 8 A8 held-out members were not read by any stage from the 22.4.3 preflight to the 22.4.3.2 freeze; every manifest of that period records them as absent or unread. Their first model comparison was the evaluate stage (2fdc58c), started about 70 minutes after the freeze commit.
- No coupon was entirely unopened: the Patch 21.3.0 characterization (2026-10-12) read all 24 files and wrote camera H/W summaries for the held-out members too (medians, quantiles, track-evolution slopes), with no model comparison. Whether those summaries were looked at before the freeze is not recorded. The 22.3.8 plan also discloses a discarded spot-check pass that pooled the whole 20260730 layer-53 file, including held-out parts 2 and 4. The 22.4.3.2 plan's 'never opened' is therefore true for model comparison and for every stage from 22.4.3 on, not for the 21.3.0 descriptive summary.
- When the window was chosen (2026-10-15), 22.3.8 had compared the model with the camera on all 16 A8 calibration members, including all 9 A25 calibration members; the window choice was not blind to the calibration data (A25 caveat).
- Source: `registers/data_use_history.json` (compiled from the stage manifests and git history).
