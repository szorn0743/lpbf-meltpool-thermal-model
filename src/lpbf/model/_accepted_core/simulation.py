"""Analytics simulation orchestration for the moving-window LPBF solver.

This module coordinates canonical process-data rows through moving-window updates,
heat-source construction, finite-volume integration, runtime diagnostics, and the
analytics HDF5 results writer. Numerical equations remain owned by their existing
physics modules.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from lpbf.postprocessing import populate_reconstructible_analysis_features
from lpbf.model._accepted_core.heat_source import HeatSourceFieldBuilder, build_centered_heat_source_for_row
from lpbf.model._accepted_core.input_data import iter_h5_process_blocks, prepare_h5_stream
from lpbf.model._accepted_core.moving_window import (
    MovingWindowState,
    apply_moving_window_update,
)
from lpbf.model._accepted_core.parameters import (
    C_TO_K,
    HeatSourceParameters,
    MovingWindowControls,
    SimulationParameters,
    get_params,
)
from lpbf.runtime import results_io
from lpbf.model._accepted_core.solver import (
    NUMBA_AVAILABLE,
    MeltPoolFeatureWorkspace,
    compute_melt_pool_features,
    compute_phase_diagnostics,
    compute_source_power_W,
    compute_stored_energy_relative_to_temperature_J,
    compute_temperature_statistics,
    compute_vaporization_diagnostics,
    explicit_fvm_step,
    explicit_fvm_step_numba,
    warm_up_numba_solver,
)



def _params_with_dt(params: SimulationParameters, dt_s: float) -> SimulationParameters:
    return replace(
        params,
        time=replace(
            params.time,
            dt_s=float(dt_s),
            total_time_s=max(float(dt_s), params.time.total_time_s),
        ),
    )


def _params_with_bulk_initial_temperature(
    params: SimulationParameters,
    bulk_temperature_K: float,
) -> SimulationParameters:
    return replace(
        params,
        initial_condition=replace(
            params.initial_condition,
            initial_temperature_C=float(bulk_temperature_K - C_TO_K),
        ),
    )

def _advance_interval(
    T: np.ndarray,
    T_scratch: np.ndarray,
    q_dot: np.ndarray,
    params: SimulationParameters,
    dt_interval_s: float,
    previous_source_power_W: float,
    cumulative_source_energy_J: float,
    cumulative_top_loss_energy_J: float,
    cumulative_side_loss_energy_J: float,
    cumulative_bottom_loss_energy_J: float,
) -> tuple[
    np.ndarray,
    np.ndarray,
    float,
    float,
    float,
    float,
    float,
    float,
    float,
    float,
]:
    """Advance one process-data interval using the existing explicit FVM stepping.

    ``q_dot`` may be identically zero during laser-off intervals; conduction and
    configured boundary heat losses still advance over the full interval.
    """
    if dt_interval_s < -1.0e-15:
        raise ValueError("Input time values must be nondecreasing.")
    remaining_s = max(0.0, dt_interval_s)
    interval_top_loss_energy_J = 0.0
    interval_side_loss_energy_J = 0.0
    interval_bottom_loss_energy_J = 0.0
    while remaining_s > 1.0e-15:
        sub_dt_s = min(float(params.time.dt_s), remaining_s)
        sub_params = (
            params
            if abs(sub_dt_s - params.time.dt_s) <= 1.0e-15
            else _params_with_dt(params, sub_dt_s)
        )
        if params.output.use_numba and NUMBA_AVAILABLE:
            T_new, boundary_powers = explicit_fvm_step_numba(
                T,
                q_dot,
                sub_params,
                temperature_out_K=T_scratch,
                return_boundary_powers=True,
            )
            T, T_scratch = T_new, T
        else:
            T, boundary_powers = explicit_fvm_step(
                T,
                q_dot,
                sub_params,
                return_boundary_powers=True,
            )
        top_substep_power_W = float(boundary_powers["top_loss_power_W"])
        side_substep_power_W = float(boundary_powers["side_loss_power_W"])
        bottom_substep_power_W = float(boundary_powers["bottom_loss_power_W"])
        cumulative_source_energy_J += previous_source_power_W * sub_dt_s
        top_substep_energy_J = top_substep_power_W * sub_dt_s
        side_substep_energy_J = side_substep_power_W * sub_dt_s
        bottom_substep_energy_J = bottom_substep_power_W * sub_dt_s
        interval_top_loss_energy_J += top_substep_energy_J
        interval_side_loss_energy_J += side_substep_energy_J
        interval_bottom_loss_energy_J += bottom_substep_energy_J
        cumulative_top_loss_energy_J += top_substep_energy_J
        cumulative_side_loss_energy_J += side_substep_energy_J
        cumulative_bottom_loss_energy_J += bottom_substep_energy_J
        remaining_s -= sub_dt_s

    if dt_interval_s > 0.0:
        top_loss_power_W = interval_top_loss_energy_J / dt_interval_s
        side_loss_power_W = interval_side_loss_energy_J / dt_interval_s
        bottom_loss_power_W = interval_bottom_loss_energy_J / dt_interval_s
        total_boundary_loss_power_W = (
            top_loss_power_W + side_loss_power_W + bottom_loss_power_W
        )
    else:
        top_loss_power_W = 0.0
        side_loss_power_W = 0.0
        bottom_loss_power_W = 0.0
        total_boundary_loss_power_W = 0.0

    return (
        T,
        T_scratch,
        cumulative_source_energy_J,
        cumulative_top_loss_energy_J,
        cumulative_side_loss_energy_J,
        cumulative_bottom_loss_energy_J,
        top_loss_power_W,
        side_loss_power_W,
        bottom_loss_power_W,
        total_boundary_loss_power_W,
    )


def _compute_runtime_diagnostics(
    T: np.ndarray,
    q_dot: np.ndarray,
    params: SimulationParameters,
    current_source: HeatSourceParameters,
    laser_on: bool,
    row_index: int,
    n_rows: int,
    current_time_s: float,
    median_buffer: np.ndarray,
    melt_pool_workspace: MeltPoolFeatureWorkspace,
) -> tuple[dict[str, float], dict[str, Any]]:
    """Validate the row state and compute analytics features for the results writer."""
    safety_check_due = (
        row_index == 0
        or row_index == n_rows - 1
        or row_index % int(params.output.safety_check_every_n_rows) == 0
    )
    if safety_check_due:
        if not np.all(np.isfinite(T)):
            raise FloatingPointError(
                f"Non-finite temperature field at row {row_index}, "
                f"time {current_time_s:.6e} s."
            )
        if not np.all(np.isfinite(q_dot)):
            raise FloatingPointError(
                f"Non-finite heat-source field at row {row_index}, "
                f"time {current_time_s:.6e} s."
            )
        discrete_source_power_W = compute_source_power_W(q_dot, params)
        expected_source_power_W = float(current_source.deposited_power_W)
        source_power_tolerance_W = max(
            1.0e-10,
            1.0e-10 * abs(expected_source_power_W),
        )
        if not np.isclose(
            discrete_source_power_W,
            expected_source_power_W,
            rtol=0.0,
            atol=source_power_tolerance_W,
        ):
            raise FloatingPointError(
                "Discrete heat-source normalization failed at "
                f"row {row_index}, time {current_time_s:.6e} s: "
                f"integrated={discrete_source_power_W:.12e} W, "
                f"expected={expected_source_power_W:.12e} W."
            )

    expensive_full_field_features_due = (
        row_index % int(params.output.expensive_full_field_features_every_n_rows) == 0
    )
    stats = compute_temperature_statistics(
        T,
        median_buffer=median_buffer,
        compute_distribution_statistics=expensive_full_field_features_due,
    )
    melt_pool = compute_melt_pool_features(
        T,
        params,
        laser_center_x_m=(current_source.center_x_m(params) if laser_on else None),
        laser_center_y_m=(current_source.center_y_m(params) if laser_on else None),
        workspace=melt_pool_workspace,
        compute_connectivity=expensive_full_field_features_due,
    )
    full_rate_statistics = (
        stats["temperature_min_K"],
        stats["temperature_max_K"],
        stats["temperature_mean_K"],
    )
    if not all(np.isfinite(value) for value in full_rate_statistics):
        raise FloatingPointError(
            f"Non-finite full-rate temperature statistic at row {row_index}, "
            f"time {current_time_s:.6e} s."
        )
    if expensive_full_field_features_due:
        sampled_statistics = (
            stats["temperature_median_K"],
            stats["temperature_std_K"],
            stats["temperature_skewness"],
            stats["temperature_kurtosis_pearson"],
            melt_pool["liquid_largest_component_fraction"],
        )
        if not all(np.isfinite(value) for value in sampled_statistics):
            raise FloatingPointError(
                f"Non-finite sampled full-field feature at row {row_index}, "
                f"time {current_time_s:.6e} s."
            )
    if stats["temperature_min_K"] < 0.0:
        raise FloatingPointError(
            f"Negative Kelvin temperature at row {row_index}, "
            f"time {current_time_s:.6e} s."
        )
    return stats, melt_pool


def _run_analytics_simulation(
    params: SimulationParameters,
    source: HeatSourceParameters,
    controls: MovingWindowControls,
    blocks: Iterable[dict[str, np.ndarray]],
    n_rows: int,
    input_metadata: dict[str, Any],
    bulk_temperature_K: float,
) -> list[Path]:
    """Run the full-rate solver and write one analytics-only HDF5 file."""
    params = _params_with_bulk_initial_temperature(params, bulk_temperature_K)
    params.validate()
    source.validate(params)

    output_dir = Path(params.output.output_directory)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / params.output.output_h5_filename
    if output_path.exists():
        output_path.unlink()

    T = np.full(
        (params.grid.Nx, params.grid.Ny, params.grid.Nz),
        bulk_temperature_K,
        dtype=np.float64,
    )
    T_scratch = np.empty_like(T)
    median_buffer = np.empty(T.size, dtype=np.float64)
    field_builder = HeatSourceFieldBuilder(params)
    melt_pool_workspace = MeltPoolFeatureWorkspace(T.shape)
    q_dot = field_builder.buffer
    q_dot.fill(0.0)
    current_source = replace(source, incident_power_W=0.0, absorptivity=0.0)
    state = MovingWindowState(bulk_temperature_K=bulk_temperature_K)

    if params.output.use_numba:
        warm_up_numba_solver(params)

    cumulative_source_energy_J = 0.0
    cumulative_top_loss_energy_J = 0.0
    cumulative_side_loss_energy_J = 0.0
    cumulative_bottom_loss_energy_J = 0.0
    cumulative_window_exit_energy_J = 0.0
    cumulative_reset_removed_energy_J = 0.0
    previous_time_s: float | None = None
    previous_source_power_W = np.nan
    top_loss_power_W = 0.0
    side_loss_power_W = 0.0
    bottom_loss_power_W = 0.0
    total_boundary_loss_power_W = 0.0
    low_clip_events = 0
    high_clip_events = 0
    nonfinite_ted_events = 0
    invalid_powered_ted_events = 0
    records_processed = 0

    print("Starting analytics-only moving-window simulation.")
    print(f"  Output HDF5:        {output_path}")
    print(f"  Rows:               {n_rows}")
    print(f"  Grid:               {params.grid.Nx} x {params.grid.Ny} x {params.grid.Nz}")
    print(f"  Solver dt:          {params.time.dt_s:.6e} s")
    print(f"  Numba enabled:      {params.output.use_numba and NUMBA_AVAILABLE}")
    print(f"  Input block rows:   {params.output.input_block_rows}")
    print(f"  HDF5 buffer rows:   {params.output.h5_buffer_rows}")

    writer = results_io.AnalyticsH5Writer(
        path=output_path,
        n_rows=n_rows,
        params=params,
        input_metadata=input_metadata,
    )
    try:
        for block in blocks:
            block_length = int(block["row_index"].size)
            for local_index in range(block_length):
                row_index = int(block["row_index"][local_index])
                current_time_s = float(block["time_s"][local_index])

                if previous_time_s is not None:
                    dt_interval_s = current_time_s - previous_time_s
                    previous_source_power_W = float(current_source.deposited_power_W)
                    (
                        T,
                        T_scratch,
                        cumulative_source_energy_J,
                        cumulative_top_loss_energy_J,
                        cumulative_side_loss_energy_J,
                        cumulative_bottom_loss_energy_J,
                        top_loss_power_W,
                        side_loss_power_W,
                        bottom_loss_power_W,
                        total_boundary_loss_power_W,
                    ) = _advance_interval(
                        T=T,
                        T_scratch=T_scratch,
                        q_dot=q_dot,
                        params=params,
                        dt_interval_s=dt_interval_s,
                        previous_source_power_W=previous_source_power_W,
                        cumulative_source_energy_J=cumulative_source_energy_J,
                        cumulative_top_loss_energy_J=cumulative_top_loss_energy_J,
                        cumulative_side_loss_energy_J=cumulative_side_loss_energy_J,
                        cumulative_bottom_loss_energy_J=cumulative_bottom_loss_energy_J,
                    )
                else:
                    previous_source_power_W = np.nan

                laser_x_mm = float(block["laser_x_mm"][local_index])
                laser_y_mm = float(block["laser_y_mm"][local_index])
                laser_on = bool(block["laser_on"][local_index])
                T, state, moving_record = apply_moving_window_update(
                    temperature_K=T,
                    state=state,
                    params=params,
                    controls=controls,
                    laser_x_mm=laser_x_mm,
                    laser_y_mm=laser_y_mm,
                    laser_on=laser_on,
                )
                cumulative_window_exit_energy_J += float(moving_record.window_exit_energy_J)
                cumulative_reset_removed_energy_J += float(moving_record.reset_removed_energy_J)

                ted_eta = float(block["ted_effective_absorptivity"][local_index])
                ted_reflected_fraction_used = float(
                    block.ted_reflected_fraction_used[local_index]
                    if block.ted_reflected_fraction_used is not None
                    else block.measured_reflectivity[local_index]
                )
                ted_reflected_fraction_raw = float(
                    block.ted_reflected_fraction_raw[local_index]
                    if block.ted_reflected_fraction_raw is not None
                    else np.nan
                )
                effective_absorptivity_raw = float(
                    block.effective_absorptivity_raw[local_index]
                    if block.effective_absorptivity_raw is not None
                    else np.nan
                )
                ted_nonfinite = bool(block["ted_nonfinite_flag"][local_index])
                ted_reference_nonpositive = bool(
                    block["ted_reference_nonpositive_flag"][local_index]
                )
                derived_calibration_valid = bool(
                    laser_on and (not ted_nonfinite) and (not ted_reference_nonpositive)
                )
                if block.ted_calibration_valid_flag is not None:
                    explicit_calibration_valid = bool(
                        block.ted_calibration_valid_flag[local_index]
                    )
                    if explicit_calibration_valid != derived_calibration_valid:
                        raise ValueError(
                            "Inconsistent TED calibration-valid flag at process row "
                            f"{row_index}: explicit={explicit_calibration_valid}, "
                            f"derived={derived_calibration_valid}."
                        )
                ted_calibration_valid = derived_calibration_valid
                ted_invalid_powered = bool(laser_on and (not ted_calibration_valid))
                if block.ted_invalid_powered_flag is not None:
                    explicit_invalid_powered = bool(
                        block.ted_invalid_powered_flag[local_index]
                    )
                    if explicit_invalid_powered != ted_invalid_powered:
                        raise ValueError(
                            "Inconsistent TED invalid-powered flag at process row "
                            f"{row_index}: explicit={explicit_invalid_powered}, "
                            f"derived={ted_invalid_powered}."
                        )
                source_enabled = bool(laser_on and ted_calibration_valid)
                q_dot, current_source = build_centered_heat_source_for_row(
                    params=params,
                    source_template=source,
                    controls=controls,
                    spot_size_um=float(block["spot_size_um"][local_index]),
                    laser_on=source_enabled,
                    accumulated_subcell_x_mm=state.accumulated_subcell_x_mm,
                    accumulated_subcell_y_mm=state.accumulated_subcell_y_mm,
                    effective_absorptivity=(ted_eta if np.isfinite(ted_eta) else 0.0),
                    field_builder=field_builder,
                    row_index=row_index,
                    moving_window_state=state,
                    moving_window_update=moving_record,
                )

                stats, melt_pool = _compute_runtime_diagnostics(
                    T=T,
                    q_dot=q_dot,
                    params=params,
                    current_source=current_source,
                    laser_on=laser_on,
                    row_index=row_index,
                    n_rows=n_rows,
                    current_time_s=current_time_s,
                    median_buffer=median_buffer,
                    melt_pool_workspace=melt_pool_workspace,
                )

                low_clip = bool(block["ted_reflection_clipped_low_flag"][local_index])
                high_clip = bool(block["ted_reflection_clipped_high_flag"][local_index])
                low_clip_events += int(low_clip)
                high_clip_events += int(high_clip)
                nonfinite_ted_events += int(ted_nonfinite)
                invalid_powered_ted_events += int(ted_invalid_powered)

                feature_record = {
                    "row_index": row_index,
                    "time_s": current_time_s,
                    "temperature_min_K": stats["temperature_min_K"],
                    "temperature_max_K": stats["temperature_max_K"],
                    "temperature_mean_K": stats["temperature_mean_K"],
                    "temperature_median_K": stats["temperature_median_K"],
                    "temperature_std_K": stats["temperature_std_K"],
                    "temperature_skewness": stats["temperature_skewness"],
                    "temperature_kurtosis_pearson": stats["temperature_kurtosis_pearson"],
                    "liquid_volume_m3": melt_pool["liquid_volume_m3"],
                    "melt_pool_aspect_ratio": melt_pool["melt_pool_aspect_ratio"],
                    "melt_pool_centroid_offset_x_m": melt_pool["melt_pool_centroid_offset_x_m"],
                    "melt_pool_centroid_offset_y_m": melt_pool["melt_pool_centroid_offset_y_m"],
                    "liquid_largest_component_fraction": melt_pool[
                        "liquid_largest_component_fraction"
                    ],
                }
                process_record = {
                    "laser_x_mm": laser_x_mm,
                    "laser_y_mm": laser_y_mm,
                    "laser_on": laser_on,
                    "scan_track_id": int(block["scan_track_id"][local_index]),
                    "on_axis_ted_raw": float(block["on_axis_ted_raw"][local_index]),
                    "ted_reflected_fraction_raw": ted_reflected_fraction_raw,
                    "ted_reflected_fraction_used": ted_reflected_fraction_used,
                    "effective_absorptivity_raw": effective_absorptivity_raw,
                    "effective_absorptivity": ted_eta,
                    "ted_effective_absorptivity": ted_eta,
                    "applied_absorptivity": float(current_source.absorptivity),
                    "source_power_used_previous_interval_W": previous_source_power_W,
                    "source_power_for_next_interval_W": float(current_source.deposited_power_W),
                    "top_loss_power_previous_interval_W": float(top_loss_power_W),
                    "side_loss_power_previous_interval_W": float(side_loss_power_W),
                    "bottom_loss_power_previous_interval_W": float(
                        bottom_loss_power_W
                    ),
                    "total_boundary_loss_power_previous_interval_W": float(
                        total_boundary_loss_power_W
                    ),
                    "window_shift_x_cells": int(moving_record.window_shift_x_cells),
                    "window_shift_y_cells": int(moving_record.window_shift_y_cells),
                    "window_reset_flag": bool(moving_record.window_reset_flag),
                    "window_reset_reason": moving_record.window_reset_reason,
                    "ted_reflection_clipped_low_flag": low_clip,
                    "ted_reflection_clipped_high_flag": high_clip,
                    "ted_reference_nonpositive_flag": ted_reference_nonpositive,
                    "ted_nonfinite_flag": ted_nonfinite,
                    "ted_calibration_valid_flag": ted_calibration_valid,
                    "ted_invalid_powered_flag": ted_invalid_powered,
                    "source_enabled_flag": source_enabled,
                    "window_exit_energy_J": float(moving_record.window_exit_energy_J),
                    "reset_removed_energy_J": float(moving_record.reset_removed_energy_J),
                    "cumulative_source_energy_J": cumulative_source_energy_J,
                    "cumulative_top_loss_energy_J": cumulative_top_loss_energy_J,
                    "cumulative_side_loss_energy_J": cumulative_side_loss_energy_J,
                    "cumulative_bottom_loss_energy_J": cumulative_bottom_loss_energy_J,
                    "cumulative_total_boundary_loss_energy_J": (
                        cumulative_top_loss_energy_J
                        + cumulative_side_loss_energy_J
                        + cumulative_bottom_loss_energy_J
                    ),
                    "cumulative_window_exit_energy_J": cumulative_window_exit_energy_J,
                    "cumulative_reset_removed_energy_J": cumulative_reset_removed_energy_J,
                }
                writer.append(feature_record, process_record)

                validation_due = (
                    row_index == 0
                    or row_index == n_rows - 1
                    or row_index % int(params.output.validation_every_n_rows) == 0
                    or bool(moving_record.window_reset_flag)
                    or stats["temperature_max_K"] >= params.material.T_boiling_K
                )
                if validation_due:
                    stored_energy_J = compute_stored_energy_relative_to_temperature_J(
                        T,
                        reference_temperature_K=bulk_temperature_K,
                        params=params,
                    )
                    phase = compute_phase_diagnostics(T, params)
                    vapor = compute_vaporization_diagnostics(T, params)
                    residual_J = (
                        cumulative_source_energy_J
                        - cumulative_top_loss_energy_J
                        - cumulative_side_loss_energy_J
                        - cumulative_bottom_loss_energy_J
                        - cumulative_window_exit_energy_J
                        - cumulative_reset_removed_energy_J
                        - stored_energy_J
                    )
                    relative_error = abs(residual_J) / max(
                        abs(cumulative_source_energy_J),
                        abs(stored_energy_J),
                        1.0e-12,
                    )
                    writer.append_validation(
                        {
                            "row_index": row_index,
                            "time_s": current_time_s,
                            "stored_energy_J": stored_energy_J,
                            "energy_balance_residual_J": residual_J,
                            "energy_balance_relative_error": relative_error,
                            "num_cells_mushy": phase["num_cells_mushy"],
                            "num_cells_liquid": phase["num_cells_liquid"],
                            "num_cells_above_boiling": vapor["num_cells_above_boiling_all"],
                            "boiling_flag": vapor["num_cells_above_boiling_all"] > 0,
                        }
                    )

                previous_time_s = current_time_s
                records_processed += 1
                if records_processed % max(1, int(params.output.h5_buffer_rows)) == 0:
                    print(f"  Processed {records_processed:,} / {n_rows:,} rows")
    except Exception:
        writer.close(
            {
                "run_status": "failed",
                "records_processed": records_processed,
            }
        )
        raise

    writer.close(
        {
            "run_status": "complete",
            "records_processed": records_processed,
            "ted_low_clip_events": low_clip_events,
            "ted_high_clip_events": high_clip_events,
            "ted_nonfinite_events": nonfinite_ted_events,
            "ted_invalid_powered_events": invalid_powered_ted_events,
        }
    )
    populate_reconstructible_analysis_features(output_path)
    print("Analytics simulation complete.")
    print(f"  HDF5 file: {output_path}")
    return [output_path]

def run_moving_window_simulation(
    params: SimulationParameters | None = None,
    source: HeatSourceParameters | None = None,
    controls: MovingWindowControls | None = None,
    max_rows: int | None = None,
) -> list[Path]:
    """Run the configured full-rate simulation and return the analytics HDF5 path."""
    if params is None:
        params = get_params()
    else:
        params.validate()
    source = params.heat_source if source is None else source
    controls = params.moving_window if controls is None else controls

    context = prepare_h5_stream(params, max_rows=max_rows)
    blocks = iter_h5_process_blocks(context, params)
    bulk_temperature_K = params.initial_condition.initial_temperature_K
    input_metadata = dict(context.metadata)
    input_metadata["input_mode"] = "hdf5_streaming"
    return _run_analytics_simulation(
        params=params,
        source=source,
        controls=controls,
        blocks=blocks,
        n_rows=context.n_rows,
        input_metadata=input_metadata,
        bulk_temperature_K=bulk_temperature_K,
    )

