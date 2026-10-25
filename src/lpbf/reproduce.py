"""One entry point for reproducing the thesis: ``python -m lpbf.reproduce <command> [options]``.

Commands (run from the repository root):

  check-data        list the data files the other commands need and say which are present
  example           run the synthetic end-to-end example (no experimental data needed), ~10 s
  characterize      HDF5 coupons -> camera observation tables (the characterization in the data bundle)
  smoke             the calibration smoke gate: one unit, bit-identical to the recorded one, ~6 min
  calibrate         the 17 design candidates on the 9 calibration coupons (153 units), hours
  confirm           the confirmation candidates (18 units), ~1 h
  freeze            selection by lowest measured objective (no thermal run)
  evaluate          the selected candidate on all coupons with field capture (39 units), ~2.5 h
  synthetic-camera  reading S: the synthetic camera on the evaluate stage's fields, ~5 min
  analysis          figure sources -> committee package -> thesis tables and figures (needs matplotlib)

Every command is a thin wrapper over the module that implements it; ``--help`` after a command shows that
module's own options. The thermal stages take ``--output-dir`` (default ``runs/calibration``); the recorded run of
the thesis unpacks to ``runs/recorded_calibration`` and is never overwritten.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from lpbf.paths import repository_root

ROOT = repository_root()
DATA_DIR = ROOT / "data" / "coupons"
CHARACTERIZATION_DIR = ROOT / "data" / "characterization" / "patch21_3_full_characterization_20261012_011936"
RECORDED_RUN = ROOT / "runs" / "recorded_calibration"
FREEZE = ROOT / "results" / "calibration" / "selection_freeze.json"
DATA_README = "data/README.md"


def _expected_data() -> list[tuple[str, Path, str]]:
    from lpbf.data.full_coupon_manifest import load_full_coupon_manifest

    items = [("coupon HDF5", DATA_DIR / m.expected_filename, "lpbf_coupon_hdf5.zip") for m in load_full_coupon_manifest().members]
    items += [("characterization", CHARACTERIZATION_DIR / "members", "lpbf_characterization_patch21_3.zip")]
    items += [("recorded run", RECORDED_RUN / "evaluate" / "stage_manifest.json", "lpbf_recorded_calibration_run.zip")]
    return items


def check_data(verbose: bool = True) -> dict[str, bool]:
    status: dict[str, bool] = {}
    for kind, path, archive in _expected_data():
        present = path.exists()
        status[str(path.relative_to(ROOT))] = present
        if verbose:
            print(f"{'present' if present else 'MISSING'}  {kind:18s} {path.relative_to(ROOT)}  ({archive})")
    missing = [p for p, ok in status.items() if not ok]
    if verbose:
        print(f"\n{len(status) - len(missing)} of {len(status)} present." + (f" See {DATA_README} for the data bundle." if missing else ""))
    return status


def _require(paths: list[Path]) -> None:
    missing = [p for p in paths if not p.exists()]
    if missing:
        print("This command needs data that is not present:", file=sys.stderr)
        for p in missing:
            print(f"  {p}", file=sys.stderr)
        print(f"The data bundle and its layout are described in {DATA_README}; `python -m lpbf.reproduce check-data` lists every file.", file=sys.stderr)
        raise SystemExit(2)


def _freeze_args() -> list[str]:
    from lpbf.configuration import load_final_model

    return ["--freeze-file", str(FREEZE), "--freeze-sha256", load_final_model()["selected_parameters"]["selection_freeze_sha256"]]


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    command, rest = argv[0], argv[1:]
    if command == "check-data":
        status = check_data()
        return 0 if all(status.values()) else 2
    if command == "example":
        from lpbf.synthetic_example import main as example_main

        return example_main(rest)
    if command == "characterize":
        _require([DATA_DIR])
        from lpbf.characterization import main as characterize_main

        return characterize_main(rest)
    if command in ("smoke", "calibrate", "confirm", "evaluate"):
        _require([DATA_DIR, CHARACTERIZATION_DIR])
        from lpbf.calibration import main as calibration_main

        args = [command, "--data-dir", str(DATA_DIR), "--characterization-dir", str(CHARACTERIZATION_DIR)]
        if command == "evaluate":
            args += _freeze_args()
        return calibration_main(args + rest)
    if command == "freeze":
        from lpbf.calibration import main as calibration_main

        return calibration_main(["freeze", *rest])
    if command == "synthetic-camera":
        _require([DATA_DIR])
        from lpbf.observation_operators import main as synthetic_main

        return synthetic_main(["--data-dir", str(DATA_DIR), *_freeze_args(), *rest])
    if command == "analysis":
        _require([CHARACTERIZATION_DIR, RECORDED_RUN / "evaluate" / "units"])
        scripts = [
            ROOT / "results" / "figure_sources" / "scripts" / "build_sources.py",
            ROOT / "results" / "committee_package" / "scripts" / "run_all.py",
            ROOT / "results" / "thesis_figures" / "scripts" / "build.py",
        ]
        for script in scripts:
            print(f"== {script.relative_to(ROOT)}", flush=True)
            code = subprocess.run([sys.executable, str(script), *rest], cwd=ROOT).returncode
            if code:
                return code
        return 0
    print(f"unknown command {command!r}\n", file=sys.stderr)
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
