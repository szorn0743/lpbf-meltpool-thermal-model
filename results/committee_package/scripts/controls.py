"""T5 (fixed model and numerical controls) and T16 (provenance of every Patch 22.4.3.2 stage).

T5 reads each value from the code that the 22.4.3.2 runner used, at build time, so the table cannot drift from the
code; it then checks that every stage manifest recorded the same controls. Nothing here runs the thermal model.
"""
from __future__ import annotations

import subprocess
from typing import Any

import common as C
from lpbf.infrastructure import git_metadata

STAGES = (
    ("smoke", C.SMOKE_GATE, "smoke gate: one unit (anchor_center x 20260730:part_1)"),
    ("calibrate", C.CALIBRATE_MANIFEST, "17 frozen design candidates x 9 calibration coupons"),
    ("confirm", C.CONFIRM_MANIFEST, "2 confirmation candidates x 9 calibration coupons"),
    ("freeze", C.SELECTION_FREEZE, "selection freeze (no thermal run)"),
    ("evaluate", C.EVALUATE_MANIFEST, "c1 on 24 coupons, c2 on the 15 evaluation coupons"),
    ("synthetic", C.SYNTHETIC_MANIFEST, "reading S: synthetic camera on the c1 fields (no thermal run)"),
)


def _git(*args: str) -> str | None:
    """Git is an aid only: ``None`` when there is no checkout or no git (a source ZIP), never a failure."""
    if git_metadata(C.REPO)["commit"] is None:
        return None
    try:
        return subprocess.run(["git", *args], cwd=C.REPO, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


# The stages ran in the private development repository, whose history is not published; its git facts were recorded.
PRIVATE_HISTORY = C.load_json(C.REGISTERS_DIR / "private_git_history.json")


def commit_date(commit: str) -> str | None:
    if commit in PRIVATE_HISTORY["commit_dates"]:
        return PRIVATE_HISTORY["commit_dates"][commit]
    return _git("show", "-s", "--format=%cI", commit)


def evidence_added(relative: str) -> list[str | None]:
    if relative in PRIVATE_HISTORY["evidence_added"]:
        recorded = PRIVATE_HISTORY["evidence_added"][relative]
        return [recorded["commit"], recorded["date"]]
    log = _git("log", "--diff-filter=A", "--format=%h %cI", "--", relative)
    if not log:
        return [None, None]
    return log.splitlines()[-1].split()


def fixed_controls() -> list[dict[str, Any]]:
    from lpbf.calibration_contract import _abs_depth_mapping
    from lpbf.experiments.current_framework import PRODUCTION_CALIBRATION_WINDOW_CELLS
    from lpbf.geometry import FROZEN_SPACING_UM
    from lpbf.hierarchical_objective import COVERAGE_FLOOR, PIXEL_SIZE_UM
    from lpbf.log_ratio_objective import OBJECTIVE_CONTRACT_VERSION, PIXEL_FLOOR
    from lpbf.model._accepted_core.parameters import MACHINE_GAUSSIAN_RADIUS_MM, MACHINE_SPOT_DIAMETER_UM
    from lpbf.model.current_configuration import CURRENT_FIXED_CONFIGURATION
    from lpbf.model.input_data import PRODUCTION_DAQ_DT_S, PRODUCTION_DAQ_FREQUENCY_HZ, PRODUCTION_LASER_DRIVE_THRESHOLD
    from lpbf.model.laser_component_association import BEAM_SHARE_FLOOR, POLICY_VERSION
    from lpbf.model.parameters import get_model_parameters
    from lpbf.model.production_hw import PRODUCTION_HW_SEMANTICS_VERSION
    from lpbf.field_capture import dispatch_lock_check, frozen_core_check
    from lpbf.calibration import BOILING_K, coordinate_bounds, guard_maximum
    from lpbf.runtime.parameters import THERMAL_DT_S, THERMAL_SUBSTEPS_PER_DAQ
    from lpbf.scored_frame_rule import SCORED_FRAME_RULE_ID, SCORED_FRAME_RULE_VERSION

    p = get_model_parameters()
    m = p.material
    core = frozen_core_check()
    lock = dispatch_lock_check()
    bounds = coordinate_bounds()
    window_mm = PRODUCTION_CALIBRATION_WINDOW_CELLS * FROZEN_SPACING_UM / 1000.0
    a_lo, d_lo = _abs_depth_mapping(bounds["abs_depth_identifiable_coordinate"][0])
    a_hi, d_hi = _abs_depth_mapping(bounds["abs_depth_identifiable_coordinate"][1])
    a_c1, d_c1 = _abs_depth_mapping(-3.0)
    hashes_file = C.CORE_HASHES

    def row(group: str, control: str, value: str, source: str, varied: bool = False) -> dict[str, Any]:
        return {"group": group, "control": control, "value": value, "varied_by_calibration": varied, "source": source}

    return [
        row("Numerics", "Thermal grid", f"{FROZEN_SPACING_UM:g} µm cubic cells", "lpbf.geometry.FROZEN_SPACING_UM; frozen_configuration.json"),
        row("Numerics", "Production window", f"{PRODUCTION_CALIBRATION_WINDOW_CELLS} x {PRODUCTION_CALIBRATION_WINDOW_CELLS} cells ({window_mm:.3f} mm square), depth {p.geometry.Lz_mm:.3f} mm", "current_framework.PRODUCTION_CALIBRATION_WINDOW_CELLS; resize_xy_window"),
        row("Numerics", "Process (DAQ) clock", f"{PRODUCTION_DAQ_FREQUENCY_HZ / 1000:g} kHz, {PRODUCTION_DAQ_DT_S * 1e6:g} µs per row", "lpbf.model.input_data"),
        row("Numerics", "Thermal time step", f"{THERMAL_DT_S * 1e6:g} µs, {THERMAL_SUBSTEPS_PER_DAQ} substeps per DAQ row", "lpbf.runtime.parameters (overrides the legacy 3.33 µs in frozen_configuration.json)"),
        row("Numerics", "Explicit stability guard", f"directional Gershgorin bound <= {guard_maximum():g} of the safe step (solver limit 1.0)", "patch21_0 contract coupled_transport_guard; checked for every candidate before any run"),
        row("Numerics", "Frozen numerical core", f"{core['files']} files of src/lpbf/model/_accepted_core match their accepted sha256: {core['pass']}", f"{hashes_file.name} (sha256 {C.sha256_file(hashes_file)[:12]}); checked at the smoke gate"),
        row("Process input", "Laser-on rule", f"Laser Drive > {PRODUCTION_LASER_DRIVE_THRESHOLD:g} V (strict); scan tracks are the laser-on runs", "lpbf.model.input_data.PRODUCTION_LASER_DRIVE_THRESHOLD"),
        row("Process input", "Process conditions", "P and v from the read-only A17 record; hatch 0.080 mm, layer 0.030 mm", "docs/reference/LPBF_Process_Parameters.csv (A17)"),
        row("Heat source", "Beam", f"Gaussian exp(-2r²/R²), R = {MACHINE_GAUSSIAN_RADIUS_MM:g} mm (1/e² radius; spot {MACHINE_SPOT_DIAMETER_UM:g} µm diameter), normalised on the grid", "_accepted_core/heat_source.py; deposition_depth_source.py"),
        row("Heat source", "Depth profile", f"{CURRENT_FIXED_CONFIGURATION['deposition_depth_mode'].replace('_', ' ')}, decay length λ", "lpbf.model.deposition_depth"),
        row("Heat source", "Absorbed power", f"P x α x m_TED with m_TED = 1 ({CURRENT_FIXED_CONFIGURATION['absorptivity_semantics'].replace('_', ' ')})", "model/current_execution.py"),
        row("Heat source", "Calibrated coordinate t -> (α, λ)", f"one principal direction (A9): t in [{bounds['abs_depth_identifiable_coordinate'][0]:g}, {bounds['abs_depth_identifiable_coordinate'][1]:g}] gives α {a_lo:.3f}–{a_hi:.3f}, λ {d_lo * 1000:.1f}–{d_hi * 1000:.1f} µm; c1 (t = −3): α {a_c1:.3f}, λ {d_c1 * 1000:.1f} µm", "calibration_contract._abs_depth_mapping", True),
        row("Material", "Alloy model", f"{m.name}", "_accepted_core/parameters.py (not calibrated)"),
        row("Material", "Solidus, liquidus, boiling", f"{m.T_solidus_K:.2f} K, {m.T_liquidus_K:.2f} K, {m.T_boiling_K:.2f} K", "_accepted_core/parameters.py"),
        row("Material", "Density, heat capacity", f"{m.density_kg_m3:g} kg/m³; cp solid / mushy / liquid {m.cp_solid_J_kgK:g} / {m.cp_mushy_J_kgK:g} / {m.cp_liquid_J_kgK:g} J/kg K", "_accepted_core/parameters.py"),
        row("Material", "Latent heat", f"{m.latent_heat_fusion_J_kg:g} J/kg over {m.mushy_temperature_interval_K:g} K (cp_eff mushy {m.cp_eff_mushy_J_kgK:g} J/kg K)", "_accepted_core/parameters.py"),
        row("Material", "Conductivity", f"solid / mushy / liquid {m.k_solid_W_mK:g} / {m.k_mushy_W_mK:g} / {m.k_liquid_W_mK:g} W/m K; liquid x ck, and x (1 + η) along the scan", "_accepted_core/parameters.py; directional_transport.py", True),
        row("Material", "Calibrated ck and η (box)", f"ck in [{bounds['liquid_conductivity_enhancement_factor'][0]:g}, {bounds['liquid_conductivity_enhancement_factor'][1]:g}], η in [{bounds['eta_directional'][0]:g}, {bounds['eta_directional'][1]:g}]", "patch21_3_coarse_global_search_design.json", True),
        row("Boiling", "Fixed boiling regulator", f"surface loss flux above T_b = {m.T_boiling_K:.2f} K, strength {CURRENT_FIXED_CONFIGURATION['quadratic_boiling_strength']:g}, law {CURRENT_FIXED_CONFIGURATION['quadratic_boiling_loss_law'].replace('_', ' ')}; no temperature clipping", "current_configuration.CURRENT_FIXED_CONFIGURATION; _accepted_core/solver.py"),
        row("Boiling", "Peak-above-boiling diagnostic", f"peak top-surface T > {BOILING_K:g} K (diagnostic only, never in the objective)", "patch22_4_3_2_window_calibration.BOILING_K"),
        row("Observation", "Model H/W", f"liquidus contour of the laser-associated component, linearly interpolated, minAreaRect; 16 µm cells = 2 camera px (semantics {PRODUCTION_HW_SEMANTICS_VERSION})", "lpbf.model.production_hw (A2, A21)"),
        row("Observation", "Association policy", f"largest share of the beam's deposited power, floor {BEAM_SHARE_FLOOR:.0%} (policy {POLICY_VERSION}); below the floor: NO_LASER_ASSOCIATED_MELT, scored as H = W = 0", "lpbf.model.laser_component_association (A21, D1, D3)"),
        row("Observation", "Camera scale", f"{p.comparison.experimental_pixel_size_um:g} µm/px nominal (reporting {PIXEL_SIZE_UM:g}); not validated", "frozen_configuration.json comparison (A24)"),
        row("Scoring", "Scored-frame rule", f"{SCORED_FRAME_RULE_ID.replace('_', ' ')} (version {SCORED_FRAME_RULE_VERSION})", "lpbf.scored_frame_rule (A22, D2)"),
        row("Scoring", "Coverage floor", f"{COVERAGE_FLOOR:.0%} per coupon (flag, never a penalty)", "lpbf.hierarchical_objective.COVERAGE_FLOOR (A23, D3)"),
        row("Scoring", "Objective", f"contract {OBJECTIVE_CONTRACT_VERSION}: log ratios with a {PIXEL_FLOOR:g} px floor, hierarchical, w_H = w_W = 0.5", "lpbf.log_ratio_objective (A26)"),
        row("Governance", "Campaign dispatch lock", f"CAMPAIGN_DISPATCH_AUTHORIZED_BY = {lock['CAMPAIGN_DISPATCH_AUTHORIZED_BY']}; lock holds: {lock['pass']}", "Patch 22.3.5.2; S10"),
    ]


RECORDED_CONTROLS = ("beam_share_floor", "coverage_floor", "pixel_floor", "window_cells", "objective_contract_version", "production_hw_association_policy_version", "production_hw_semantics_version", "scored_frame_rule_version", "design_sha256", "objective_module_sha256", "plan_sha256")


def stage_rows() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """T16: one row per stage, and a check that every thermal stage recorded the same fixed controls."""

    rows = []
    recorded: dict[str, set] = {key: set() for key in RECORDED_CONTROLS}
    for stage, path, scope in STAGES:
        manifest = C.load_json(path)
        prov = manifest.get("provenance") or {}
        commit = prov.get("git_commit") or manifest.get("git_commit")
        execution = manifest.get("execution") or {}
        guard = manifest.get("guardrails") or {}
        runtime = prov.get("runtime") or {}
        for key in RECORDED_CONTROLS:
            if key in prov:
                recorded[key].add(prov[key])
        held_out = prov.get("held_out_members_read")
        if stage == "freeze":
            held_out = manifest.get("held_out_members_read_before_freeze")
        if stage == "synthetic":
            held_out = [u["member_identity"] for u in manifest["units"] if u["member_identity"] in C.A8_HELD_OUT]
        relative = path.relative_to(C.REPO).as_posix()
        added = evidence_added(relative)
        rows.append(
            {
                "stage": stage, "scope": scope, "manifest": relative, "manifest_sha256": C.sha256_file(path),
                "evidence_committed_in": added[0], "evidence_commit_date": added[1],
                "git_commit": commit, "commit_date": commit_date(commit), "worktree_dirty": prov.get("git_worktree_dirty"),
                "runner_module_sha256": prov.get("module_sha256"),
                "objective_contract_version": prov.get("objective_contract_version") or manifest.get("objective_contract_version"),
                "association_policy_version": prov.get("production_hw_association_policy_version"),
                "hw_semantics_version": prov.get("production_hw_semantics_version"),
                "scored_frame_rule_version": prov.get("scored_frame_rule_version"),
                "workers": execution.get("workers") or execution.get("requested_workers"), "start_method": execution.get("start_method"),
                "units_run": execution.get("units_run", execution.get("units")), "units_reused": execution.get("units_reused"),
                "wall_time_s": execution.get("wall_time_s"),
                "python": runtime.get("python"), "numpy": runtime.get("numpy"), "platform": runtime.get("platform"),
                "held_out_members_read": None if held_out is None else len(held_out),
                "thermal_model_run": stage in ("smoke", "calibrate", "confirm", "evaluate"),
                "fitting_or_selection": {"smoke": "no", "calibrate": "scores only", "confirm": "surrogate proposal and scores", "freeze": "selection (lowest measured J)", "evaluate": "no", "synthetic": "T150 fixed on calibration coupons only"}[stage],
                "campaign_dispatched": guard.get("full_campaign_dispatched", False),
                "production_semantics_changed": guard.get("production_semantics_changed", False),
                "dispatch_lock_pass": (prov.get("campaign_dispatch_lock") or {}).get("pass"),
            }
        )
    consistency = {key: sorted(values, key=str) for key, values in recorded.items()}
    consistency["all_constant"] = all(len(values) == 1 for values in recorded.values())
    if not consistency["all_constant"]:
        raise RuntimeError(f"stage manifests disagree on a fixed control: {consistency}")
    return rows, consistency
