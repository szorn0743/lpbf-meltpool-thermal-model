"""Shared style for the presentation figures: slide-sized type, one colour code, save helpers.

Colour code (reference palette slots 1-3, which validate all-pairs):
- experiment = the coaxial camera: orange;
- simulation = the calibrated model (confirm_c1): blue;
- simulated camera = the reading-S synthetic camera applied to the model: aqua.
Roles (calibration, held out, out of window) are carried by marker shape, labels or the window band, never by
these hues. Sequential scales use one hue; the image panels use the inferno heat map with a scale bar.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PACKAGE = HERE.parent
REPO = HERE.parents[3]
COMMITTEE_SCRIPTS = REPO / "docs" / "analysis" / "committee_package" / "scripts"
if str(COMMITTEE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(COMMITTEE_SCRIPTS))

import common as C  # noqa: E402  (committee package: paths, readers, constants)

FIGURES_DIR = PACKAGE / "figures"
TABLES_DIR = PACKAGE / "tables"
SOURCE_DIR = PACKAGE / "source"

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
BAND = "#ecebe6"
NEUTRAL = "#f0efec"

CAMERA = "#eb6834"
MODEL = "#2a78d6"
SYNTH = "#1baf7a"
# Marks drawn on dark image backgrounds use the palette's documented dark-mode steps of the same hues (they pass the
# lightness, CVD and contrast checks against the images' black, #000004), always with a dark halo.
CAMERA_ON_DARK = "#d95926"
MODEL_ON_DARK = "#3987e5"
SYNTH_ON_DARK = "#199e70"

# Sequential ramps, steps 100-700. Blue is the documented ramp; orange, aqua and red are derived from their slot hue
# at the blue ramp's OKLCH lightness steps (chroma scaled like the blue ramp, clipped to the sRGB gamut).
BLUE_RAMP = ("#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7", "#3987e5", "#2a78d6", "#256abf", "#1c5cab", "#184f95", "#104281", "#0d366b")
ORANGE_RAMP_STEPS = ("#fbd7ca", "#f5c4b2", "#f2b098", "#eb9c7f", "#e68764", "#df7249", "#d95923", "#c94908", "#b44005", "#9e3704", "#892f02", "#752702", "#611e01")
AQUA_RAMP_STEPS = ("#cce8d9", "#b4dbc6", "#9ad0b4", "#80c3a2", "#62b890", "#43ac7f", "#0b9f6e", "#068f62", "#027f56", "#026f4b", "#016040", "#015136", "#02432c")
RED_RAMP_STEPS = ("#fed4d0", "#fac0ba", "#f8aaa3", "#f2958e", "#ee7e77", "#e76762", "#e24a48", "#d2383a", "#bb3032", "#a72528", "#911e22", "#7e1519", "#681014")
# Diverging blue <-> red with the documented neutral midpoint; equal steps per arm.
DIVERGING = (BLUE_RAMP[10], BLUE_RAMP[7], BLUE_RAMP[4], BLUE_RAMP[1], NEUTRAL, RED_RAMP_STEPS[1], RED_RAMP_STEPS[4], RED_RAMP_STEPS[7], RED_RAMP_STEPS[10])

LABEL = {"camera": "Experiment (coaxial camera)", "model": "Simulation (calibrated model)", "synthetic": "Simulated camera"}
ROLE_MARKER = {"calibration": "o", "in_window_held_out": "s", "out_of_window_examined": "^", "out_of_window_blind": "D"}
ROLE_SHORT = {"calibration": "calibration", "in_window_held_out": "held out", "out_of_window_examined": "outside window", "out_of_window_blind": "outside window"}
WINDOW = tuple(float(v) for v in C.VED_WINDOW_J_MM3)
UM_PER_PX = C.UM_PER_PX


def setup():
    import logging

    import matplotlib

    # Glyphs missing from Segoe UI (such as the box key) fall back to DejaVu Sans, which has no semibold; that is expected.
    logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update(
        {
            "font.family": ["Segoe UI", "DejaVu Sans"],
            "font.size": 11,
            "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
            "axes.edgecolor": AXIS, "axes.linewidth": 0.8, "axes.labelcolor": INK_2, "axes.titlecolor": INK,
            "axes.titlesize": 12, "axes.titleweight": "semibold", "axes.titlelocation": "left", "axes.titlepad": 8,
            "axes.labelsize": 11, "xtick.color": MUTED, "ytick.color": MUTED, "xtick.labelcolor": INK_2,
            "ytick.labelcolor": INK_2, "xtick.labelsize": 10, "ytick.labelsize": 10, "axes.grid": True,
            "grid.color": GRID, "grid.linewidth": 0.7, "grid.linestyle": "-", "axes.axisbelow": True,
            "legend.frameon": False, "legend.fontsize": 10, "axes.spines.top": False, "axes.spines.right": False,
            "svg.hashsalt": "lpbf-presentation-figures", "svg.fonttype": "none", "lines.solid_capstyle": "round",
            "mathtext.default": "regular",
        }
    )
    return plt


def title(fig, text: str, *, y: float = 1.0, x: float = 0.0, size: float = 16) -> None:
    """Simple, unnumbered figure title at the top left."""

    fig.text(x, y, text, ha="left", va="bottom", fontsize=size, fontweight="bold", color=INK, transform=fig.transFigure)


def note(fig, text: str, *, y: float = -0.02, x: float = 0.0, size: float = 8.5) -> None:
    fig.text(x, y, text, ha="left", va="top", fontsize=size, color=INK_2, transform=fig.transFigure, linespacing=1.35)


def save(fig, name: str, directory: Path = FIGURES_DIR) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    out = []
    for ext, meta in (("png", {"Software": None}), ("svg", {"Date": None, "Creator": None})):
        path = directory / f"{name}.{ext}"
        fig.savefig(path, dpi=300 if ext == "png" else None, metadata=meta, bbox_inches="tight", pad_inches=0.12)
        out.append(path)
    return out


def halo(width: float = 3.0, color: str = "#000000", alpha: float = 0.55):
    """Path effect that keeps a coloured line legible on any image background."""

    import matplotlib.patheffects as pe

    return [pe.Stroke(linewidth=width, foreground=color, alpha=alpha), pe.Normal()]


def text_halo(width: float = 2.5, color: str = "#000000", alpha: float = 0.6):
    import matplotlib.patheffects as pe

    return [pe.withStroke(linewidth=width, foreground=color, alpha=alpha)]


def heat_cmap():
    import matplotlib

    return matplotlib.colormaps["inferno"]


def ramp_cmap(colors, name: str):
    from matplotlib.colors import LinearSegmentedColormap

    return LinearSegmentedColormap.from_list(name, colors)


def ved_label(power: float, speed: float, ved: float) -> str:
    return f"{power:.0f} W · {speed:.0f} mm/s · {ved:.0f} J/mm³"
