"""Frozen Patch 13.x coupon-experiment model configuration.

Patch 13.0.3 separates the accepted Patch 12.2.3 scientific/numerical model
state from runtime/process inputs.  Coupon power, input/output paths, layer
selection, and output filenames remain runtime concerns; frozen model and
numerical-fidelity fields are reapplied from the versioned JSON configuration
before a coupon experiment can run.

This module intentionally does not run simulations, discover HDF5 files, or
provide GUI behavior.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path

from typing import TYPE_CHECKING, Any, Mapping

from lpbf.infrastructure import (
    canonical_json_bytes as _shared_canonical_json_bytes,
    canonical_sha256 as _shared_canonical_sha256,
    read_json as _shared_read_json,
)
if TYPE_CHECKING:
    from lpbf.model.parameters import SimulationParameters


FROZEN_EXPERIMENT_CONFIGURATION_SCHEMA = "lpbf_frozen_coupon_experiment_configuration"
FROZEN_EXPERIMENT_CONFIGURATION_SCHEMA_VERSION = "13.0.3"
FROZEN_EXPERIMENT_CONFIGURATION_PATCH_VERSION = "13.0.3"
FROZEN_EXPERIMENT_CONFIGURATION_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "frozen_configuration.json"
)

# Patch 17.4 current-model identity.  This digest protects the accepted
# scientific state without importing the historical Patch 9-13 provenance
# machinery from validated_configuration.py during current execution.
CURRENT_ACCEPTED_CONFIGURATION_SHA256 = (
    "a6e7bcae89209bfb24ad560cf326bbc2ec3f075d5cec921b79863f11f120d31c"
)

# Layer-scope policy is shared by smoke selection, its methodology gate, and
# the full-production planner.  Keeping it here prevents the reserved
# independent-validation layer from drifting into an earlier workflow.
COUPON_CHARACTERIZATION_LAYER_NAMES = frozenset({"layer53"})
RESERVED_VALIDATION_LAYER_NAMES = frozenset({"layer52"})

_FROZEN_PARAMETER_BLOCKS = (
    "material",
    "geometry",
    "grid",
    "boundary_conditions",
    "initial_condition",
    "time",
    "input",
    "heat_source",
    "moving_window",
    "comparison",
)


class ExperimentConfigurationError(ValueError):
    """Raised when the frozen coupon-experiment configuration is invalid."""


def _canonical_json_bytes(value: Any) -> bytes:
    return _shared_canonical_json_bytes(value, allow_nan=True)


def _canonical_sha256(value: Any) -> str:
    return _shared_canonical_sha256(value, allow_nan=True)


def _validate_sha256(value: object, *, field: str) -> str:
    text = str(value)
    if len(text) != 64:
        raise ExperimentConfigurationError(f"{field} must be a 64-character SHA-256 digest")
    try:
        int(text, 16)
    except ValueError as exc:
        raise ExperimentConfigurationError(f"{field} must be hexadecimal SHA-256 text") from exc
    return text


@dataclass(frozen=True)
class FrozenExperimentConfiguration:
    """Immutable canonical representation of the Patch 13.0.3 configuration."""

    canonical_json: str
    sha256: str

    def to_dict(self) -> dict[str, Any]:
        """Return a detached JSON-compatible copy of the configuration."""
        return json.loads(self.canonical_json)

    def write_json(self, path: str | Path) -> Path:
        """Serialize this exact configuration to ``path`` in readable JSON form."""
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return output_path


def _validate_payload(payload: Mapping[str, Any]) -> None:
    if payload.get("schema") != FROZEN_EXPERIMENT_CONFIGURATION_SCHEMA:
        raise ExperimentConfigurationError(
            "unexpected frozen experiment configuration schema: "
            f"{payload.get('schema')!r}"
        )
    if payload.get("schema_version") != FROZEN_EXPERIMENT_CONFIGURATION_SCHEMA_VERSION:
        raise ExperimentConfigurationError(
            "unexpected frozen experiment configuration schema_version: "
            f"{payload.get('schema_version')!r}"
        )
    if payload.get("patch_version") != FROZEN_EXPERIMENT_CONFIGURATION_PATCH_VERSION:
        raise ExperimentConfigurationError(
            "unexpected frozen experiment configuration patch_version: "
            f"{payload.get('patch_version')!r}"
        )

    for field in (
        "authoritative_starting_checkpoint",
        "accepted_configuration",
        "frozen_parameter_fields",
        "runtime_process_fields",
        "validation_reservations",
        "integrity",
    ):
        if field not in payload:
            raise ExperimentConfigurationError(
                f"frozen experiment configuration is missing required field {field!r}"
            )

    if payload["authoritative_starting_checkpoint"] != "lpbf_patch_12_2_3_completed":
        raise ExperimentConfigurationError(
            "authoritative_starting_checkpoint must remain lpbf_patch_12_2_3_completed"
        )
    accepted_configuration_hash = _canonical_sha256(payload["accepted_configuration"])
    if accepted_configuration_hash != CURRENT_ACCEPTED_CONFIGURATION_SHA256:
        raise ExperimentConfigurationError(
            "accepted_configuration differs from the current hash-protected model state"
        )
    if payload["validation_reservations"] != {
        "layer52_reserved_for_independent_validation": True,
        "layer52_available_for_fitting": False,
        "layer52_available_for_model_selection": False,
    }:
        raise ExperimentConfigurationError(
            "layer52 validation reservation must remain frozen and unavailable for fitting/model selection"
        )

    frozen_fields = payload["frozen_parameter_fields"]
    if not isinstance(frozen_fields, Mapping):
        raise ExperimentConfigurationError("frozen_parameter_fields must be a JSON object")
    missing_blocks = sorted(set(_FROZEN_PARAMETER_BLOCKS) - set(frozen_fields))
    unexpected_blocks = sorted(set(frozen_fields) - set(_FROZEN_PARAMETER_BLOCKS))
    if missing_blocks or unexpected_blocks:
        raise ExperimentConfigurationError(
            "frozen parameter block mismatch; "
            f"missing={missing_blocks}, unexpected={unexpected_blocks}"
        )
    for block_name in _FROZEN_PARAMETER_BLOCKS:
        if not isinstance(frozen_fields[block_name], Mapping):
            raise ExperimentConfigurationError(
                f"frozen_parameter_fields.{block_name} must be a JSON object"
            )

    accepted = payload["accepted_configuration"]
    source = accepted["source"]
    transport = accepted["transport"]
    beam = accepted["beam"]
    ted = accepted["ted"]
    numerical = accepted["numerical"]

    if frozen_fields["heat_source"].get("calibration_factor") != source["calibration_factor"]:
        raise ExperimentConfigurationError("frozen calibration_factor does not match accepted state")
    if frozen_fields["heat_source"].get("depth_mm") != source["depth_mm"]:
        raise ExperimentConfigurationError("frozen depth_mm does not match accepted state")
    if (
        frozen_fields["material"].get("liquid_conductivity_enhancement_factor")
        != transport["liquid_conductivity_enhancement_factor"]
    ):
        raise ExperimentConfigurationError(
            "frozen liquid_conductivity_enhancement_factor does not match accepted state"
        )
    if frozen_fields["input"].get("default_spot_size_um") != beam["machine_spot_diameter_um"]:
        raise ExperimentConfigurationError("frozen machine spot diameter does not match accepted state")
    if frozen_fields["heat_source"].get("gaussian_radius_mm") != beam["gaussian_radius_mm"]:
        raise ExperimentConfigurationError("frozen Gaussian radius does not match accepted state")
    if payload.get("ted_treatment_identifier") != ted["treatment_identifier"]:
        raise ExperimentConfigurationError("TED treatment identifier does not match accepted state")
    if frozen_fields["time"].get("dt_s") != numerical["production_timestep_s"]:
        raise ExperimentConfigurationError("frozen timestep does not match accepted state")
    if frozen_fields["comparison"].get("hw_geometry_method") != numerical["hw_extraction_method"]:
        raise ExperimentConfigurationError("frozen H/W method does not match accepted state")

    geometry = frozen_fields["geometry"]
    grid = frozen_fields["grid"]
    spacings_um = (
        1000.0 * float(geometry["Lx_mm"]) / int(grid["Nx"]),
        1000.0 * float(geometry["Ly_mm"]) / int(grid["Ny"]),
        1000.0 * float(geometry["Lz_mm"]) / int(grid["Nz"]),
    )
    if any(abs(spacing - float(numerical["grid_spacing_um"])) > 1.0e-12 for spacing in spacings_um):
        raise ExperimentConfigurationError(
            "frozen grid/geometry no longer reproduce the accepted production grid spacing"
        )


def frozen_experiment_configuration_from_payload(
    payload: Mapping[str, Any],
    *,
    verify_integrity: bool = True,
) -> FrozenExperimentConfiguration:
    """Validate a decoded payload and return its immutable canonical representation."""
    if not isinstance(payload, Mapping):
        raise ExperimentConfigurationError("frozen experiment configuration root must be a JSON object")
    detached = json.loads(json.dumps(payload))
    _validate_payload(detached)

    integrity = detached.get("integrity")
    if not isinstance(integrity, Mapping):
        raise ExperimentConfigurationError("integrity must be a JSON object")
    expected = _validate_sha256(
        integrity.get("canonical_configuration_sha256"),
        field="integrity.canonical_configuration_sha256",
    )
    unhashed = dict(detached)
    unhashed.pop("integrity", None)
    actual = _canonical_sha256(unhashed)
    if verify_integrity and actual != expected:
        raise ExperimentConfigurationError(
            "frozen experiment configuration failed its canonical SHA-256 integrity check"
        )

    canonical_json = _canonical_json_bytes(detached).decode("utf-8")
    return FrozenExperimentConfiguration(canonical_json=canonical_json, sha256=expected)


def load_frozen_experiment_configuration(
    path: str | Path | None = None,
    *,
    verify_integrity: bool = True,
) -> FrozenExperimentConfiguration:
    """Load and validate the authoritative Patch 13.0.3 frozen configuration."""
    config_path = FROZEN_EXPERIMENT_CONFIGURATION_PATH if path is None else Path(path)
    if not config_path.is_file():
        raise FileNotFoundError(f"frozen experiment configuration not found: {config_path}")
    try:
        payload = _shared_read_json(config_path)
    except json.JSONDecodeError as exc:
        raise ExperimentConfigurationError(
            f"invalid JSON in frozen experiment configuration {config_path}: {exc.msg}"
        ) from exc
    return frozen_experiment_configuration_from_payload(
        payload,
        verify_integrity=verify_integrity,
    )


def apply_frozen_experiment_configuration(
    params: "SimulationParameters",
    configuration: FrozenExperimentConfiguration | None = None,
) -> "SimulationParameters":
    """Return ``params`` with every Patch 13.0.3 frozen field re-applied.

    Runtime/process fields intentionally not represented in ``frozen_parameter_fields``
    (for example coupon incident power, HDF5 path, output directory, layer name,
    and output filename) are preserved from ``params``.
    """
    config = load_frozen_experiment_configuration() if configuration is None else configuration
    payload = config.to_dict()
    _validate_payload(payload)
    fields = payload["frozen_parameter_fields"]

    replacements: dict[str, Any] = {}
    for block_name in _FROZEN_PARAMETER_BLOCKS:
        current_block = getattr(params, block_name)
        replacements[block_name] = replace(current_block, **dict(fields[block_name]))

    frozen_params = replace(params, **replacements)
    frozen_params.validate()
    assert_frozen_experiment_parameters_match(frozen_params, config)
    return frozen_params


def assert_frozen_experiment_parameters_match(
    params: SimulationParameters,
    configuration: FrozenExperimentConfiguration | None = None,
) -> None:
    """Fail closed if any frozen field differs from Patch 13.0.3."""
    config = load_frozen_experiment_configuration() if configuration is None else configuration
    payload = config.to_dict()
    fields = payload["frozen_parameter_fields"]

    changed: list[str] = []
    for block_name in _FROZEN_PARAMETER_BLOCKS:
        current_block = getattr(params, block_name)
        for field_name, expected in fields[block_name].items():
            actual = getattr(current_block, field_name)
            if actual != expected:
                changed.append(f"{block_name}.{field_name}")

    if changed:
        raise RuntimeError(
            "Frozen Patch 13.0.3 experiment configuration changed; coupon experiments "
            "must not alter accepted physics/numerical fidelity. Changed fields: "
            + ", ".join(sorted(changed))
        )
