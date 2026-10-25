"""A small SYNTHETIC coupon that exercises the whole pipeline without the experimental data.

``python -m lpbf.reproduce example`` writes a fake coupon HDF5 file in the layout of the real ones (two short laser
tracks, a camera frame every 23 process rows), runs the frozen thermal model at the thesis's selected parameters
on it, extracts the model's H/W with the production beam-share association, applies the scored-frame rule and the
log-ratio objective, and writes ``example_result.json``.

Everything here is synthetic: the "camera" H/W are constants written into the file, the laser path is two straight
lines, and the numbers that come out demonstrate only that installation, input parsing, the solver, melt-pool
extraction and scoring run end to end. They have no scientific meaning and are not comparable with the thesis.

The run is the manifest-free path of the model: the calibration runner refuses files that are not the 24 recorded
coupons, so this module calls the same building blocks one level below it (``exact_fixed_time_params`` ->
``resize_xy_window`` -> ``prepare_current_physics_process_condition`` -> ``execute_temperature_traced_trial`` ->
``_calibration_observation_records`` -> ``aggregate_log_ratio_records``). The model code is untouched.
"""
from __future__ import annotations

import csv
import time
from pathlib import Path
from typing import Any

import h5py
import numpy as np

from lpbf.calibration_contract import Patch21GlobalParameterPolicy, condition_id
from lpbf.calibration_design import WINDOW_CELLS
from lpbf.camera_observations import measure_blob
from lpbf.configuration import CAMERA_COLS, CAMERA_LAYER, CAMERA_ROWS, CAMERA_THRESHOLD, load_final_model
from lpbf.data.coupon_inputs import CouponCondition
from lpbf.experiments.current_framework import (
    _calibration_observation_records,
    current_numerical_stability_preflight,
    execute_temperature_traced_trial,
    require_energy_accounting,
)
from lpbf.frame_records import _json_safe
from lpbf.geometry import resize_xy_window
from lpbf.infrastructure import sha256_file, write_json
from lpbf.log_ratio_objective import aggregate_log_ratio_records
from lpbf.model import current_execution
from lpbf.model.current_configuration import CURRENT_MODEL_CONFIGURATION, validate_current_physics_parameters
from lpbf.model.input_data import PRODUCTION_DAQ_DT_S
from lpbf.runtime.parameters import exact_fixed_time_params
from lpbf.scored_frame_rule import apply_scored_frame_rule, scored_frame_indices

SYNTHETIC_SET_ID = "synthetic"
SYNTHETIC_MEMBER = f"{SYNTHETIC_SET_ID}:part_1"
POWER_W = 140.0
SPEED_MM_S = 850.0
SPOT_MM = 0.08
HATCH_MM = 0.080
ROWS_PER_FRAME = 23  # ~8000 fps camera against the 200 kHz process clock
CAMERA_H_PX, CAMERA_W_PX = 10.0, 8.0  # the constant "camera" observation written into the file
CHANNELS = ["Laser Drive", "Laser Power", "On-Axis HIGH", "On-Axis LOW", "On-Axis TED", "Sync Pulse", "X-Position", "Y-Position", "NI_laser", "NI_AE", "X-Machine", "Y-Machine", "H", "W"]


def synthetic_process(rows_per_track: int = 160, off_rows: int = 60, tracks: int = 2) -> dict[str, np.ndarray]:
    """Two (or more) straight tracks one hatch apart, scanned back and forth, with laser-off margins."""

    n = off_rows + tracks * (rows_per_track + off_rows)
    drive = np.zeros(n); ted = np.full(n, 0.107); x = np.zeros(n); y = np.zeros(n); track = np.zeros(n, dtype=np.int64)
    step_mm = SPEED_MM_S * PRODUCTION_DAQ_DT_S
    x_now, y_now = 0.0, 0.0
    row = off_rows
    for t in range(tracks):
        direction = 1.0 if t % 2 == 0 else -1.0
        for k in range(rows_per_track):
            drive[row] = 5.0
            ted[row] = 0.253
            x_now += direction * step_mm
            x[row], y[row] = x_now, y_now
            track[row] = t + 1
            row += 1
        x[row : row + off_rows] = x_now
        y[row : row + off_rows] = y_now
        y_now += HATCH_MM
        row += off_rows
    x[:off_rows] = 0.0
    on = drive > 2.5
    h = np.where(on, CAMERA_H_PX, 0.0)
    w = np.where(on, CAMERA_W_PX, 0.0)
    return {"drive": drive, "ted": ted, "x": x, "y": y, "track": track, "H": h, "W": w}


def synthetic_frame(h_px: float, w_px: float) -> np.ndarray:
    """A bright ellipse on the camera's 64 x 24 frame, so that ``measure_blob`` has something to measure."""

    yy, xx = np.mgrid[0:CAMERA_ROWS, 0:CAMERA_COLS]
    cy, cx = CAMERA_ROWS / 2.0 - 0.5, CAMERA_COLS / 2.0 - 0.5
    inside = ((xx - cx) / (h_px / 2.0)) ** 2 + ((yy - cy) / (w_px / 2.0)) ** 2 <= 1.0
    return np.where(inside, 230, 20).astype(np.uint8)


