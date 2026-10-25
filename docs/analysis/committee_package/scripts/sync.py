"""T19: synchronization quality per coupon (plan Part 1, item 6).

Sources, all committed or in the Patch 21.3 characterization:
- ``member_audit.json`` (all 24): sync method and version, raw, sync-mapped, laser-on and eligible frame counts;
- ``frame_observations.csv`` and ``scan_tracks.csv`` (all 24): where each track's first and last eligible frame
  maps relative to the track's powered process rows, recomputed here. For the 16 A8 calibration members these
  values are checked against the Patch 22.3.6 audit, which also gives the anchor convention (rising-edge anchor at the
  first frame in July, falling-edge anchor at the last frame in September; ledger O11). The 8 held-out members were
  not in that audit, so their anchor fractions are reported as not audited;
- the 22.4.3.2 synthetic stage (all 24): the share of scored frames whose process row maps back to the same frame.
"""
from __future__ import annotations

from statistics import median
from typing import Any

import common as C


def track_mapping(member: str) -> dict[str, Any]:
    acquisition_set, part = C.member_key(member)
    base = C.CHARACTERIZATION / "members" / f"{acquisition_set}_part_{part}_layer53"
    bounds = {int(r["scan_track_id"]): (int(r["process_row_start"]), int(r["process_row_end"])) for r in C.read_csv(base / "scan_tracks.csv")}
    rows: dict[int, list[int]] = {}
    for r in C.read_csv(base / "frame_observations.csv"):
        if r["eligible_melt_pool_observation"] == "True":
            rows.setdefault(int(r["scan_track_id"]), []).append(int(r["mapped_process_row"]))
    after_start, before_end, sizes = [], [], []
    for track, mapped in rows.items():
        start, end = bounds[track]
        after_start.append(min(mapped) - start)
        before_end.append(end - max(mapped))
        sizes.append(len(mapped))
    n = len(rows)
    return {
        "tracks_with_eligible_frames": n,
        "eligible_frames": sum(sizes),
        "first_maps_to_track_start_fraction": sum(1 for x in after_start if x == 0) / n,
        "last_maps_to_track_end_fraction": sum(1 for x in before_end if x == 0) / n,
        "median_rows_after_track_start": float(median(after_start)),
        "median_rows_before_track_end": float(median(before_end)),
        "single_frame_tracks": sum(1 for s in sizes if s == 1),
        "short_tracks_lt_4_frames": sum(1 for s in sizes if s < 4),
    }


def run() -> dict[str, Any]:
    audit = {m["member_identity"]: m["summary"] for m in C.load_json(C.SYNC_AUDIT_22_3_6)["members"]}
    maps_back = {u["member_identity"]: u["row_maps_back_to_frame_fraction"] for u in C.load_json(C.SYNTHETIC_MANIFEST)["units"]}
    rows, checked = [], 0
    for member in sorted(C.ROLE, key=C.member_key):
        info = C.characterization_audit(member)
        sync, meta = info["camera_sync"], info["synchronization_metadata"]
        mapping = track_mapping(member)
        if mapping["eligible_frames"] != sync["eligible_melt_pool_frame_count"]:
            raise RuntimeError(f"{member}: eligible frames by track differ from the characterization count")
        ref = audit.get(member)
        if ref is not None:
            for mine, theirs in (
                ("tracks_with_eligible_frames", "track_count"), ("eligible_frames", "eligible_frame_count"),
                ("first_maps_to_track_start_fraction", "first_maps_to_track_start_fraction"), ("last_maps_to_track_end_fraction", "last_maps_to_track_end_fraction"),
                ("single_frame_tracks", "single_frame_track_count"), ("short_tracks_lt_4_frames", "short_track_count_lt_4_frames"),
            ):
                if mapping[mine] != ref[theirs]:
                    raise RuntimeError(f"{member}: {mine} {mapping[mine]} != 22.3.6 audit {ref[theirs]}")
                checked += 1
        acquisition_set = C.member_key(member)[0]
        rows.append(
            {
                "member": member, "role": C.ROLE[member], "campaign": "July" if acquisition_set in ("20260730", "20260731") else "September",
                "sync_method": meta["method"], "sync_version": meta["version"],
                "raw_camera_frames_layer": sync["raw_camera_frame_count"], "sync_mapped_frames": sync["synchronization_valid_frame_count"],
                "laser_on_mapped_frames": sync["laser_on_mapped_frame_count"], "laser_off_mapped_frames": sync["laser_off_mapped_frame_count"],
                "eligible_frames": sync["eligible_melt_pool_frame_count"], "repeated_mapped_rows": sync["repeated_mapped_process_row_unique_count"],
                "out_of_range_mapped_frames": sync["out_of_range_mapped_frame_count"], "timestamps_strictly_increasing": sync["camera_timestamp_strictly_increasing"],
                **mapping,
                "first_frame_rising_edge_anchor_fraction": ref["first_frame_rising_edge_anchor_fraction"] if ref else None,
                "last_frame_falling_edge_anchor_fraction": ref["last_frame_falling_edge_anchor_fraction"] if ref else None,
                "anchor_audit": "22.3.6 audit" if ref else "not audited (A8 held out; 22.3.6 read calibration members only)",
                "row_maps_back_to_frame_fraction": maps_back[member],
            }
        )
    check = {"members_checked_against_22_3_6": sum(1 for r in rows if r["anchor_audit"] == "22.3.6 audit"), "values_checked": checked, "status": "PASS"}
    return {"rows": rows, "check": check, "paths": {"sync": C.write_csv(C.DATA_DIR / "T19_synchronization.csv", rows)}}
