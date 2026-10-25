"""Thesis tables T1-T10 (thesis list numbering).

Model and numerical values are read from the code the Patch 22.4.3.2 runner imported (as committee T05 does); data
values from the committee package's datasets. Setup facts that the repository and the coupon files do not record
(machine, wavelength, feedstock, plate, atmosphere, fume extraction, coupon height and layer count, exposure) are the
owner's experimental record as written in thesis section 3.2.1 and are marked "owner" in the CSV and Markdown.

Each table is a dict: id, name, title, columns, rows (display strings), notes (printed under the table in the thesis
document), provenance (Markdown only), csv_header and csv_rows (full precision).
"""
from __future__ import annotations

import math
import re

import numpy as np

import data as D
import style as S

OWNER = "owner (thesis section 3.2.1); not recorded in the repository or the coupon files"


def _ci(v, lo, hi, nd=3) -> str:
    return f"{v:.{nd}f} [{lo:.{nd}f}, {hi:.{nd}f}]"


def _pct(v, nd=1) -> str:
    return f"{v:.{nd}f} %"


def _date(s: str) -> str:
    y, m, d = s.split("-")
    return f"{['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][int(m) - 1]} {int(d)}"


CAMPAIGN = {
    "20260730": "Jul 30, repeated set",
    "20260731": "Jul 31, repeated set",
    "20260904": "Sep 4, speed sweep",
    "20260910": "Sep 10, power sweep",
}
ROLE_TEXT = {
    "calibration": "Calibration",
    "in_window_held_out": "Held out, in window",
    "out_of_window_examined": "Out of window, examined",
    "out_of_window_blind": "Out of window, blind",
}


def _cond_label(c: dict) -> str:
    return f"{c['power_W']:.0f} W, {c['speed_mm_s']:.0f} mm/s"


# ---------------------------------------------------------------------- T1


def t1_setup() -> dict:
    from lpbf.model._accepted_core.parameters import MACHINE_SPOT_DIAMETER_UM
    from lpbf.model.input_data import PRODUCTION_DAQ_FREQUENCY_HZ

    cps = D.coupons()
    rec = D.process_record()
    spots = {r["Spot Size (mm)"] for r in rec}
    assert spots == {0.08} and abs(MACHINE_SPOT_DIAMETER_UM - 80.0) < 1e-9
    p = [c["power_W"] for c in cps]
    v = [c["speed_mm_s"] for c in cps]
    e = [c["ved_J_mm3"] for c in cps]
    rows = [
        ("Machine", "Aconity Mini laser powder bed fusion system", OWNER),
        ("Laser wavelength", "1070 nm", OWNER),
        ("Laser spot diameter (nominal)", f"{MACHINE_SPOT_DIAMETER_UM:.0f} µm, all coupons", "process record (A17)"),
        ("Feedstock", "m4p 316L.03 stainless steel powder", OWNER),
        ("Build plate", "316L stainless steel", OWNER),
        ("Atmosphere", "Argon, O₂ < 300 ppm", OWNER),
        ("Fume extraction", "Pump at 50 % duty cycle", OWNER),
        ("Coupon geometry (programmed)", "≈ 4 mm × 4 mm × 6.48 mm",
         OWNER + "; footprint consistent with the HDF5 part boundaries (4.10–4.30 mm × 4.05–4.10 mm)"),
        ("Layers per coupon", "216", OWNER),
        ("Layer thickness", f"{S.C.LAYER_MM * 1000:.0f} µm", "A17; committee common.LAYER_MM"),
        ("Hatch spacing", f"{S.C.HATCH_MM * 1000:.0f} µm", "A17; committee common.HATCH_MM"),
        ("Scan strategy", "Contour pass, then hatch infill; hatch direction rotates by 45° between layers "
                          "(0°, 45°, 90°, 135°)", OWNER + "; rotation seen in layers 51–53 of the coupon files"),
        ("Layer analysed", "Layer 53 of every coupon; 54 laser-on scan tracks per coupon (track 1 = contour)",
         "full_coupon_dataset_manifest.json; HDF5 Laser Drive"),
        ("Laser power", f"{min(p):.0f}–{max(p):.0f} W", "process record (A17)"),
        ("Scan speed", f"{min(v):.0f}–{max(v):.0f} mm/s", "process record (A17)"),
        ("Volumetric energy density", f"{min(e):.1f}–{max(e):.1f} J/mm³ (24 coupons, "
                                      f"{len({c['condition'] for c in cps})} conditions)", "computed, P / (v h t)"),
        ("Process data acquisition", f"{PRODUCTION_DAQ_FREQUENCY_HZ / 1000:.0f} kHz", "lpbf.model.input_data"),
        ("Coaxial camera", "Teledyne DALSA Genie Nano M640-NIR, 8-bit; 64 × 24 px region; ≈ 8 kHz; 40 µs exposure",
         "ledger A24 (exposure: owner); HDF5 gige_image"),
        ("Camera scale (nominal)", f"{S.UM_PER_PX:.0f} µm/px, not independently calibrated", "ledger A24"),
    ]
    return {
        "id": "T1", "name": "T1_lpbf_setup", "title": "LPBF experimental setup and fixed process parameters",
        "columns": ["Parameter", "Value"], "rows": [[a, b] for a, b, _ in rows], "widths": [0.34, 0.66],
        "notes": [],
        "provenance": ["Rows marked 'owner' come from the thesis draft (section 3.2.1) and the owner's experimental "
                       "record; the repository and the coupon HDF5 files do not record them. The HDF5 field "
                       "'n_layers_hit' (199–214) counts segmented layers and is not the design layer count."],
        "csv_header": ["parameter", "value", "source"], "csv_rows": [list(r) for r in rows],
    }