def write_synthetic_coupon(path: Path, *, rows_per_track: int = 160) -> dict[str, Any]:
    """Write the fake HDF5 file and return the arrays that describe it."""

    process = synthetic_process(rows_per_track=rows_per_track)
    n = process["drive"].size
    data = np.zeros((len(CHANNELS), n))
    for name, key in (("Laser Drive", "drive"), ("On-Axis TED", "ted"), ("X-Machine", "x"), ("Y-Machine", "y"), ("H", "H"), ("W", "W")):
        data[CHANNELS.index(name)] = process[key]
    data[CHANNELS.index("Laser Power")] = 3.33
    mapped_rows = np.arange(14, n, ROWS_PER_FRAME, dtype=np.int64)
    frames = mapped_rows.size
    gige_time = 1000.0 + np.arange(frames) * 1.003e-4
    data_to_frame = np.full(n, -1, dtype=np.int64)
    data_to_frame[mapped_rows] = np.arange(frames)
    images = np.stack([synthetic_frame(CAMERA_H_PX, CAMERA_W_PX) if process["drive"][r] > 2.5 else np.full((CAMERA_ROWS, CAMERA_COLS), 20, dtype=np.uint8) for r in mapped_rows])
    path.parent.mkdir(parents=True, exist_ok=True)
    with h5py.File(path, "w") as h5:
        h5.attrs["part_id"] = "synthetic part 1 (NOT experimental data)"
        group = h5.create_group(CAMERA_LAYER)
        group.create_dataset("data", data=data)
        group.create_dataset("names", data=np.array([c.encode() for c in CHANNELS], dtype=object), dtype=h5py.special_dtype(vlen=bytes))
        group.create_dataset("gige_time", data=gige_time)
        group.create_dataset("gige_image", data=images)
        sync = group.create_group("sync")
        sync.attrs["method"] = "synthetic: every 23rd process row is a camera frame"
        sync.attrs["sync_gige_to_data_version"] = "synthetic"
        sync.attrs["data_threshold"] = 2.5
        sync.create_dataset("gige_image_to_data_index", data=mapped_rows)
        sync.create_dataset("data_to_gige_image_index", data=data_to_frame)
    return {**process, "mapped_rows": mapped_rows, "images": images, "rows": n, "frames": frames}


def camera_side_frame_rows(coupon: dict[str, Any]) -> list[dict[str, Any]]:
    """Every synchronized laser-on frame with its 'camera' H/W, labelled by the scored-frame rule."""

    rows = []
    for frame, row in enumerate(coupon["mapped_rows"].tolist()):
        if coupon["drive"][row] <= 2.5:
            continue
        rows.append(
            {
                "member_identity": SYNTHETIC_MEMBER,
                "acquisition_set_id": SYNTHETIC_SET_ID,
                "power_W": POWER_W,
                "speed_mm_s": SPEED_MM_S,
                "exact_condition_id": condition_id(POWER_W, SPEED_MM_S),
                "scan_track_id": str(int(coupon["track"][row])),
                "frame_index": frame,
                "mapped_process_row": row,
                "experimental_H_pixels": float(coupon["H"][row]),
                "experimental_W_pixels": float(coupon["W"][row]),
                "observation_eligible": True,
                "observation_status": "ELIGIBLE_FINITE_HW",
            }
        )
    return apply_scored_frame_rule(rows)


