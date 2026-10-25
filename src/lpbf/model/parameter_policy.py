"""Registry-bound parameter-policy contract outside the thermal solver.

Patch 20.12 separates three concepts that were previously easy to conflate:

1. the realized four-field physical state consumed by the solver;
2. the optimizer-controlled policy coefficient vector; and
3. fixed model structure and diagnostic/numerical quantities.

Every current policy definition is fail-closed against the authoritative
quantity registry.  Coefficients may be a subset or a transformed/shared
parameterization, but every coefficient must have explicit metadata and every
realized physical field must have an explicit coefficient-to-physical mapping.
Coupon/member identity is never an admissible predictor or lookup key.

This module selects no calibration bounds, priors, predictor scaling, optimizer,
or process-conditioned policy.  The executable current baseline remains the
accepted constant/global policy.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import math
from typing import Any, Mapping, Protocol, runtime_checkable

from lpbf.model.current_configuration import (
    CURRENT_FIXED_CONFIGURATION,
    CurrentPhysicsParameters,
)
from lpbf.model.quantity_registry import (
    CALIBRATABLE,
    CURRENT_CALIBRATABLE_PARAMETER_NAMES,
    CURRENT_FIXED_REGULATOR_PARAMETER_NAMES,
    CURRENT_PROCESS_PREDICTOR_NAMES,
    FIXED_REGULATOR,
    GLOBAL,
    PROCESS_CONDITIONED,
    PROCESS_PREDICTOR,
    quantity_definition,
)
from lpbf.provenance.schema_registry import (
    schema_definition,
    schema_envelope,
)


_PARAMETER_POLICY_DEF = schema_definition("parameter_policy")
_PROCESS_CONDITION_DEF = schema_definition("process_condition")
_OPTIMIZER_COEFFICIENT_DEF = schema_definition("optimizer_coefficient_vector")
PARAMETER_POLICY_SCHEMA = _PARAMETER_POLICY_DEF.schema
PARAMETER_POLICY_SCHEMA_VERSION = _PARAMETER_POLICY_DEF.write_version
PROCESS_CONDITION_SCHEMA = _PROCESS_CONDITION_DEF.schema
PROCESS_CONDITION_SCHEMA_VERSION = _PROCESS_CONDITION_DEF.write_version
OPTIMIZER_COEFFICIENT_VECTOR_SCHEMA = _OPTIMIZER_COEFFICIENT_DEF.schema
OPTIMIZER_COEFFICIENT_VECTOR_SCHEMA_VERSION = _OPTIMIZER_COEFFICIENT_DEF.write_version
CONSTANT_POLICY_TYPE = "constant_global"
CONSTANT_POLICY_VERSION = "2"
SHARED_POLICY_SCOPE = "shared_across_all_coupons"

DIRECT_COEFFICIENT = "direct_optimizer_coefficient"
DERIVED_COEFFICIENTS = "derived_from_optimizer_coefficients"
FIXED_POLICY_VALUE = "fixed_policy_value"
ALLOWED_PHYSICAL_MAPPING_SOURCES = frozenset(
    {DIRECT_COEFFICIENT, DERIVED_COEFFICIENTS, FIXED_POLICY_VALUE}
)
ALLOWED_COEFFICIENT_ROLES = frozenset(
    {"direct_physical_mapping", "transformation_parameter", "shared_constraint_parameter"}
)
_FORBIDDEN_LOOKUP_TOKENS = (
    "coupon_lookup",
    "member_lookup",
    "per_coupon",
    "per_member",
    "condition_id_lookup",
    "lookup_table",
)


class ParameterPolicyError(ValueError):
    """Raised when a parameter policy or realization violates its contract."""


def _finite(name: str, value: float) -> float:
    value = float(value)
    if not math.isfinite(value):
        raise ParameterPolicyError(f"{name} must be finite")
    return value


def _canonical_identity(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        dict(payload), sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    return sha256(encoded.encode("utf-8")).hexdigest()


def _mapping(name: str, value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ParameterPolicyError(f"{name} must be a mapping")
    return value


def _ordered_names(name: str, value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ParameterPolicyError(f"{name} must be a list")
    normalized = tuple(str(item).strip() for item in value)
    if any(not item for item in normalized):
        raise ParameterPolicyError(f"{name} may not contain empty names")
    if len(set(normalized)) != len(normalized):
        raise ParameterPolicyError(f"{name} must contain unique names")
    return normalized


def _assert_no_member_lookup_metadata(value: Any, *, path: str = "policy") -> None:
    """Reject schema-level member/coupon lookup constructs recursively."""

    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key).lower()
            if any(token in key_text for token in _FORBIDDEN_LOOKUP_TOKENS):
                # Explicit prohibition flags are required by the schema and are
                # safe only when they are literally False.
                if child is not False:
                    raise ParameterPolicyError(
                        f"coupon/member-specific lookup metadata is prohibited: {path}.{key}"
                    )
                continue
            _assert_no_member_lookup_metadata(child, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _assert_no_member_lookup_metadata(child, path=f"{path}[{index}]")
    elif isinstance(value, str):
        lowered = value.lower()
        if any(token in lowered for token in _FORBIDDEN_LOOKUP_TOKENS):
            raise ParameterPolicyError(
                f"coupon/member-specific lookup semantics are prohibited: {path}"
            )


@dataclass(frozen=True)
class ProcessCondition:
    """Process covariates available to shared calibration policies.

    ``condition_id`` is provenance identity only.  It is intentionally excluded
    from the predictor registry and runtime lookup-invariance checks guarantee
    that a policy cannot use it to select coupon/member-specific parameters.
    """

    condition_id: str
    power_W: float
    speed_mm_s: float
    power_units: str = "W"
    speed_units: str = "mm/s"

    def __post_init__(self) -> None:
        condition_id = str(self.condition_id).strip()
        if not condition_id:
            raise ParameterPolicyError("condition_id must be non-empty")
        object.__setattr__(self, "condition_id", condition_id)
        power = _finite("power_W", self.power_W)
        speed = _finite("speed_mm_s", self.speed_mm_s)
        if power <= 0.0:
            raise ParameterPolicyError("power_W must be > 0")
        if speed <= 0.0:
            raise ParameterPolicyError("speed_mm_s must be > 0")
        expected_power_units = quantity_definition("power_W").units
        expected_speed_units = quantity_definition("speed_mm_s").units
        if self.power_units != expected_power_units:
            raise ParameterPolicyError(
                f"power_units must be exactly {expected_power_units!r}"
            )
        if self.speed_units != expected_speed_units:
            raise ParameterPolicyError(
                f"speed_units must be exactly {expected_speed_units!r}"
            )
        object.__setattr__(self, "power_W", power)
        object.__setattr__(self, "speed_mm_s", speed)

    def to_dict(self) -> dict[str, Any]:
        return {
            **schema_envelope("process_condition"),
            "condition_id": self.condition_id,
            "condition_id_role": "provenance_only_not_policy_predictor",
            "power": {"value": self.power_W, "units": self.power_units},
            "speed": {"value": self.speed_mm_s, "units": self.speed_units},
            "predictor_source_values": {
                "power_W": {"value": self.power_W, "units": self.power_units},
                "speed_mm_s": {"value": self.speed_mm_s, "units": self.speed_units},
            },
            "stable_identity": self.stable_identity,
        }

    @property
    def stable_identity(self) -> str:
        payload = {
            "condition_id": self.condition_id,
            "power_W": self.power_W,
            "power_units": self.power_units,
            "speed_mm_s": self.speed_mm_s,
            "speed_units": self.speed_units,
        }
        return _canonical_identity(payload)


@dataclass(frozen=True)
class OptimizerCoefficientVector:
    """Explicit optimizer-controlled coefficient vector and registry bindings."""

    coefficient_order: tuple[str, ...]
    values: Mapping[str, float]
    metadata: Mapping[str, Mapping[str, Any]]

    def __post_init__(self) -> None:
        order = _ordered_names("coefficient_order", self.coefficient_order)
        values = dict(self.values)
        metadata = dict(self.metadata)
        if set(values) != set(order) or len(values) != len(order):
            raise ParameterPolicyError(
                "optimizer coefficient values must match coefficient_order exactly"
            )
        if set(metadata) != set(order) or len(metadata) != len(order):
            raise ParameterPolicyError(
                "optimizer coefficient metadata must match coefficient_order exactly"
            )
        normalized_values = {name: _finite(name, values[name]) for name in order}
        normalized_metadata = {name: metadata[name] for name in order}
        object.__setattr__(self, "coefficient_order", order)
        object.__setattr__(self, "values", normalized_values)
        object.__setattr__(self, "metadata", normalized_metadata)

    @property
    def stable_identity(self) -> str:
        payload = {
            **schema_envelope("optimizer_coefficient_vector"),
            "coefficient_order": list(self.coefficient_order),
            "values": dict(self.values),
            "metadata": {name: dict(self.metadata[name]) for name in self.coefficient_order},
        }
        return _canonical_identity(payload)

    def to_dict(self) -> dict[str, Any]:
        return {
            **schema_envelope("optimizer_coefficient_vector"),
            "coefficient_order": list(self.coefficient_order),
            "values": dict(self.values),
            "metadata": {name: dict(self.metadata[name]) for name in self.coefficient_order},
            "stable_identity": self.stable_identity,
        }


@runtime_checkable
class ParameterPolicy(Protocol):
    """Narrow calibration-facing protocol; no solver dependency is permitted."""

    policy_type: str
    policy_version: str

    def parameters_for(self, process_condition: ProcessCondition) -> CurrentPhysicsParameters:
        """Return one deterministic explicit four-parameter physical state."""

    def coefficient_dict(self) -> Mapping[str, float]:
        """Return optimizer-controlled coefficients, distinct from realized state."""

    def definition_dict(self) -> Mapping[str, Any]:
        """Return deterministic policy provenance without realized coupon results."""


def _validate_realized_state_contract(payload: Mapping[str, Any]) -> None:
    contract = _mapping("realized_physical_state_contract", payload.get("realized_physical_state_contract"))
    order = _ordered_names("realized_physical_state_contract.parameter_order", contract.get("parameter_order"))
    if order != CURRENT_CALIBRATABLE_PARAMETER_NAMES:
        raise ParameterPolicyError(
            "realized physical state must contain exactly the four registry calibratable parameters"
        )
    units = _mapping("realized_physical_state_contract.parameter_units", contract.get("parameter_units"))
    if set(units) != set(order) or len(units) != len(order):
        raise ParameterPolicyError("realized physical-state units must match authoritative parameters")
    for name in order:
        definition = quantity_definition(name)
        if definition.quantity_role != CALIBRATABLE:
            raise ParameterPolicyError(f"realized quantity {name!r} is not calibratable")
        if units[name] != definition.units:
            raise ParameterPolicyError(
                f"realized physical-state unit mismatch for {name}: {units[name]!r} != {definition.units!r}"
            )
    if any(name in contract for name in CURRENT_FIXED_REGULATOR_PARAMETER_NAMES):
        raise ParameterPolicyError("fixed regulator may not enter realized physical state")


def _validate_fixed_model_structure(payload: Mapping[str, Any]) -> None:
    fixed = _mapping("fixed_model_structure", payload.get("fixed_model_structure"))
    expected_names = CURRENT_FIXED_REGULATOR_PARAMETER_NAMES
    if set(fixed) != set(expected_names) or len(fixed) != len(expected_names):
        raise ParameterPolicyError(
            "fixed_model_structure must contain exactly the registry fixed-regulator quantities"
        )
    for name in expected_names:
        entry = _mapping(f"fixed_model_structure.{name}", fixed[name])
        definition = quantity_definition(name)
        if definition.quantity_role != FIXED_REGULATOR:
            raise ParameterPolicyError(f"fixed quantity {name!r} is not a fixed regulator")
        if entry.get("units") != definition.units:
            raise ParameterPolicyError(f"fixed-model unit mismatch for {name}")
        if entry.get("quantity_role") != FIXED_REGULATOR:
            raise ParameterPolicyError(f"fixed-model role mismatch for {name}")
        if entry.get("optimizer_controlled") is not False:
            raise ParameterPolicyError(f"fixed-model quantity {name} may not be optimizer-controlled")
        expected = _finite(name, CURRENT_FIXED_CONFIGURATION[name])
        actual = _finite(f"fixed_model_structure.{name}.value", entry.get("value"))
        if actual != expected:
            raise ParameterPolicyError(
                f"fixed-model value mismatch for {name}: {actual} != {expected}"
            )


def _validate_predictor_contract(payload: Mapping[str, Any]) -> tuple[str, ...]:
    contract = _mapping("predictor_contract", payload.get("predictor_contract"))
    names = _ordered_names("predictor_contract.names", contract.get("names"))
    units = _mapping("predictor_contract.units", contract.get("units"))
    if set(units) != set(names) or len(units) != len(names):
        raise ParameterPolicyError("predictor units must match predictor names")
    for name in names:
        try:
            definition = quantity_definition(name)
        except KeyError as exc:
            raise ParameterPolicyError(f"unknown process predictor: {name!r}") from exc
        if definition.quantity_role != PROCESS_PREDICTOR:
            raise ParameterPolicyError(f"quantity {name!r} is not an authorized process predictor")
        if units[name] != definition.units:
            raise ParameterPolicyError(
                f"predictor unit mismatch for {name}: {units[name]!r} != {definition.units!r}"
            )
    components: dict[str, Mapping[str, Any]] = {}
    for field in ("centering", "scaling", "interpolation_domain", "extrapolation_policy"):
        metadata = _mapping(f"predictor_contract.{field}", contract.get(field))
        if not str(metadata.get("type", "")).strip():
            raise ParameterPolicyError(f"predictor_contract.{field}.type must be explicit")
        component_names = _ordered_names(
            f"predictor_contract.{field}.predictor_names",
            metadata.get("predictor_names", []),
        )
        if component_names != names:
            raise ParameterPolicyError(
                f"predictor_contract.{field} must bind exactly the declared predictor_names"
            )
        components[field] = metadata

    for field in ("centering", "scaling", "extrapolation_policy"):
        _mapping(
            f"predictor_contract.{field}.parameters",
            components[field].get("parameters"),
        )

    domain_bounds = _mapping(
        "predictor_contract.interpolation_domain.bounds",
        components["interpolation_domain"].get("bounds"),
    )
    if set(domain_bounds) != set(names) or len(domain_bounds) != len(names):
        raise ParameterPolicyError(
            "interpolation-domain bounds must cover exactly the declared predictors"
        )
    for name in names:
        entry = _mapping(f"interpolation bound for {name}", domain_bounds[name])
        expected_units = quantity_definition(name).units
        if entry.get("units") != expected_units:
            raise ParameterPolicyError(f"interpolation-domain unit mismatch for {name}")
        minimum = _finite(f"interpolation-domain minimum for {name}", entry.get("minimum"))
        maximum = _finite(f"interpolation-domain maximum for {name}", entry.get("maximum"))
        if not minimum < maximum:
            raise ParameterPolicyError(
                f"interpolation-domain bounds for {name} require minimum < maximum"
            )

    if contract.get("identity_fields_permitted") is not False:
        raise ParameterPolicyError("member/coupon identity fields may not be policy predictors")
    return names


def _validate_coefficient_metadata(
    *,
    name: str,
    metadata: Mapping[str, Any],
    coefficient_units: str,
) -> tuple[str, ...]:
    if metadata.get("name") != name:
        raise ParameterPolicyError(f"coefficient/name mismatch for {name!r}")
    if metadata.get("units") != coefficient_units:
        raise ParameterPolicyError(f"coefficient unit metadata mismatch for {name!r}")
    if metadata.get("optimizer_controlled") is not True:
        raise ParameterPolicyError(f"optimizer coefficient {name!r} must be marked optimizer_controlled")
    role = str(metadata.get("coefficient_role", ""))
    if role not in ALLOWED_COEFFICIENT_ROLES:
        raise ParameterPolicyError(f"unsupported coefficient role for {name!r}: {role!r}")
    targets = _ordered_names(f"coefficient_metadata.{name}.target_parameters", metadata.get("target_parameters"))
    if not targets:
        raise ParameterPolicyError(f"coefficient {name!r} must bind to at least one physical target")
    for target in targets:
        try:
            definition = quantity_definition(target)
        except KeyError as exc:
            raise ParameterPolicyError(
                f"coefficient {name!r} targets unknown quantity {target!r}"
            ) from exc
        if definition.quantity_role != CALIBRATABLE:
            raise ParameterPolicyError(
                f"coefficient {name!r} may target only calibratable quantities, not {target!r}"
            )

    transformation = _mapping(
        f"coefficient_metadata.{name}.transformation", metadata.get("transformation")
    )
    transformation_type = str(transformation.get("type", "")).strip()
    if not transformation_type:
        raise ParameterPolicyError(f"coefficient {name!r} transformation type must be explicit")
    if any(token in transformation_type.lower() for token in _FORBIDDEN_LOOKUP_TOKENS):
        raise ParameterPolicyError(f"coefficient {name!r} uses prohibited lookup transformation")
    if transformation.get("input_units") != coefficient_units:
        raise ParameterPolicyError(f"coefficient {name!r} transformation input units mismatch")
    output_units = _mapping(
        f"coefficient_metadata.{name}.transformation.output_units",
        transformation.get("output_units"),
    )
    if set(output_units) != set(targets) or len(output_units) != len(targets):
        raise ParameterPolicyError(
            f"coefficient {name!r} transformation outputs must match target_parameters"
        )
    for target in targets:
        expected_units = quantity_definition(target).units
        if output_units[target] != expected_units:
            raise ParameterPolicyError(
                f"coefficient {name!r} transformation output unit mismatch for {target}"
            )
    if transformation.get("deterministic") is not True:
        raise ParameterPolicyError(f"coefficient {name!r} transformation must be deterministic")

    constraint = _mapping(f"coefficient_metadata.{name}.constraint", metadata.get("constraint"))
    if not str(constraint.get("type", "")).strip():
        raise ParameterPolicyError(f"coefficient {name!r} constraint type must be explicit")
    if constraint.get("target_parameters") != list(targets):
        raise ParameterPolicyError(
            f"coefficient {name!r} constraint targets must match registry-bound targets"
        )
    return targets


def _validate_optimizer_vector(payload: Mapping[str, Any]) -> OptimizerCoefficientVector:
    vector = _mapping("optimizer_coefficient_vector", payload.get("optimizer_coefficient_vector"))
    if vector.get("schema") != OPTIMIZER_COEFFICIENT_VECTOR_SCHEMA:
        raise ParameterPolicyError("unexpected optimizer-coefficient-vector schema")
    if vector.get("schema_version") != OPTIMIZER_COEFFICIENT_VECTOR_SCHEMA_VERSION:
        raise ParameterPolicyError("unexpected optimizer-coefficient-vector schema version")
    order = _ordered_names("optimizer_coefficient_vector.coefficient_order", vector.get("coefficient_order"))
    values = _mapping("optimizer_coefficient_vector.values", vector.get("values"))
    metadata = _mapping("optimizer_coefficient_vector.metadata", vector.get("metadata"))
    if set(values) != set(order) or len(values) != len(order):
        raise ParameterPolicyError("optimizer coefficient values must match coefficient_order exactly")
    if set(metadata) != set(order) or len(metadata) != len(order):
        raise ParameterPolicyError("optimizer coefficient metadata must match coefficient_order exactly")
    if any(name in CURRENT_FIXED_REGULATOR_PARAMETER_NAMES for name in order):
        raise ParameterPolicyError("fixed boiling regulator may not enter optimizer coefficient vector")

    for name in order:
        coefficient_metadata = _mapping(f"optimizer_coefficient_vector.metadata.{name}", metadata[name])
        units = str(coefficient_metadata.get("units", "")).strip()
        if not units:
            raise ParameterPolicyError(f"coefficient {name!r} units must be explicit")
        _validate_coefficient_metadata(
            name=name,
            metadata=coefficient_metadata,
            coefficient_units=units,
        )

    result = OptimizerCoefficientVector(
        coefficient_order=order,
        values={name: values[name] for name in order},
        metadata={name: metadata[name] for name in order},
    )
    declared = vector.get("stable_identity")
    if declared is not None and str(declared) != result.stable_identity:
        raise ParameterPolicyError("optimizer coefficient vector identity is inconsistent")
    return result


def _validate_physical_mapping(
    payload: Mapping[str, Any],
    *,
    vector: OptimizerCoefficientVector,
    predictor_names: tuple[str, ...],
    parameter_roles: Mapping[str, Any],
) -> None:
    mapping = _mapping(
        "coefficient_to_physical_mapping", payload.get("coefficient_to_physical_mapping")
    )
    if mapping.get("mapping_scope") != "shared_across_all_coupons":
        raise ParameterPolicyError("coefficient-to-physical mapping must be shared across coupons")
    outputs = _mapping("coefficient_to_physical_mapping.outputs", mapping.get("outputs"))
    if set(outputs) != set(CURRENT_CALIBRATABLE_PARAMETER_NAMES) or len(outputs) != len(CURRENT_CALIBRATABLE_PARAMETER_NAMES):
        raise ParameterPolicyError(
            "coefficient-to-physical mapping must define all four physical outputs"
        )

    used_coefficients: list[str] = []
    used_predictors: list[str] = []
    coefficient_names = set(vector.coefficient_order)
    predictor_set = set(predictor_names)
    for parameter_name in CURRENT_CALIBRATABLE_PARAMETER_NAMES:
        output = _mapping(
            f"coefficient_to_physical_mapping.outputs.{parameter_name}", outputs[parameter_name]
        )
        if output.get("parameter_name") != parameter_name:
            raise ParameterPolicyError(f"physical mapping name mismatch for {parameter_name}")
        expected_units = quantity_definition(parameter_name).units
        if output.get("units") != expected_units:
            raise ParameterPolicyError(f"physical mapping unit mismatch for {parameter_name}")
        if output.get("parameter_role") != parameter_roles[parameter_name]:
            raise ParameterPolicyError(f"physical mapping role mismatch for {parameter_name}")
        source = str(output.get("source", ""))
        if source not in ALLOWED_PHYSICAL_MAPPING_SOURCES:
            raise ParameterPolicyError(
                f"unsupported physical mapping source for {parameter_name}: {source!r}"
            )
        coefficient_refs = _ordered_names(
            f"physical mapping coefficients for {parameter_name}", output.get("coefficient_names", [])
        )
        predictor_refs = _ordered_names(
            f"physical mapping predictors for {parameter_name}", output.get("predictor_names", [])
        )
        unknown_coefficients = sorted(set(coefficient_refs) - coefficient_names)
        if unknown_coefficients:
            raise ParameterPolicyError(
                f"physical mapping for {parameter_name} references unknown coefficient(s): {unknown_coefficients}"
            )
        unknown_predictors = sorted(set(predictor_refs) - predictor_set)
        if unknown_predictors:
            raise ParameterPolicyError(
                f"physical mapping for {parameter_name} references unknown predictor(s): {unknown_predictors}"
            )

        role = parameter_roles[parameter_name]
        if role == GLOBAL and predictor_refs:
            raise ParameterPolicyError(
                f"global parameter {parameter_name} may not depend on process predictors"
            )
        if role == PROCESS_CONDITIONED and not predictor_refs:
            raise ParameterPolicyError(
                f"process-conditioned parameter {parameter_name} must declare predictor use"
            )
        if source == FIXED_POLICY_VALUE:
            if coefficient_refs:
                raise ParameterPolicyError(
                    f"fixed policy value {parameter_name} may not reference optimizer coefficients"
                )
            if role != GLOBAL:
                raise ParameterPolicyError(
                    f"fixed policy value {parameter_name} must have global parameter role"
                )
            fixed_value = _mapping(
                f"physical mapping fixed value for {parameter_name}", output.get("fixed_value")
            )
            if fixed_value.get("units") != expected_units:
                raise ParameterPolicyError(f"fixed policy value unit mismatch for {parameter_name}")
            _finite(f"fixed policy value {parameter_name}", fixed_value.get("value"))
        else:
            if not coefficient_refs:
                raise ParameterPolicyError(
                    f"optimizer-derived physical output {parameter_name} must reference coefficients"
                )
            if source == DIRECT_COEFFICIENT and len(coefficient_refs) != 1:
                raise ParameterPolicyError(
                    f"direct physical output {parameter_name} must reference exactly one coefficient"
                )
        used_coefficients.extend(coefficient_refs)
        used_predictors.extend(predictor_refs)

    unused_coefficients = [name for name in vector.coefficient_order if name not in used_coefficients]
    if unused_coefficients:
        raise ParameterPolicyError(f"unused optimizer coefficient(s): {unused_coefficients}")
    unused_predictors = [name for name in predictor_names if name not in used_predictors]
    if unused_predictors:
        raise ParameterPolicyError(f"unused process predictor(s): {unused_predictors}")

    for coefficient_name in vector.coefficient_order:
        declared_targets = set(vector.metadata[coefficient_name]["target_parameters"])
        actual_targets = {
            parameter_name
            for parameter_name in CURRENT_CALIBRATABLE_PARAMETER_NAMES
            if coefficient_name in outputs[parameter_name].get("coefficient_names", [])
        }
        if actual_targets != declared_targets:
            raise ParameterPolicyError(
                f"coefficient target mismatch for {coefficient_name!r}: metadata={sorted(declared_targets)}, mapping={sorted(actual_targets)}"
            )


def validate_policy_definition(definition: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the Patch 20.12 current policy contract without fitting data."""

    payload = dict(definition)
    if payload.get("schema") != PARAMETER_POLICY_SCHEMA:
        raise ParameterPolicyError("unexpected parameter-policy schema")
    if payload.get("schema_version") != PARAMETER_POLICY_SCHEMA_VERSION:
        raise ParameterPolicyError("unexpected parameter-policy schema version")
    if payload.get("policy_scope") != SHARED_POLICY_SCOPE:
        raise ParameterPolicyError("parameter policy must be shared across coupons")
    if payload.get("coupon_specific_parameter_tuning_permitted") is not False:
        raise ParameterPolicyError("coupon-specific parameter tuning is prohibited")
    if payload.get("member_identity_as_policy_predictor_permitted") is not False:
        raise ParameterPolicyError("member/coupon identity may not be a policy predictor")
    _assert_no_member_lookup_metadata(payload)

    role_map = _mapping("parameter_roles", payload.get("parameter_roles"))
    if set(role_map) != set(CURRENT_CALIBRATABLE_PARAMETER_NAMES) or len(role_map) != len(CURRENT_CALIBRATABLE_PARAMETER_NAMES):
        raise ParameterPolicyError(
            "parameter_roles must cover the four parameters in authoritative order"
        )
    for name, role in role_map.items():
        definition_entry = quantity_definition(name)
        if definition_entry.quantity_role != CALIBRATABLE:
            raise ParameterPolicyError(f"parameter role refers to non-calibratable quantity: {name}")
        if role not in definition_entry.allowed_policy_roles:
            raise ParameterPolicyError(
                f"unsupported calibratable parameter role for {name}: {role!r}"
            )

    _validate_realized_state_contract(payload)
    _validate_fixed_model_structure(payload)
    predictor_names = _validate_predictor_contract(payload)
    vector = _validate_optimizer_vector(payload)
    _validate_physical_mapping(
        payload,
        vector=vector,
        predictor_names=predictor_names,
        parameter_roles=role_map,
    )

    functional_form = _mapping("functional_form", payload.get("functional_form"))
    if not str(functional_form.get("name", "")).strip():
        raise ParameterPolicyError("functional_form metadata must be explicit")
    if functional_form.get("shared_across_coupons") is not True:
        raise ParameterPolicyError("process-response functional form must be shared across coupons")
    if functional_form.get("member_lookup_permitted") is not False:
        raise ParameterPolicyError("functional form must explicitly prohibit member lookup")

    constraints = _mapping("constraints", payload.get("constraints"))
    if constraints.get("coupon_specific_parameter_tuning_permitted") is not False:
        raise ParameterPolicyError("policy constraints must prohibit coupon-specific tuning")
    if constraints.get("fixed_regulator_excluded") is not True:
        raise ParameterPolicyError("policy constraints must exclude the fixed regulator")
    if constraints.get("member_identity_predictor_excluded") is not True:
        raise ParameterPolicyError("policy constraints must exclude member identity predictors")

    # Compatibility aliases remain readable by accepted Patch 20.2-20.5 consumers,
    # but current validation binds them to the authoritative nested contracts.
    if "coefficient_names" in payload:
        if tuple(payload["coefficient_names"]) != vector.coefficient_order:
            raise ParameterPolicyError("coefficient_names alias disagrees with optimizer vector")
    if "coefficients" in payload:
        if dict(payload["coefficients"]) != dict(vector.values):
            raise ParameterPolicyError("coefficients alias disagrees with optimizer vector")
    if "coefficient_units" in payload:
        expected_units = {
            name: vector.metadata[name]["units"] for name in vector.coefficient_order
        }
        if dict(payload["coefficient_units"]) != expected_units:
            raise ParameterPolicyError("coefficient_units alias disagrees with optimizer metadata")
    if "predictor_names" in payload and tuple(payload["predictor_names"]) != predictor_names:
        raise ParameterPolicyError("predictor_names alias disagrees with predictor_contract")
    if "predictor_units" in payload:
        expected_predictor_units = {
            name: quantity_definition(name).units for name in predictor_names
        }
        if dict(payload["predictor_units"]) != expected_predictor_units:
            raise ParameterPolicyError("predictor_units alias disagrees with predictor_contract")

    declared_identity = payload.pop("policy_identity", None)
    computed_identity = _canonical_identity(payload)
    if declared_identity is not None and str(declared_identity) != computed_identity:
        raise ParameterPolicyError("parameter policy identity is inconsistent")
    return {**payload, "policy_identity": computed_identity}


