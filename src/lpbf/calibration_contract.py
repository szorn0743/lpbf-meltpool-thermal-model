"""Frozen Patch 21.0 calibration contract.

This module freezes the *calibration design* without fitting parameters.  It
implements the accepted pre-fit restrictions carried forward from Patch 20.15:

* absorptivity and deposition depth are represented by one identifiable
  composite coordinate rather than two independent optimizer coordinates;
* liquid-conductivity enhancement and directional transport remain separate
  coordinates but are subject to a coupled numerical-feasibility guard;
* all fitted quantities are global/shared across coupons in Patch 21.0;
* quadratic boiling strength remains the fixed 0.5 regulator;
* H and W remain separate primary observables with a condition-balanced
  objective and a condition-level held-out partition.

No optimizer is selected and no model parameter is fitted here.  Real-data
thermal execution remains behind the public atomic calibration evaluator and is
owned by the Patch 21.0 local-feasibility runner.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from importlib.resources import files
import json
import math
from typing import Any, Iterable, Mapping, Sequence

from lpbf.data.full_coupon_manifest import FullCouponManifest, load_full_coupon_manifest
from lpbf.geometry import resize_xy_window
from lpbf.model.current_configuration import (
    CURRENT_CALIBRATABLE_PARAMETER_NAMES,
    CURRENT_FIXED_CONFIGURATION,
    CURRENT_FIXED_REGULATOR_PARAMETER_NAMES,
    CurrentPhysicsParameters,
)
from lpbf.model.parameter_policy import (
    DERIVED_COEFFICIENTS,
    DIRECT_COEFFICIENT,
    OptimizerCoefficientVector,
    ParameterPolicyError,
    ProcessCondition,
    SHARED_POLICY_SCOPE,
    ConstantParameterPolicy,
    validate_policy_definition,
)
from lpbf.model.quantity_registry import (
    FIXED_REGULATOR,
    GLOBAL,
    quantity_definition,
)
from lpbf.execution.api import current_numerical_stability_preflight
from lpbf.model.parameters import get_model_parameters
from lpbf.runtime.configuration import (
    apply_frozen_experiment_configuration,
    load_frozen_experiment_configuration,
)
from lpbf.runtime.parameters import THERMAL_DT_S


PATCH_VERSION = "21.0.0"
CONTRACT_RESOURCE = "patch21_0_calibration_contract.json"
POLICY_TYPE = "patch21_0_global_identifiable_subspace"
POLICY_VERSION = "1"
ABS_DEPTH_COORDINATE = "abs_depth_identifiable_coordinate"
CONDUCTIVITY_COORDINATE = "liquid_conductivity_enhancement_factor"
DIRECTIONAL_COORDINATE = "eta_directional"
COEFFICIENT_ORDER = (
    ABS_DEPTH_COORDINATE,
    CONDUCTIVITY_COORDINATE,
    DIRECTIONAL_COORDINATE,
)


class Patch210ContractError(ValueError):
    """Raised when the Patch 21.0 calibration contract is violated."""


def _finite(name: str, value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise Patch210ContractError(f"{name} must be numeric") from exc
    if not math.isfinite(number):
        raise Patch210ContractError(f"{name} must be finite")
    return number


def load_patch21_0_contract() -> dict[str, Any]:
    """Load and minimally validate the packaged Patch 21.0 design freeze."""

    resource = files("lpbf.data").joinpath(CONTRACT_RESOURCE)
    payload = json.loads(resource.read_text(encoding="utf-8"))
    if payload.get("schema") != "lpbf_patch21_0_calibration_contract":
        raise Patch210ContractError("unexpected Patch 21.0 calibration-contract schema")
    if payload.get("schema_version") != PATCH_VERSION:
        raise Patch210ContractError("unexpected Patch 21.0 calibration-contract version")
    if payload.get("patch") != "21.0":
        raise Patch210ContractError("Patch 21.0 calibration contract has wrong patch identity")
    if tuple(payload["optimizer_parameterization"]["coefficient_order"]) != COEFFICIENT_ORDER:
        raise Patch210ContractError("Patch 21.0 optimizer coefficient order has drifted")
    if payload["model_structure"]["quadratic_boiling_strength"] != float(
        CURRENT_FIXED_CONFIGURATION["quadratic_boiling_strength"]
    ):
        raise Patch210ContractError("fixed quadratic boiling regulator has drifted")
    return payload


def _bounds(contract: Mapping[str, Any] | None = None) -> dict[str, tuple[float, float]]:
    design = load_patch21_0_contract() if contract is None else contract
    reparam = design["optimizer_parameterization"]["absorptivity_deposition_depth_reparameterization"]
    direct = design["optimizer_parameterization"]["direct_coordinate_bounds"]
    return {
        ABS_DEPTH_COORDINATE: tuple(float(v) for v in reparam["coordinate_bounds"]),
        CONDUCTIVITY_COORDINATE: (
            float(direct[CONDUCTIVITY_COORDINATE]["minimum"]),
            float(direct[CONDUCTIVITY_COORDINATE]["maximum"]),
        ),
        DIRECTIONAL_COORDINATE: (
            float(direct[DIRECTIONAL_COORDINATE]["minimum"]),
            float(direct[DIRECTIONAL_COORDINATE]["maximum"]),
        ),
    }


def _abs_depth_mapping(
    coordinate: float,
    contract: Mapping[str, Any] | None = None,
) -> tuple[float, float]:
    design = load_patch21_0_contract() if contract is None else contract
    info = design["optimizer_parameterization"]["absorptivity_deposition_depth_reparameterization"]
    reference = info["reference_state"]
    direction = info["principal_direction_normalized_step_coordinates"]
    steps = info["patch20_15_step_scales"]
    c = _finite(ABS_DEPTH_COORDINATE, coordinate)
    absorptivity = float(reference["absorptivity"]) + c * float(
        direction["absorptivity"]
    ) * float(steps["absorptivity"])
    depth = float(reference["deposition_depth_mm"]) + c * float(
        direction["deposition_depth_mm"]
    ) * float(steps["deposition_depth_mm"])
    return float(absorptivity), float(depth)


@dataclass(frozen=True)
class Patch21OptimizerCoefficients:
    """The three optimizer-controlled coordinates frozen by Patch 21.0."""

    abs_depth_identifiable_coordinate: float
    liquid_conductivity_enhancement_factor: float
    eta_directional: float

    def __post_init__(self) -> None:
        for name in COEFFICIENT_ORDER:
            object.__setattr__(self, name, _finite(name, getattr(self, name)))
        for name, (minimum, maximum) in _bounds().items():
            value = float(getattr(self, name))
            if value < minimum or value > maximum:
                raise Patch210ContractError(
                    f"{name}={value} is outside frozen Patch 21.0 bounds [{minimum}, {maximum}]"
                )

    def to_dict(self) -> dict[str, float]:
        return {name: float(getattr(self, name)) for name in COEFFICIENT_ORDER}

    def realized_parameters(self) -> CurrentPhysicsParameters:
        absorptivity, depth = _abs_depth_mapping(
            self.abs_depth_identifiable_coordinate
        )
        return CurrentPhysicsParameters(
            absorptivity=absorptivity,
            liquid_conductivity_enhancement_factor=float(
                self.liquid_conductivity_enhancement_factor
            ),
            eta_directional=float(self.eta_directional),
            deposition_depth_mm=depth,
        )


def _coefficient_metadata(coefficients: Patch21OptimizerCoefficients) -> dict[str, dict[str, Any]]:
    bounds = _bounds()
    metadata: dict[str, dict[str, Any]] = {}

    minimum, maximum = bounds[ABS_DEPTH_COORDINATE]
    metadata[ABS_DEPTH_COORDINATE] = {
        "name": ABS_DEPTH_COORDINATE,
        "units": "dimensionless",
        "optimizer_controlled": True,
        "coefficient_role": "transformation_parameter",
        "target_parameters": ["absorptivity", "deposition_depth_mm"],
        "transformation": {
            "type": "patch21_0_principal_observable_direction",
            "input_units": "dimensionless",
            "output_units": {
                "absorptivity": quantity_definition("absorptivity").units,
                "deposition_depth_mm": quantity_definition("deposition_depth_mm").units,
            },
            "deterministic": True,
            "selected_as_calibration_transformation": True,
        },
        "constraint": {
            "type": "hard_box_coordinate_bound",
            "target_parameters": ["absorptivity", "deposition_depth_mm"],
            "minimum": minimum,
            "maximum": maximum,
            "calibration_bounds_selected": True,
            "prior_selected": False,
        },
    }

    for name, target in (
        (CONDUCTIVITY_COORDINATE, "liquid_conductivity_enhancement_factor"),
        (DIRECTIONAL_COORDINATE, "eta_directional"),
    ):
        minimum, maximum = bounds[name]
        units = quantity_definition(target).units
        metadata[name] = {
            "name": name,
            "units": units,
            "optimizer_controlled": True,
            "coefficient_role": "direct_physical_mapping",
            "target_parameters": [target],
            "transformation": {
                "type": "identity",
                "input_units": units,
                "output_units": {target: units},
                "deterministic": True,
                "selected_as_calibration_transformation": True,
            },
            "constraint": {
                "type": "hard_box_coordinate_bound_plus_coupled_transport_guard",
                "target_parameters": [target],
                "minimum": minimum,
                "maximum": maximum,
                "calibration_bounds_selected": True,
                "prior_selected": False,
            },
        }
    return metadata


@dataclass(frozen=True)
class Patch21GlobalParameterPolicy:
    """Global/shared three-coordinate Patch 21.0 calibration policy."""

    coefficients: Patch21OptimizerCoefficients
    policy_type: str = POLICY_TYPE
    policy_version: str = POLICY_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.coefficients, Patch21OptimizerCoefficients):
            raise TypeError("coefficients must be Patch21OptimizerCoefficients")
        if self.policy_type != POLICY_TYPE or self.policy_version != POLICY_VERSION:
            raise Patch210ContractError("Patch 21.0 policy identity is immutable")

    @classmethod
    def from_values(
        cls,
        abs_depth_identifiable_coordinate: float,
        liquid_conductivity_enhancement_factor: float,
        eta_directional: float,
    ) -> "Patch21GlobalParameterPolicy":
        return cls(
            Patch21OptimizerCoefficients(
                abs_depth_identifiable_coordinate=abs_depth_identifiable_coordinate,
                liquid_conductivity_enhancement_factor=liquid_conductivity_enhancement_factor,
                eta_directional=eta_directional,
            )
        )

    def coefficient_dict(self) -> Mapping[str, float]:
        return self.coefficients.to_dict()

    def parameters_for(self, process_condition: ProcessCondition) -> CurrentPhysicsParameters:
        if not isinstance(process_condition, ProcessCondition):
            raise TypeError("process_condition must be ProcessCondition")
        return self.coefficients.realized_parameters()

    def definition_dict(self) -> Mapping[str, Any]:
        physical = self.coefficients.realized_parameters()
        base = dict(ConstantParameterPolicy.from_parameters(physical).definition_dict())
        base.pop("policy_identity", None)
        metadata = _coefficient_metadata(self.coefficients)
        vector = OptimizerCoefficientVector(
            coefficient_order=COEFFICIENT_ORDER,
            values=self.coefficient_dict(),
            metadata=metadata,
        )
        base["policy_type"] = self.policy_type
        base["policy_version"] = self.policy_version
        base["parameter_roles"] = {
            name: GLOBAL for name in CURRENT_CALIBRATABLE_PARAMETER_NAMES
        }
        base["optimizer_coefficient_vector"] = vector.to_dict()
        base["coefficient_names"] = list(COEFFICIENT_ORDER)
        base["coefficient_units"] = {
            name: metadata[name]["units"] for name in COEFFICIENT_ORDER
        }
        base["coefficients"] = self.coefficients.to_dict()
        base["coefficient_to_physical_mapping"] = {
            "mapping_scope": SHARED_POLICY_SCOPE,
            "outputs": {
                "absorptivity": {
                    "parameter_name": "absorptivity",
                    "units": quantity_definition("absorptivity").units,
                    "parameter_role": GLOBAL,
                    "source": DERIVED_COEFFICIENTS,
                    "coefficient_names": [ABS_DEPTH_COORDINATE],
                    "predictor_names": [],
                },
                "liquid_conductivity_enhancement_factor": {
                    "parameter_name": "liquid_conductivity_enhancement_factor",
                    "units": quantity_definition(
                        "liquid_conductivity_enhancement_factor"
                    ).units,
                    "parameter_role": GLOBAL,
                    "source": DIRECT_COEFFICIENT,
                    "coefficient_names": [CONDUCTIVITY_COORDINATE],
                    "predictor_names": [],
                },
                "eta_directional": {
                    "parameter_name": "eta_directional",
                    "units": quantity_definition("eta_directional").units,
                    "parameter_role": GLOBAL,
                    "source": DIRECT_COEFFICIENT,
                    "coefficient_names": [DIRECTIONAL_COORDINATE],
                    "predictor_names": [],
                },
                "deposition_depth_mm": {
                    "parameter_name": "deposition_depth_mm",
                    "units": quantity_definition("deposition_depth_mm").units,
                    "parameter_role": GLOBAL,
                    "source": DERIVED_COEFFICIENTS,
                    "coefficient_names": [ABS_DEPTH_COORDINATE],
                    "predictor_names": [],
                },
            },
        }
        base["functional_form"] = {
            "name": "patch21_0_global_identifiable_subspace",
            "shared_across_coupons": True,
            "member_lookup_permitted": False,
        }
        base["constraints"] = {
            "calibration_bounds_selected": True,
            "priors_selected": False,
            "process_predictors_selected": False,
            "coupled_transport_guard_selected": True,
            "coupled_transport_guard_quantity": "directional.selected_over_safe_limit",
            "coupled_transport_guard_maximum": float(
                load_patch21_0_contract()["coupled_transport_guard"]["maximum_allowed"]
            ),
            "fixed_regulator_excluded": True,
            "coupon_specific_parameter_tuning_permitted": False,
            "member_identity_predictor_excluded": True,
        }
        base["quadratic_boiling_strength_is_policy_coefficient"] = False
        base["parameter_fitting_performed"] = False
        return validate_policy_definition(base)


def patch21_policy_from_values(
    abs_depth_identifiable_coordinate: float,
    liquid_conductivity_enhancement_factor: float,
    eta_directional: float,
) -> Patch21GlobalParameterPolicy:
    return Patch21GlobalParameterPolicy.from_values(
        abs_depth_identifiable_coordinate,
        liquid_conductivity_enhancement_factor,
        eta_directional,
    )


def _frozen_preflight_params() -> Any:
    """Construct the HDF5-independent numerical state used by the atomic evaluator."""

    params = apply_frozen_experiment_configuration(
        get_model_parameters(), load_frozen_experiment_configuration()
    )
    params = replace(params, time=replace(params.time, dt_s=THERMAL_DT_S))
    return resize_xy_window(params, 79)


def patch21_candidate_admissibility(
    coefficients_or_policy: Patch21OptimizerCoefficients | Patch21GlobalParameterPolicy,
) -> dict[str, Any]:
    """Apply box bounds and the frozen non-marginal coupled transport guard.

    This check is intentionally HDF5-independent and must run before thermal
    solver entry for every Patch 21 candidate.
    """

    if isinstance(coefficients_or_policy, Patch21GlobalParameterPolicy):
        coefficients = coefficients_or_policy.coefficients
    elif isinstance(coefficients_or_policy, Patch21OptimizerCoefficients):
        coefficients = coefficients_or_policy
    else:
        raise TypeError("expected Patch21OptimizerCoefficients or Patch21GlobalParameterPolicy")

    physics = coefficients.realized_parameters()
    preflight = current_numerical_stability_preflight(_frozen_preflight_params(), physics)
    ratio = _finite(
        "directional.selected_over_safe_limit",
        preflight["directional"]["selected_over_safe_limit"],
    )
    maximum = float(load_patch21_0_contract()["coupled_transport_guard"]["maximum_allowed"])
    accepted = bool(preflight.get("status") == "PASS" and ratio <= maximum)
    return {
        "schema": "lpbf_patch21_0_candidate_admissibility",
        "schema_version": PATCH_VERSION,
        "status": "PASS" if accepted else "REJECT",
        "admissible": accepted,
        "optimizer_coefficients": coefficients.to_dict(),
        "realized_parameters": {
            name: float(getattr(physics, name)) for name in CURRENT_CALIBRATABLE_PARAMETER_NAMES
        },
        "frozen_numerical_preflight": preflight,
        "coupled_transport_guard": {
            "quantity": "directional.selected_over_safe_limit",
            "actual": ratio,
            "maximum_allowed": maximum,
            "non_marginal_margin_fraction": 1.0 - maximum,
            "passes": bool(ratio <= maximum),
        },
        "thermal_execution_permitted": accepted,
    }


def condition_id(power_W: float, speed_mm_s: float) -> str:
    power = _finite("power_W", power_W)
    speed = _finite("speed_mm_s", speed_mm_s)
    if not power.is_integer() or not speed.is_integer():
        raise Patch210ContractError(
            "Patch 21.0 frozen condition IDs require integer nominal P and v values"
        )
    return f"P{int(power)}_V{int(speed)}"


def member_identity(acquisition_set_id: str, part_number: int) -> str:
    return f"{str(acquisition_set_id)}:part_{int(part_number)}"


def validate_patch21_partition(
    manifest: FullCouponManifest | None = None,
    contract: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Prove exact member coverage and condition-level leakage prevention."""

    current = load_full_coupon_manifest() if manifest is None else manifest.require_hash_complete()
    design = load_patch21_0_contract() if contract is None else contract
    if current.canonical_identity != design["authoritative_evidence"]["canonical_manifest_identity"]:
        raise Patch210ContractError("Patch 21.0 partition manifest identity mismatch")

    partition = design["data_partition"]
    calibration = list(partition["calibration_members"])
    validation = list(partition["validation_members"])
    rows = calibration + validation
    if len(rows) != 24:
        raise Patch210ContractError("Patch 21.0 partition must cover exactly 24 members")

    declared: dict[tuple[str, int], Mapping[str, Any]] = {}
    for row in rows:
        key = (str(row["acquisition_set_id"]), int(row["part_number"]))
        if key in declared:
            raise Patch210ContractError(f"duplicate partition member {key}")
        declared[key] = row

    manifest_keys = {
        (member.key.acquisition_set_id, member.key.part_number): member
        for member in current.enabled_members
    }
    if set(declared) != set(manifest_keys):
        raise Patch210ContractError("Patch 21.0 partition does not exactly cover canonical members")

    for key, row in declared.items():
        member = manifest_keys[key]
        expected = {
            "expected_filename": member.expected_filename,
            "sha256": member.sha256,
            "power_W": float(member.nominal_power_W),
            "speed_mm_s": float(member.nominal_speed_mm_s),
            "condition_id": condition_id(member.nominal_power_W, member.nominal_speed_mm_s),
        }
        for field, value in expected.items():
            if row[field] != value:
                raise Patch210ContractError(
                    f"partition field mismatch for {key} {field}: {row[field]!r} != {value!r}"
                )

    calibration_conditions = {str(row["condition_id"]) for row in calibration}
    validation_conditions = {str(row["condition_id"]) for row in validation}
    if calibration_conditions & validation_conditions:
        raise Patch210ContractError("exact P/v condition leakage across calibration/validation split")
    if calibration_conditions != set(partition["calibration_condition_ids"]):
        raise Patch210ContractError("calibration condition IDs disagree with frozen partition")
    if validation_conditions != set(partition["validation_condition_ids"]):
        raise Patch210ContractError("validation condition IDs disagree with frozen partition")
    if len(calibration) != int(partition["calibration_member_count"]):
        raise Patch210ContractError("calibration member count mismatch")
    if len(validation) != int(partition["validation_member_count"]):
        raise Patch210ContractError("validation member count mismatch")
    if len(calibration_conditions) != int(partition["calibration_unique_condition_count"]):
        raise Patch210ContractError("calibration unique-condition count mismatch")
    if len(validation_conditions) != int(partition["validation_unique_condition_count"]):
        raise Patch210ContractError("validation unique-condition count mismatch")

    return {
        "status": "PASS",
        "manifest_identity": current.canonical_identity,
        "member_count": len(rows),
        "calibration_member_count": len(calibration),
        "validation_member_count": len(validation),
        "calibration_unique_condition_count": len(calibration_conditions),
        "validation_unique_condition_count": len(validation_conditions),
        "condition_leakage_count": 0,
    }


