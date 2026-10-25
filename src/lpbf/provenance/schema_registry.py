"""Current schema/version registry for supported result and provenance records.

Patch 20.12 versions the calibration-facing policy, coefficient-vector, process
condition, realized-state identity, and policy-realization schemas while
preserving explicit read compatibility with accepted Patch 20.3/20.4 records.
Historical experiment schemas remain frozen at their accepted versions.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping


SCHEMA_REGISTRY_SCHEMA = "lpbf_current_schema_registry"
SCHEMA_REGISTRY_SCHEMA_VERSION = "20.12.0"


@dataclass(frozen=True)
class SchemaDefinition:
    key: str
    schema: str
    write_version: str
    record_kind: str
    readable_versions: tuple[str, ...]
    description: str

    def envelope(self) -> dict[str, str]:
        return {"schema": self.schema, "schema_version": self.write_version}

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "schema": self.schema,
            "write_version": self.write_version,
            "record_kind": self.record_kind,
            "readable_versions": list(self.readable_versions),
            "description": self.description,
        }


_DEFINITIONS = (
    SchemaDefinition(
        key="process_condition",
        schema="lpbf_process_condition",
        write_version="20.12.0",
        record_kind="provenance",
        readable_versions=("20.2", "20.4", "20.12.0"),
        description="Process-condition identity and registry-bound predictor source values.",
    ),
    SchemaDefinition(
        key="parameter_policy",
        schema="lpbf_parameter_policy",
        write_version="20.12.0",
        record_kind="provenance",
        readable_versions=("20.2", "20.4", "20.12.0"),
        description="Complete deterministic registry-bound parameter-policy definition.",
    ),
    SchemaDefinition(
        key="optimizer_coefficient_vector",
        schema="lpbf_optimizer_coefficient_vector",
        write_version="20.12.0",
        record_kind="identity",
        readable_versions=("20.12.0",),
        description=(
            "Optimizer-controlled policy coefficient vector, distinct from the realized "
            "four-field physical state and fixed model structure."
        ),
    ),
    SchemaDefinition(
        key="policy_realization",
        schema="lpbf_policy_realization",
        write_version="20.12.0",
        record_kind="provenance",
        readable_versions=("20.3", "20.4", "20.12.0"),
        description="Policy/process/input realization bound to one trial.",
    ),
    SchemaDefinition(
        key="realized_parameter_vector",
        schema="lpbf_realized_parameter_vector",
        write_version="20.12.0",
        record_kind="identity",
        readable_versions=("20.3", "20.4", "20.12.0"),
        description="Ordered explicit four-parameter realized physical-state identity.",
    ),
    SchemaDefinition(
        key="experiment_trial_identity",
        schema="lpbf_experiment_trial_identity",
        write_version="20.12.0",
        record_kind="identity",
        readable_versions=("20.3", "20.4", "20.12.0"),
        description="Deterministic trial cache/restart identity payload.",
    ),
    SchemaDefinition(
        key="experiment_checkpoint_contract",
        schema="lpbf_experiment_checkpoint_contract",
        write_version="20.12.0",
        record_kind="identity",
        readable_versions=("20.3", "20.4", "20.12.0"),
        description="Ordered checkpoint/restart identity contract.",
    ),
    SchemaDefinition(
        key="numerical_stability_preflight",
        schema="lpbf_current_numerical_stability_preflight",
        write_version="20.4",
        record_kind="result",
        readable_versions=("20.3", "20.4"),
        description="Combined frozen directional/boiling stability preflight.",
    ),
    SchemaDefinition(
        key="patch19_9_policy_realizations",
        schema="lpbf_patch19_9_policy_realizations",
        write_version="20.4",
        record_kind="result",
        readable_versions=("20.3", "20.4"),
        description="Patch 19.9 policy-realization ledger written by the current framework.",
    ),
    SchemaDefinition(
        key="calibration_trial_evaluation",
        schema="lpbf_calibration_trial_evaluation",
        write_version="20.10.0",
        record_kind="result",
        readable_versions=("20.10.0",),
        description="Atomic calibration-facing trial evaluation record introduced by Patch 20.10.",
    ),
)

SCHEMA_DEFINITIONS: Mapping[str, SchemaDefinition] = MappingProxyType(
    {definition.key: definition for definition in _DEFINITIONS}
)
if len(SCHEMA_DEFINITIONS) != len(_DEFINITIONS):
    raise RuntimeError("duplicate keys in current schema registry")


class SchemaRegistryError(ValueError):
    pass


def schema_definition(key: str) -> SchemaDefinition:
    try:
        return SCHEMA_DEFINITIONS[str(key)]
    except KeyError as exc:
        raise KeyError(f"unknown current schema key: {key!r}") from exc


def schema_envelope(key: str) -> dict[str, str]:
    return schema_definition(key).envelope()


def validate_readable_schema(record: Mapping[str, Any], key: str) -> None:
    """Fail closed unless a record uses a scientifically supported read version."""

    definition = schema_definition(key)
    if record.get("schema") != definition.schema:
        raise SchemaRegistryError(
            f"unexpected schema for {key}: {record.get('schema')!r}"
        )
    version = str(record.get("schema_version", ""))
    if version not in definition.readable_versions:
        raise SchemaRegistryError(
            f"unsupported {definition.schema} read version: {version!r}"
        )


def current_schema_registry_dict() -> dict[str, Any]:
    return {
        "schema": SCHEMA_REGISTRY_SCHEMA,
        "schema_version": SCHEMA_REGISTRY_SCHEMA_VERSION,
        "write_policy": "current writers emit only each schema's write_version",
        "migration_policy": (
            "legacy versions are read-only and retained only where required for accepted "
            "Patch 19.x scientific reproduction or Patch 20.3/20.4 provenance migration"
        ),
        "schemas": [definition.to_dict() for definition in _DEFINITIONS],
    }


__all__ = [
    "SCHEMA_DEFINITIONS",
    "SCHEMA_REGISTRY_SCHEMA",
    "SCHEMA_REGISTRY_SCHEMA_VERSION",
    "SchemaDefinition",
    "SchemaRegistryError",
    "current_schema_registry_dict",
    "schema_definition",
    "schema_envelope",
    "validate_readable_schema",
]
