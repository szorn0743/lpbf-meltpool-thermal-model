"""Build the committee statistical-output package (passes 1 and 2) from the frozen Patch 22.4.3.2 records.

Usage, from the repo root (PowerShell):
    $env:PYTHONPATH = "$PWD\\src"
    .\\.venv-analysis\\Scripts\\python.exe docs\\analysis\\committee_package\\scripts\\run_all.py
With ``.venv`` (no matplotlib) every table and data file is produced and the figure renders are skipped. Without
the external coupon HDF5 files, the F13 sources are not rebuilt and the committed ones are kept.

Read-only on every input. No thermal run, no fitting, no selection.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import platform
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common as C  # noqa: E402
import bootstrap  # noqa: E402
import build_datasets  # noqa: E402
import candidates  # noqa: E402
import controls  # noqa: E402
import field_figures  # noqa: E402
import figures  # noqa: E402
import figures_pass2  # noqa: E402
import operators  # noqa: E402
import replicates  # noqa: E402
import sensitivity  # noqa: E402
import slopes  # noqa: E402
import sync  # noqa: E402
import tables  # noqa: E402
import tables_pass2  # noqa: E402
import variance  # noqa: E402


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=C.REPO, capture_output=True, text=True, check=True).stdout.strip()


def _rel(path: Path) -> str:
    return Path(path).resolve().relative_to(C.REPO).as_posix()


def input_hashes() -> dict[str, str]:
    paths = [
        C.EVALUATE_MANIFEST, C.CALIBRATE_MANIFEST, C.CONFIRM_MANIFEST, C.CALIBRATION_READING, C.SELECTION_FREEZE,
        C.SYNTHETIC_FRAMES, C.STEP0_TRENDS, C.PROCESS_RECORD, C.DATASET_MANIFEST,
        C.REGISTERS_DIR / "predeclared_criteria.json", C.REGISTERS_DIR / "data_use_history.json",
        C.REPO / "docs" / "patches" / "22.3.6" / "evidence" / "PATCH_22_3_6_SYNC_TRACK_START_AUDIT_TRACKS.csv",
    ]
    paths += [
        C.SYNTHETIC_MANIFEST, C.SMOKE_GATE, C.STEP0_FAMILY, C.STEP3_LEVEL_FREE, C.STEP4_CANDIDATES, C.STEP4_VERDICT,
        C.SYNC_AUDIT_22_3_6, C.REPO / "PATCH_22_3_4_ACCEPTED_CORE_HASHES.json",
        C.EVIDENCE / "confirm" / "confirmation_proposal.json",
    ]
    out = {_rel(p): C.sha256_file(p) for p in paths}
    for member in sorted(C.ROLE, key=C.member_key):
        out[_rel(C.unit_path(member))] = C.sha256_file(C.unit_path(member))
        s, part = C.member_key(member)
        base = C.CHARACTERIZATION / "members" / f"{s}_part_{part}_layer53"
        for name in ("member_audit.json", "frame_observations.csv", "scan_tracks.csv"):
            out[_rel(base / name)] = C.sha256_file(base / name)
    for member in C.group_members()["out_of_window_all"] + C.ROLE_MEMBERS["in_window_held_out"]:
        path = C.UNITS_DIR / f"confirm_c2__{member.replace(':', '_')}.json"
        out[_rel(path)] = C.sha256_file(path)
    return out


def external_hashes() -> dict[str, str]:
    """The three coupon HDF5 files F13 reads (outside the repo), when present."""

    out = {}
    for member, _ in field_figures.COUPONS:
        s, part = C.member_key(member)
        path = C.COUPON_DATA_DIR / f"part_{part}_{s}.h5"
        if path.is_file():
            out[str(path)] = C.sha256_file(path)
    return out


def field_hashes() -> dict[str, dict[str, str]]:
    """The c1 field files are read only for their frame -> process-row map; each must match the evaluate manifest."""

    manifest = {u["work_unit_id"]: u["capture_file"] for u in C.evaluate_manifest()["units"] if u.get("capture_file")}
    out = {}
    for member in sorted(C.ROLE, key=C.member_key):
        path = C.FIELDS_DIR / f"{C.CANDIDATE}__{member.replace(':', '_')}.npz"
        digest = C.sha256_file(path)
        want = manifest[f"22.4.3.2:{C.CANDIDATE}@{member}"]["sha256"]
        if digest != want:
            raise RuntimeError(f"{path.name}: sha256 {digest} != manifest {want}")
        out[_rel(path)] = digest
    return out


def methods_manifest(generator_index) -> dict:
    return {
        "schema": "lpbf_committee_package_methods_manifest",
        "package": "docs/analysis/committee_package",
        "pass": 2,
        "candidate": C.CANDIDATE,
        "status": "descriptive analysis of frozen records; no thermal run, no fitting, no selection",
        "estimands": {
            "e_Q": "sqrt of the hierarchical mean of r_Q^2, r_Q = ln(max(Q_model, 1 px) / max(Q_camera, 1 px)), Q in {H, W} (A26)",
            "J": "0.5 e_H^2 + 0.5 e_W^2 over a group's conditions (A26)",
            "median_ratio": "median of exp(r_Q) over a unit's pooled scored frames (descriptive)",
            "v_ratio": "e_Q(held out) / e_Q(calibration), each over its own conditions (reading V, plan 22.4.3.2)",
            "slopes": "least squares of ln(coupon median) on [1, ln P, ln v] or [1, ln VED]",
            "ratio_trend": "least squares of the coupon median r_Q on [1, ln VED] over 24 coupons",
            "replicate_difference": "ln(coupon median 0731 / 0730) for sizes, plain difference for e and median r (T10)",
            "oracle_floor": "e of a predictor equal to the camera's own track median, coupon median or other-day coupon median for every frame (T10)",
            "variance_partition": "exact frame-weighted sum-of-squares split: within track, between tracks in a coupon, between coupons in a condition, between conditions (T12)",
            "icc_design_effect": "one-way random-effects ICC (ANOVA, unbalanced n0), deff = 1 + (mean cluster size - 1) ICC, effective n = N / deff (T12)",
            "within_coupon_power": "Spearman of model and camera over frames and track medians; coupon e against camera frames shuffled within the coupon (T12)",
            "bland_altman": "coupon median r_Q against the geometric mean of the coupon median sizes; bias and 1.96 SD limits over the 14 in-window coupons (F8)",
            "operator_comparison": "the contract hierarchy applied to the reading-S synthetic camera against the re-measured camera, recomputed from synthetic_frames.csv.gz (T14)",
            "sensitivity_variants": "e and J under frame/track/coupon weighting, pixel floors 0.5/1/2 px, no-pool frames left out, minimum track length, leave one coupon out (T15)",
        },
        "aggregation_hierarchy": ["camera_frame", "scan_track", "coupon", "exact_condition_replicate", "unique_condition", "group"],
        "weighting": "every level an unweighted mean of the level below (A10); frame counts never weight tracks, coupons or conditions",
        "inferential_unit": "coupon (24) and condition (18); frames (24,129 scored) are not independent observations",
        "bootstrap": {
            "method": "percentile",
            "confidence_level": C.CONFIDENCE,
            "replicates": C.BOOTSTRAP_REPLICATES,
            "seed": C.SEED,
            "generator": "numpy.random.default_rng([seed, family, index]) (PCG64)",
            "families": {
                "1": "groups of >= 2 coupons: coupons resampled with replacement within the group; hierarchy recomputed with multiplicity weights; a condition absent from a draw drops out",
                "2": "coupons, conditions and one-coupon groups: scan tracks resampled with replacement within each coupon (within-coupon uncertainty only)",
                "3": "process slopes: coupons resampled within the subset; draws with a rank-deficient design skipped and counted",
                "4": "ratio-vs-VED trend: coupons resampled over all 24",
                "5": "replicate pairs (T10): scan tracks resampled within each coupon of a pair, independently; index = the coupon's position among the 24",
                "6": f"permutation control (T12): camera values shuffled across a coupon's scored frames, {variance.PERMUTATIONS} permutations per coupon; index = the coupon's position among the 24",
                "7": "Bland-Altman bias (F8): the 14 in-window coupons resampled; index 0 = H, 1 = W",
                "8": "operator slopes (T14): coupons resampled over all 24, one set of draws shared by every operator",
            },
            "generator_index": generator_index,
            "v_ratio_intervals": "held out / calibration: families 1 and 1 (independent groups); part_5 / calibration: family 2 (part_5) over family 1 (calibration)",
        },
        "missing_values": {
            "undefined_frames": "excluded and counted, never fabricated (A23); none occurred for confirm_c1",
            "no_pool_frames": "scored as H = W = 0 (D1) with the 1 px floor; model size medians use frames with a predicted pool",
            "excluded_by_rule": "first and last eligible frame of every scan track (A22); listed in D7",
            "camera_invalid": "laser-on mapped frames with non-finite camera H/W (3 frames); never in residuals; listed in D7",
            "synthetic_unpaired": "frames without a synthetic or re-measured camera blob are left out of the synthetic-operator scores and counted as lost coverage (T14)",
            "zero_width_blobs": "synthetic blobs of zero width have no H/W shape; left out of shape medians only",
        },
        "predeclared_vs_exploratory": {
            "T1": "conventions (predeclared: A10, A20-A26)",
            "T2": "descriptive record", "T3": "descriptive record (register compiled 2026-10-19)", "T4": "descriptive record",
            "T5": "record (values read from the code at build time; consistency across stage manifests checked)",
            "T6": "predeclared selection rule; values from the committed runs",
            "T7": "point values = reading C (predeclared, descriptive reading); intervals exploratory",
            "T8": "point ratios = reading V (predeclared, V_PASS); intervals and bootstrap shares exploratory",
            "T9": "Spearman values = reading X (predeclared, X_PARTIAL); coupon and group intervals exploratory",
            "T10": "exploratory (replicates and measurement floor; plan Part 1, item 3)",
            "T11": "exploratory (results report 4 was descriptive, not predeclared)",
            "T12": "exploratory (variance, effective sample size, within-coupon power; plan Part 1, item 4)",
            "T13": "descriptive",
            "T14": "synthetic-camera values = reading S (predeclared, S_DESCRIPTIVE); width-matched and threshold rows = 22.3.8 predeclared readings R-b, Q-b and Step 0; operator slopes exploratory",
            "T15": "exploratory (descriptive sensitivity on frozen records; no new search)",
            "T16": "record", "T17": "register of predeclared criteria", "T18": "exploratory", "T19": "descriptive record (checked against the 22.3.6 audit)",
            "F1": "descriptive", "F2": "descriptive", "F3": "descriptive",
            "F4": "recorded surrogate of the predeclared procedure; slices and guard boundary descriptive",
            "F5": "descriptive",
            "F6": "points: reading X inputs (predeclared Spearman); fitted trend and band exploratory",
            "F7": "descriptive", "F8": "exploratory", "F9": "exploratory", "F10": "descriptive", "F11": "exploratory",
            "F12": "exploratory", "F13": "descriptive illustration (frame chosen by a fixed rule)", "F14": "descriptive", "F15": "descriptive",
            "D1-D4, D7": "data", "D5": "exploratory (intervals added after the readings)",
            "D6": "record, with an independent reconstruction of the selection", "D8": "figure sources (data)",
        },
        "verification": "every coupon and group e_H, e_W, J and median ratio recomputed from the unit files equals the evaluate manifest to <= 1e-12; the synthetic-operator scores equal the synthetic manifest; the sync mapping equals the 22.3.6 audit; the selection is reconstructed from the recorded scores (PROVENANCE.json)",
        "scale_caveat": "micrometres use the nominal 8 um/px (A24); shapes, slopes, ratios of errors and rank correlations are scale-free (T14 E)",
        "held_out_status": "the 8 A8 held-out members were opened by the 22.4.3.2 evaluation after its freeze (A8, A27); this package uses them descriptively only",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--replicates", type=int, default=C.BOOTSTRAP_REPLICATES)
    parser.add_argument("--no-render", action="store_true", help="write figure sources but skip the matplotlib renders")
    args = parser.parse_args()
    if not C.units_available():
        print("c1 evaluate unit files not found under patch22_4_3_2_output/evaluate/units", file=sys.stderr)
        return 2
    started = dt.datetime.now().astimezone()
    analysis = build_datasets.build()
    verification = build_datasets.verify(analysis)
    print("manifest check:", verification["status"], "max |diff|", verification["max_abs_difference_vs_manifest"])
    boot = bootstrap.run(analysis, replicates=args.replicates)
    slope = slopes.run(analysis, replicates=args.replicates)
    outputs: dict[str, list] = {}
    outputs["build_datasets.py"] = list(build_datasets.write(analysis, boot["cis"]).values())
    outputs["bootstrap.py"] = list(boot["paths"].values())
    outputs["slopes.py"] = list(slope["paths"].values())

    rep = replicates.run(analysis, replicates=args.replicates)
    var = variance.run(analysis)
    ops = operators.run(analysis, replicates=args.replicates)
    sens = sensitivity.run(analysis)
    cand = candidates.run()
    syn = sync.run()
    fixed = controls.fixed_controls()
    stage_rows, consistency = controls.stage_rows()
    print("synthetic check:", ops["check"]["status"], "| sync check:", syn["check"]["status"], "| selection reconstruction:", cand["reconstruction"]["status"])
    outputs["replicates.py"] = list(rep["paths"].values())
    outputs["variance.py"] = list(var["paths"].values())
    outputs["operators.py"] = list(ops["paths"].values())
    outputs["sensitivity.py"] = list(sens["paths"].values())
    outputs["candidates.py"] = list(cand["paths"].values())
    outputs["sync.py"] = list(syn["paths"].values())

    outputs["tables.py"] = tables.run(analysis, boot["cis"], slope)
    d3 = build_datasets.coupon_records(analysis, boot["cis"])
    d4 = build_datasets.condition_group_records(analysis, boot["cis"])
    package = {
        "Package": "docs/analysis/committee_package, passes 1 and 2",
        "Candidate": f"{C.CANDIDATE} (frozen; selection freeze {C.load_json(C.SELECTION_FREEZE)['content_sha256'][:12]})",
        "Thermal runs, fitting, selection": "none, none, none",
        "Semantic versions": ", ".join(f"{k} {v}" for k, v in C.VERSIONS.items()),
        "Bootstrap": f"percentile, {args.replicates:,} replicates, seed {C.SEED}, families 1-8 (METHODS_MANIFEST.json)",
        "Environment": "tables and data: .venv (requirements.lock.txt); figures: .venv-analysis = the lock + matplotlib (requirements.analysis.txt)",
        "Workers": "single process (no thermal work units, A19 does not apply)",
        "Verification": (
            f"evaluate manifest {verification['values_checked']} values (max diff {verification['max_abs_difference_vs_manifest']:.1e}); "
            f"synthetic manifest {ops['check']['values_checked']} values (max diff {ops['check']['max_abs_difference']:.1e}); "
            f"22.3.6 sync audit {syn['check']['values_checked']} values; selection reconstruction {cand['reconstruction']['status']}; "
            f"calibrate and confirm unit files {len(cand['archive']['units'])} sha256-checked"
        ),
        "Held-out access": "the 8 A8 held-out coupons are read from the 22.4.3.2 evaluate records (opened after the freeze, A8, A27), descriptively",
        "Reproduction": "run_all.py; compare OUTPUT_SHA256SUMS.txt (byte-identical between builds)",
    }
    outputs["tables_pass2.py"] = (
        tables_pass2.t5(fixed, consistency) + tables_pass2.t9(analysis, d3, d4) + tables_pass2.t10(rep) + tables_pass2.t12(var)
        + tables_pass2.t14(ops) + tables_pass2.t15(sens) + tables_pass2.t16(stage_rows, consistency, package) + tables_pass2.t19(syn)
    )
    outputs["figures.py (sources)"] = figures.write_sources()
    outputs["figures_pass2.py (sources)"] = figures_pass2.write_sources()
    f13_rebuilt = field_figures.sources_available()
    if f13_rebuilt:
        outputs["field_figures.py (sources)"] = field_figures.write_sources(analysis)
    else:
        print("coupon HDF5 or c1 field files not found: F13 sources kept as committed")
        outputs["field_figures.py (sources)"] = [figures.SOURCE_DIR / name for name in ("F13_camera_pixels.csv", "F13_outlines.csv", "F13_frames.csv")]
    rendered = False
    if not args.no_render:
        try:
            import matplotlib  # noqa: F401
        except ImportError:
            print("matplotlib not available: figure renders skipped (use .venv-analysis)")
        else:
            outputs["figures.py (renders)"] = figures.render()
            outputs["figures_pass2.py (renders)"] = figures_pass2.render()
            import matplotlib.pyplot as plt

            outputs["field_figures.py (renders)"] = field_figures.render(plt)
            rendered = True
    C.write_json(C.PACKAGE / "METHODS_MANIFEST.json", methods_manifest(boot["generator_index"]))

    lines = []
    for script, paths in outputs.items():
        lines.append(f"# {script}")
        for p in sorted(set(paths), key=str):
            lines.append(f"{C.sha256_file(p)}  {_rel(p)}")
    lines.append("# run_all.py")
    lines.append(f"{C.sha256_file(C.PACKAGE / 'METHODS_MANIFEST.json')}  {_rel(C.PACKAGE / 'METHODS_MANIFEST.json')}")
    (C.PACKAGE / "OUTPUT_SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    try:
        import matplotlib

        mpl_version = matplotlib.__version__
    except ImportError:
        mpl_version = None
    provenance = {
        "schema": "lpbf_committee_package_provenance",
        "pass": 2,
        "run_started": started.isoformat(timespec="seconds"),
        "git_head_at_run": _git("rev-parse", "HEAD"),
        "git_tracked_changes_at_run": bool(_git("status", "--porcelain", "--untracked-files=no")),
        "scripts_sha256": {_rel(p): C.sha256_file(p) for p in sorted((C.PACKAGE / "scripts").glob("*.py"))},
        "runtime": {"python": platform.python_version(), "numpy": np.__version__, "matplotlib": mpl_version, "platform": platform.platform()},
        "candidate": C.CANDIDATE,
        "semantic_versions": C.VERSIONS,
        "bootstrap_replicates": args.replicates,
        "seed": C.SEED,
        "figures_rendered": rendered,
        "f13_sources_rebuilt": f13_rebuilt,
        "inputs_sha256": input_hashes(),
        "external_inputs_sha256": external_hashes(),
        "field_files_sha256_checked_against_manifest": field_hashes(),
        "calibrate_and_confirm_unit_files_checked_against_manifests": len(cand["archive"]["units"]),
        "verification": {
            "evaluate_manifest": verification,
            "step0_camera_slopes": slope["step0_check"],
            "synthetic_manifest": ops["check"],
            "sync_22_3_6_audit": syn["check"],
            "selection_reconstruction": cand["reconstruction"],
            "fixed_controls_constant_across_stages": consistency,
        },
        "held_out_access": "read from the 22.4.3.2 evaluate unit files; the 8 A8 held-out members were opened there after the freeze (A8, A27)",
        "fitting_or_selection_performed": False,
        "thermal_runs_performed": False,
        "workers": "single process (no thermal work units)",
    }
    C.write_json(C.PACKAGE / "PROVENANCE.json", provenance)
    print(f"wrote {sum(len(v) for v in outputs.values())} output files; figures rendered: {rendered}; F13 sources rebuilt: {f13_rebuilt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