# ---------------------------------------------------------------------- T2


def t2_matrix() -> dict:
    cps = sorted(D.coupons(), key=lambda c: (c["acquisition_set"], c["part"]))
    count = {}
    for c in cps:
        count[c["condition"]] = count.get(c["condition"], 0) + 1
    rows, csv_rows = [], []
    for c in cps:
        rep = "repeated (Jul 30 and Jul 31)" if count[c["condition"]] == 2 else "single"
        rows.append([_date(c["acquisition_date"]), str(c["part"]), f"{c['power_W']:.0f}", f"{c['speed_mm_s']:.0f}",
                     f"{c['ved_J_mm3']:.1f}", CAMPAIGN[str(c["acquisition_set"])].split(", ")[1],
                     "×2" if count[c["condition"]] == 2 else "–", ROLE_TEXT[c["role"]]])
        csv_rows.append([c["member"], c["acquisition_date"], c["part"], c["power_W"], c["speed_mm_s"], c["ved_J_mm3"],
                         CAMPAIGN[str(c["acquisition_set"])], c["condition"], rep, c["a8_role"], c["role"],
                         c["scored_frames"], c["tracks_scored"]])
    n = {r: sum(1 for c in cps if c["role"] == r) for r in S.ROLE_ORDER}
    return {
        "id": "T2", "name": "T2_coupon_matrix", "title": "Experimental coupon matrix",
        "columns": ["Date (2026)", "Part", "P (W)", "v (mm/s)", "VED (J/mm³)", "Campaign", "Replicate", "Analysis role"],
        "rows": rows, "widths": [0.10, 0.06, 0.07, 0.10, 0.10, 0.16, 0.13, 0.28],
        "notes": ["VED = P / (v h t) with h = 0.080 mm and t = 0.030 mm. ×2: the same condition was built on Jul 30 "
                  "and Jul 31. Roles: calibration " f"{n['calibration']}, held out in window "
                  f"{n['in_window_held_out']}, out of window examined {n['out_of_window_examined']}, out of window "
                  f"blind {n['out_of_window_blind']} coupons."],
        "provenance": ["P, v and spot size are the read-only process record (docs/reference/LPBF_Process_Parameters.csv, "
                       "ledger A17); roles are ledger A25."],
        "csv_header": ["coupon", "date", "part", "power_W", "speed_mm_s", "ved_J_mm3", "campaign", "condition",
                       "replicate", "a8_role", "analysis_role", "scored_frames", "tracks_scored"],
        "csv_rows": csv_rows,
    }


# ---------------------------------------------------------------------- T3


def t3_channels() -> dict:
    """The owner's channel table, verbatim (owner, 2026-10-23: 'contain only this data')."""

    rows = [
        ["Laser Drive", "Laser drive/state", "64-bit float", "200 kHz", "V",
         "Laser-state determination; ≥ 2.5 V = laser on, < 2.5 V = laser off"],
        ["Sync Pulse", "Synchronization channel", "64-bit float", "200 kHz", "—",
         "Recorded synchronization channel; not directly used in present analysis"],
        ["X-Machine", "Mapped machine X coordinate", "64-bit float", "200 kHz", "mm", "Machine/build plate coordinate"],
        ["Y-Machine", "Mapped machine Y coordinate", "64-bit float", "200 kHz", "mm", "Machine/build plate coordinate"],
        ["Coaxial GigE camera", "Coaxial melt-pool image", "8-bit grayscale (uint8), 24 × 64 pixels", "8 kHz",
         "Dimensionless intensity (0–255)", "Source imagery for experimental melt-pool geometry"],
        ["H", "Threshold derived major axis dimension", "64-bit float", "8 kHz-Derived", "pixels",
         "Experimental melt pool major axis dimension"],
        ["W", "Threshold derived minor axis dimension", "64-bit float", "8 kHz-Derived", "pixels",
         "Experimental melt pool minor axis dimension"],
    ]
    return {
        "id": "T3", "name": "T3_data_channels", "title": "Recorded data channels and their roles",
        "columns": ["Process Channel", "Description", "Format", "Acquisition Rate", "Unit", "Role in present study"],
        "rows": rows, "widths": [0.14, 0.18, 0.17, 0.12, 0.14, 0.25],
        "notes": [],
        "provenance": ["Content supplied by the owner (2026-10-23) and reproduced as given. The code's laser-on rule is "
                       "strict, Laser Drive > 2.5 V (lpbf.model.input_data); the signal is binary 0/5 V, so the two "
                       "wordings select the same frames."],
        "csv_header": ["process_channel", "description", "format", "acquisition_rate", "unit", "role"],
        "csv_rows": rows,
    }


# ---------------------------------------------------------------------- T4


