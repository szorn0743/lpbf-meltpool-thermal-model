"""T12: where the variation sits, the effective sample size, and the model's within-coupon explanatory power.

A. Variance partition. The frame-weighted sum of squares of each quantity splits exactly into within-track,
   between-track (within coupon), between-coupon (within condition, i.e. the 0730/0731 day difference) and
   between-condition parts. The shares say at which level the data vary.
B. Effective sample size. One-way random-effects ICC with coupons (or tracks) as clusters, the design effect
   1 + (m - 1) ICC and N / deff. Frames are not independent observations; the inferential unit is the coupon.
C. Within-coupon explanatory power (plan Part 1, item 4). Per coupon, the rank correlation of model and camera H
   (and W) across frames and across track medians, and a permutation control: camera values are shuffled across the
   coupon's scored frames (the model's frames stay in place, family 6), and the coupon e is recomputed through the
   same track hierarchy. If the actual e is no lower than the shuffled e, the model's frame-to-frame variation inside
   a coupon carries no information about the camera's.
"""
from __future__ import annotations

import math
from statistics import median
from typing import Any, Mapping, Sequence

import numpy as np

import common as C

FAMILY_PERMUTATION = 6
PERMUTATIONS = 1000
QUANTITIES = (
    ("r_H", "r_H (log residual)", False),
    ("r_W", "r_W (log residual)", False),
    ("ln_cam_H", "ln camera H", False),
    ("ln_cam_W", "ln camera W", False),
    ("ln_sim_H", "ln model H (pool frames)", True),
    ("ln_sim_W", "ln model W (pool frames)", True),
)


def _value(f: Mapping[str, Any], key: str) -> float | None:
    if key in ("r_H", "r_W"):
        return float(f[key])
    if key.startswith("ln_sim") and f["no_pool"]:
        return None
    source = {"ln_cam_H": "cam_H_px", "ln_cam_W": "cam_W_px", "ln_sim_H": "sim_H_px", "ln_sim_W": "sim_W_px"}[key]
    return math.log(float(f[source]))


def partition(frames: Sequence[Mapping[str, Any]], key: str) -> dict[str, float]:
    """Exact frame-weighted SS decomposition: track, coupon and condition means nested."""

    rows = [(f["condition"], f["member"], f["scan_track_id"], v) for f in frames if (v := _value(f, key)) is not None]
    y = np.array([r[3] for r in rows])
    grand = y.mean()

    def means(level: int) -> dict[tuple, tuple[float, int]]:
        acc: dict[tuple, list[float]] = {}
        for r in rows:
            acc.setdefault(r[: level + 1], []).append(r[3])
        return {k: (float(np.mean(v)), len(v)) for k, v in acc.items()}

    cond, coup, track = means(0), means(1), means(2)
    ss_within = float(sum((r[3] - track[r[:3]][0]) ** 2 for r in rows))
    ss_track = float(sum(n * (m - coup[k[:2]][0]) ** 2 for k, (m, n) in track.items()))
    ss_coupon = float(sum(n * (m - cond[k[:1]][0]) ** 2 for k, (m, n) in coup.items()))
    ss_condition = float(sum(n * (m - grand) ** 2 for (m, n) in cond.values()))
    total = float(((y - grand) ** 2).sum())
    if not math.isclose(ss_within + ss_track + ss_coupon + ss_condition, total, rel_tol=1e-9):
        raise RuntimeError(f"{key}: sum-of-squares partition does not add up")
    return {
        "frames": len(rows), "tracks": len(track), "coupons": len(coup), "conditions": len(cond), "total_variance": total / (len(rows) - 1),
        "share_within_track": ss_within / total, "share_between_tracks_within_coupon": ss_track / total,
        "share_between_coupons_within_condition": ss_coupon / total, "share_between_conditions": ss_condition / total,
    }


