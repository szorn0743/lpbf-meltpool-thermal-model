"""Patch 19.8.5 high-temperature diagnostic disposition contract.

This module freezes how temperature information is carried forward after the
Patch 19.8.4 fixed-regulator geometry-preservation result. It intentionally
contains no solver execution, temperature clipping, optimization logic, or
calibration-admissibility gate.

H and W remain the primary calibration observables. High-temperature metrics
are mandatory secondary physicality/known-limitation diagnostics that must be
visible in characterization, calibration, and validation outputs.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping


PATCH_VERSION = "19.8.5"
CONTRACT_SCHEMA = "lpbf_patch19_8_5_high_temperature_diagnostic_disposition"
CANONICAL_RECORD_SCHEMA = "lpbf_high_temperature_diagnostics"
CANONICAL_RECORD_SCHEMA_VERSION = PATCH_VERSION

NOMINAL_HIGH_TEMPERATURE_REFERENCE_K = 3133.15
DESCRIPTIVE_SCREENING_REFERENCE_K = 3233.15
TEMPERATURE_CLIPPING_PERMITTED = False
SCREENING_REFERENCE_BLOCKS_CALIBRATION = False

PRIMARY_CALIBRATION_OBSERVABLES = ("H", "W")
TEMPERATURE_DIAGNOSTIC_ROLE = "SECONDARY_PHYSICALITY_AND_KNOWN_LIMITATION_DIAGNOSTIC"
REQUIRED_OUTPUT_CONTEXTS = ("characterization", "calibration", "validation")


class TemperatureDiagnosticContractError(ValueError):
    """Raised when mandatory Patch 19.8.5 diagnostic data are incomplete."""


@dataclass(frozen=True)
class TemperatureDiagnosticDefinition:
    """One mandatory canonical temperature diagnostic."""

    name: str
    units: str
    source: str
    description: str

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "units": self.units,
            "source": self.source,
            "role": TEMPERATURE_DIAGNOSTIC_ROLE,
            "description": self.description,
        }


MANDATORY_HIGH_TEMPERATURE_DIAGNOSTICS: tuple[TemperatureDiagnosticDefinition, ...] = (
    TemperatureDiagnosticDefinition(
        name="raw_global_Tmax_K",
        units="K",
        source="every-substep represented-volume trace",
        description="Maximum raw temperature anywhere in the represented volume.",
    ),
    TemperatureDiagnosticDefinition(
        name="raw_global_surface_Tmax_K",
        units="K",
        source="every-substep top-surface trace",
        description="Maximum raw temperature on the accepted top free-surface plane.",
    ),
    TemperatureDiagnosticDefinition(
        name="peak_z_index",
        units="grid index",
        source="global-Tmax snapshot",
        description="Accepted z-index of the cell containing the global raw Tmax.",
    ),
    TemperatureDiagnosticDefinition(
        name="peak_layers_below_top",
        units="computational layers",
        source="global-Tmax snapshot",
        description="Number of computational layers between global Tmax and the top surface.",
    ),
    TemperatureDiagnosticDefinition(
        name="whole_volume_T99_9_K",
        units="K",
        source="global-Tmax snapshot",
        description="99.9th percentile of the represented-volume temperature field at global Tmax.",
    ),
    TemperatureDiagnosticDefinition(
        name="maximum_volume_above_3133_15_K_mm3",
        units="mm^3",
        source="every-substep represented-volume trace",
        description="Maximum represented volume at or above 3133.15 K.",
    ),
    TemperatureDiagnosticDefinition(
        name="total_any_cell_above_3133_15_K_duration_s",
        units="s",
        source="every-substep represented-volume trace",
        description="Total Eulerian represented-domain time with any cell at or above 3133.15 K.",
    ),
    TemperatureDiagnosticDefinition(
        name="longest_consecutive_any_cell_above_3133_15_K_duration_s",
        units="s",
        source="every-substep represented-volume trace",
        description="Longest continuous Eulerian represented-domain episode at or above 3133.15 K.",
    ),
    TemperatureDiagnosticDefinition(
        name="volume_time_above_3133_15_K_mm3_s",
        units="mm^3 s",
        source="every-substep represented-volume trace",
        description="Integrated represented volume-time at or above 3133.15 K.",
    ),
    TemperatureDiagnosticDefinition(
        name="cumulative_boiling_energy_fraction_of_absorbed",
        units="dimensionless",
        source="energy accounting",
        description="Cumulative boiling-loss energy divided by cumulative absorbed laser energy.",
    ),
)

MANDATORY_HIGH_TEMPERATURE_DIAGNOSTIC_KEYS = tuple(
    item.name for item in MANDATORY_HIGH_TEMPERATURE_DIAGNOSTICS
)


_NONNEGATIVE_KEYS = {
    "peak_z_index",
    "peak_layers_below_top",
    "maximum_volume_above_3133_15_K_mm3",
    "total_any_cell_above_3133_15_K_duration_s",
    "longest_consecutive_any_cell_above_3133_15_K_duration_s",
    "volume_time_above_3133_15_K_mm3_s",
    "cumulative_boiling_energy_fraction_of_absorbed",
}


def _finite_number(value: Any, *, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise TemperatureDiagnosticContractError(f"{name} must be numeric") from exc
    if not math.isfinite(result):
        raise TemperatureDiagnosticContractError(f"{name} must be finite")
    return result


def validate_high_temperature_diagnostics(record: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize one canonical Patch 19.8.5 diagnostic record.

    No upper-temperature admissibility gate is applied. Very high but finite
    values remain visible diagnostics rather than being clipped or rejected.
    """

    if not isinstance(record, Mapping):
        raise TypeError("record must be a mapping")
    missing = [name for name in MANDATORY_HIGH_TEMPERATURE_DIAGNOSTIC_KEYS if name not in record]
    if missing:
        raise TemperatureDiagnosticContractError(
            "missing mandatory high-temperature diagnostics: " + ", ".join(missing)
        )

    normalized: dict[str, Any] = {
        "schema": CANONICAL_RECORD_SCHEMA,
        "schema_version": CANONICAL_RECORD_SCHEMA_VERSION,
        "diagnostic_role": TEMPERATURE_DIAGNOSTIC_ROLE,
        "nominal_high_temperature_reference_K": NOMINAL_HIGH_TEMPERATURE_REFERENCE_K,
        "descriptive_screening_reference_K": DESCRIPTIVE_SCREENING_REFERENCE_K,
        "screening_reference_blocks_calibration": False,
        "temperature_clipping_permitted": False,
    }
    for name in MANDATORY_HIGH_TEMPERATURE_DIAGNOSTIC_KEYS:
        value = _finite_number(record[name], name=name)
        if name in _NONNEGATIVE_KEYS and value < 0.0:
            raise TemperatureDiagnosticContractError(f"{name} must be nonnegative")
        if name in {"peak_z_index", "peak_layers_below_top"}:
            if not value.is_integer():
                raise TemperatureDiagnosticContractError(f"{name} must be an integer-valued index/count")
            normalized[name] = int(value)
        else:
            normalized[name] = value

    if normalized["longest_consecutive_any_cell_above_3133_15_K_duration_s"] > normalized[
        "total_any_cell_above_3133_15_K_duration_s"
    ] + 1.0e-15:
        raise TemperatureDiagnosticContractError(
            "longest consecutive above-threshold duration cannot exceed total duration"
        )
    return normalized