def t4_material() -> dict:
    from lpbf.model.parameters import get_model_parameters

    m = get_model_parameters().material
    c1 = next(c for c in D.candidates() if c["selected"])
    rows = [
        ["Density", "ρ", f"{m.density_kg_m3:g}", "kg/m³", "constant"],
        ["Solidus temperature", "T_s", f"{m.T_solidus_K:.2f}", "K", f"{m.T_solidus_K - 273.15:.0f} °C"],
        ["Liquidus temperature", "T_l", f"{m.T_liquidus_K:.2f}", "K", f"{m.T_liquidus_K - 273.15:.0f} °C"],
        ["Boiling temperature", "T_b", f"{m.T_boiling_K:.2f}", "K", "threshold of the boiling regulator"],
        ["Latent heat of fusion", "L", f"{m.latent_heat_fusion_J_kg:,.0f}", "J/kg",
         f"spread over the {m.mushy_temperature_interval_K:g} K mushy interval"],
        ["Specific heat, solid", "c_p,s", f"{m.cp_solid_J_kgK:g}", "J/(kg·K)", "T ≤ T_s"],
        ["Specific heat, mushy (sensible)", "c_p,m", f"{m.cp_mushy_J_kgK:g}", "J/(kg·K)", "T_s < T < T_l"],
        ["Specific heat, mushy (effective)", "c_p,eff", f"{m.cp_eff_mushy_J_kgK:,.0f}", "J/(kg·K)",
         "c_p,m + L / (T_l − T_s)"],
        ["Specific heat, liquid", "c_p,l", f"{m.cp_liquid_J_kgK:g}", "J/(kg·K)", "T ≥ T_l"],
        ["Conductivity, solid", "k_s", f"{m.k_solid_W_mK:g}", "W/(m·K)", "T ≤ T_s"],
        ["Conductivity, mushy", "k_m", f"{m.k_mushy_W_mK:g}", "W/(m·K)", "T_s < T < T_l"],
        ["Conductivity, liquid", "k_l", f"{m.k_liquid_W_mK:g}", "W/(m·K)",
         f"multiplied by c_k (calibrated; {c1['ck']:.3f} × {m.k_liquid_W_mK:g} = "
         f"{c1['ck'] * m.k_liquid_W_mK:.1f} W/(m·K) in the selected state)"],
    ]
    assert abs(m.cp_eff_mushy_J_kgK - (m.cp_mushy_J_kgK + m.latent_heat_fusion_J_kg / m.mushy_temperature_interval_K)) < 1e-6
    return {
        "id": "T4", "name": "T4_material_properties", "title": "316L material properties used by the model",
        "columns": ["Property", "Symbol", "Value", "Units", "Remark"], "rows": rows,
        "widths": [0.28, 0.10, 0.12, 0.12, 0.38],
        "notes": ["Phase-dependent first-pass engineering values; they were fixed and not calibrated. "
                  "The directional term (η) multiplies the liquid conductivity along the scan by (1 + η); "
                  f"η = {c1['eta']:g} in the selected state."],
        "provenance": ["Read at build time from lpbf.model.parameters.get_model_parameters().material "
                       "(_accepted_core/parameters.py)."],
        "csv_header": ["property", "symbol", "value", "units", "remark"], "csv_rows": rows,
    }


# ---------------------------------------------------------------------- T5