@dataclass(frozen=True)
class ConstantPolicyCoefficients:
    """Policy coefficients for the global M0 compatibility baseline."""

    absorptivity: float
    liquid_conductivity_enhancement_factor: float
    eta_directional: float
    deposition_depth_mm: float

    def __post_init__(self) -> None:
        for name in CURRENT_CALIBRATABLE_PARAMETER_NAMES:
            object.__setattr__(self, name, _finite(name, getattr(self, name)))

    @classmethod
    def from_parameters(cls, parameters: CurrentPhysicsParameters) -> "ConstantPolicyCoefficients":
        if not isinstance(parameters, CurrentPhysicsParameters):
            raise TypeError("parameters must be CurrentPhysicsParameters")
        if parameters.deposition_depth_mm is None:
            raise ParameterPolicyError(
                "constant/global calibration policy requires finite deposition_depth_mm"
            )
        return cls(
            absorptivity=parameters.absorptivity,
            liquid_conductivity_enhancement_factor=parameters.liquid_conductivity_enhancement_factor,
            eta_directional=parameters.eta_directional,
            deposition_depth_mm=parameters.deposition_depth_mm,
        )

    def to_dict(self) -> dict[str, float]:
        return {name: float(getattr(self, name)) for name in CURRENT_CALIBRATABLE_PARAMETER_NAMES}

    def realize(self) -> CurrentPhysicsParameters:
        return CurrentPhysicsParameters(**self.to_dict())


