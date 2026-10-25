# Provenance

This repository is a curated export of the private development repository of the thesis, taken at its commit
`f15cce9` (2026-10-24). That repository holds the full history (55 commits from 2026-10-13, starting with byte-identical
imports of earlier code packages), and it is kept as the archival record. Its history is not published here.

## Which code produced the results

Every stage of the calibration recorded its private commit, a clean worktree and the SHA-256 of the module that ran
it (`provenance.git_commit`, `git_worktree_dirty`, `module_sha256` in the stage manifests under
`docs/patches/22.4.3.2/evidence/`).

| Stage | Private commit | Date | Module recorded | Equals the module in this repository |
|---|---|---|---|---|
| smoke | `bebec6d` | 2026-10-15 | `patch22_4_3_2_window_calibration` | no: earlier revision (see below) |
| calibrate | `78dc07d` | 2026-10-15 | `patch22_4_3_2_window_calibration` | no: earlier revision (see below) |
| confirm | `ec53a55` | 2026-10-16 | `patch22_4_3_2_window_calibration` | **yes** |
| freeze | committed at `d01ac72` | 2026-10-16 | (no thermal run) | — |
| evaluate | `2fdc58c` | 2026-10-16 | `patch22_4_3_2_window_calibration` | **yes** |
| synthetic | `2fdc58c` | 2026-10-16 | `patch22_4_3_2_synthetic_camera` | **yes** |

The smoke and calibrate stages ran with the revision before `ec53a55`. That commit changed the runner in one place:
17 lines added to `_walk`, the walk that places the confirmation candidates along the surrogate's valley (it also
converted the file's line endings). The fix, and why it was made after the first confirmation, is recorded in
`docs/patches/22.4.3.2/evidence/pre_fix/README.md`. The thermal evaluation of a candidate on a coupon did not change.

To check a module against a record:

```powershell
python -c "import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" src\lpbf\patch22_4_3_2_window_calibration.py
```

and compare with `provenance.module_sha256` in `docs/patches/22.4.3.2/evidence/evaluate/stage_manifest.json`. The 8
files of the frozen numerical core are checked against `PATCH_22_3_4_ACCEPTED_CORE_HASHES.json` by
`tests/test_accepted_core_hashes.py`; the smoke gate checked the same hashes before the run.

## What is byte-identical, and what changed

Every file copied from the private repository is byte-identical to its copy at `f15cce9`, except:

| File | Change |
|---|---|
| `docs/analysis/committee_package/scripts/controls.py` | Table T16 reads the git facts of the private repository (the commit that first added each stage manifest, and the dates of the recorded commits) from `registers/private_git_history.json`, a snapshot taken at export, because those commits are not in this repository. Falls back to `git` otherwise. |
| `docs/analysis/committee_package/scripts/common.py` | The default coupon-data folder is `data/coupons/` instead of a path on the development machine. |
| `docs/DECISIONS.md` | Replaced by a condensed version with the same entry IDs. |
| `docs/analysis/committee_package/README.md`, `docs/analysis/thesis_figures/README.md`, `docs/reference/README.md` | Development-machine paths, notes on the thesis draft and references to the development tooling removed. |

New in this repository: `README.md`, `PROVENANCE.md`, `LICENSE`, `CITATION.cff`, `.gitignore`, `data/README.md`,
`data/SHA256SUMS.txt`, `docs/analysis/committee_package/registers/private_git_history.json`,
`docs/analysis/presentation_figures/README.md`, `docs/analysis/presentation_figures/scripts/build_sources.py` and
`tests/test_accepted_core_hashes.py` (which takes over the core-hash check from a test that was left out).

Some records still name the development machine's folders (for example `C:\Users\...\all_coupons`) or private
commits. They were left as they are: the analysis packages record their SHA-256 as inputs, and editing them would
break that chain. The same holds for the calibration plan, `docs/patches/22.4.3.2/PATCH_22_4_3_2_PLAN.md`: it is the
predeclared protocol, every stage manifest records its SHA-256 (`plan_sha256`), and it is kept byte-identical, including
its closing checklist, which refers to development files. A few records also mention documents that were not exported (plans and reports of earlier steps);
those references point to the private repository.

## What was left out

- The git history and tags of the private repository.
- 56 of the 124 modules of `src/lpbf/`: 50 that nothing reached, and 6 reached only by the runners and tests of
  earlier steps. What remains is exactly what the calibration runner, the synthetic-camera stage, the analysis builds
  and the remaining tests import, plus the whole frozen core (its `simulation.py` is not imported but is hash-pinned).
- The runners, PowerShell launchers and regression tools of earlier steps (22.3.5 to 22.3.7), and 6 test files that
  exercise only those.
- The development records of earlier steps (plans, implementation reports, run instructions, console logs), except
  the evidence files that the code reads. The archive of superseded documents and old run instructions.
- The full decision ledger (condensed into `docs/DECISIONS.md`).
- The talk figures, tables and animations of the defense presentation (their image sources stay, because the thesis
  figures read them).
- The thesis document and the defense notes.
- Editor and AI-assistant configuration files.
- A third-party dissertation draft used as a method reference for the experimental system.
- The data (see `data/README.md`): the coupon HDF5 files, the Patch 21.3 characterization and the recorded run
  outputs, which are distributed separately.