def icc(values: Sequence[float], clusters: Sequence[Any]) -> dict[str, float]:
    """One-way random-effects ICC (ANOVA estimator, unbalanced n0), design effect and effective N."""

    groups: dict[Any, list[float]] = {}
    for v, c in zip(values, clusters):
        groups.setdefault(c, []).append(v)
    y = np.asarray(values, dtype=float)
    n_total, k = y.size, len(groups)
    grand = y.mean()
    ssb = sum(len(g) * (np.mean(g) - grand) ** 2 for g in groups.values())
    ssw = sum(((np.asarray(g) - np.mean(g)) ** 2).sum() for g in groups.values())
    msb, msw = ssb / (k - 1), ssw / (n_total - k)
    n0 = (n_total - sum(len(g) ** 2 for g in groups.values()) / n_total) / (k - 1)
    rho = (msb - msw) / (msb + (n0 - 1) * msw)
    mean_size = n_total / k
    deff = 1.0 + (mean_size - 1.0) * max(rho, 0.0)
    return {"clusters": k, "frames": n_total, "mean_cluster_size": mean_size, "icc": float(rho), "design_effect": float(deff), "effective_n": float(n_total / deff)}


def effective_rows(analysis: Mapping[str, Any]) -> list[dict[str, Any]]:
    groups = C.group_members()
    rows = []
    for name in ("calibration", "in_window_held_out", "out_of_window_all", "all_24"):
        members = set(groups[name])
        frames = [f for f in analysis["scored"] if f["member"] in members]
        row: dict[str, Any] = {
            "group": name, "label": C.GROUP_LABEL[name], "frames": len(frames),
            "tracks": len({(f["member"], f["scan_track_id"]) for f in frames}), "coupons": len(members),
            "conditions": len({f["condition"] for f in frames}),
        }
        for q in ("H", "W"):
            values = [f[f"r_{q}"] for f in frames]
            by_coupon = icc(values, [f["member"] for f in frames])
            by_track = icc(values, [(f["member"], f["scan_track_id"]) for f in frames])
            row.update(
                {
                    f"icc_coupon_r_{q}": by_coupon["icc"], f"deff_coupon_r_{q}": by_coupon["design_effect"], f"n_eff_coupon_r_{q}": by_coupon["effective_n"],
                    f"icc_track_r_{q}": by_track["icc"], f"deff_track_r_{q}": by_track["design_effect"], f"n_eff_track_r_{q}": by_track["effective_n"],
                }
            )
        row["mean_frames_per_coupon"] = len(frames) / len(members)
        rows.append(row)
    return rows


# ---------------------------------------------------------------------- within-coupon explanatory power