def t5_configuration() -> dict:
    from lpbf.calibration_contract import _abs_depth_mapping
    from lpbf.experiments.current_framework import (FROZEN_BOILING_AUDIT_TMAX_K,
                                                    FROZEN_BOUNDARY_EXPLICIT_FRACTION_LIMIT,
                                                    PRODUCTION_CALIBRATION_WINDOW_CELLS)
    from lpbf.geometry import FROZEN_SPACING_UM
    from lpbf.hierarchical_objective import COVERAGE_FLOOR
    from lpbf.log_ratio_objective import PIXEL_FLOOR
    from lpbf.model._accepted_core.parameters import MACHINE_GAUSSIAN_RADIUS_MM
    from lpbf.model.current_configuration import CURRENT_FIXED_CONFIGURATION
    from lpbf.model.input_data import PRODUCTION_DAQ_DT_S, PRODUCTION_LASER_DRIVE_THRESHOLD
    from lpbf.model.laser_component_association import BEAM_SHARE_FLOOR
    from lpbf.model.parameters import get_model_parameters
    from lpbf.patch22_4_3_2_window_calibration import coordinate_bounds, guard_maximum
    from lpbf.runtime.parameters import THERMAL_DT_S, THERMAL_SUBSTEPS_PER_DAQ

    p = get_model_parameters()
    bc, mw = p.boundary_conditions, p.moving_window
    nz = round(p.geometry.Lz_mm * 1000 / FROZEN_SPACING_UM)
    assert abs(nz * FROZEN_SPACING_UM / 1000 - p.geometry.Lz_mm) < 1e-9
    win_mm = PRODUCTION_CALIBRATION_WINDOW_CELLS * FROZEN_SPACING_UM / 1000
    bounds = coordinate_bounds()
    c1 = next(c for c in D.candidates() if c["selected"])
    a_c1, d_c1 = _abs_depth_mapping(c1["t"])
    amb_K = bc.ambient_temperature_C + 273.15
    far_K = bc.far_field_temperature_C + 273.15
    init_K = p.initial_condition.initial_temperature_C + 273.15
    tb = p.material.T_boiling_K
    fx = "fixed"
    rows = [
        ["Process inputs", "", "", "", ""],
        ["Laser trajectory", "x, y", "prescribed", "mm", f"X-Machine, Y-Machine at {1 / PRODUCTION_DAQ_DT_S / 1000:.0f} kHz"],
        ["Laser state", "–", "prescribed", "–", f"on if Laser Drive > {PRODUCTION_LASER_DRIVE_THRESHOLD:g} V"],
        ["Laser power", "P", "prescribed", "W", "nominal value per coupon (process record)"],
        ["Process interval", "Δt_process", "prescribed", "µs", f"{PRODUCTION_DAQ_DT_S * 1e6:g}"],
        ["Discretization", "", "", "", ""],
        ["Cell size", "Δx", fx, "µm", f"{FROZEN_SPACING_UM:g} (cubic cells)"],
        ["Moving window", "N_x × N_y × N_z", fx, "cells",
         f"{PRODUCTION_CALIBRATION_WINDOW_CELLS} × {PRODUCTION_CALIBRATION_WINDOW_CELLS} × {nz} "
         f"({win_mm:.3f} × {win_mm:.3f} × {p.geometry.Lz_mm:.3f} mm)"],
        ["Thermal time step", "Δt", fx, "µs", f"{THERMAL_DT_S * 1e6:g} ({THERMAL_SUBSTEPS_PER_DAQ} substeps per process row)"],
        ["Explicit stability safety factor", "s", fx, "–", f"{p.time.explicit_stability_safety_factor:.2f}"],
        ["Transport stability guard", "Δt / Δt_safe", fx, "–", f"≤ {guard_maximum():.2f} for every candidate"],
        ["Boundary-loss stability", "F_boundary", fx, "–",
         f"< {FROZEN_BOUNDARY_EXPLICIT_FRACTION_LIMIT:.2f} (audited to {FROZEN_BOILING_AUDIT_TMAX_K:.0f} K)"],
        ["Window motion", "–", fx, "–", "whole-cell field shifts; sub-cell offset kept in the source position"],
        ["Window reset distance", "d_reset", fx, "mm",
         f"{mw.reset_distance_threshold_mm:g} (field reset to {init_K:.2f} K)"],
        ["Initial and bulk temperature", "T_bulk", fx, "K", f"{init_K:.2f}"],
        ["Heat source", "", "", "", ""],
        ["Lateral profile", "R", fx, "mm", f"Gaussian, 1/e² radius {MACHINE_GAUSSIAN_RADIUS_MM:g}"],
        ["Depth profile", "b(s; δ)", fx, "–", "normalized truncated exponential"],
        ["Absorbed power", "P_abs", fx, "W", "α P m_TED with m_TED = 1"],
        ["Boundaries", "", "", "", ""],
        ["Top surface", "h_conv, T_∞", fx, "W/(m²·K), K",
         f"convection, {bc.convection_coefficient_W_m2K:g}, {amb_K:.2f}; radiation inactive"],
        ["Sides and bottom", "h_solid, T_far", fx, "W/(m²·K), K", f"solid-absorbing, {bc.h_solid_W_m2K:g}, {far_K:.2f}"],
        ["Boiling regulator", "", "", "", ""],
        ["Threshold", "T_b", fx, "K", f"{tb:.2f}"],
        ["Strength", "b", fx, "–", f"{CURRENT_FIXED_CONFIGURATION['quadratic_boiling_strength']:g}"],
        ["Reference conductance", "h_ref", fx, "W/(m²·K)", f"{bc.boiling_max_conductance_W_m2K:.1e}".replace("e+06", " × 10⁶")],
        ["Reference superheat", "ΔT_ref", fx, "K", f"{bc.boiling_reference_superheat_K:g}"],
        ["Transition width", "–", fx, "K", f"{bc.boiling_transition_width_K:g} (smoothstep); energy sink, no cap"],
        ["Observation", "", "", "", ""],
        ["Liquid mask", "T ≥ T_l", fx, "–", "top-surface cells, 4-connected components"],
        ["Laser association", "B_m", fx, "–", f"largest beam share, at least {BEAM_SHARE_FLOOR:.0%}"],
        ["Footprint geometry", "H_sim, W_sim", fx, "px",
         f"interpolated liquidus contour, minimum-area rectangle; {S.UM_PER_PX:g} µm/px nominal"],
        ["Enclosure", "–", fx, "–", "component touching the window edge: undefined"],
        ["Scoring", "", "", "", ""],
        ["Scored frames", "–", fx, "–", "first and last eligible frame of each track excluded"],
        ["Pixel floor and weights", "–", fx, "px, –", f"{PIXEL_FLOOR:g} px; w_H = w_W = 0.5"],
        ["Coverage floor", "–", fx, "–", f"{COVERAGE_FLOOR:.0%} per coupon (flag only)"],
        ["Calibrated reduced-order parameters", "", "", "", ""],
        ["Absorptivity", "α", "calibrated via t", "–",
         f"α(t), t ∈ [{bounds['abs_depth_identifiable_coordinate'][0]:g}, ".replace("-", "−")
         + f"{bounds['abs_depth_identifiable_coordinate'][1]:g}]; selected {a_c1:.3f}"],
        ["Deposition depth", "δ", "calibrated via t", "mm", f"δ(t), coupled to α; selected {d_c1:.4f}"],
        ["Liquid conductivity factor", "c_k", "calibrated", "–",
         f"[{bounds['liquid_conductivity_enhancement_factor'][0]:g}, "
         f"{bounds['liquid_conductivity_enhancement_factor'][1]:g}]; selected {c1['ck']:.3f}"],
        ["Directional transport", "η", "calibrated", "–",
         f"[{bounds['eta_directional'][0]:g}, {bounds['eta_directional'][1]:g}]; selected {c1['eta']:g}"],
    ]
    return {
        "id": "T5", "name": "T5_model_configuration", "title": "Final numerical-model configuration",
        "columns": ["Quantity", "Symbol", "Role", "Units", "Value or treatment"], "rows": rows,
        "group_rows": True, "widths": [0.27, 0.13, 0.13, 0.12, 0.35],
        "notes": ["Material properties are listed separately. Absorptivity and deposition depth share one "
                  "calibration coordinate, t."],
        "provenance": ["Read at build time from the code the 22.4.3.2 runner imported: lpbf.model.parameters, "
                       "current_configuration, experiments.current_framework, runtime.parameters, geometry, "
                       "laser_component_association, hierarchical_objective, log_ratio_objective."],
        "csv_header": ["quantity", "symbol", "role", "units", "value"], "csv_rows": rows,
    }


