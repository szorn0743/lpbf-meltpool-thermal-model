"""Readers for the thesis tables and figures.

Read-only and descriptive: every value comes from the committed committee-package data (D1-D7 and its T-tables'
data), the presentation-figure image sources, or the recorded 22.3.8 / 22.4.3.2 evidence. Nothing is run, fitted or
selected here.
"""
from __future__ import annotations

import csv
import json
from functools import lru_cache
from pathlib import Path

import numpy as np

from style import COMMITTEE, PRESENTATION, REPO

DATA = COMMITTEE / "data"
COMMITTEE_SOURCE = COMMITTEE / "figures" / "source"
PRESENTATION_SOURCE = PRESENTATION / "source"


def _num(value: str):
    if value is None:
        return None
    v = value.strip()
    if v == "":
        return None
    if v in ("true", "false"):
        return v == "true"
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        return v


def read_csv(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as fh:
        return [{k: _num(v) for k, v in row.items()} for row in csv.DictReader(fh)]


@lru_cache(maxsize=None)
def coupons() -> tuple[dict, ...]:
    return tuple(read_csv(DATA / "D3_coupons.csv"))


@lru_cache(maxsize=None)
def conditions_groups() -> tuple[dict, ...]:
    return tuple(read_csv(DATA / "D4_conditions_groups.csv"))


def conditions() -> list[dict]:
    return [r for r in conditions_groups() if r["level"] == "condition"]


def group(name: str) -> dict:
    for r in conditions_groups():
        if r["level"] == "group" and r["name"] == name:
            return r
    raise KeyError(name)


@lru_cache(maxsize=None)
def bootstrap_summary() -> tuple[dict, ...]:
    return tuple(read_csv(DATA / "bootstrap" / "D5_bootstrap_summary.csv"))


def boot(scope: str, name: str, statistic: str) -> dict:
    for r in bootstrap_summary():
        if r["scope"] == scope and r["name"] == name and r["statistic"] == statistic:
            return r
    raise KeyError((scope, name, statistic))


@lru_cache(maxsize=None)
def candidates() -> tuple[dict, ...]:
    return tuple(read_csv(DATA / "D6_candidate_search" / "D6_candidates.csv"))


ANCHOR_NAME = {
    "anchor_center": "Anchor: center of the box",
    "anchor_t_min": "Anchor: lowest $t$",
    "anchor_t_max": "Anchor: highest $t$",
    "anchor_low_ck_high_eta": "Anchor: low $c_k$, high $η$",
    "anchor_transport_guard_edge": "Anchor: stability-guard edge",
}


def display_name(candidate: str) -> str:
    """Readable candidate names in every thesis table and figure (owner, 2026-10-23): confirm_c1 -> Candidate 1,
    confirm_c2 -> Candidate 2, halton_04 -> Halton point 4, anchors by what they anchor. Record IDs stay in the CSV
    and Markdown provenance only."""

    if candidate.startswith("confirm_c"):
        return f"Candidate {int(candidate.removeprefix('confirm_c'))}"
    if candidate.startswith("halton_"):
        return f"Halton point {int(candidate.removeprefix('halton_'))}"
    return ANCHOR_NAME[candidate]


def selection_reconstruction() -> dict:
    return json.loads((DATA / "D6_candidate_search" / "D6_selection_reconstruction.json").read_text(encoding="utf-8"))


def replicate_pairs() -> list[dict]:
    return read_csv(DATA / "T10_replicate_pairs.csv")


def process_slopes() -> list[dict]:
    return read_csv(DATA / "T11_process_slopes.csv")


def operator_groups() -> list[dict]:
    return read_csv(DATA / "T14_operator_groups.csv")






def tracks() -> list[dict]:
    return read_csv(DATA / "D2_tracks.csv")


def operator_frames() -> list[dict]:
    return read_csv(COMMITTEE_SOURCE / "F13_frames.csv")


def operator_outlines() -> dict[tuple[str, str], np.ndarray]:
    out: dict[tuple[str, str], list] = {}
    for r in read_csv(COMMITTEE_SOURCE / "F13_outlines.csv"):
        out.setdefault((r["member"], r["operator"]), []).append((r["vertex"], r["x_px"], r["y_px"]))
    return {k: np.array([(x, y) for _, x, y in sorted(v)], dtype=float) for k, v in out.items()}


def operator_camera_pixels() -> dict[str, np.ndarray]:
    out: dict[str, np.ndarray] = {}
    for r in read_csv(COMMITTEE_SOURCE / "F13_camera_pixels.csv"):
        img = out.setdefault(r["member"], np.zeros((24, 64), dtype=float))
        img[r["row"], r["col"]] = r["counts"]
    return out


def representative_frames() -> list[dict]:
    return read_csv(PRESENTATION_SOURCE / "representative_frames.csv")


def representative_arrays():
    return np.load(PRESENTATION_SOURCE / "representative_frames.npz")


def pipeline_frame() -> tuple[list[dict], dict]:
    rows = read_csv(PRESENTATION_SOURCE / "pipeline_frame.csv")
    arrays = dict(np.load(PRESENTATION_SOURCE / "pipeline_frame.npz"))
    return rows, arrays


def process_record() -> list[dict]:
    """The read-only A17 experimental record (never written)."""

    return read_csv(REPO / "docs" / "reference" / "LPBF_Process_Parameters.csv")