def _constant_coefficient_metadata() -> dict[str, dict[str, Any]]:
    metadata: dict[str, dict[str, Any]] = {}
    for name in CURRENT_CALIBRATABLE_PARAMETER_NAMES:
        units = quantity_definition(name).units
        metadata[name] = {
            "name": name,
            "units": units,
            "optimizer_controlled": True,
            "coefficient_role": "direct_physical_mapping",
            "target_parameters": [name],
            "transformation": {
                "type": "identity",
                "input_units": units,
                "output_units": {name: units},
                "deterministic": True,
                "selected_as_calibration_transformation": False,
            },
            "constraint": {
                "type": "none_selected",
                "target_parameters": [name],
                "calibration_bounds_selected": False,
                "prior_selected": False,
            },
        }
    return metadata


@dataclass(frozen=True)
class ConstantParameterPolicy:
    """One global four-parameter vector shared by every process condition."""

    coefficients: ConstantPolicyCoefficients
    policy_type: str = CONSTANT_POLICY_TYPE
    policy_version: str = CONSTANT_POLICY_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.coefficients, ConstantPolicyCoefficients):
            raise TypeError("coefficients must be ConstantPolicyCoefficients")
        if self.policy_type != CONSTANT_POLICY_TYPE:
            raise ParameterPolicyError("constant policy_type is immutable")
        if self.policy_version != CONSTANT_POLICY_VERSION:
            raise ParameterPolicyError("constant policy_version is immutable")

    @classmethod
    def from_parameters(cls, parameters: CurrentPhysicsParameters) -> "ConstantParameterPolicy":
        return cls(ConstantPolicyCoefficients.from_parameters(parameters))

    def parameters_for(self, process_condition: ProcessCondition) -> CurrentPhysicsParameters:
        if not isinstance(process_condition, ProcessCondition):
            raise TypeError("process_condition must be ProcessCondition")
        return self.coefficients.realize()

    def coefficient_dict(self) -> Mapping[str, float]:
        return self.coefficients.to_dict()

    def definition_dict(self) -> Mapping[str, Any]:
        values = self.coefficients.to_dict()
        metadata = _constant_coefficient_metadata()
        vector = OptimizerCoefficientVector(
            coefficient_order=CURRENT_CALIBRATABLE_PARAMETER_NAMES,
            values=values,
            metadata=metadata,
        )
        coefficient_units = {
            name: metadata[name]["units"] for name in CURRENT_CALIBRATABLE_PARAMETER_NAMES
        }
        outputs = {
            name: {
                "parameter_name": name,
                "units": quantity_definition(name).units,
                "parameter_role": GLOBAL,
                "source": DIRECT_COEFFICIENT,
                "coefficient_names": [name],
                "predictor_names": [],
            }
            for name in CURRENT_CALIBRATABLE_PARAMETER_NAMES
        }
        payload = {
            **schema_envelope("parameter_policy"),
            "policy_type": self.policy_type,
            "policy_version": self.policy_version,
            "policy_scope": SHARED_POLICY_SCOPE,
            "parameter_roles": {
                name: GLOBAL for name in CURRENT_CALIBRATABLE_PARAMETER_NAMES
            },
            "realized_physical_state_contract": {
                "parameter_order": list(CURRENT_CALIBRATABLE_PARAMETER_NAMES),
                "parameter_units": {
                    name: quantity_definition(name).units
                    for name in CURRENT_CALIBRATABLE_PARAMETER_NAMES
                },
                "fixed_model_quantities_included": False,
            },
            "optimizer_coefficient_vector": vector.to_dict(),
            "fixed_model_structure": {
                name: {
                    "value": float(CURRENT_FIXED_CONFIGURATION[name]),
                    "units": quantity_definition(name).units,
                    "quantity_role": FIXED_REGULATOR,
                    "optimizer_controlled": False,
                }
                for name in CURRENT_FIXED_REGULATOR_PARAMETER_NAMES
            },
            "predictor_contract": {
                "names": [],
                "units": {},
                "centering": {"type": "none", "predictor_names": [], "parameters": {}},
                "scaling": {"type": "none", "predictor_names": [], "parameters": {}},
                "interpolation_domain": {
                    "type": "not_applicable",
                    "predictor_names": [],
                    "bounds": {},
                },
                "extrapolation_policy": {
                    "type": "not_applicable",
                    "predictor_names": [],
                    "parameters": {},
                },
                "identity_fields_permitted": False,
            },
            "coefficient_to_physical_mapping": {
                "mapping_scope": SHARED_POLICY_SCOPE,
                "outputs": outputs,
            },
            "functional_form": {
                "name": "constant",
                "shared_across_coupons": True,
                "member_lookup_permitted": False,
            },
            "constraints": {
                "calibration_bounds_selected": False,
                "priors_selected": False,
                "process_predictors_selected": False,
                "fixed_regulator_excluded": True,
                "coupon_specific_parameter_tuning_permitted": False,
                "member_identity_predictor_excluded": True,
            },
            "coupon_specific_parameter_tuning_permitted": False,
            "member_identity_as_policy_predictor_permitted": False,
            "quadratic_boiling_strength_is_policy_coefficient": False,
            "parameter_fitting_performed": False,
            # Compatibility aliases retained for accepted Patch 20.2-20.5 readers.
            "coefficient_names": list(CURRENT_CALIBRATABLE_PARAMETER_NAMES),
            "coefficient_units": coefficient_units,
            "coefficients": values,
            "predictor_names": [],
            "predictor_units": {},
            "predictor_scaling": {"type": "none", "parameters": {}},
            "predictors": [],
            "process_condition_fields_reserved": list(CURRENT_PROCESS_PREDICTOR_NAMES),
        }
        return validate_policy_definition(payload)