# ---------------------------------------------------------------------- T6


def t6_calibration_parameters() -> dict:
    from lpbf.calibration_contract import _abs_depth_mapping
    from lpbf.patch22_4_3_2_window_calibration import coordinate_bounds, guard_maximum

    b = coordinate_bounds()
    t_lo, t_hi = b["abs_depth_identifiable_coordinate"]
    a0, d0 = _abs_depth_mapping(0.0)
    a1, d1 = _abs_depth_mapping(1.0)
    a_lo, d_hi = _abs_depth_mapping(t_lo)
    a_hi, d_lo = _abs_depth_mapping(t_hi)
    c1 = next(c for c in D.candidates() if c["selected"])
    a_c1, d_c1 = _abs_depth_mapping(c1["t"])
    neg = lambda x: f"{x:g}".replace("-", "−")  # noqa: E731
    rows = [
        ["Absorptivity–depth coordinate", "t", f"[{neg(t_lo)}, {neg(t_hi)}]", "–", "calibration coordinate",
         "One identifiable direction that moves α and δ together", f"{neg(c1['t'])} (lower bound)"],
        ["Absorptivity", "α(t)", f"{a_lo:.3f}–{a_hi:.3f}", "–", f"α = {a0:.6f} + {a1 - a0:.7f} t",
         "Fraction of incident power absorbed", f"{a_c1:.3f}"],
        ["Deposition depth", "δ(t)", f"{d_lo:.4f}–{d_hi:.4f}", "mm", f"δ = {d0:.6f} − {d0 - d1:.8f} t",
         "Decay length of the exponential depth profile", f"{d_c1:.4f}"],
        ["Liquid conductivity factor", "c_k", "[{0:g}, {1:g}]".format(*b["liquid_conductivity_enhancement_factor"]), "–",
         "calibration coordinate", "Multiplies the liquid conductivity (unresolved melt flow)", f"{c1['ck']:.3f}"],
        ["Directional transport", "η", "[{0:g}, {1:g}]".format(*b["eta_directional"]), "–", "calibration coordinate",
         "Extra liquid conductivity along the local scan direction, × (1 + η)", f"{c1['eta']:g} (lower bound)"],
        ["Stability guard", "Δt / Δt_safe", f"≤ {guard_maximum():.2f}", "–", "constraint on (c_k, η)",
         "Rejects numerically marginal states before any run", f"{c1['guard_value']:.3f}"],
    ]
    return {
        "id": "T6", "name": "T6_calibration_parameters", "title": "Calibration parameters and bounds",
        "columns": ["Quantity", "Symbol", "Bounds", "Unit", "Definition", "Physical interpretation", "Selected"],
        "rows": rows, "widths": [0.17, 0.10, 0.12, 0.07, 0.21, 0.23, 0.10],
        "notes": ["Selected: Candidate 1, the calibrated state. Increasing t raises α and shortens δ. The "
                  "boiling-regulator strength (b = 0.5) and all other quantities were fixed and are not calibration "
                  "coordinates."],
        "provenance": ["Bounds from lpbf.patch22_4_3_2_window_calibration.coordinate_bounds(); the mapping from "
                       "lpbf.calibration_contract._abs_depth_mapping; selected state from committee D6."],
        "csv_header": ["quantity", "symbol", "bounds", "units", "definition", "interpretation", "selected"],
        "csv_rows": rows,
    }


# ---------------------------------------------------------------------- T7


