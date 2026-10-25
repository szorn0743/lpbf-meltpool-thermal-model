"""Thesis style: Times New Roman to match the thesis body, 6.25 in text width, print-safe colours.

Colour code (the same as the presentation figures):
- experiment = the coaxial camera: orange;
- simulation = the calibrated model (confirm_c1): blue;
- simulated camera = the reading-S synthetic camera applied to the model: aqua.
Data roles (calibration, held out, out of window) are carried by marker shape and fill in ink and grey, never by
these hues, so that the role key also survives a greyscale print.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PACKAGE = HERE.parent
REPO = HERE.parents[3]
COMMITTEE = REPO / "docs" / "analysis" / "committee_package"
PRESENTATION = REPO / "docs" / "analysis" / "presentation_figures"
if str(COMMITTEE / "scripts") not in sys.path:
    sys.path.append(str(COMMITTEE / "scripts"))  # appended: its tables.py must not shadow this package's modules

import common as C  # noqa: E402  (committee package: paths, readers, constants)

FIGURES_DIR = PACKAGE / "figures"
TABLES_DIR = PACKAGE / "tables"
SOURCE_DIR = PACKAGE / "source"

# Thesis page: letter, 1.25 in left and 1 in right margins.
FULL_W = 6.25
HALF_W = 3.05

WHITE = "#ffffff"
INK = "#0b0b0b"
INK_2 = "#3d3c39"
MUTED = "#7a7974"
GREY = "#9a9993"
GRID = "#e4e3dd"
AXIS = "#8f8e88"
BAND = "#ecebe6"
NEUTRAL = "#f0efec"

CAMERA = "#eb6834"
MODEL = "#2a78d6"
SYNTH = "#1baf7a"
CAMERA_ON_DARK = "#d95926"
MODEL_ON_DARK = "#3987e5"
SYNTH_ON_DARK = "#199e70"
BLUE_RAMP = ("#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7", "#3987e5", "#2a78d6", "#256abf", "#1c5cab", "#184f95", "#104281", "#0d366b")
ORANGE_RAMP = ("#fbd7ca", "#f5c4b2", "#f2b098", "#eb9c7f", "#e68764", "#df7249", "#d95923", "#c94908", "#b44005", "#9e3704", "#892f02", "#752702", "#611e01")

ROLE_ORDER = ("calibration", "in_window_held_out", "out_of_window_examined", "out_of_window_blind")
ROLE_LABEL = {
    "calibration": "Calibration",
    "in_window_held_out": "Held out, in window",
    "out_of_window_examined": "Out of window, examined",
    "out_of_window_blind": "Out of window, blind",
}
# marker, face, edge: filled ink circle, open ink square, filled grey triangle, open ink diamond.
ROLE_STYLE = {
    "calibration": ("o", INK, INK),
    "in_window_held_out": ("s", WHITE, INK),
    "out_of_window_examined": ("^", GREY, "#5c5b57"),
    "out_of_window_blind": ("D", WHITE, INK),
}
WINDOW = tuple(float(v) for v in C.VED_WINDOW_J_MM3)
UM_PER_PX = C.UM_PER_PX


def setup():
    import logging

    import matplotlib

    logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update(
        {
            "font.family": "serif",
            "font.serif": ["Times New Roman", "DejaVu Serif"],
            "mathtext.fontset": "stix",
            "font.size": 9,
            "figure.facecolor": WHITE, "axes.facecolor": WHITE, "savefig.facecolor": WHITE,
            "axes.edgecolor": AXIS, "axes.linewidth": 0.7, "axes.labelcolor": INK, "axes.titlecolor": INK,
            "axes.titlesize": 9.5, "axes.titleweight": "normal", "axes.titlelocation": "left", "axes.titlepad": 5,
            "axes.labelsize": 9, "xtick.color": AXIS, "ytick.color": AXIS, "xtick.labelcolor": INK,
            "ytick.labelcolor": INK, "xtick.labelsize": 8, "ytick.labelsize": 8, "xtick.major.width": 0.6,
            "ytick.major.width": 0.6, "xtick.major.size": 3, "ytick.major.size": 3, "axes.grid": True,
            "grid.color": GRID, "grid.linewidth": 0.5, "axes.axisbelow": True, "legend.frameon": False,
            "legend.fontsize": 8, "legend.handletextpad": 0.4, "legend.columnspacing": 1.2,
            "axes.spines.top": False, "axes.spines.right": False, "svg.hashsalt": "lpbf-thesis-figures",
            "svg.fonttype": "none", "lines.solid_capstyle": "round", "lines.linewidth": 1.1,
        }
    )
    return plt


def panel(ax, letter: str, text: str = "") -> None:
    """Panel label '(a) text' at the top left of an axes."""

    label = f"({letter})" + (f" {text}" if text else "")
    ax.set_title(label, loc="left", fontsize=9.5, color=INK)


def save(fig, name: str, directory: Path = FIGURES_DIR) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    out = []
    for ext, meta in (("png", {"Software": None}), ("svg", {"Date": None, "Creator": None})):
        path = directory / f"{name}.{ext}"
        fig.savefig(path, dpi=300 if ext == "png" else None, metadata=meta, bbox_inches="tight", pad_inches=0.04)
        out.append(path)
    return out


def role_scatter(ax, x, y, role: str, *, size: float = 26, zorder: int = 3, label: str | None = None, **kw):
    marker, face, edge = ROLE_STYLE[role]
    return ax.scatter(x, y, s=size, marker=marker, facecolor=face, edgecolor=edge, linewidth=0.8, zorder=zorder,
                      label=label if label is not None else ROLE_LABEL[role], **kw)


def role_handles(roles=ROLE_ORDER, size: float = 5.5):
    from matplotlib.lines import Line2D

    handles = []
    for role in roles:
        marker, face, edge = ROLE_STYLE[role]
        handles.append(Line2D([], [], linestyle="none", marker=marker, markersize=size, markerfacecolor=face,
                              markeredgecolor=edge, markeredgewidth=0.8, label=ROLE_LABEL[role]))
    return handles


def window_band(ax, *, label: bool = True, y: float = 0.98) -> None:
    ax.axvspan(*WINDOW, color=BAND, zorder=0, lw=0)
    if label:
        ax.text(sum(WINDOW) / 2, y, "calibration\nwindow", transform=ax.get_xaxis_transform(), ha="center", va="top",
                fontsize=7, color=MUTED, linespacing=1.0)


def halo(width: float = 2.4, color: str = "#000000", alpha: float = 0.6):
    import matplotlib.patheffects as pe

    return [pe.Stroke(linewidth=width, foreground=color, alpha=alpha), pe.Normal()]


def text_halo(width: float = 2.2, color: str = "#000000", alpha: float = 0.65):
    import matplotlib.patheffects as pe

    return [pe.withStroke(linewidth=width, foreground=color, alpha=alpha)]


def write_csv(path: Path, header: list[str], rows: list[list]) -> Path:
    """CSV with LF line endings and repr-free floats (full precision)."""

    import csv
    import io

    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    for row in rows:
        w.writerow(["" if v is None else (repr(v) if isinstance(v, float) else v) for v in row])
    path.write_bytes(buf.getvalue().encode("utf-8"))
    return path
