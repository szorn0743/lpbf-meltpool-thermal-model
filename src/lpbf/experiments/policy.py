"""Policy realization and trial-identity boundaries for current execution.

Policy realization is kept separate from dataset resolution and numerical
execution. This module selects no fitted values, bounds, optimizer, or
scientific policy; it validates and realizes the explicit policy supplied by a
caller.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from lpbf.infrastructure import canonical_sha256
from lpbf.model.current_configuration import (
    CURRENT_CALIBRATABLE_PARAMETER_NAMES,
    CURRENT_FIXED_CONFIGURATION,
    CurrentPhysicsParameters,
)
from lpbf.model.parameter_policy import (
    ParameterPolicy,
    ProcessCondition,
    optimizer_coefficient_vector,
    realize_parameter_policy,
    validate_policy_definition,
)
from lpbf.provenance.schema_registry import (
    schema_envelope,
    validate_readable_schema,
)

from .errors import CurrentExperimentFrameworkError


def realized_parameter_vector(physics: CurrentPhysicsParameters) -> dict[str, float]:
    """Return only the four calibratable physical values in authoritative order."""

    if not isinstance(physics, CurrentPhysicsParameters):
        raise TypeError("physics must be CurrentPhysicsParameters")
    if physics.deposition_depth_mm is None:
        raise CurrentExperimentFrameworkError(
            "calibration-facing experiment execution requires finite deposition_depth_mm"
        )
    return {
        name: float(getattr(physics, name)) for name in CURRENT_CALIBRATABLE_PARAMETER_NAMES
    }


def normalized_policy_definition(policy: ParameterPolicy) -> dict[str, Any]:
    """Return the fail-closed Patch 20.12 registry-bound policy definition."""

    if not isinstance(policy, ParameterPolicy):
        raise TypeError("policy does not satisfy the ParameterPolicy protocol")
    try:
        validated = validate_policy_definition(policy.definition_dict())
        # Also force coefficient_dict to agree with the structured optimizer
        # vector before any trial identity or solver work is constructed.
        optimizer_coefficient_vector(policy)
    except Exception as exc:
        raise CurrentExperimentFrameworkError(str(exc)) from exc
    definition = dict(validated)
    declared = definition.pop("policy_identity", None)
    computed = canonical_sha256(definition)
    if declared is not None and str(declared) != computed:
        raise CurrentExperimentFrameworkError("parameter policy identity is inconsistent")
    return {**definition, "policy_identity": computed}


@dataclass(frozen=True)
class PolicyRealization:
    """One explicit policy realization bound to an input/process condition."""

    process_condition: ProcessCondition
    policy_definition: Mapping[str, Any]
    realized_parameters: CurrentPhysicsParameters
    realized_parameter_identity: str
    trial_identity: str
    input_sha256: str
    execution_scope: str
    trial_context: Mapping[str, Any]

    @property
    def policy_identity(self) -> str:
        return str(self.policy_definition["policy_identity"])

    def provenance_dict(self) -> dict[str, Any]:
        return {
            **schema_envelope("policy_realization"),
            "execution_scope": self.execution_scope,
            "input_sha256": self.input_sha256,
            "process_condition": self.process_condition.to_dict(),
            "policy_definition": dict(self.policy_definition),
            "optimizer_coefficient_vector": dict(
                self.policy_definition["optimizer_coefficient_vector"]
            ),
            # Compatibility flat vector retained for accepted readers.
            "realized_parameter_vector": realized_parameter_vector(self.realized_parameters),
            "realized_physical_state": {
                **schema_envelope("realized_parameter_vector"),
                "parameter_order": list(CURRENT_CALIBRATABLE_PARAMETER_NAMES),
                "values": realized_parameter_vector(self.realized_parameters),
                "stable_identity": self.realized_parameter_identity,
            },
            "realized_parameter_identity": self.realized_parameter_identity,
            "trial_context": dict(self.trial_context),
            "trial_identity": self.trial_identity,
            "fixed_model_quantities": {
                "quadratic_boiling_strength": {
                    "value": float(
                        CURRENT_FIXED_CONFIGURATION["quadratic_boiling_strength"]
                    ),
                    "units": "dimensionless",
                    "role": "fixed_regulator",
                    "policy_coefficient": False,
                }
            },
            # Read compatibility for accepted Patch 20.3 provenance consumers.
            "quadratic_boiling_strength": float(
                CURRENT_FIXED_CONFIGURATION["quadratic_boiling_strength"]
            ),
        }



def normalize_policy_realization_record_for_read(record: Mapping[str, Any]) -> dict[str, Any]:
    """Read current or accepted legacy policy-realization provenance safely.

    Patch 20.3/20.4 records remain readable evidence. They are never silently
    promoted to the Patch 20.12 executable policy contract because they lack
    the hardened optimizer-coefficient and mapping metadata.
    """

    payload = dict(record)
    if payload.get("schema") == "lpbf_policy_realization":
        validate_readable_schema(payload, "policy_realization")
        if payload.get("schema_version") == schema_envelope("policy_realization")["schema_version"]:
            return payload
        return {
            **payload,
            "read_only_legacy_policy_realization": True,
            "execution_under_patch20_12_permitted": False,
        }
    if payload.get("framework_schema_version") == "20.3":
        strength = float(payload.get("quadratic_boiling_strength", 0.5))
        migrated = {
            "schema": "lpbf_policy_realization",
            "schema_version": "20.4",
            **{
                key: value
                for key, value in payload.items()
                if key not in {"framework_schema_version", "quadratic_boiling_strength_role"}
            },
            "fixed_model_quantities": {
                "quadratic_boiling_strength": {
                    "value": strength,
                    "units": "dimensionless",
                    "role": "fixed_regulator",
                    "policy_coefficient": False,
                }
            },
            "read_only_legacy_policy_realization": True,
            "execution_under_patch20_12_permitted": False,
        }
        validate_readable_schema(migrated, "policy_realization")
        return migrated
    raise CurrentExperimentFrameworkError(
        "unsupported policy-realization provenance schema/version"
    )

def realize_policy_for_trial(
    *,
    policy: ParameterPolicy,
    process_condition: ProcessCondition,
    input_sha256: str,
    execution_scope: str,
    trial_context: Mapping[str, Any] | None = None,
) -> PolicyRealization:
    """Realize a policy and derive deterministic cache/checkpoint identity.

    Identity binds the exact input bytes, process condition, complete policy
    definition, realized four-parameter vector, experiment execution scope, and
    caller-supplied trial context.  A future process-conditioned policy therefore
    cannot alias a constant policy merely because one realized vector happens to
    be numerically equal.
    """

    if not str(input_sha256).strip():
        raise CurrentExperimentFrameworkError("input_sha256 must be non-empty")
    scope = str(execution_scope).strip()
    if not scope:
        raise CurrentExperimentFrameworkError("execution_scope must be non-empty")
    context = dict(trial_context or {})
    definition = normalized_policy_definition(policy)
    physics = realize_parameter_policy(policy, process_condition)
    vector = realized_parameter_vector(physics)
    vector_identity = canonical_sha256(
        {
            **schema_envelope("realized_parameter_vector"),
            "parameter_order": list(CURRENT_CALIBRATABLE_PARAMETER_NAMES),
            "values": vector,
        }
    )
    identity_payload = {
        **schema_envelope("experiment_trial_identity"),
        "execution_scope": scope,
        "input_sha256": str(input_sha256),
        "process_condition_identity": process_condition.stable_identity,
        "policy_identity": definition["policy_identity"],
        "realized_parameter_identity": vector_identity,
        "trial_context": context,
    }
    return PolicyRealization(
        process_condition=process_condition,
        policy_definition=definition,
        realized_parameters=physics,
        realized_parameter_identity=vector_identity,
        trial_identity=canonical_sha256(identity_payload),
        input_sha256=str(input_sha256),
        execution_scope=scope,
        trial_context=context,
    )



__all__ = [
    "PolicyRealization",
    "normalized_policy_definition",
    "normalize_policy_realization_record_for_read",
    "realize_policy_for_trial",
    "realized_parameter_vector",
]