def t7_replicates() -> dict:
    pairs = D.replicate_pairs()
    conds = sorted({r["condition"] for r in pairs}, key=lambda c: next(r["ved_J_mm3"] for r in pairs if r["condition"] == c))
    cps = {c["member"]: c for c in D.coupons()}
    rows, csv_rows, absd = [], [], {"cam_H": [], "cam_W": []}
    for cond in conds:
        h = next(r for r in pairs if r["condition"] == cond and r["quantity"] == "cam_H")
        w = next(r for r in pairs if r["condition"] == cond and r["quantity"] == "cam_W")
        c = cps[h["member_0730"]]
        row = [_cond_label(c), f"{h['ved_J_mm3']:.1f}", ROLE_TEXT[h["role"]].replace(", in window", ""),
               f"{h['value_0730']:.2f}", f"{h['value_0731']:.2f}",
               f"{100 * h['difference']:+.1f} [{100 * h['difference_ci_lo']:+.1f}, {100 * h['difference_ci_hi']:+.1f}]",
               f"{w['value_0730']:.2f}", f"{w['value_0731']:.2f}",
               f"{100 * w['difference']:+.1f} [{100 * w['difference_ci_lo']:+.1f}, {100 * w['difference_ci_hi']:+.1f}]"]
        rows.append([x.replace("-", "−") if i >= 3 else x for i, x in enumerate(row)])
        for r in (h, w):
            absd[r["quantity"]].append(abs(r["difference"]))
            csv_rows.append([cond, r["role"], r["ved_J_mm3"], r["quantity"], r["member_0730"], r["member_0731"],
                             r["value_0730"], r["value_0731"], r["difference"], r["difference_ci_lo"],
                             r["difference_ci_hi"], r["ci_excludes_zero"]])
    any_excl = any(r["ci_excludes_zero"] for r in pairs if r["quantity"] in ("cam_H", "cam_W"))
    mean_h = 100 * float(np.mean(absd["cam_H"]))
    mean_w = 100 * float(np.mean(absd["cam_W"]))
    return {
        "id": "T7", "name": "T7_july_replicates", "title": "Repeatability of the July replicate conditions",
        "columns": ["Condition", "VED (J/mm³)", "Role", "H, Jul 30 (px)", "H, Jul 31 (px)", "ΔH (%) [95 % CI]",
                    "W, Jul 30 (px)", "W, Jul 31 (px)", "ΔW (%) [95 % CI]"],
        "rows": rows, "widths": [0.15, 0.08, 0.10, 0.09, 0.09, 0.14, 0.09, 0.09, 0.14],
        "notes": ["Camera coupon medians of the scored frames. Δ = 100 ln(Jul 31 / Jul 30); 95 % intervals from "
                  "4,000 track-bootstrap resamples within each coupon. Mean |ΔH| = "
                  f"{mean_h:.1f} %, mean |ΔW| = {mean_w:.1f} %; "
                  + ("no interval excludes zero." if not any_excl else "some intervals exclude zero.")],
        "provenance": ["Committee data T10_replicate_pairs.csv (exploratory)."],
        "csv_header": ["condition", "role", "ved_J_mm3", "quantity", "coupon_0730", "coupon_0731", "value_0730_px",
                       "value_0731_px", "ln_ratio_0731_0730", "ci_lo", "ci_hi", "ci_excludes_zero"],
        "csv_rows": csv_rows, "summary": {"mean_abs_H_pct": mean_h, "mean_abs_W_pct": mean_w, "any_excl": any_excl},
    }


# ---------------------------------------------------------------------- T8


def t8_selected_state() -> dict:
    from lpbf.calibration_contract import _abs_depth_mapping

    cands = sorted(D.candidates(), key=lambda c: c["J"])
    c1, c2 = cands[0], cands[1]
    assert c1["selected"] and c1["candidate"] == "confirm_c1"

    def col(c):
        a, d = _abs_depth_mapping(c["t"])
        return [
            "confirmation (surrogate minimizer)" if c["candidate"] == "confirm_c1" else "confirmation (flat valley)",
            f"{c['t']:g}".replace("-", "−"), f"{c['ck']:.3f}", f"{c['eta']:.3f}", f"{a:.3f}", f"{d:.4f}",
            f"{c['J']:.4f}", f"{c['e_H']:.3f}", f"{c['e_W']:.3f}",
            f"{0.5 * c['H_component']:.3f} / {0.5 * c['W_component']:.3f}", f"{c['rank_by_J']} of {len(cands)}",
            f"{c['guard_value']:.3f}", f"{c['coverage']:.3f}", f"{c['scored_frames']:,}", f"{c['no_pool_frames']}",
            f"{100 * c['fraction_peak_above_boiling']:.1f} %", f"{c['median_peak_surface_K']:.0f}",
        ]

    labels = ["Origin", "t", "c_k", "η", "α", "δ (mm)", "J", "e_H", "e_W", "½ Q_H / ½ Q_W", "Rank by J",
              "Stability guard value (≤ 0.95)", "Coverage", "Scored frames", "Frames without a pool",
              "Frames with peak above 3133 K", "Median peak surface T (K)"]
    a, b = col(c1), col(c2)
    rows = [[l, x, y] for l, x, y in zip(labels, a, b)]
    return {
        "id": "T8", "name": "T8_selected_state", "title": "Selected calibration state",
        "columns": ["Quantity", f"{D.display_name(c1['candidate'])} (selected)",
                    f"{D.display_name(c2['candidate'])} (second best)"], "rows": rows,
        "widths": [0.40, 0.30, 0.30],
        "notes": [f"Both on the 9 calibration coupons. {D.display_name(c1['candidate'])} lies at the lower bounds of t "
                  f"and η; c_k is interior. The near-best set (J ≤ 1.10 J_min) contains only these two candidates."],
        "provenance": ["Committee D6_candidates.csv (recorded calibrate and confirm stages). "
                       f"{D.display_name(c1['candidate'])} and {D.display_name(c2['candidate'])} are "
                       f"{c1['candidate']} and {c2['candidate']} in the 22.4.3.2 records."],
        "csv_header": ["quantity", f"{D.display_name(c1['candidate'])} ({c1['candidate']})",
                       f"{D.display_name(c2['candidate'])} ({c2['candidate']})"], "csv_rows": rows,
    }


# ---------------------------------------------------------------------- T9


