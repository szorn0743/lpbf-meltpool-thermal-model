# Pre-fix confirm and freeze (superseded, never committed as the freeze)

These files are the first `confirm` and `freeze` outputs of Patch 22.4.3.2, produced at commit `78dc07d`. They are
kept as the record of a post-data deviation. They are **not** the selection freeze: the runner's `evaluate` stage
accepts only the committed `../selection_freeze.json`.

## What happened

- Confirm ran only `confirm_c1`, the surrogate minimizer at coded (−1, 0.835, −1), measured J = 0.29807.
- The surrogate has a flat valley: λ = (−0.0102, 0.0196, 0.1449), v_min ≈ (−6e-6, −0.118, 0.993).
  - The plan places c2 and c3 along v_min at the predicted 1.10 · J_min level, clipped to the box and guard.
  - c3 leaves the box at once through η = 0, so skipping it is correct.
  - c2's level point, about (−1, 0.740, −0.199), lies outside the box only by about 5e-6 in t. That is
    eigenvector noise at the t = −1 face. The ray clip in `_walk` still stopped the walk at s = 0, so c2 was
    dropped (`clipped_by: "box"`, `run: false`).
- First freeze: reading C_EDGE, selected `confirm_c1`, near-best and E-set {`confirm_c1`}.
  - `selection_freeze.json` sha256 `51712a509145c6be9a225785c05a02d71a20a046c34c7d68f34b6cd9da1c7411`.
  - No held-out member was read.

## Decision and fix

- The owner decided on 2026-10-16 to fix the code to match the approved plan, run c2 and re-freeze.
  - Selection stays the lowest measured J among all evaluated candidates.
  - The box is unchanged.
- The fix, with its regression test `test_flat_valley_walk_projects_a_level_point_that_eigenvector_noise_puts_just_outside_a_box_face`:
  - when the ray leaves the box before the level, and the level point lies within the plan's existing 0.05
    coded proximity tolerance of the box, `_walk` projects the level point onto the box (`clipped_by:
    "level_projected"`);
  - it then checks the guard along the segment.
  - Every other case is unchanged.
- Effect on this data:
  - c2 = (−1, 0.7400, −0.1987), i.e. t = −3, ck = 2.3700, η = 0.4006, predicted J 0.3118;
  - c1 is unchanged and c3 is still skipped.
- The re-run confirm reuses the 9 `confirm_c1` units. Resume requires the same coordinates, member hashes and
  frame rows.
