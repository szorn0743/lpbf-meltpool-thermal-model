"""Rebuild the image sources that the thesis figures read, without rendering the talk figures.

From the repo root (PowerShell):
    $env:PYTHONPATH = "$PWD\\src"
    .\\.venv-analysis\\Scripts\\python.exe results\\figure_sources\\scripts\\build_sources.py

Steps: (1) sources that need the external inputs (skipped, keeping the committed sources, when they are absent);
(2) sources derived from the committee package data.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def main() -> int:
    start = time.time()

    import extract

    if extract.available():
        print("extract: reading coupon HDF5 and c1 field files", flush=True)
        extract.write_sources()
    else:
        print("extract: skipped, using the committed image sources", flush=True)

    import charts

    charts.write_sources()
    print(f"done in {time.time() - start:.0f} s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
