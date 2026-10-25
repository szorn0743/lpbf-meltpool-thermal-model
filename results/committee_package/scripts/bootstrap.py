"""D5: bootstrap distributions for the confirm_c1 errors and ratios.

Two resampling units, both clusters, never frames:
- groups of >= 2 coupons: coupons are resampled with replacement within the group (family 1). The statistic is the
  contract hierarchy on the drawn coupons with multiplicity weights (a condition absent from a draw drops out);
- single coupons, conditions and one-coupon groups: scan tracks are resampled with replacement within each coupon
  (family 2). These intervals describe within-coupon sampling only, not coupon-to-coupon variation.

Generators are ``numpy.random.default_rng([SEED, family, index])``; the index of each group and coupon is recorded.
The npz files hold the statistic draws; the resample counts are not stored, since the generators reproduce them.
"""
from __future__ import annotations

import io
import math
import zipfile
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

import common as C

FAMILY_GROUP = 1
FAMILY_TRACK = 2
STATS = ("e_H", "e_W", "J", "median_H_ratio", "median_W_ratio")


def save_npz(path: Path, arrays: Mapping[str, np.ndarray]) -> Path:
    """Uncompressed-header, fixed-timestamp npz so that reruns are byte-identical."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(arrays):
            buffer = io.BytesIO()
            np.lib.format.write_array(buffer, np.ascontiguousarray(arrays[name]), allow_pickle=False)
            info = zipfile.ZipInfo(f"{name}.npy", date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, buffer.getvalue())
    return path


def safe(name: str) -> str:
    return name.replace(":", "_")


def weighted_median(values: np.ndarray, unit_index: np.ndarray, counts: np.ndarray, chunk: int = 250) -> np.ndarray:
    """Median of the multiset where value i appears counts[r, unit_index[i]] times, for each replicate r.

    Equals ``numpy.median`` of the expanded sample (mean of the two middle values when the total is even).
    """

    order = np.argsort(values, kind="stable")
    values, unit_index = values[order], unit_index[order]
    out = np.empty(counts.shape[0])
    for start in range(0, counts.shape[0], chunk):
        weights = counts[start : start + chunk][:, unit_index]
        cumulative = np.cumsum(weights, axis=1)
        total = cumulative[:, -1]
        low = np.argmax(cumulative > ((total - 1) // 2)[:, None], axis=1)
        high = np.argmax(cumulative > (total // 2)[:, None], axis=1)
        out[start : start + chunk] = (values[low] + values[high]) / 2.0
    return out


def _ratio_arrays(frames: Sequence[Mapping[str, Any]]) -> tuple[np.ndarray, np.ndarray]:
    return np.array([math.exp(f["r_H"]) for f in frames]), np.array([math.exp(f["r_W"]) for f in frames])


def coupon_track_draws(analysis: Mapping[str, Any], replicates: int) -> dict[str, dict[str, np.ndarray]]:
    """Track bootstrap within each coupon: msq_H, msq_W, median ratios and the track-count matrix."""

    out = {}
    tracks_by_member: dict[str, list] = {}
    for t in analysis["tracks"]:
        tracks_by_member.setdefault(t["member"], []).append(t)
    for index, member in enumerate(sorted(analysis["coupons"], key=C.member_key)):
        tracks = tracks_by_member[member]
        counts = C.draw_counts(C.rng(FAMILY_TRACK, index), len(tracks), replicates)
        msq_h = np.array([t["H_mean_sq_log"] for t in tracks])
        msq_w = np.array([t["W_mean_sq_log"] for t in tracks])
        frames = [f for t in tracks for f in t["frames"]]
        unit = np.array([k for k, t in enumerate(tracks) for _ in t["frames"]])
        ratio_h, ratio_w = _ratio_arrays(frames)
        out[member] = {
            "index": index,
            "counts": counts.astype(np.int16),
            "msq_H": counts @ msq_h / len(tracks),
            "msq_W": counts @ msq_w / len(tracks),
            "median_H_ratio": weighted_median(ratio_h, unit, counts),
            "median_W_ratio": weighted_median(ratio_w, unit, counts),
            "_ratio_h": ratio_h, "_ratio_w": ratio_w, "_unit": unit,
        }
    return out


def _from_msq(msq_h: np.ndarray, msq_w: np.ndarray) -> dict[str, np.ndarray]:
    return {"e_H": np.sqrt(msq_h), "e_W": np.sqrt(msq_w), "J": 0.5 * msq_h + 0.5 * msq_w}


def pooled_track_draws(members: Sequence[str], coupon_draws: Mapping[str, Mapping[str, np.ndarray]], coupons: Mapping[str, Mapping[str, Any]]) -> dict[str, np.ndarray]:
    """Condition or one-condition group under the track bootstrap: mean over its coupons (same replicate index)."""

    by_condition: dict[str, list[str]] = {}
    for m in members:
        by_condition.setdefault(coupons[m]["condition"], []).append(m)
    cond_h = [np.mean([coupon_draws[m]["msq_H"] for m in ms], axis=0) for ms in by_condition.values()]
    cond_w = [np.mean([coupon_draws[m]["msq_W"] for m in ms], axis=0) for ms in by_condition.values()]
    stats = _from_msq(np.mean(cond_h, axis=0), np.mean(cond_w, axis=0))
    if len(members) == 1:
        stats["median_H_ratio"] = coupon_draws[members[0]]["median_H_ratio"]
        stats["median_W_ratio"] = coupon_draws[members[0]]["median_W_ratio"]
    else:
        counts = np.hstack([coupon_draws[m]["counts"] for m in members])
        offsets = np.cumsum([0] + [coupon_draws[m]["counts"].shape[1] for m in members])[:-1]
        unit = np.concatenate([coupon_draws[m]["_unit"] + off for m, off in zip(members, offsets)])
        stats["median_H_ratio"] = weighted_median(np.concatenate([coupon_draws[m]["_ratio_h"] for m in members]), unit, counts)
        stats["median_W_ratio"] = weighted_median(np.concatenate([coupon_draws[m]["_ratio_w"] for m in members]), unit, counts)
    return stats


def group_coupon_draws(analysis: Mapping[str, Any], replicates: int) -> dict[str, dict[str, np.ndarray]]:
    coupons = analysis["coupons"]
    out = {}
    for index, (name, group) in enumerate(analysis["groups"].items()):
        members = list(group["members"])
        if len(members) < 2:
            continue
        conditions = sorted({coupons[m]["condition"] for m in members})
        cond_index = np.array([conditions.index(coupons[m]["condition"]) for m in members])
        counts = C.draw_counts(C.rng(FAMILY_GROUP, index), len(members), replicates)
        comp_h, comp_w = C.weighted_group_components(
            np.array([coupons[m]["H_mean_sq_log"] for m in members]), np.array([coupons[m]["W_mean_sq_log"] for m in members]), cond_index, counts
        )
        frames = [f for m in members for f in analysis["frames_by_member"][m]]
        unit = np.array([k for k, m in enumerate(members) for _ in analysis["frames_by_member"][m]])
        ratio_h, ratio_w = _ratio_arrays(frames)
        out[name] = {
            "index": index,
            "counts": counts.astype(np.int16),
            **_from_msq(comp_h, comp_w),
            "median_H_ratio": weighted_median(ratio_h, unit, counts),
            "median_W_ratio": weighted_median(ratio_w, unit, counts),
        }
    return out


def _interval(draws: np.ndarray) -> list[float]:
    lo, hi = C.percentile_ci(draws)
    return [float(lo), float(hi)]


def run(analysis: Mapping[str, Any], replicates: int = C.BOOTSTRAP_REPLICATES) -> dict[str, Any]:
    coupons = analysis["coupons"]
    track = coupon_track_draws(analysis, replicates)
    group = group_coupon_draws(analysis, replicates)
    cis: dict[str, dict[str, Any]] = {"coupons": {}, "conditions": {}, "groups": {}, "ratios": {}}
    summary: list[dict[str, Any]] = []
    arrays: dict[str, dict[str, np.ndarray]] = {"coupon_track": {}, "group_coupon": {}, "ratios": {}}

    def record(scope: str, name: str, stats: Mapping[str, np.ndarray], point: Mapping[str, Any], unit: str, seed_keys: str) -> dict[str, Any]:
        intervals = {}
        for key in STATS:
            intervals[key] = _interval(stats[key])
            summary.append(
                {
                    "scope": scope, "name": name, "statistic": key, "point_estimate": point[key],
                    "ci_lo": intervals[key][0], "ci_hi": intervals[key][1], "resampling_unit": unit,
                    "replicates": replicates, "seed": C.SEED, "generator_keys": seed_keys,
                }
            )
        return {"unit": unit, "replicates": replicates, "intervals": intervals}

    for member, draws in track.items():
        stats = {**_from_msq(draws["msq_H"], draws["msq_W"]), "median_H_ratio": draws["median_H_ratio"], "median_W_ratio": draws["median_W_ratio"]}
        cis["coupons"][member] = record("coupon", member, stats, coupons[member], "track_within_coupon", f"[{C.SEED}, {FAMILY_TRACK}, {draws['index']}]")
        arrays["coupon_track"].update({f"{safe(member)}__{k}": v for k, v in stats.items()})
    for cid, row in analysis["conditions"].items():
        stats = pooled_track_draws(row["members"], track, coupons)
        keys = ", ".join(f"[{C.SEED}, {FAMILY_TRACK}, {track[m]['index']}]" for m in row["members"])
        cis["conditions"][cid] = record("condition", cid, stats, row, "track_within_coupon", keys)
    for name, row in analysis["groups"].items():
        if name in group:
            stats = group[name]
            cis["groups"][name] = record("group", name, stats, row, "coupon", f"[{C.SEED}, {FAMILY_GROUP}, {stats['index']}]")
            arrays["group_coupon"].update({f"{name}__{k}": stats[k] for k in STATS})
        else:
            stats = pooled_track_draws(row["members"], track, coupons)
            cis["groups"][name] = record("group", name, stats, row, "track_within_coupon", f"[{C.SEED}, {FAMILY_TRACK}, {track[row['members'][0]]['index']}]")

    # Reading-V ratios: held out / calibration (independent coupon draws), part_5 / calibration (track x coupon).
    cal, held = group["calibration"], group["in_window_held_out"]
    part5 = track[C.CROSS_CAMPAIGN]
    groups = analysis["groups"]
    for q in ("H", "W"):
        for name, num, point_num, unit in (
            ("held_out_over_calibration", held[f"e_{q}"], groups["in_window_held_out"][f"e_{q}"], "coupon (both groups, independent)"),
            ("part_5_over_calibration", np.sqrt(part5[f"msq_{q}"]), groups["cross_campaign_20260904_part_5"][f"e_{q}"], "track within 20260904:part_5; coupon within calibration"),
        ):
            draws = num / cal[f"e_{q}"]
            point = point_num / groups["calibration"][f"e_{q}"]
            lo, hi = _interval(draws)
            key = f"{name}__e_{q}"
            arrays["ratios"][key] = draws
            cis["ratios"][key] = {"point": point, "ci": [lo, hi], "unit": unit, "share_at_or_below_1_25": float(np.mean(draws <= 1.25))}
            summary.append(
                {
                    "scope": "v_ratio", "name": name, "statistic": f"e_{q} ratio", "point_estimate": point, "ci_lo": lo, "ci_hi": hi,
                    "resampling_unit": unit, "replicates": replicates, "seed": C.SEED, "generator_keys": "as the numerator and denominator draws",
                }
            )
    paths = {
        "coupon_track": save_npz(C.DATA_DIR / "bootstrap" / "D5_coupon_track_bootstrap.npz", arrays["coupon_track"]),
        "group_coupon": save_npz(C.DATA_DIR / "bootstrap" / "D5_group_coupon_bootstrap.npz", arrays["group_coupon"]),
        "ratios": save_npz(C.DATA_DIR / "bootstrap" / "D5_v_ratio_bootstrap.npz", arrays["ratios"]),
        "summary": C.write_csv(C.DATA_DIR / "bootstrap" / "D5_bootstrap_summary.csv", summary),
    }
    index = {
        "groups": {name: [C.SEED, FAMILY_GROUP, draws["index"]] for name, draws in group.items()},
        "coupons": {member: [C.SEED, FAMILY_TRACK, draws["index"]] for member, draws in track.items()},
    }
    return {"cis": cis, "paths": paths, "generator_index": index}