def canonicalize_high_temperature_diagnostics(
    trace: Mapping[str, Any],
    energy_diagnostics: Mapping[str, Any],
) -> dict[str, Any]:
    """Map accepted Patch 19.8 trace/accounting names to the frozen output schema."""

    if not isinstance(trace, Mapping) or not isinstance(energy_diagnostics, Mapping):
        raise TypeError("trace and energy_diagnostics must be mappings")
    peak = trace.get("peak_snapshot")
    if not isinstance(peak, Mapping):
        raise TemperatureDiagnosticContractError("temperature trace is missing peak_snapshot")

    if "boiling_energy_fraction_of_absorbed" in energy_diagnostics:
        boiling_fraction = _finite_number(
            energy_diagnostics["boiling_energy_fraction_of_absorbed"],
            name="boiling_energy_fraction_of_absorbed",
        )
    else:
        boiling_energy = _finite_number(
            energy_diagnostics.get("cumulative_boiling_loss_energy_J"),
            name="cumulative_boiling_loss_energy_J",
        )
        absorbed_energy = _finite_number(
            energy_diagnostics.get("cumulative_absorbed_laser_energy_J"),
            name="cumulative_absorbed_laser_energy_J",
        )
        if absorbed_energy <= 0.0:
            raise TemperatureDiagnosticContractError(
                "cumulative_absorbed_laser_energy_J must be positive"
            )
        boiling_fraction = boiling_energy / absorbed_energy

    source = {
        "raw_global_Tmax_K": trace.get("raw_global_Tmax_K"),
        "raw_global_surface_Tmax_K": trace.get("raw_global_surface_Tmax_K"),
        "peak_z_index": peak.get("peak_z_index"),
        "peak_layers_below_top": peak.get("peak_layers_below_top"),
        "whole_volume_T99_9_K": peak.get("T_p99_9_K"),
        "maximum_volume_above_3133_15_K_mm3": trace.get("maximum_volume_above_nominal_limit_mm3"),
        "total_any_cell_above_3133_15_K_duration_s": trace.get("any_cell_above_nominal_duration_s"),
        "longest_consecutive_any_cell_above_3133_15_K_duration_s": trace.get(
            "maximum_consecutive_any_cell_above_nominal_duration_s"
        ),
        "volume_time_above_3133_15_K_mm3_s": trace.get("volume_time_above_nominal_mm3_s"),
        "cumulative_boiling_energy_fraction_of_absorbed": boiling_fraction,
    }
    return validate_high_temperature_diagnostics(source)


