"""Authoritative current parameter/configuration contract.

Patch 19.7.3 centralized the four calibration-facing degrees of freedom.
Patch 19.8.6 closes the boiling-control study by promoting the scientifically
accepted quadratic boiling regulator to fixed current-model structure at
``quadratic_boiling_strength = 0.5``.  The regulator is not calibratable and
must never appear in an optimizer-controlled vector.

Calibration bounds and preferred values for the four retained FIT parameters
remain intentionally unselected at this checkpoint.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import math
from types import MappingProxyType
from typing import Any, Mapping

from lpbf.model.deposition_depth import (
    EXPONENTIAL_DEPOSITION_DEPTH_MODE,
    LEGACY_DEPOSITION_DEPTH_MODE,
    DepositionDepthDesignState,
)
from lpbf.model.directional_transport import principal_liquid_conductivities
from lpbf.model.quantity_registry import (
    CURRENT_CALIBRATABLE_PARAMETER_NAMES as REGISTRY_CALIBRATABLE_PARAMETER_NAMES,
    CURRENT_FIXED_REGULATOR_PARAMETER_NAMES,
    POLICY_ROLE_UNSELECTED,
    current_quantity_registry_dict,
    quantity_definition as registry_quantity_definition,
)


CURRENT_CONFIGURATION_SCHEMA = "lpbf_current_parameter_configuration"
CURRENT_CONFIGURATION_SCHEMA_VERSION = "19.8.6"
CURRENT_PARAMETER_STATE_SCHEMA = "lpbf_current_physics_parameters"
CURRENT_PARAMETER_STATE_SCHEMA_VERSION = "19.7.3"

FIT = "FIT"
DISABLED = "DISABLED"
FIXED_REGULATOR = "FIXED_REGULATOR"
EXPLICIT_REQUIRED = "EXPLICIT_REQUIRED"
FIXED_MODEL_STRUCTURE = "FIXED_MODEL_STRUCTURE"
CALIBRATION_BOUNDS_UNSELECTED = "UNSELECTED"

CURRENT_CALIBRATABLE_PARAMETER_NAMES = REGISTRY_CALIBRATABLE_PARAMETER_NAMES
# Compatibility name retained for accepted Patch 19.x manifests and readers.
CURRENT_FIT_PARAMETER_NAMES = CURRENT_CALIBRATABLE_PARAMETER_NAMES
QUADRATIC_BOILING_PARAMETER_NAME = CURRENT_FIXED_REGULATOR_PARAMETER_NAMES[0]
CURRENT_PARAMETER_NAMES = CURRENT_FIT_PARAMETER_NAMES + (
    QUADRATIC_BOILING_PARAMETER_NAME,
)


@dataclass(frozen=True)
class ParameterBounds:
    """Serializable accepted physical/implementation bound description.

    ``maximum_reference`` is used when an accepted upper bound depends on the
    process-condition geometry instead of being a universal scalar.
    """

    minimum: float | None = None
    maximum: float | None = None
    minimum_inclusive: bool = True
    maximum_inclusive: bool = True
    maximum_reference: str | None = None
    basis: str = "accepted physical/implementation contract"

    def to_dict(self) -> dict[str, Any]:
        return {
            "minimum": self.minimum,
            "maximum": self.maximum,
            "minimum_inclusive": bool(self.minimum_inclusive),
            "maximum_inclusive": bool(self.maximum_inclusive),
            "maximum_reference": self.maximum_reference,
            "basis": self.basis,
        }


@dataclass(frozen=True)
class CurrentParameterDefinition:
    """One authoritative current-model parameter definition."""

    name: str
    units: str
    disposition: str
    default_value: float | None
    default_policy: str
    physical_bounds: ParameterBounds
    calibration_bounds: ParameterBounds | None
    calibration_bounds_status: str
    provenance: tuple[str, ...]
    description: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "units": self.units,
            "disposition": self.disposition,
            "default_value": self.default_value,
            "default_policy": self.default_policy,
            "physical_bounds": self.physical_bounds.to_dict(),
            "calibration_bounds": (
                None
                if self.calibration_bounds is None
                else self.calibration_bounds.to_dict()
            ),
            "calibration_bounds_status": self.calibration_bounds_status,
            "provenance": list(self.provenance),
            "description": self.description,
            "quantity_role": registry_quantity_definition(self.name).quantity_role,
            "allowed_policy_roles": list(
                registry_quantity_definition(self.name).allowed_policy_roles
            ),
            "selected_policy_role": registry_quantity_definition(
                self.name
            ).selected_policy_role,
        }


CURRENT_PARAMETER_DEFINITIONS: tuple[CurrentParameterDefinition, ...] = (
    CurrentParameterDefinition(
        name="absorptivity",
        units=registry_quantity_definition("absorptivity").units,
        disposition=FIT,
        default_value=None,
        default_policy=EXPLICIT_REQUIRED,
        physical_bounds=ParameterBounds(minimum=0.0, maximum=1.0),
        calibration_bounds=None,
        calibration_bounds_status=CALIBRATION_BOUNDS_UNSELECTED,
        provenance=(
            "PASS_PATCH_16_4_2_REVIEW_ACCEPTED",
            "PASS_PATCH_19_6_PREFIT_MODEL_STRUCTURE_FROZEN",
        ),
        description="Global absorbed-power scale alpha with neutral TED modulation.",
    ),
    CurrentParameterDefinition(
        name="liquid_conductivity_enhancement_factor",
        units=registry_quantity_definition("liquid_conductivity_enhancement_factor").units,
        disposition=FIT,
        default_value=None,
        default_policy=EXPLICIT_REQUIRED,
        physical_bounds=ParameterBounds(minimum=1.0, maximum=None),
        calibration_bounds=None,
        calibration_bounds_status=CALIBRATION_BOUNDS_UNSELECTED,
        provenance=(
            "PASS_PATCH_16_5_2_REVIEW_ACCEPTED",
            "PASS_PATCH_19_6_PREFIT_MODEL_STRUCTURE_FROZEN",
        ),
        description="Scalar liquid-phase conductivity enhancement closure factor.",
    ),
    CurrentParameterDefinition(
        name="eta_directional",
        units=registry_quantity_definition("eta_directional").units,
        disposition=FIT,
        default_value=None,
        default_policy=EXPLICIT_REQUIRED,
        physical_bounds=ParameterBounds(
            minimum=0.0,
            maximum=1.0,
            basis="Patch 18.0 frozen conservative implementation/verification range; not a calibration range",
        ),
        calibration_bounds=None,
        calibration_bounds_status=CALIBRATION_BOUNDS_UNSELECTED,
        provenance=(
            "PASS_PATCH_18_6_DIRECTIONAL_TRANSPORT_RETAINED_AS_CALIBRATION_PARAMETER",
            "PASS_PATCH_19_6_PREFIT_MODEL_STRUCTURE_FROZEN",
        ),
        description="Additive scan-direction liquid transport strength eta_directional.",
    ),
    CurrentParameterDefinition(
        name="deposition_depth_mm",
        units=registry_quantity_definition("deposition_depth_mm").units,
        disposition=FIT,
        default_value=None,
        default_policy=EXPLICIT_REQUIRED,
        physical_bounds=ParameterBounds(
            minimum=0.0,
            maximum=None,
            minimum_inclusive=False,
            maximum_reference="base_params.geometry.Lz_mm",
            basis="accepted normalized truncated-exponential kernel domain contract",
        ),
        calibration_bounds=None,
        calibration_bounds_status=CALIBRATION_BOUNDS_UNSELECTED,
        provenance=(
            "PASS_PATCH_19_4_DEPOSITION_DEPTH_FULL_SENSITIVITY",
            "PASS_PATCH_19_6_PREFIT_MODEL_STRUCTURE_FROZEN",
        ),
        description="Normalized truncated-exponential characteristic deposition depth.",
    ),
    CurrentParameterDefinition(
        name=QUADRATIC_BOILING_PARAMETER_NAME,
        units=registry_quantity_definition(QUADRATIC_BOILING_PARAMETER_NAME).units,
        disposition=FIXED_REGULATOR,
        default_value=0.5,
        default_policy=FIXED_MODEL_STRUCTURE,
        physical_bounds=ParameterBounds(
            minimum=0.5,
            maximum=0.5,
            basis="Patch 19.8.4 geometry-preservation evidence and Patch 19.8.6 fixed-regulator disposition",
        ),
        calibration_bounds=None,
        calibration_bounds_status="NOT_APPLICABLE_FIXED_REGULATOR",
        provenance=(
            "PASS_PATCH_16_5_6_REVIEW_ACCEPTED",
            "PASS_PATCH_19_6_PREFIT_MODEL_STRUCTURE_FROZEN",
            "PASS_PATCH_19_8_4_FIXED_REGULATOR_GEOMETRY_PRESERVED",
            "PASS_PATCH_19_8_5_HIGH_TEMPERATURE_DIAGNOSTIC_DISPOSITION_FROZEN",
            "PASS_PATCH_19_8_6_FIXED_BOILING_REGULATOR_FROZEN",
        ),
        description="Fixed reduced-order quadratic boiling thermal regulator; excluded from calibration.",
    ),
)

_PARAMETER_DEFINITION_BY_NAME = {
    definition.name: definition for definition in CURRENT_PARAMETER_DEFINITIONS
}
if tuple(_PARAMETER_DEFINITION_BY_NAME) != CURRENT_PARAMETER_NAMES:
    raise RuntimeError("current parameter definitions do not match authoritative order")

@dataclass(frozen=True)
class CurrentModelConfiguration:
    """Fixed current-model structure, explicitly outside calibration control."""

    quadratic_boiling_strength: float = 0.5
    quadratic_boiling_loss_law: str = "smoothstep_quadratic"
    deposition_depth_mode: str = EXPONENTIAL_DEPOSITION_DEPTH_MODE
    absorptivity_semantics: str = "global_alpha_times_neutral_m_TED"

    def to_dict(self) -> dict[str, Any]:
        return {
            "quadratic_boiling_strength": float(self.quadratic_boiling_strength),
            "quadratic_boiling_loss_law": self.quadratic_boiling_loss_law,
            "deposition_depth_mode": self.deposition_depth_mode,
            "absorptivity_semantics": self.absorptivity_semantics,
        }


CURRENT_MODEL_CONFIGURATION = CurrentModelConfiguration()
# Read-only compatibility mapping retained for accepted Patch 19.x consumers.
CURRENT_FIXED_CONFIGURATION: Mapping[str, Any] = MappingProxyType(
    CURRENT_MODEL_CONFIGURATION.to_dict()
)


@dataclass(frozen=True)
class CurrentPhysicsParameters:
    """Explicit four-parameter state retained by the Patch 19.6 model freeze.

    Every FIT field is required.  ``deposition_depth_mm=None`` is supported only
    for exact historical regression through the private legacy-control seam;
    the authoritative calibration-facing evaluator requires a finite depth.
    """

    absorptivity: float
    liquid_conductivity_enhancement_factor: float
    eta_directional: float
    deposition_depth_mm: float | None

    @property
    def deposition_depth_mode(self) -> str:
        return (
            LEGACY_DEPOSITION_DEPTH_MODE
            if self.deposition_depth_mm is None
            else EXPONENTIAL_DEPOSITION_DEPTH_MODE
        )

    def to_dict(self) -> dict[str, float | str | None]:
        """Return the compatibility mapping used by Patch 19.7.2 callers."""
        return {
            "absorptivity": float(self.absorptivity),
            "liquid_conductivity_enhancement_factor": float(
                self.liquid_conductivity_enhancement_factor
            ),
            "eta_directional": float(self.eta_directional),
            "deposition_depth_mode": self.deposition_depth_mode,
            "deposition_depth_mm": (
                None
                if self.deposition_depth_mm is None
                else float(self.deposition_depth_mm)
            ),
        }

    def to_serializable_dict(self) -> dict[str, Any]:
        return {
            "schema": CURRENT_PARAMETER_STATE_SCHEMA,
            "schema_version": CURRENT_PARAMETER_STATE_SCHEMA_VERSION,
            "values": self.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CurrentPhysicsParameters":
        """Construct from a four-field or compatibility five-field mapping."""
        if not isinstance(payload, Mapping):
            raise TypeError("parameter payload must be a mapping")
        allowed = set(CURRENT_FIT_PARAMETER_NAMES) | {"deposition_depth_mode"}
        extra = sorted(set(payload) - allowed)
        missing = sorted(set(CURRENT_FIT_PARAMETER_NAMES) - set(payload))
        if extra:
            raise ValueError(f"unknown current parameter field(s): {extra}")
        if missing:
            raise ValueError(f"missing current parameter field(s): {missing}")
        depth = payload["deposition_depth_mm"]
        state = cls(
            absorptivity=float(payload["absorptivity"]),
            liquid_conductivity_enhancement_factor=float(
                payload["liquid_conductivity_enhancement_factor"]
            ),
            eta_directional=float(payload["eta_directional"]),
            deposition_depth_mm=None if depth is None else float(depth),
        )
        if "deposition_depth_mode" in payload:
            supplied_mode = str(payload["deposition_depth_mode"])
            if supplied_mode != state.deposition_depth_mode:
                raise ValueError(
                    "deposition_depth_mode is inconsistent with deposition_depth_mm"
                )
        return state


class CurrentConfigurationError(ValueError):
    """Raised when the authoritative current configuration is invalid."""


def parameter_definition(name: str) -> CurrentParameterDefinition:
    try:
        return _PARAMETER_DEFINITION_BY_NAME[name]
    except KeyError as exc:
        raise KeyError(f"unknown current-model parameter: {name!r}") from exc


def current_parameter_configuration_dict() -> dict[str, Any]:
    """Return the canonical JSON-safe current configuration schema.

    Patch 20.4 makes the quantity registry authoritative for names, units, and
    scientific roles.  Historical ``FIT`` terminology remains only as an
    explicit compatibility projection for accepted Patch 19.x readers.
    """
    registry = current_quantity_registry_dict()
    return {
        "schema": CURRENT_CONFIGURATION_SCHEMA,
        "schema_version": CURRENT_CONFIGURATION_SCHEMA_VERSION,
        "model_structure_status": "PASS_PATCH_19_6_PREFIT_MODEL_STRUCTURE_FROZEN",
        "quantity_registry": registry,
        "parameter_order": list(CURRENT_PARAMETER_NAMES),
        "calibratable_parameter_order": list(CURRENT_CALIBRATABLE_PARAMETER_NAMES),
        "fixed_regulator_parameter_order": [QUADRATIC_BOILING_PARAMETER_NAME],
        "calibratable_policy_role_options": registry["calibratable_policy_roles"],
        "calibratable_policy_role_selection": POLICY_ROLE_UNSELECTED,
        "coupon_specific_parameter_tuning_permitted": False,
        "shared_process_response_required_if_process_conditioned": True,
        "parameters": [definition.to_dict() for definition in CURRENT_PARAMETER_DEFINITIONS],
        "fixed_model_configuration": CURRENT_MODEL_CONFIGURATION.to_dict(),
        "fixed_boiling_regulator_status": "PASS_PATCH_19_8_6_FIXED_BOILING_REGULATOR_FROZEN",
        "optimizer_may_modify_fixed_regulator": False,
        "optimizer_coefficient_contract": {
            "schema_owner": "lpbf.model.parameter_policy",
            "physical_parameter_vector_must_equal_optimizer_vector": False,
            "subset_parameterization_permitted": True,
            "transformed_parameterization_permitted": True,
            "shared_constraint_parameterization_permitted": True,
            "fixed_regulator_excluded": True,
            "coefficient_selection_status": "UNSELECTED_UNTIL_PATCH_21_0",
        },
        "calibration_bounds_selected": False,
        "preferred_calibration_values_selected": False,
        "legacy_patch19_read_compatibility": {
            "fit_parameter_order": list(CURRENT_FIT_PARAMETER_NAMES),
            "optimizer_mutable_parameter_order": list(CURRENT_CALIBRATABLE_PARAMETER_NAMES),
            "fixed_configuration": dict(CURRENT_FIXED_CONFIGURATION),
            "preferred_fit_values_selected": False,
        },
        # Compatibility aliases retained because accepted Patch 19.x readers and
        # regression tests still consume these exact keys.  New code must use the
        # registry and modern fields above.
        "fit_parameter_order": list(CURRENT_FIT_PARAMETER_NAMES),
        "optimizer_mutable_parameter_order": list(CURRENT_CALIBRATABLE_PARAMETER_NAMES),
        "fixed_configuration": dict(CURRENT_FIXED_CONFIGURATION),
        "preferred_fit_values_selected": False,
    }


def _validate_scalar_bound(name: str, value: float, bounds: ParameterBounds) -> None:
    if not math.isfinite(value):
        raise CurrentConfigurationError(f"{name} must be finite")
    if bounds.minimum is not None:
        if bounds.minimum_inclusive:
            valid = value >= bounds.minimum
        else:
            valid = value > bounds.minimum
        if not valid:
            operator = ">=" if bounds.minimum_inclusive else ">"
            raise CurrentConfigurationError(
                f"{name} must satisfy {operator} {bounds.minimum}"
            )
    if bounds.maximum is not None:
        if bounds.maximum_inclusive:
            valid = value <= bounds.maximum
        else:
            valid = value < bounds.maximum
        if not valid:
            operator = "<=" if bounds.maximum_inclusive else "<"
            raise CurrentConfigurationError(
                f"{name} must satisfy {operator} {bounds.maximum}"
            )


def validate_current_physics_parameters(
    base_params: Any,
    physics: CurrentPhysicsParameters,
    *,
    allow_legacy_deposition_control: bool = True,
) -> None:
    """Validate only frozen physical/implementation constraints.

    This function deliberately does not enforce calibration search bounds;
    Patch 19.6 selected none; they remain unselected through Patch 19.8.6.
    """

    for name in CURRENT_FIT_PARAMETER_NAMES[:3]:
        definition = parameter_definition(name)
        _validate_scalar_bound(name, float(getattr(physics, name)), definition.physical_bounds)

    try:
        principal_liquid_conductivities(
            physical_liquid_conductivity_W_mK=float(base_params.material.k_liquid_W_mK),
            isotropic_enhancement_factor=float(
                physics.liquid_conductivity_enhancement_factor
            ),
            eta=float(physics.eta_directional),
        )
    except Exception as exc:
        raise CurrentConfigurationError(str(exc)) from exc

    if physics.deposition_depth_mm is None and not allow_legacy_deposition_control:
        raise CurrentConfigurationError(
            "the authoritative four-parameter current API requires a finite deposition_depth_mm; legacy uniform-depth control is regression-only"
        )

    state = DepositionDepthDesignState(
        mode=physics.deposition_depth_mode,
        legacy_depth_mm=float(base_params.heat_source.depth_mm),
        exponential_characteristic_depth_mm=(
            None
            if physics.deposition_depth_mm is None
            else float(physics.deposition_depth_mm)
        ),
    )
    try:
        state.validate(domain_depth_mm=float(base_params.geometry.Lz_mm))
    except Exception as exc:
        raise CurrentConfigurationError(str(exc)) from exc


def build_current_trial_parameters(
    base_params: Any,
    physics: CurrentPhysicsParameters,
):
    """Apply the centralized current scalar/fixed configuration to a trial."""
    validate_current_physics_parameters(base_params, physics)
    trial_params = replace(
        base_params,
        material=replace(
            base_params.material,
            liquid_conductivity_enhancement_factor=float(
                physics.liquid_conductivity_enhancement_factor
            ),
        ),
        boundary_conditions=replace(
            base_params.boundary_conditions,
            boiling_damper_strength=float(
                CURRENT_MODEL_CONFIGURATION.quadratic_boiling_strength
            ),
            boiling_loss_law=str(
                CURRENT_MODEL_CONFIGURATION.quadratic_boiling_loss_law
            ),
        ),
    )
    trial_params.validate()
    return trial_params


__all__ = [
    "CALIBRATION_BOUNDS_UNSELECTED",
    "CURRENT_CONFIGURATION_SCHEMA",
    "CURRENT_CONFIGURATION_SCHEMA_VERSION",
    "CURRENT_CALIBRATABLE_PARAMETER_NAMES",
    "CURRENT_FIT_PARAMETER_NAMES",
    "CURRENT_FIXED_CONFIGURATION",
    "CURRENT_MODEL_CONFIGURATION",
    "CURRENT_PARAMETER_DEFINITIONS",
    "CURRENT_PARAMETER_NAMES",
    "CURRENT_PARAMETER_STATE_SCHEMA",
    "CURRENT_PARAMETER_STATE_SCHEMA_VERSION",
    "CurrentConfigurationError",
    "CurrentModelConfiguration",
    "CurrentParameterDefinition",
    "CurrentPhysicsParameters",
    "DISABLED",
    "FIXED_REGULATOR",
    "EXPLICIT_REQUIRED",
    "FIT",
    "FIXED_MODEL_STRUCTURE",
    "ParameterBounds",
    "build_current_trial_parameters",
    "current_parameter_configuration_dict",
    "parameter_definition",
    "validate_current_physics_parameters",
]
