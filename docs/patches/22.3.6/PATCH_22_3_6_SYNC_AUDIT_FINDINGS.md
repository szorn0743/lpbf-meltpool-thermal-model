# Patch 22.3.6 stage 1: synchronization audit at scan-track edges

**Status:** `PASS_PATCH_22_3_6_SYNC_TRACK_START_AUDIT` (2026-10-14, commit `cd197e5`). Diagnostic only.
No thermal run, no semantic change. The 16 calibration members only; held-out HDF5 files were not opened.

## What was audited

For every scan track of every calibration member (861 tracks, 18,020 eligible frames):
- the first and last *eligible* camera frame (laser on, finite non-negative H/W, valid mapping);
- whether that frame is a matched rising/falling sync edge and whether its mapped row is a piecewise anchor;
- its mapped process row relative to the track's first/last laser-on row;
- the number of dark frames and the camera time between it and the nearest dark frame.

A "scan track" is a contiguous laser-on run of process rows. Track 1 of each member is a serpentine of about
12 mm path length, so a run can span many hatch lines; hatch turnarounds inside a run are not track edges.

## Finding 1: the two campaigns use different anchoring conventions

| | July (0730, 0731; 8 members, 431 tracks) | September (0904, 0910; 8 members, 430 tracks) |
|---|---|---|
| First eligible frame is the rising-edge anchor | 431 / 431 | 0 / 430 |
| First eligible frame: rows after the laser-on row | 0 on every track | median 12, p90 26, max 59 |
| Dark frames before it | 1 | 2 (425 tracks) |
| Last eligible frame is the falling-edge anchor | 0 / 431 | 430 / 430 |
| Last eligible frame: rows before the laser-off row | median 22 (10–116) | exactly 9 on every track |
| `selected_resample_factor` (sync attribute) | 1.1 | 0.8 |

Raw sync states confirm the mechanism. In July the first bright frame is pinned to the first laser-on row
(e.g. 0730:part_1 frame 12450 → row 4163, laser drive 5.0). In September the first bright frame is pinned
about 10 rows *before* laser-on (0904:part_1 frame 179 → row 4473, laser drive 0.0), so it is ineligible,
and the first eligible frame is the next one (frame 180 → row 4492, nine rows after laser-on).

So the frame→row mapping carries a **campaign-dependent offset of about 10 rows (50 µs)** at the anchors:
2–3 grid cells of laser travel at 600–850 mm/s. The only sync parameter that differs between the campaigns is
the resample factor. Whether the same offset persists mid-track is not determined by this audit; any timing
interpretation of residual cases (roadmap 22.3.6 class B) must allow for it.

## Finding 2: the row clock is consistent

September layers have about twice the process rows of July layers (86,890 vs 43,786 for part 1). This is not
a sampling-rate change: path length from the X/Y-Machine channels divided by rows × 5 µs reproduces the nominal
speeds (0730:part_1 851 vs 850 mm/s; 0904:part_1 580 vs 600; 0910:part_3 701 vs 700). September scans are
slower and the part split retained more idle rows. The fixed 200 kHz row clock stands.

## Finding 3: what the scored-frame rule (F1) removes

Owner decision D2 (2026-10-14): exclude the first and last eligible frame of every scan track.
- Frames removed: 1,712 of 18,020 (9.5 %). First-only would remove 861 (4.8 %).
- Tracks with ≤ 2 eligible frames are removed entirely: 30 of 861 (10 single-frame, 20 two-frame tracks;
  0–3 per member). These are the short corner vectors.
- In July the removed first frame is exactly the frame where the model has deposited no energy yet. In
  September it is a frame 0–59 rows after laser-on whose mapping is interpolated from a shifted anchor.

## Evidence

`evidence/PATCH_22_3_6_SYNC_TRACK_START_AUDIT.json` (per-member summaries),
`evidence/PATCH_22_3_6_SYNC_TRACK_START_AUDIT_TRACKS.csv` (one row per track),
`evidence/PATCH_22_3_6_SYNC_AUDIT_CONSOLE.log`. Produced by
`Invoke-Patch22_3_6_AssociationCensus.ps1 -RunSyncAudit` (`run_sync_track_start_audit` in
`src/lpbf/patch22_3_6_association_census.py`).