def t9_calibration_held_out() -> dict:
    groups = [("calibration", "group"), ("in_window_held_out", "group"), ("cross_campaign_20260904_part_5", "group")]
    cols = []
    for name, _ in groups:
        g = D.group(name)
        b = {s: D.boot("group", name, s) for s in ("e_H", "e_W", "J", "median_H_ratio", "median_W_ratio")}
        cols.append((g, b))
    cps = D.coupons()

    def coverage(name):
        if name.startswith("cross"):
            return min(c["coverage"] for c in cps if c["member"] == S.C.CROSS_CAMPAIGN)
        return min(c["coverage"] for c in cps if c["role"] == name)

    vH = D.boot("v_ratio", "held_out_over_calibration", "e_H ratio")
    vW = D.boot("v_ratio", "held_out_over_calibration", "e_W ratio")
    pH = D.boot("v_ratio", "part_5_over_calibration", "e_H ratio")
    pW = D.boot("v_ratio", "part_5_over_calibration", "e_W ratio")
    labels = ["Coupons (conditions)", "Scored frames", "e_H", "e_W", "J", "H ratio, model / camera",
              "W ratio, model / camera", "Camera H × W (µm)", "Model H × W (µm)", "Coverage (lowest coupon)",
              "Frames without a pool", "V_H = e_H / e_H,cal", "V_W = e_W / e_W,cal"]
    out = []
    for i, ((g, b), (name, _)) in enumerate(zip(cols, groups)):
        col = [f"{g['coupons']} ({g['conditions']})", f"{g['scored_frames']:,}",
               _ci(g["e_H"], b["e_H"]["ci_lo"], b["e_H"]["ci_hi"]), _ci(g["e_W"], b["e_W"]["ci_lo"], b["e_W"]["ci_hi"]),
               _ci(g["J"], b["J"]["ci_lo"], b["J"]["ci_hi"]),
               _ci(g["median_H_ratio"], b["median_H_ratio"]["ci_lo"], b["median_H_ratio"]["ci_hi"], 2),
               _ci(g["median_W_ratio"], b["median_W_ratio"]["ci_lo"], b["median_W_ratio"]["ci_hi"], 2),
               f"{g['cam_H_px_median'] * S.UM_PER_PX:.0f} × {g['cam_W_px_median'] * S.UM_PER_PX:.0f}",
               f"{g['sim_H_px_median_pool'] * S.UM_PER_PX:.0f} × {g['sim_W_px_median_pool'] * S.UM_PER_PX:.0f}",
               f"{coverage(name):.3f}", f"{g['no_pool_frames']}"]
        if i == 0:
            col += ["–", "–"]
        elif i == 1:
            col += [_ci(g["e_H"] / cols[0][0]["e_H"], vH["ci_lo"], vH["ci_hi"]),
                    _ci(g["e_W"] / cols[0][0]["e_W"], vW["ci_lo"], vW["ci_hi"])]
        else:
            col += [_ci(g["e_H"] / cols[0][0]["e_H"], pH["ci_lo"], pH["ci_hi"]),
                    _ci(g["e_W"] / cols[0][0]["e_W"], pW["ci_lo"], pW["ci_hi"])]
        out.append(col)
    rows = [[l] + [c[k] for c in out] for k, l in enumerate(labels)]
    v_pass = (cols[1][0]["e_H"] / cols[0][0]["e_H"] <= 1.25) and (cols[1][0]["e_W"] / cols[0][0]["e_W"] <= 1.25)
    return {
        "id": "T9", "name": "T9_calibration_and_held_out", "title": "Calibration and held-out performance",
        "columns": ["Quantity", "Calibration", "Held out, in window", "Sep 4, 180 W, 1000 mm/s (held out)"],
        "rows": rows, "widths": [0.28, 0.24, 0.24, 0.24],
        "notes": ["Errors are hierarchical log-RMSEs over the group's conditions; ratios are medians of the frame "
                  "ratios, with frames without a pool scored as H = W = 0 (1 px floor). Brackets: 95 % percentile "
                  "bootstrap over coupons within the group (single coupon: over tracks). Model sizes are medians of "
                  "the frames with a pool. Predefined criterion V ≤ 1.25 for H and W: "
                  + ("met for both." if v_pass else "not met for both.")],
        "provenance": ["Committee D4 group rows, D5 bootstrap summary (v_ratio) and D3 coverage."],
        "csv_header": ["quantity", "calibration", "in_window_held_out", "cross_campaign_20260904_part_5"],
        "csv_rows": rows, "summary": {"v_pass": v_pass},
    }


# ---------------------------------------------------------------------- T10


def _spearman(x, y) -> float:
    rx = np.argsort(np.argsort(x)).astype(float)
    ry = np.argsort(np.argsort(y)).astype(float)
    return float(np.corrcoef(rx, ry)[0, 1])


