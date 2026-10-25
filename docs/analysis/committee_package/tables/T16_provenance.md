# Provenance

Where every number in the package comes from: the Patch 22.4.3.2 stages and this package.

## Patch 22.4.3.2 stages

| Stage | Scope | Code commit (date) | Evidence committed | Clean tree | Policy / semantics / rule / objective | Workers | Units run / reused | Wall time | Python / numpy | Held-out coupons read | Fitting or selection | Manifest sha256 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| smoke | smoke gate: one unit (anchor_center x 20260730:part_1) | `bebec6d` 2026-10-15 | `78dc07d` 2026-10-15 | yes | 22.3.7 / 22.3.7 / 22.3.7 / 22.4.3.2 | 1 (serial) | 1 / 0 | 0.10 h | 3.13.15 / 2.5.4 | 0 | no | `81cbb95bfcf2` |
| calibrate | 17 frozen design candidates x 9 calibration coupons | `78dc07d` 2026-10-15 | `d01ac72` 2026-10-16 | yes | 22.3.7 / 22.3.7 / 22.3.7 / 22.4.3.2 | 4 (spawn) | 153 / 0 | 5.93 h | 3.13.15 / 2.5.4 | 0 | scores only | `a3b79d44c099` |
| confirm | 2 confirmation candidates x 9 calibration coupons | `ec53a55` 2026-10-16 | `d01ac72` 2026-10-16 | yes | 22.3.7 / 22.3.7 / 22.3.7 / 22.4.3.2 | 4 (spawn) | 9 / 9 | 0.63 h | 3.13.15 / 2.5.4 | 0 | surrogate proposal and scores | `8720905b616f` |
| freeze | selection freeze (no thermal run) | `ec53a55` 2026-10-16 | `d01ac72` 2026-10-16 | – | – / – / – / 22.4.3.2 | – | – | – | – | 0 | selection (lowest measured J) | `43184dff94c9` |
| evaluate | c1 on 24 coupons, c2 on the 15 evaluation coupons | `2fdc58c` 2026-10-16 | `a7031e0` 2026-10-16 | yes | 22.3.7 / 22.3.7 / 22.3.7 / 22.4.3.2 | 4 (spawn) | 39 / 0 | 2.31 h | 3.13.15 / 2.5.4 | 8 | no | `d4408c946847` |
| synthetic | reading S: synthetic camera on the c1 fields (no thermal run) | `2fdc58c` 2026-10-16 | `a7031e0` 2026-10-16 | yes | – / – / – / – | 4 (spawn) | 24 / – | 0.07 h | 3.13.15 / 2.5.4 | 8 | T150 fixed on calibration coupons only | `5384bfacab64` |

## This package

| Item | Value |
|---|---|
| Package | docs/analysis/committee_package, passes 1 and 2 |
| Candidate | confirm_c1 (frozen; selection freeze 754e2a4a5b62) |
| Thermal runs, fitting, selection | none, none, none |
| Semantic versions | production_hw_association_policy_version 22.3.7, production_hw_semantics_version 22.3.7, scored_frame_rule_version 22.3.7, objective_contract_version 22.4.3.2 |
| Bootstrap | percentile, 4,000 replicates, seed 20261019, families 1-8 (METHODS_MANIFEST.json) |
| Environment | tables and data: .venv (requirements.lock.txt); figures: .venv-analysis = the lock + matplotlib (requirements.analysis.txt) |
| Workers | single process (no thermal work units, A19 does not apply) |
| Verification | evaluate manifest 174 values (max diff 0.0e+00); synthetic manifest 108 values (max diff 0.0e+00); 22.3.6 sync audit 96 values; selection reconstruction PASS; calibrate and confirm unit files 171 sha256-checked |
| Held-out access | the 8 A8 held-out coupons are read from the 22.4.3.2 evaluate records (opened after the freeze, A8, A27), descriptively |
| Reproduction | run_all.py; compare OUTPUT_SHA256SUMS.txt (byte-identical between builds) |

**Notes.**

- Each stage's manifest records its code commit, a clean working tree, the semantic versions, the worker count and start method (4 spawn workers for every multi-unit stage, A19; the one-unit smoke gate ran serially), the runtime and the held-out members it read. No stage dispatched the 272-unit campaign, changed production semantics or lifted the dispatch lock.
- Held-out access: none of the 8 A8 held-out coupons was read before the freeze (smoke, calibrate, confirm, freeze: 0); the evaluate stage read all 8 after the committed freeze, and reading S rendered them afterwards at the T150 fixed on calibration coupons.
- Fixed controls identical in every stage manifest: yes (beam_share_floor, coverage_floor, pixel_floor, window_cells, objective_contract_version, production_hw_association_policy_version, production_hw_semantics_version, scored_frame_rule_version, design_sha256, objective_module_sha256, plan_sha256).
- Test status: each patch stage was gated on the full test suite (implementation report); the package's own checks are in `tests/test_committee_package.py`, and the suite result at the package commit is in the README. The build itself never runs tests, so this table stays byte-identical between builds.
- Run-specific facts (build time, git head, runtime, input hashes) are in `PROVENANCE.json`; output hashes in `OUTPUT_SHA256SUMS.txt`.
