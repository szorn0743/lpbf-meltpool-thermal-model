# Image sources for the thesis figures

The defense talk had its own figures, tables and animations; they are not part of this repository. What remains here
is what the thesis figures (`docs/analysis/thesis_figures/`) read from that package:

| Path | What it holds |
|---|---|
| `source/` | The stored image sources: representative camera and model frames, the pipeline frame, the threshold and isotherm outlines, per-condition sizes, and the other values the talk figures plotted. |
| `scripts/extract.py` | Reads the coupon HDF5 files and the `confirm_c1` field files and writes the image sources. |
| `scripts/charts.py` | Writes the sources derived from the committee package data (for example `condition_sizes.csv`). Its render functions are not used here. |
| `scripts/style.py` | Paths and constants shared by the two. |
| `scripts/build_sources.py` | Rebuilds `source/`, without rendering any figure. |

From the repository root, with the data bundle unpacked (see the top-level README):

```powershell
$env:PYTHONPATH = "$PWD\src"
.\.venv-analysis\Scripts\python.exe docs\analysis\presentation_figures\scripts\build_sources.py
git status docs\analysis\presentation_figures\source   # nothing changed: the extraction is deterministic
```

Without the HDF5 and field files, the extraction step is skipped and the committed sources are kept.