def _coupon_arrays(tracks: Sequence[Mapping[str, Any]], q: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    sim, cam, starts = [], [], []
    for t in tracks:
        starts.append(len(sim))
        for f in t["frames"]:
            sim.append(math.log(max(float(f[f"sim_{q}_px"]), C.PIXEL_FLOOR)))
            cam.append(math.log(max(float(f[f"cam_{q}_px"]), C.PIXEL_FLOOR)))
    return np.array(sim), np.array(cam), np.array(starts)


def _coupon_msq(sim: np.ndarray, cam_matrix: np.ndarray, starts: np.ndarray) -> np.ndarray:
    """Coupon mean over tracks of the track mean of (sim - cam)^2, for each row of ``cam_matrix``."""

    sq = (sim[None, :] - cam_matrix) ** 2
    sums = np.add.reduceat(sq, starts, axis=1)
    sizes = np.diff(np.append(starts, sim.size))
    return (sums / sizes).mean(axis=1)


def explanatory_rows(analysis: Mapping[str, Any], permutations: int = PERMUTATIONS) -> list[dict[str, Any]]:
    tracks_by: dict[str, list] = {}
    for t in analysis["tracks"]:
        tracks_by.setdefault(t["member"], []).append(t)
    order = sorted(C.ROLE, key=C.member_key)
    rows = []
    for member in order:
        tracks = tracks_by[member]
        row: dict[str, Any] = {"member": member, "role": C.ROLE[member], "ved_J_mm3": analysis["record"][member]["ved_J_mm3"], "tracks": len(tracks)}
        generator = C.rng(FAMILY_PERMUTATION, order.index(member))
        n = sum(len(t["frames"]) for t in tracks)
        perms = generator.permuted(np.tile(np.arange(n), (permutations, 1)), axis=1)
        for q in ("H", "W"):
            pool = [(float(f[f"sim_{q}_px"]), float(f[f"cam_{q}_px"])) for t in tracks for f in t["frames"] if not f["no_pool"]]
            row[f"frame_spearman_{q}"] = C.spearman([p[0] for p in pool], [p[1] for p in pool])
            track_pairs = []
            for t in tracks:
                values = [(float(f[f"sim_{q}_px"]), float(f[f"cam_{q}_px"])) for f in t["frames"] if not f["no_pool"]]
                if len(values) >= 3:
                    track_pairs.append((median(v[0] for v in values), median(v[1] for v in values)))
            row[f"track_spearman_{q}"] = C.spearman([p[0] for p in track_pairs], [p[1] for p in track_pairs])
            row[f"tracks_used_{q}"] = len(track_pairs)
            sim, cam, starts = _coupon_arrays(tracks, q)
            actual = float(_coupon_msq(sim, cam[None, :], starts)[0])
            shuffled = _coupon_msq(sim, cam[perms], starts)
            row[f"e_{q}_actual"] = math.sqrt(actual)
            row[f"e_{q}_shuffled_mean"] = float(np.sqrt(shuffled).mean())
            row[f"e_{q}_actual_over_shuffled"] = math.sqrt(actual) / float(np.sqrt(shuffled).mean())
            row[f"p_{q}_shuffled_at_or_below_actual"] = float((1 + np.sum(shuffled <= actual)) / (permutations + 1))
            if not math.isclose(math.sqrt(actual), analysis["coupons"][member][f"e_{q}"], rel_tol=1e-12):
                raise RuntimeError(f"{member}: vectorised coupon e_{q} differs from the hierarchy")
        row["permutations"] = permutations
        row["generator_keys"] = f"[{C.SEED}, {FAMILY_PERMUTATION}, {order.index(member)}]"
        rows.append(row)
    return rows


def explanatory_summary(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    groups = C.group_members()
    out = []
    for name in ("calibration", "in_window_held_out", "out_of_window_all", "all_24"):
        sub = [r for r in rows if r["member"] in set(groups[name])]
        item: dict[str, Any] = {"group": name, "label": C.GROUP_LABEL[name], "coupons": len(sub)}
        for q in ("H", "W"):
            item[f"median_frame_spearman_{q}"] = float(median(r[f"frame_spearman_{q}"] for r in sub))
            item[f"median_track_spearman_{q}"] = float(median(r[f"track_spearman_{q}"] for r in sub))
            item[f"median_e_{q}_actual_over_shuffled"] = float(median(r[f"e_{q}_actual_over_shuffled"] for r in sub))
            item[f"coupons_p_{q}_below_0_05"] = sum(1 for r in sub if r[f"p_{q}_shuffled_at_or_below_actual"] < 0.05)
        out.append(item)
    return out


def run(analysis: Mapping[str, Any]) -> dict[str, Any]:
    part = []
    for scope, members in (("all_24", set(C.ROLE)), ("calibration", set(C.ROLE_MEMBERS["calibration"]))):
        frames = [f for f in analysis["scored"] if f["member"] in members]
        for key, label, _ in QUANTITIES:
            part.append({"scope": scope, "quantity": key, "label": label, **partition(frames, key)})
    effective = effective_rows(analysis)
    explanatory = explanatory_rows(analysis)
    summary = explanatory_summary(explanatory)
    paths = {
        "partition": C.write_csv(C.DATA_DIR / "T12_variance_partition.csv", part),
        "effective": C.write_csv(C.DATA_DIR / "T12_effective_sample_size.csv", effective),
        "explanatory": C.write_csv(C.DATA_DIR / "T12_within_coupon_power.csv", explanatory),
        "explanatory_summary": C.write_csv(C.DATA_DIR / "T12_within_coupon_power_summary.csv", summary),
    }
    return {"partition": part, "effective": effective, "explanatory": explanatory, "explanatory_summary": summary, "paths": paths}