def calibration_member_identities(contract: Mapping[str, Any] | None = None) -> frozenset[str]:
    design = load_patch21_0_contract() if contract is None else contract
    return frozenset(
        member_identity(row["acquisition_set_id"], row["part_number"])
        for row in design["data_partition"]["calibration_members"]
    )


def validation_member_identities(contract: Mapping[str, Any] | None = None) -> frozenset[str]:
    design = load_patch21_0_contract() if contract is None else contract
    return frozenset(
        member_identity(row["acquisition_set_id"], row["part_number"])
        for row in design["data_partition"]["validation_members"]
    )


def patch21_calibration_objective(
    records: Sequence[Mapping[str, Any]],
    *,
    contract: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute the frozen condition-balanced H/W objective on calibration data only.

    Each record represents one member at one candidate and must contain member
    identity, nominal P/v, status, and experimental/simulated H/W values.  A
    failed/invalid candidate returns the frozen scalar optimizer bookkeeping
    penalty; failed rows are never converted into fabricated H/W residuals.
    """

    design = load_patch21_0_contract() if contract is None else contract
    objective = design["objective"]
    allowed = calibration_member_identities(design)
    validation = validation_member_identities(design)
    expected_count = int(design["data_partition"]["calibration_member_count"])
    penalty = float(objective["failed_candidate_scalar_penalty"])

    if not records:
        raise Patch210ContractError("calibration objective requires member records")

    seen: set[str] = set()
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    failure_rows: list[dict[str, Any]] = []
    for raw in records:
        row = dict(raw)
        identity = str(row["member_identity"])
        if identity in validation:
            raise Patch210ContractError(
                f"held-out validation member {identity} may not enter calibration objective"
            )
        if identity not in allowed:
            raise Patch210ContractError(f"unknown/non-calibration member {identity}")
        if identity in seen:
            raise Patch210ContractError(f"duplicate calibration objective member {identity}")
        seen.add(identity)
        if str(row.get("status")) != "PASS":
            failure_rows.append(
                {
                    "member_identity": identity,
                    "status": str(row.get("status")),
                    "failure": row.get("failure"),
                }
            )
            continue
        cid = condition_id(row["power_W"], row["speed_mm_s"])
        grouped.setdefault(cid, []).append(row)

    if failure_rows:
        return {
            "schema": "lpbf_patch21_0_calibration_objective",
            "schema_version": PATCH_VERSION,
            "status": "FAILED_CANDIDATE_PENALTY",
            "objective_value": penalty,
            "penalty_applied": True,
            "failed_member_records": failure_rows,
            "fabricated_residuals_used": False,
        }

    if len(seen) != expected_count:
        missing = sorted(allowed - seen)
        raise Patch210ContractError(
            f"calibration objective requires all {expected_count} frozen calibration members; missing={missing}"
        )

    h_scale = float(objective["normalization_scales_pixels"]["H_pixels"])
    w_scale = float(objective["normalization_scales_pixels"]["W_pixels"])
    h_weight = float(objective["metric_weights"]["H_pixels"])
    w_weight = float(objective["metric_weights"]["W_pixels"])
    h_by_condition: dict[str, float] = {}
    w_by_condition: dict[str, float] = {}

    for cid, group in sorted(grouped.items()):
        h_terms: list[float] = []
        w_terms: list[float] = []
        for row in group:
            h_exp = _finite("experimental_H_pixels", row["experimental_H_pixels"])
            w_exp = _finite("experimental_W_pixels", row["experimental_W_pixels"])
            h_sim = _finite("simulated_H_pixels", row["simulated_H_pixels"])
            w_sim = _finite("simulated_W_pixels", row["simulated_W_pixels"])
            h_terms.append(((h_sim - h_exp) / h_scale) ** 2)
            w_terms.append(((w_sim - w_exp) / w_scale) ** 2)
        h_by_condition[cid] = sum(h_terms) / len(h_terms)
        w_by_condition[cid] = sum(w_terms) / len(w_terms)

    expected_conditions = set(design["data_partition"]["calibration_condition_ids"])
    if set(grouped) != expected_conditions:
        raise Patch210ContractError("objective condition coverage does not match frozen calibration partition")

    h_component = sum(h_by_condition.values()) / len(h_by_condition)
    w_component = sum(w_by_condition.values()) / len(w_by_condition)
    total = h_weight * h_component + w_weight * w_component
    return {
        "schema": "lpbf_patch21_0_calibration_objective",
        "schema_version": PATCH_VERSION,
        "status": "PASS",
        "objective_value": float(total),
        "penalty_applied": False,
        "H_component_unweighted_condition_mean": float(h_component),
        "W_component_unweighted_condition_mean": float(w_component),
        "H_weight": h_weight,
        "W_weight": w_weight,
        "condition_count": len(grouped),
        "member_count": len(seen),
        "condition_H_terms": h_by_condition,
        "condition_W_terms": w_by_condition,
        "fabricated_residuals_used": False,
        "temperature_diagnostics_in_objective": False,
    }


def local_feasibility_state_policies(
    contract: Mapping[str, Any] | None = None,
) -> tuple[tuple[str, Patch21GlobalParameterPolicy], ...]:
    design = load_patch21_0_contract() if contract is None else contract
    output: list[tuple[str, Patch21GlobalParameterPolicy]] = []
    for row in design["local_feasibility_gate"]["states"]:
        output.append(
            (
                str(row["state_id"]),
                Patch21GlobalParameterPolicy.from_values(
                    row[ABS_DEPTH_COORDINATE],
                    row[CONDUCTIVITY_COORDINATE],
                    row[DIRECTIONAL_COORDINATE],
                ),
            )
        )
    return tuple(output)


__all__ = [
    "PATCH_VERSION",
    "COEFFICIENT_ORDER",
    "Patch210ContractError",
    "Patch21OptimizerCoefficients",
    "Patch21GlobalParameterPolicy",
    "load_patch21_0_contract",
    "patch21_policy_from_values",
    "patch21_candidate_admissibility",
    "validate_patch21_partition",
    "calibration_member_identities",
    "validation_member_identities",
    "patch21_calibration_objective",
    "local_feasibility_state_policies",
    "condition_id",
    "member_identity",
]
