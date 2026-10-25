"""Shared current-experiment runtime construction.

This module owns only behavior that is identical across supported current LPBF
experiment executions.  Experiment-specific observation selection, layer
semantics, output naming, diagnostics, gates, and failure handling remain with
their owning drivers.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from lpbf.model.parameters import SimulationParameters, get_model_parameters
from lpbf.runtime.configuration import (
    FrozenExperimentConfiguration,
    apply_frozen_experiment_configuration,
    assert_frozen_experiment_parameters_match,
)


def construct_frozen_runtime_parameters(
    *,
    input_path: Path,
    incident_power_W: float,
    layer_name: str,
    output_h5_filename: str,
    output_directory: Path,
    configuration: FrozenExperimentConfiguration,
) -> SimulationParameters:
    """Construct one frozen-model runtime parameter set from explicit run fields.

    The helper deliberately stops before experiment-specific identity checks and
    ``validate()`` so callers preserve their historical exception ordering and
    domain-specific error messages.
    """
    base = get_model_parameters()
    runtime = replace(
        base,
        input=replace(
            base.input,
            h5_path_select=Path(input_path),
            h5_use_file_dialog=False,
        ),
        heat_source=replace(
            base.heat_source,
            incident_power_W=float(incident_power_W),
        ),
        comparison=replace(
            base.comparison,
            layer_name=str(layer_name),
            output_h5_filename=str(output_h5_filename),
        ),
        output=replace(base.output, output_directory=Path(output_directory)),
    )
    params = apply_frozen_experiment_configuration(runtime, configuration)
    assert_frozen_experiment_parameters_match(params, configuration)
    return params