def run_example(output_directory: str | Path, *, rows_per_track: int = 160, progress: bool = True) -> dict[str, Any]:
    started = time.monotonic()
    out = Path(output_directory).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)

    def say(text: str) -> None:
        if progress:
            print(text, flush=True)

    h5_path = out / "synthetic_coupon.h5"
    coupon = write_synthetic_coupon(h5_path, rows_per_track=rows_per_track)
    say(f"1/6 wrote synthetic coupon: {coupon['rows']} process rows, {coupon['frames']} camera frames -> {h5_path.name}")

    frame_rows = camera_side_frame_rows(coupon)
    scored = scored_frame_indices(frame_rows)
    blob = measure_blob(coupon["images"][scored[0]], CAMERA_THRESHOLD)
    say(f"2/6 camera side: {len(frame_rows)} laser-on frames, {len(scored)} scored after the edge rule; blob at threshold {CAMERA_THRESHOLD}: H {blob['H_px']:.1f} px, W {blob['W_px']:.1f} px")

    final = load_final_model()
    coordinates = final["selected_parameters"]["coordinates"]
    condition = CouponCondition(coupon_id=1, power_W=POWER_W, nominal_speed_mm_s=SPEED_MM_S, spot_diameter_mm=SPOT_MM, sha256=sha256_file(h5_path), acquisition_set_id=SYNTHETIC_SET_ID, layer_name=CAMERA_LAYER, expected_filename=h5_path.name)
    base = resize_xy_window(exact_fixed_time_params(h5_path, condition), WINDOW_CELLS)
    prepared = current_execution.prepare_current_physics_process_condition(base)
    physics = Patch21GlobalParameterPolicy.from_values(**coordinates).coefficients.realized_parameters()
    validate_current_physics_parameters(base, physics, allow_legacy_deposition_control=False)
    params = current_execution.current_physics_trial_parameters(base, physics)
    preflight = current_numerical_stability_preflight(params, physics, boiling_strength=CURRENT_MODEL_CONFIGURATION.quadratic_boiling_strength)
    if preflight.get("status") != "PASS":
        raise RuntimeError(f"numerical preflight rejected the trial: {preflight}")
    say(f"3/6 parsed the file and built the frozen runtime ({WINDOW_CELLS} x {WINDOW_CELLS} window) at the thesis parameters: alpha {physics.absorptivity:.3f}, depth {physics.deposition_depth_mm:.4f} mm, ck {physics.liquid_conductivity_enhancement_factor:.3f}, eta {physics.eta_directional:.1f}")

    trial = execute_temperature_traced_trial(params=params, preloaded=prepared.preloaded, physics=physics, observation_frame_indices=np.asarray(scored, dtype=np.int64), unenclosed_contour_policy="record_nan")
    observations = _calibration_observation_records(trial.comparison_result, allow_nonfinite_primary=True)
    energy = require_energy_accounting(dict(observations[-1]["observation_diagnostics"])).to_dict()
    trace = dict(trial.temperature_trace)
    say(f"4/6 solver ran {int(trial.comparison_result.metadata['rows_simulated'])} process rows in {trace['thermal_substep_count']} thermal substeps; peak {float(trace['raw_global_Tmax_K']):.0f} K; energy balance relative error {float(energy['energy_balance_relative_error']):.1e}")

    by_frame = {int(o["frame_index"]): o for o in observations}
    records = []
    for row in frame_rows:
        record = dict(row)
        observation = by_frame.get(int(row["frame_index"]))
        if not row["scored_frame"]:
            record["status"] = "EXCLUDED"
        elif observation is None:
            raise RuntimeError(f"no model observation for scored frame {row['frame_index']}")
        elif str(observation["observation_status"]).startswith("UNDEFINED_"):
            record.update({"status": "UNDEFINED", "undefined_reason": observation["undefined_reason"], "simulated_H_pixels": None, "simulated_W_pixels": None})
        else:
            record.update({"status": "PASS", "simulated_H_pixels": observation["simulated_H_pixels"], "simulated_W_pixels": observation["simulated_W_pixels"], "melt_classification": observation["melt_classification"]})
        record["failure"] = None
        records.append(record)
    scored_records = [r for r in records if r["status"] == "PASS"]
    say(f"5/6 melt-pool extraction: {len(scored_records)} scored frames with finite H/W, {sum(r['status'] == 'UNDEFINED' for r in records)} undefined; model H/W of the first scored frame {scored_records[0]['simulated_H_pixels']:.2f} / {scored_records[0]['simulated_W_pixels']:.2f} px" if scored_records else "5/6 melt-pool extraction: no scored frame had a finite H/W")

    score = aggregate_log_ratio_records(records, member_ids=[SYNTHETIC_MEMBER], condition_ids=[condition_id(POWER_W, SPEED_MM_S)])
    result = {
        "synthetic": True,
        "note": "SYNTHETIC EXAMPLE: fake coupon, constant 'camera' H/W; demonstrates the pipeline only and has no scientific meaning",
        "coupon_file": h5_path.name,
        "coupon_sha256": condition.sha256,
        "process_rows": coupon["rows"],
        "camera_frames": coupon["frames"],
        "selected_parameters": final["selected_parameters"],
        "realized_physics": {"absorptivity": physics.absorptivity, "deposition_depth_mm": physics.deposition_depth_mm, "liquid_conductivity_enhancement_factor": physics.liquid_conductivity_enhancement_factor, "eta_directional": physics.eta_directional},
        "numerical_preflight_status": preflight.get("status"),
        "camera_blob_first_scored_frame": blob,
        "temperature_trace": trace,
        "energy_accounting": energy,
        "frame_records": records,
        "objective": {k: score[k] for k in ("status", "objective_value", "e_H", "e_W", "coverage_flag", "counts")},
        "wall_time_s": round(time.monotonic() - started, 1),
    }
    write_json(out / "example_result.json", _json_safe(result))
    with (out / "frame_records.csv").open("w", encoding="utf-8", newline="") as handle:
        columns = ["frame_index", "mapped_process_row", "scan_track_id", "status", "exclusion_reason", "experimental_H_pixels", "experimental_W_pixels", "simulated_H_pixels", "simulated_W_pixels", "melt_classification"]
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for record in records:
            writer.writerow({k: record.get(k) for k in columns})
    say(f"6/6 scoring: J = {score['objective_value']:.4f} (e_H {score['e_H']:.3f}, e_W {score['e_W']:.3f}, coverage {score['counts']['coverage']:.2f}); wrote {out / 'example_result.json'} in {result['wall_time_s']} s")
    return result


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output-dir", default="examples/synthetic/output")
    parser.add_argument("--rows-per-track", type=int, default=160)
    args = parser.parse_args(argv)
    run_example(args.output_dir, rows_per_track=args.rows_per_track)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