def optimizer_coefficient_vector(policy: ParameterPolicy) -> OptimizerCoefficientVector:
    """Return the validated optimizer coefficient vector for a current policy."""

    if not isinstance(policy, ParameterPolicy):
        raise TypeError("policy does not satisfy the ParameterPolicy protocol")
    definition = validate_policy_definition(policy.definition_dict())
    vector = _validate_optimizer_vector(definition)
    actual = dict(policy.coefficient_dict())
    if tuple(actual) != vector.coefficient_order:
        raise ParameterPolicyError(
            "policy coefficient_dict order/names disagree with optimizer coefficient contract"
        )
    for name in vector.coefficient_order:
        if _finite(name, actual[name]) != vector.values[name]:
            raise ParameterPolicyError(
                f"policy coefficient_dict value disagrees with definition for {name!r}"
            )
    return vector


def _physical_vector(physics: CurrentPhysicsParameters) -> dict[str, float]:
    if physics.deposition_depth_mm is None:
        raise ParameterPolicyError("calibration-facing policy may not realize legacy deposition control")
    vector: dict[str, float] = {}
    for name in CURRENT_CALIBRATABLE_PARAMETER_NAMES:
        vector[name] = _finite(name, getattr(physics, name))
    return vector


def _verify_declared_mapping_against_realization(
    definition: Mapping[str, Any],
    vector: OptimizerCoefficientVector,
    realized: CurrentPhysicsParameters,
) -> None:
    values = _physical_vector(realized)
    outputs = definition["coefficient_to_physical_mapping"]["outputs"]
    for parameter_name in CURRENT_CALIBRATABLE_PARAMETER_NAMES:
        output = outputs[parameter_name]
        source = output["source"]
        if source == FIXED_POLICY_VALUE:
            expected = float(output["fixed_value"]["value"])
            if values[parameter_name] != expected:
                raise ParameterPolicyError(
                    f"realized {parameter_name} disagrees with declared fixed policy value"
                )
        elif source == DIRECT_COEFFICIENT:
            coefficient_name = output["coefficient_names"][0]
            metadata = vector.metadata[coefficient_name]
            if metadata["transformation"]["type"] == "identity":
                expected = float(vector.values[coefficient_name])
                if values[parameter_name] != expected:
                    raise ParameterPolicyError(
                        f"realized {parameter_name} disagrees with direct optimizer coefficient {coefficient_name!r}"
                    )