def attach_high_temperature_diagnostics(
    output_payload: Mapping[str, Any],
    diagnostics: Mapping[str, Any],
    *,
    output_context: str,
) -> dict[str, Any]:
    """Attach mandatory diagnostics to a calibration/validation-style payload."""

    if output_context not in REQUIRED_OUTPUT_CONTEXTS:
        raise TemperatureDiagnosticContractError(
            "output_context must be one of: " + ", ".join(REQUIRED_OUTPUT_CONTEXTS)
        )
    normalized = validate_high_temperature_diagnostics(diagnostics)
    result = dict(output_payload)
    if "high_temperature_diagnostics" in result:
        raise TemperatureDiagnosticContractError(
            "output already contains high_temperature_diagnostics; refusing silent replacement"
        )
    result["high_temperature_diagnostics"] = normalized
    result["high_temperature_diagnostic_disposition"] = {
        "patch": PATCH_VERSION,
        "output_context": output_context,
        "mandatory": True,
        "primary_calibration_observables": list(PRIMARY_CALIBRATION_OBSERVABLES),
        "temperature_metrics_are_primary_objective_terms": False,
        "screening_reference_blocks_calibration": False,
        "temperature_clipping_permitted": False,
    }
    return result


__all__ = [
    "CANONICAL_RECORD_SCHEMA",
    "CANONICAL_RECORD_SCHEMA_VERSION",
    "CONTRACT_SCHEMA",
    "DESCRIPTIVE_SCREENING_REFERENCE_K",
    "MANDATORY_HIGH_TEMPERATURE_DIAGNOSTICS",
    "MANDATORY_HIGH_TEMPERATURE_DIAGNOSTIC_KEYS",
    "NOMINAL_HIGH_TEMPERATURE_REFERENCE_K",
    "PATCH_VERSION",
    "PRIMARY_CALIBRATION_OBSERVABLES",
    "REQUIRED_OUTPUT_CONTEXTS",
    "SCREENING_REFERENCE_BLOCKS_CALIBRATION",
    "TEMPERATURE_CLIPPING_PERMITTED",
    "TEMPERATURE_DIAGNOSTIC_ROLE",
    "TemperatureDiagnosticContractError",
    "TemperatureDiagnosticDefinition",
    "attach_high_temperature_diagnostics",
    "canonicalize_high_temperature_diagnostics",
    "validate_high_temperature_diagnostics",
]
