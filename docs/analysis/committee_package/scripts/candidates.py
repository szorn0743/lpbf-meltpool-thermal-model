"""D6: the candidate-search archive, with an independent reconstruction of the selection; F4 and F14 sources.

The archive gathers, for all 19 calibrated candidates (17 frozen design points and 2 confirmation points), every
recorded parameter, objective value, diagnostic, coverage figure and failure flag, the per-coupon and per-condition
rows and the unit hashes, so that the selected point can be reconstructed without the runner:
- the selection rule (lowest measured J among candidates without a coverage flag) and the near-best set
  (J <= 1.10 J_min) are re-applied to the recorded scores;
- the quadratic surrogate is refitted on the 17 design points with the runner's own ``fit_quadratic`` and compared
  with the recorded fit (it proposes; it never selected);
- reading C (edge) is re-derived from the coded coordinates and the guard.
The per-candidate peak temperatures come from the gitignored calibrate and confirm unit files, each checked against
its manifest sha256.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Mapping

import numpy as np

import common as C

GRID = 61
GUARD_GRID = 41
SLICES = (("t_ck", 0, 1, 2), ("t_eta", 0, 2, 1), ("ck_eta", 1, 2, 0))  # name, x axis, y axis, fixed axis (coded index)
COORDS = ("abs_depth_identifiable_coordinate", "liquid_conductivity_enhancement_factor", "eta_directional")


def _stage_units() -> dict[tuple[str, str], dict[str, Any]]:
    out = {}
    for stage, path in (("calibrate", C.CALIBRATE_MANIFEST), ("confirm", C.CONFIRM_MANIFEST)):
        manifest = C.load_json(path)
        for u in manifest["units"]:
            out[(u["candidate_id"], u["member_identity"])] = {**u, "stage": stage, "stage_commit": manifest["provenance"]["git_commit"]}
    return out


def _unit_file(stage: str, candidate: str, member: str):
    folder = C.CALIBRATE_UNITS_DIR if stage == "calibrate" else C.CONFIRM_UNITS_DIR
    return folder / f"{candidate}__{member.replace(':', '_')}.json"


def unit_peaks(units: Mapping[tuple[str, str], Mapping[str, Any]]) -> dict[tuple[str, str], np.ndarray]:
    """Per (candidate, member): peak top-surface temperature of every scored frame, from sha-checked unit files."""

    out = {}
    for key, u in units.items():
        path = _unit_file(u["stage"], *key)
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != u["unit_sha256"]:
            raise RuntimeError(f"{path.name}: sha256 differs from the {u['stage']} manifest")
        out[key] = np.array([float(v) for v in json.loads(raw)["peak_surface_temperature_K_by_frame"].values()])
    return out


def archive() -> dict[str, Any]:
    from lpbf.calibration_contract import _abs_depth_mapping

    reading = C.load_json(C.CALIBRATION_READING)
    freeze = C.load_json(C.SELECTION_FREEZE)
    scores = reading["scores"]
    units = _stage_units()
    peaks = unit_peaks(units)
    predicted = {c["candidate_id"]: c["predicted_J"] for c in reading["surrogate"]["confirmation_candidates"]}
    rank = {r["candidate_id"]: k + 1 for k, r in enumerate(reading["selection"]["ranking"])}
    near = set(reading["selection"]["near_best"])
    candidates, coupons, conditions, unit_rows = [], [], [], []
    for cand in reading["candidates"]:
        cid = cand["candidate_id"]
        s = scores[cid]
        alpha, depth = _abs_depth_mapping(cand["coordinates"]["abs_depth_identifiable_coordinate"])
        cand_units = {m: u for (c, m), u in units.items() if c == cid}
        all_peaks = np.concatenate([peaks[(cid, m)] for m in sorted(cand_units, key=C.member_key)])
        if not math.isclose(float(np.mean(all_peaks > C.BOILING_K)), s["fraction_peak_above_boiling"], abs_tol=1e-15):
            raise RuntimeError(f"{cid}: peak fraction from the unit files differs from the recorded score")
        candidates.append(
            {
                "candidate": cid, "origin": cand["origin"], "stage": next(iter(cand_units.values()))["stage"], "stage_commit": next(iter(cand_units.values()))["stage_commit"],
                "t": cand["coordinates"][COORDS[0]], "ck": cand["coordinates"][COORDS[1]], "eta": cand["coordinates"][COORDS[2]],
                "coded_x1": cand["coded"][0], "coded_x2": cand["coded"][1], "coded_x3": cand["coded"][2],
                "absorptivity": alpha, "deposition_depth_mm": depth, "guard_value": cand["guard_value"],
                "status": s["status"], "failures": "; ".join(s["failures"]), "penalty_applied": s["penalty_applied"],
                "J": s["J"], "e_H": s["e_H"], "e_W": s["e_W"], "H_component": s["H_component"], "W_component": s["W_component"],
                "J_pixel_22_3_7": s["sensitivity"]["pixel_22_3_7"], "pixel_22_3_7_status": s["sensitivity"]["pixel_22_3_7_status"],
                "coverage": s["coverage"], "coverage_flag": s["coverage_flag"], "low_coverage_coupons": " ".join(s["low_coverage_coupons"]),
                "scored_frames": s["scored_frame_count"], "captured_frames": s["captured_frame_count"], "floored_frames": s["floored_frame_count"],
                "floored_H": s["floored_by_quantity"].get("H"), "floored_W": s["floored_by_quantity"].get("W"),
                "no_pool_frames": s["zero_prediction_frame_count"], "no_laser_associated_melt": s["no_laser_associated_melt_count"],
                "production_status_counts": json.dumps(s["production_status_counts"], sort_keys=True),
                "fraction_peak_above_boiling": s["fraction_peak_above_boiling"], "median_peak_surface_K": s["median_peak_surface_K"],
                "rank_by_J": rank[cid], "near_best": cid in near, "selected": cid == freeze["selected"]["candidate_id"],
                "surrogate_predicted_J": predicted.get(cid),
            }
        )
        for row in s["coupon_rows"]:
            m = row["member_identity"]
            pk = peaks[(cid, m)]
            coupons.append(
                {
                    "candidate": cid, "member": m, "condition": row["exact_condition_id"], "scored_frames": row["scored_frame_count"],
                    "coverage": row["coverage"], "e_H": row["e_H"], "e_W": row["e_W"], "J_coupon": row["coupon_scalar_objective"],
                    "median_r_H": row["median_r_H"], "median_r_W": row["median_r_W"], "median_H_ratio": row["median_H_ratio"],
                    "median_W_ratio": row["median_W_ratio"], "floored_frames": row["floored_frame_count"],
                    "median_peak_surface_K": float(np.median(pk)), "fraction_peak_above_boiling": float(np.mean(pk > C.BOILING_K)),
                    "p95_peak_surface_K": float(np.percentile(pk, 95)),
                }
            )
        for row in s["condition_rows"]:
            conditions.append({"candidate": cid, **{k: (" ".join(v) if isinstance(v, list) else v) for k, v in row.items()}})
        for m, u in sorted(cand_units.items(), key=lambda item: C.member_key(item[0])):
            unit_rows.append(
                {
                    "candidate": cid, "member": m, "stage": u["stage"], "work_unit_id": u["work_unit_id"], "ok": u["ok"],
                    "requested_frames": u["requested_frame_count"], "returned_frames": u["returned_frame_count"], "captured_frames": u["captured_frame_count"],
                    "gate_failures": "; ".join(u["gate_failures"]), "unit_sha256": u["unit_sha256"], "unit_file_checked": True,
                }
            )
    return {"candidates": candidates, "coupons": coupons, "conditions": conditions, "units": unit_rows, "reading": reading, "freeze": freeze}


def reconstruct(arch: Mapping[str, Any]) -> dict[str, Any]:
    from lpbf.patch22_4_3_2_window_calibration import EDGE_CODED, EDGE_GUARD_FRACTION, NEAR_BEST_FACTOR, fit_quadratic, guard_maximum

    reading, freeze = arch["reading"], arch["freeze"]
    rows = {r["candidate"]: r for r in arch["candidates"]}
    eligible = [r for r in rows.values() if not r["coverage_flag"] and r["status"] == "PASS"]
    best = min(eligible, key=lambda r: r["J"])
    j_min = best["J"]
    near = sorted(r["candidate"] for r in eligible if r["J"] <= NEAR_BEST_FACTOR * j_min)
    design = [c for c in reading["candidates"] if c["origin"] == "frozen_design"]
    fit = fit_quadratic([c["coded"] for c in design], [reading["scores"][c["candidate_id"]]["J"] for c in design])
    recorded = reading["surrogate"]["fit"]
    coef_diff = max(abs(a - b) for a, b in zip(fit["coefficients"], recorded["coefficients"]))
    sel = rows[best["candidate"]]
    coded = (sel["coded_x1"], sel["coded_x2"], sel["coded_x3"])
    edge_coords = [name for name, x in zip(COORDS, coded) if abs(x) >= EDGE_CODED]
    guard_edge = sel["guard_value"] >= EDGE_GUARD_FRACTION * guard_maximum()
    out = {
        "rule": "lowest measured J among candidates with status PASS and no coverage flag; near-best: J <= 1.10 J_min (plan 22.4.3.2)",
        "candidates_scored": len(rows), "candidates_eligible": len(eligible),
        "selected_reconstructed": best["candidate"], "selected_recorded": freeze["selected"]["candidate_id"],
        "J_min_reconstructed": j_min, "J_min_recorded": freeze["J_min"],
        "near_best_reconstructed": near, "near_best_recorded": sorted(c["candidate_id"] for c in freeze["near_best"]),
        "surrogate_refit": {
            "points": fit["point_count"], "r_squared": fit["r_squared"], "loo_rmse": fit["loo_rmse"],
            "r_squared_recorded": recorded["r_squared"], "loo_rmse_recorded": recorded["loo_rmse"], "max_abs_coefficient_difference": coef_diff,
        },
        "reading_C": {
            "coordinates_at_edge_reconstructed": edge_coords, "coordinates_at_edge_recorded": freeze["edge"]["coordinates_at_edge"],
            "guard_value": sel["guard_value"], "guard_edge_threshold": EDGE_GUARD_FRACTION * guard_maximum(), "guard_at_edge": guard_edge,
            "reading_reconstructed": "C_EDGE" if edge_coords or guard_edge else "C_INTERIOR", "reading_recorded": freeze["reading_C"],
        },
        "freeze_content_sha256": freeze["content_sha256"],
    }
    ok = (
        out["selected_reconstructed"] == out["selected_recorded"]
        and out["J_min_reconstructed"] == out["J_min_recorded"]
        and out["near_best_reconstructed"] == out["near_best_recorded"]
        and coef_diff < 1e-9
        and edge_coords == list(freeze["edge"]["coordinates_at_edge"])
        and out["reading_C"]["reading_reconstructed"] == out["reading_C"]["reading_recorded"]
    )
    if not ok:
        raise RuntimeError(f"selection reconstruction disagrees with the freeze: {out}")
    out["status"] = "PASS"
    return out


def surface_grids(arch: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """F4: the recorded surrogate on three slices through c1, and the coupled guard on the same slices."""

    from lpbf.patch22_4_3_2_window_calibration import CODED_CENTER, CODED_HALF_RANGE, candidate_admissibility, guard_maximum, surrogate_value

    beta = arch["reading"]["surrogate"]["fit"]["coefficients"]
    c1 = next(r for r in arch["candidates"] if r["selected"])
    c1_coded = np.array([c1["coded_x1"], c1["coded_x2"], c1["coded_x3"]])

    cache: dict[tuple[float, float, float], float] = {}

    def guard(coded: np.ndarray) -> float:
        key = tuple(round(float(x), 12) for x in coded)
        if key not in cache:
            coords = {name: c + h * float(x) for name, c, h, x in zip(COORDS, CODED_CENTER, CODED_HALF_RANGE, coded)}
            cache[key] = float(candidate_admissibility(coords)["guard_value"])
        return cache[key]

    # The guard does not depend on t (closed-form directional bound); confirm on three t values before using it.
    for probe in ((0.3, 0.7), (-0.6, 0.9), (1.0, 1.0)):
        values = {round(guard(np.array([t, *probe])), 15) for t in (-1.0, 0.0, 1.0)}
        if len(values) != 1:
            raise RuntimeError("guard value depends on t")
    axis = np.linspace(-1.0, 1.0, GRID)
    gaxis = np.linspace(-1.0, 1.0, GUARD_GRID)
    surface, guard_rows = [], []
    for name, ix, iy, ifix in SLICES:
        for y in axis:
            for x in axis:
                point = c1_coded.copy()
                point[ix], point[iy] = x, y
                surface.append({"slice": name, "x_coded": float(x), "y_coded": float(y), "fixed_coded": float(c1_coded[ifix]), "J_surrogate": float(surrogate_value(beta, point))})
        for y in gaxis:
            for x in gaxis:
                point = c1_coded.copy()
                point[ix], point[iy] = x, y
                if name == "t_ck" or name == "t_eta":
                    point[0] = 0.0  # guard is independent of t; evaluate once per (ck, eta)
                guard_rows.append({"slice": name, "x_coded": float(x), "y_coded": float(y), "guard_value": guard(point)})
    meta = {"guard_maximum": guard_maximum(), "grid": GRID, "guard_grid": GUARD_GRID, "c1_coded": c1_coded.tolist(), "slices": [s[0] for s in SLICES]}
    return surface, guard_rows, meta


def run() -> dict[str, Any]:
    arch = archive()
    recon = reconstruct(arch)
    surface, guard_rows, meta = surface_grids(arch)
    folder = C.DATA_DIR / "D6_candidate_search"
    paths = {
        "candidates": C.write_csv(folder / "D6_candidates.csv", arch["candidates"]),
        "coupons": C.write_csv(folder / "D6_candidate_coupons.csv", arch["coupons"]),
        "conditions": C.write_csv(folder / "D6_candidate_conditions.csv", arch["conditions"]),
        "units": C.write_csv(folder / "D6_candidate_units.csv", arch["units"]),
        "reconstruction": C.write_json(folder / "D6_selection_reconstruction.json", recon),
        "surface": C.write_csv(C.FIGURES_DIR / "source" / "F4_surrogate_slices.csv", surface),
        "guard": C.write_csv(C.FIGURES_DIR / "source" / "F4_guard_slices.csv", guard_rows),
        "surface_meta": C.write_json(C.FIGURES_DIR / "source" / "F4_surface_meta.json", meta),
    }
    return {"archive": arch, "reconstruction": recon, "surface": surface, "guard": guard_rows, "meta": meta, "paths": paths}