def realize_parameter_policy(
    policy: ParameterPolicy,
    process_condition: ProcessCondition,
) -> CurrentPhysicsParameters:
    """Realize a policy and fail closed on schema/runtime role inconsistencies."""

    if not isinstance(policy, ParameterPolicy):
        raise TypeError("policy does not satisfy the ParameterPolicy protocol")
    if not isinstance(process_condition, ProcessCondition):
        raise TypeError("process_condition must be ProcessCondition")

    definition = validate_policy_definition(policy.definition_dict())
    vector = optimizer_coefficient_vector(policy)
    realized = policy.parameters_for(process_condition)
    if not isinstance(realized, CurrentPhysicsParameters):
        raise ParameterPolicyError("policy must realize CurrentPhysicsParameters")
    _physical_vector(realized)
    _verify_declared_mapping_against_realization(definition, vector, realized)

    # Determinism gate: identical inputs must return exactly the same physical state.
    repeated = policy.parameters_for(process_condition)
    if repeated != realized:
        raise ParameterPolicyError("parameter policy realization is not deterministic")

    # Member/coupon lookup gate: changing provenance identity while holding all
    # authorized predictors fixed must not change any physical parameter.
    alias_condition = ProcessCondition(
        condition_id=process_condition.condition_id + "::lookup_invariance_probe",
        power_W=process_condition.power_W,
        speed_mm_s=process_condition.speed_mm_s,
        power_units=process_condition.power_units,
        speed_units=process_condition.speed_units,
    )
    alias_realized = policy.parameters_for(alias_condition)
    if not isinstance(alias_realized, CurrentPhysicsParameters) or alias_realized != realized:
        raise ParameterPolicyError(
            "parameter policy depends on condition/member identity; coupon-specific lookup is prohibited"
        )

    # Role-consistency gate: parameters declared global must remain unchanged
    # under a small predictor perturbation.  Process-conditioned outputs may vary.
    probe_condition = ProcessCondition(
        condition_id=process_condition.condition_id + "::role_probe",
        power_W=process_condition.power_W * 1.001,
        speed_mm_s=process_condition.speed_mm_s * 1.001,
        power_units=process_condition.power_units,
        speed_units=process_condition.speed_units,
    )
    probe_realized = policy.parameters_for(probe_condition)
    if not isinstance(probe_realized, CurrentPhysicsParameters):
        raise ParameterPolicyError("policy role probe did not realize CurrentPhysicsParameters")
    _physical_vector(probe_realized)
    for name, role in definition["parameter_roles"].items():
        if role == GLOBAL and getattr(probe_realized, name) != getattr(realized, name):
            raise ParameterPolicyError(
                f"parameter {name!r} is declared global but varies with process condition"
            )
    return realized


__all__ = [
    "ALLOWED_COEFFICIENT_ROLES",
    "ALLOWED_PHYSICAL_MAPPING_SOURCES",
    "CONSTANT_POLICY_TYPE",
    "CONSTANT_POLICY_VERSION",
    "DERIVED_COEFFICIENTS",
    "DIRECT_COEFFICIENT",
    "FIXED_POLICY_VALUE",
    "OPTIMIZER_COEFFICIENT_VECTOR_SCHEMA",
    "OPTIMIZER_COEFFICIENT_VECTOR_SCHEMA_VERSION",
    "PARAMETER_POLICY_SCHEMA",
    "PARAMETER_POLICY_SCHEMA_VERSION",
    "PROCESS_CONDITION_SCHEMA",
    "PROCESS_CONDITION_SCHEMA_VERSION",
    "SHARED_POLICY_SCOPE",
    "ConstantParameterPolicy",
    "ConstantPolicyCoefficients",
    "OptimizerCoefficientVector",
    "ParameterPolicy",
    "ParameterPolicyError",
    "ProcessCondition",
    "optimizer_coefficient_vector",
    "realize_parameter_policy",
    "validate_policy_definition",
]