def t10_out_of_window() -> dict:
    cps = sorted([c for c in D.coupons() if c["role"].startswith("out_of_window")], key=lambda c: c["ved_J_mm3"])
    rows, csv_rows = [], []
    for c in cps:
        rows.append([_cond_label(c), f"{c['ved_J_mm3']:.1f}", "examined" if c["role"].endswith("examined") else "blind",
                     _ci(c["median_H_ratio"], c["median_H_ratio_ci_lo"], c["median_H_ratio_ci_hi"], 2),
                     _ci(c["median_W_ratio"], c["median_W_ratio_ci_lo"], c["median_W_ratio_ci_hi"], 2),
                     f"{100 * c['no_pool_fraction']:.1f}", f"{c['coverage']:.3f}"])
        csv_rows.append([c["member"], c["power_W"], c["speed_mm_s"], c["ved_J_mm3"], c["role"], c["median_H_ratio"],
                         c["median_H_ratio_ci_lo"], c["median_H_ratio_ci_hi"], c["median_W_ratio"],
                         c["median_W_ratio_ci_lo"], c["median_W_ratio_ci_hi"], c["e_H"], c["e_W"],
                         c["no_pool_fraction"], c["coverage"], c["median_r_H"], c["median_r_W"]])
    for name, label in (("out_of_window_low_ved", "Below the window (6)"), ("out_of_window_high_ved", "Above the window (4)"),
                        ("out_of_window_all", "All out of window (10)")):
        g = D.group(name)
        bh, bw = D.boot("group", name, "median_H_ratio"), D.boot("group", name, "median_W_ratio")
        rows.append([label, "", "", _ci(g["median_H_ratio"], bh["ci_lo"], bh["ci_hi"], 2),
                     _ci(g["median_W_ratio"], bw["ci_lo"], bw["ci_hi"], 2),
                     f"{100 * g['no_pool_frames'] / g['scored_frames']:.1f}",
                     f"{min(c['coverage'] for c in cps if c['member'] in g['members'].split()):.3f}"])
        csv_rows.append([name, "", "", "", "group", g["median_H_ratio"], bh["ci_lo"], bh["ci_hi"], g["median_W_ratio"],
                         bw["ci_lo"], bw["ci_hi"], g["e_H"], g["e_W"], g["no_pool_frames"] / g["scored_frames"],
                         min(c["coverage"] for c in cps), "", ""])
    ved = [c["ved_J_mm3"] for c in cps]
    rho_H = _spearman(ved, [c["median_r_H"] for c in cps])
    rho_W = _spearman(ved, [c["median_r_W"] for c in cps])
    low_H_above = sum(1 for c in cps if c["ved_J_mm3"] < S.WINDOW[0] and c["median_H_ratio"] > 1)
    n_low = sum(1 for c in cps if c["ved_J_mm3"] < S.WINDOW[0])
    return {
        "id": "T10", "name": "T10_out_of_window", "title": "Out-of-window performance by process condition",
        "columns": ["Condition", "VED (J/mm³)", "Status", "H ratio [95 % CI]", "W ratio [95 % CI]",
                    "No pool (%)", "Coverage"],
        "rows": rows, "group_from": len(cps), "widths": [0.22, 0.11, 0.12, 0.17, 0.17, 0.10, 0.11],
        "notes": ["Each out-of-window condition is one coupon. Ratios are medians of the frame ratios (model / camera); "
                  "intervals from 4,000 track-bootstrap resamples (single coupon) or coupon-bootstrap resamples "
                  "(groups). 'Examined' coupons were compared with the model during development; 'blind' coupons "
                  "were first compared after the freeze. Spearman rank correlation of the coupon median log "
                  f"residual with VED: ρ = {rho_H:.3f} (H), {rho_W:.3f} (W). Below the window, H is still larger than "
                  f"the camera's for {low_H_above} of {n_low} coupons; W is smaller for all {n_low}."],
        "provenance": ["Committee D3 coupon rows and D4/D5 group rows."],
        "csv_header": ["coupon", "power_W", "speed_mm_s", "ved_J_mm3", "role", "median_H_ratio", "H_ci_lo", "H_ci_hi",
                       "median_W_ratio", "W_ci_lo", "W_ci_hi", "e_H", "e_W", "no_pool_fraction", "coverage",
                       "median_r_H", "median_r_W"],
        "csv_rows": csv_rows, "summary": {"rho_H": rho_H, "rho_W": rho_W, "low_H_above": low_H_above, "n_low": n_low},
    }


ALL = {
    "T1": t1_setup, "T2": t2_matrix, "T3": t3_channels, "T4": t4_material, "T5": t5_configuration,
    "T6": t6_calibration_parameters, "T7": t7_replicates, "T8": t8_selected_state, "T9": t9_calibration_held_out,
    "T10": t10_out_of_window,
}


def clean(text: str) -> str:
    """Thesis conventions for displayed text: '95%' without a space, and a minus sign in negative numbers."""

    return re.sub(r"(?<![\w.])-(?=\d)", "−", text.replace(" %", "%"))


def finish(table: dict) -> dict:
    """Apply the display conventions to the shown columns, rows and notes (CSV values stay raw)."""

    table["rows"] = [[clean(x) for x in row] for row in table["rows"]]
    table["notes"] = [clean(n) for n in table["notes"]]
    table["columns"] = [clean(c) for c in table["columns"]]
    return table


def build(key: str) -> dict:
    return finish(ALL[key]())


def render(table: dict) -> dict[str, bytes]:
    """The table's CSV (full precision) and Markdown (as displayed), as bytes."""

    import csv
    import io

    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(table["csv_header"])
    for row in table["csv_rows"]:
        w.writerow(["" if v is None else (repr(v) if isinstance(v, float) else v) for v in row])
    lines = [f"# {table['title']}", "", "| " + " | ".join(table["columns"]) + " |",
             "|" + "|".join("---" for _ in table["columns"]) + "|"]
    for r in table["rows"]:
        lines.append("| " + " | ".join(str(x) for x in r) + " |")
    lines.append("")
    for n in table["notes"] + table.get("provenance", []):
        lines.append(f"- {n}")
    if table["id"] == "T1":
        lines.append("")
        lines.append("Sources: " + "; ".join(f"{r[0]}: {r[2]}" for r in table["csv_rows"]))
    lines.append("")
    return {f"{table['name']}.csv": buf.getvalue().encode("utf-8"), f"{table['name']}.md": "\n".join(lines).encode("utf-8")}


def write(table: dict) -> None:
    S.TABLES_DIR.mkdir(parents=True, exist_ok=True)
    for name, data in render(table).items():
        (S.TABLES_DIR / name).write_bytes(data)
