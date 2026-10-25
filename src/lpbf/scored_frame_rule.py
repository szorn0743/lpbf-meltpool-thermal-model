"""Patch 22.3.7 scored-frame rule (F1; owner decision D2, 2026-10-14).

The first and last eligible camera frame of every scan track, and the only
frame of a single-frame track, are excluded from scoring.  Both laser edges are
synchronization anchors that carry up to one frame interval of timing bias
(ledger O11), and at the first row of a track the model has not yet deposited
energy at the new laser position (Patch 22.3.6 census: 524 of 525 track-first
frames were not comparable).  Excluded frames keep their identity and
provenance; they are never requested from the thermal evaluator, never enter
residuals, and are removed from the coverage denominator.  The rule applies
identically to calibration and held-out coupons.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping, Sequence

SCORED_FRAME_RULE_VERSION = "22.3.7"
SCORED_FRAME_RULE_ID = "exclude_first_and_last_eligible_frame_of_each_scan_track"
EXCLUDED_TRACK_FIRST = "EXCLUDED_TRACK_FIRST"
EXCLUDED_TRACK_LAST = "EXCLUDED_TRACK_LAST"
EXCLUDED_TRACK_SINGLE_FRAME = "EXCLUDED_TRACK_SINGLE_FRAME"
NOT_ELIGIBLE = "NOT_ELIGIBLE"
EXCLUSION_REASONS = (EXCLUDED_TRACK_FIRST, EXCLUDED_TRACK_LAST, EXCLUDED_TRACK_SINGLE_FRAME, NOT_ELIGIBLE)


def _eligible(row: Mapping[str, Any]) -> bool:
    return bool(row.get("observation_eligible", row.get("eligible_melt_pool_observation", True)))


def label_track_positions(frame_rows: Sequence[Mapping[str, Any]]) -> dict[int, dict[str, Any]]:
    """Position of every eligible frame inside its scan track (first / last / single / interior)."""

    by_track: dict[str, set[int]] = defaultdict(set)
    for row in frame_rows:
        if not _eligible(row):
            continue
        by_track[str(row["scan_track_id"])].add(int(row["frame_index"]))
    positions: dict[int, dict[str, Any]] = {}
    for track_id, frames in by_track.items():
        ordered = sorted(frames)
        count = len(ordered)
        for position, frame in enumerate(ordered):
            first, last = position == 0, position == count - 1
            positions[frame] = {
                "scan_track_id": track_id,
                "position": position,
                "track_frame_count": count,
                "is_first": first,
                "is_last": last,
                "edge_class": "single" if first and last else "first" if first else "last" if last else "interior",
            }
    return positions


def apply_scored_frame_rule(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Return copies of ``rows`` with ``scored_frame``, ``exclusion_reason`` and ``track_position`` set."""

    positions = label_track_positions(rows)
    labelled: list[dict[str, Any]] = []
    for row in rows:
        record = dict(row)
        frame = int(row["frame_index"])
        position = positions.get(frame) if _eligible(row) else None
        if position is None:
            reason: str | None = NOT_ELIGIBLE
        else:
            edge = position["edge_class"]
            reason = (
                EXCLUDED_TRACK_SINGLE_FRAME
                if edge == "single"
                else EXCLUDED_TRACK_FIRST
                if edge == "first"
                else EXCLUDED_TRACK_LAST
                if edge == "last"
                else None
            )
        record.update(
            {
                "scored_frame": reason is None,
                "exclusion_reason": reason,
                "track_position": None if position is None else dict(position),
                "scored_frame_rule_version": SCORED_FRAME_RULE_VERSION,
                "scored_frame_rule_id": SCORED_FRAME_RULE_ID,
            }
        )
        labelled.append(record)
    return labelled


def scored_frame_indices(rows: Sequence[Mapping[str, Any]]) -> tuple[int, ...]:
    return tuple(sorted({int(row["frame_index"]) for row in rows if bool(row.get("scored_frame"))}))


def scored_frame_rule_record() -> dict[str, Any]:
    return {
        "id": SCORED_FRAME_RULE_ID,
        "version": SCORED_FRAME_RULE_VERSION,
        "excluded": ["first eligible frame of each scan track", "last eligible frame of each scan track", "only frame of a single-frame track"],
        "applies_to": "calibration_and_held_out_coupons_identically",
        "decision": "owner decision D2, 2026-10-14 (ledger A20); basis: Patch 22.3.6 census and sync audit",
    }


__all__ = [
    "EXCLUDED_TRACK_FIRST",
    "EXCLUDED_TRACK_LAST",
    "EXCLUDED_TRACK_SINGLE_FRAME",
    "EXCLUSION_REASONS",
    "NOT_ELIGIBLE",
    "SCORED_FRAME_RULE_ID",
    "SCORED_FRAME_RULE_VERSION",
    "apply_scored_frame_rule",
    "label_track_positions",
    "scored_frame_indices",
    "scored_frame_rule_record",
]
