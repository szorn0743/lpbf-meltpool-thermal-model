"""Authoritative current quantity/role registry.

Patch 20.12 hardens the Patch 20.4 registry into the single authority for
calibration-facing quantity names, units, scientific roles, policy-role
eligibility, and process predictors.  It remains metadata only: no calibration
bounds, priors, fitted values, process-response form, or parameter-role choice
is selected here.

The four retained physical calibration quantities may ultimately be global or
shared process-conditioned quantities.  ``power_W`` and ``speed_mm_s`` are the
only process predictors authorized by the current contract.  Coupon/member
identity is provenance, never a predictor. Coupon-specific parameter tuning is not an allowed role.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping


QUANTITY_REGISTRY_SCHEMA = "lpbf_current_quantity_registry"
QUANTITY_REGISTRY_SCHEMA_VERSION = "20.12.0"

CALIBRATABLE = "calibratable"
FIXED_REGULATOR = "fixed_regulator"
NUMERICAL = "numerical"
DIAGNOSTIC = "diagnostic"
PROCESS_PREDICTOR = "process_predictor"

GLOBAL = "global"
PROCESS_CONDITIONED = "process_conditioned"
POLICY_ROLE_UNSELECTED = "unselected"

ALLOWED_QUANTITY_ROLES = frozenset(
    {CALIBRATABLE, FIXED_REGULATOR, NUMERICAL, DIAGNOSTIC, PROCESS_PREDICTOR}
)
ALLOWED_CALIBRATABLE_POLICY_ROLES = (GLOBAL, PROCESS_CONDITIONED)


@dataclass(frozen=True)
class QuantityDefinition:
    """One authoritative name/unit/role record for a current quantity."""

    name: str
    units: str
    quantity_role: str
    scientific_use: str
    description: str
    allowed_policy_roles: tuple[str, ...] = ()
    selected_policy_role: str | None = None
    provenance: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name or not self.units:
            raise ValueError("quantity name and units must be non-empty")
        if self.quantity_role not in ALLOWED_QUANTITY_ROLES:
            raise ValueError(f"unsupported quantity role: {self.quantity_role!r}")
        if self.quantity_role == CALIBRATABLE:
            if tuple(self.allowed_policy_roles) != ALLOWED_CALIBRATABLE_POLICY_ROLES:
                raise ValueError(
                    "calibratable quantities must permit exactly global and process_conditioned roles"
                )
            if self.selected_policy_role not in (None, POLICY_ROLE_UNSELECTED):
                if self.selected_policy_role not in ALLOWED_CALIBRATABLE_POLICY_ROLES:
                    raise ValueError("unsupported selected calibratable policy role")
        elif self.allowed_policy_roles:
            raise ValueError("non-calibratable quantities may not expose policy roles")
        if self.quantity_role != CALIBRATABLE and self.selected_policy_role is not None:
            raise ValueError("non-calibratable quantities may not select a policy role")

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "units": self.units,
            "quantity_role": self.quantity_role,
            "scientific_use": self.scientific_use,
            "description": self.description,
            "allowed_policy_roles": list(self.allowed_policy_roles),
            "selected_policy_role": self.selected_policy_role,
            "provenance": list(self.provenance),
        }


# Calibration degrees of freedom.  The role choice between global and one shared
# process-conditioned function remains intentionally unselected.
_PARAMETER_QUANTITIES: tuple[QuantityDefinition, ...] = (
    QuantityDefinition(
        name="absorptivity",
        units="dimensionless",
        quantity_role=CALIBRATABLE,
        scientific_use="calibration_parameter",
        description="Absorbed-power scale alpha with neutral TED modulation.",
        allowed_policy_roles=ALLOWED_CALIBRATABLE_POLICY_ROLES,
        selected_policy_role=POLICY_ROLE_UNSELECTED,
        provenance=(
            "PASS_PATCH_16_4_2_REVIEW_ACCEPTED",
            "PASS_PATCH_19_6_PREFIT_MODEL_STRUCTURE_FROZEN",
        ),
    ),
    QuantityDefinition(
        name="liquid_conductivity_enhancement_factor",
        units="dimensionless",
        quantity_role=CALIBRATABLE,
        scientific_use="calibration_parameter",
        description="Scalar liquid-phase conductivity enhancement closure factor.",
        allowed_policy_roles=ALLOWED_CALIBRATABLE_POLICY_ROLES,
        selected_policy_role=POLICY_ROLE_UNSELECTED,
        provenance=(
            "PASS_PATCH_16_5_2_REVIEW_ACCEPTED",
            "PASS_PATCH_19_6_PREFIT_MODEL_STRUCTURE_FROZEN",
        ),
    ),
    QuantityDefinition(
        name="eta_directional",
        units="dimensionless",
        quantity_role=CALIBRATABLE,
        scientific_use="calibration_parameter",
        description="Additive scan-direction liquid transport strength.",
        allowed_policy_roles=ALLOWED_CALIBRATABLE_POLICY_ROLES,
        selected_policy_role=POLICY_ROLE_UNSELECTED,
        provenance=(
            "PASS_PATCH_18_6_DIRECTIONAL_TRANSPORT_RETAINED_AS_CALIBRATION_PARAMETER",
            "PASS_PATCH_19_6_PREFIT_MODEL_STRUCTURE_FROZEN",
        ),
    ),
    QuantityDefinition(
        name="deposition_depth_mm",
        units="mm",
        quantity_role=CALIBRATABLE,
        scientific_use="calibration_parameter",
        description="Normalized truncated-exponential characteristic deposition depth.",
        allowed_policy_roles=ALLOWED_CALIBRATABLE_POLICY_ROLES,
        selected_policy_role=POLICY_ROLE_UNSELECTED,
        provenance=(
            "PASS_PATCH_19_4_DEPOSITION_DEPTH_FULL_SENSITIVITY",
            "PASS_PATCH_19_6_PREFIT_MODEL_STRUCTURE_FROZEN",
        ),
    ),
    QuantityDefinition(
        name="quadratic_boiling_strength",
        units="dimensionless",
        quantity_role=FIXED_REGULATOR,
        scientific_use="fixed_model_structure",
        description="Fixed reduced-order quadratic boiling thermal regulator.",
        provenance=(
            "PASS_PATCH_19_8_4_FIXED_REGULATOR_GEOMETRY_PRESERVED",
            "PASS_PATCH_19_8_6_FIXED_BOILING_REGULATOR_FROZEN",
        ),
    ),
)

# Process covariates that a future shared process-conditioned policy is allowed
# to consume.  Identity fields (coupon/member/set/file) deliberately do not
# appear here and therefore cannot be declared as predictors.
_PROCESS_PREDICTOR_QUANTITIES: tuple[QuantityDefinition, ...] = (
    QuantityDefinition(
        name="power_W",
        units="W",
        quantity_role=PROCESS_PREDICTOR,
        scientific_use="process_policy_predictor",
        description="Nominal laser power supplied by the canonical dataset contract.",
    ),
    QuantityDefinition(
        name="speed_mm_s",
        units="mm/s",
        quantity_role=PROCESS_PREDICTOR,
        scientific_use="process_policy_predictor",
        description="Nominal scan speed supplied by the canonical dataset contract.",
    ),
)

# Current numerical guardrails used by the generic experiment framework.
_NUMERICAL_QUANTITIES: tuple[QuantityDefinition, ...] = (
    QuantityDefinition(
        name="numerical_audit_temperature_max_K",
        units="K",
        quantity_role=NUMERICAL,
        scientific_use="stability_preflight_guardrail",
        description="Frozen maximum temperature used by the boiling stability audit.",
    ),
    QuantityDefinition(
        name="boundary_explicit_fraction_limit",
        units="dimensionless",
        quantity_role=NUMERICAL,
        scientific_use="stability_preflight_guardrail",
        description="Frozen explicit boiling-boundary loss-fraction limit.",
    ),
    QuantityDefinition(
        name="energy_balance_relative_error_limit",
        units="dimensionless",
        quantity_role=NUMERICAL,
        scientific_use="execution_integrity_guardrail",
        description="Maximum accepted absolute relative energy-balance error.",
    ),
)

# Calibration observables and physicality diagnostics used in accepted current
# characterization.  Their scientific_use field distinguishes primary geometry
# observables from secondary physicality diagnostics without inventing a new
# optimization objective.
_DIAGNOSTIC_QUANTITIES: tuple[QuantityDefinition, ...] = (
    QuantityDefinition(
        name="simulated_H_pixels",
        units="pixels",
        quantity_role=DIAGNOSTIC,
        scientific_use="primary_calibration_observable",
        description="Simulated melt-pool height in the accepted comparison metric.",
    ),
    QuantityDefinition(
        name="simulated_W_pixels",
        units="pixels",
        quantity_role=DIAGNOSTIC,
        scientific_use="primary_calibration_observable",
        description="Simulated melt-pool width in the accepted comparison metric.",
    ),
    QuantityDefinition(
        name="simulated_H_over_W",
        units="dimensionless",
        quantity_role=DIAGNOSTIC,
        scientific_use="derived_geometry_diagnostic",
        description="Derived H/W ratio; undefined for accepted zero-footprint states.",
    ),
    QuantityDefinition(
        name="T_peak_surface_K",
        units="K",
        quantity_role=DIAGNOSTIC,
        scientific_use="secondary_physicality_diagnostic",
        description="Raw peak surface temperature diagnostic.",
    ),
    QuantityDefinition(
        name="T_peak_volume_K",
        units="K",
        quantity_role=DIAGNOSTIC,
        scientific_use="secondary_physicality_diagnostic",
        description="Raw peak volume temperature diagnostic.",
    ),
    QuantityDefinition(
        name="cumulative_boiling_loss_energy_J",
        units="J",
        quantity_role=DIAGNOSTIC,
        scientific_use="secondary_physicality_diagnostic",
        description="Cumulative energy removed by the accepted boiling regulator.",
    ),
    QuantityDefinition(
        name="energy_balance_relative_error",
        units="dimensionless",
        quantity_role=DIAGNOSTIC,
        scientific_use="execution_integrity_diagnostic",
        description="Relative energy-balance closure diagnostic.",
    ),
)

CURRENT_QUANTITY_DEFINITIONS = (
    _PARAMETER_QUANTITIES
    + _PROCESS_PREDICTOR_QUANTITIES
    + _NUMERICAL_QUANTITIES
    + _DIAGNOSTIC_QUANTITIES
)
_QUANTITY_BY_NAME = {entry.name: entry for entry in CURRENT_QUANTITY_DEFINITIONS}
if len(_QUANTITY_BY_NAME) != len(CURRENT_QUANTITY_DEFINITIONS):
    raise RuntimeError("current quantity registry contains duplicate names")

CURRENT_CALIBRATABLE_PARAMETER_NAMES = tuple(
    entry.name for entry in _PARAMETER_QUANTITIES if entry.quantity_role == CALIBRATABLE
)
CURRENT_FIXED_REGULATOR_PARAMETER_NAMES = tuple(
    entry.name for entry in _PARAMETER_QUANTITIES if entry.quantity_role == FIXED_REGULATOR
)
CURRENT_PROCESS_PREDICTOR_NAMES = tuple(
    entry.name for entry in _PROCESS_PREDICTOR_QUANTITIES
)
CURRENT_NUMERICAL_QUANTITY_NAMES = tuple(entry.name for entry in _NUMERICAL_QUANTITIES)
CURRENT_DIAGNOSTIC_QUANTITY_NAMES = tuple(entry.name for entry in _DIAGNOSTIC_QUANTITIES)
CURRENT_PARAMETER_UNITS: Mapping[str, str] = MappingProxyType(
    {entry.name: entry.units for entry in _PARAMETER_QUANTITIES}
)
CURRENT_PROCESS_PREDICTOR_UNITS: Mapping[str, str] = MappingProxyType(
    {entry.name: entry.units for entry in _PROCESS_PREDICTOR_QUANTITIES}
)


def quantity_definition(name: str) -> QuantityDefinition:
    try:
        return _QUANTITY_BY_NAME[str(name)]
    except KeyError as exc:
        raise KeyError(f"unknown current quantity: {name!r}") from exc


def require_quantity_role(name: str, role: str) -> QuantityDefinition:
    """Return a registry entry only when its scientific role matches exactly."""

    definition = quantity_definition(name)
    if definition.quantity_role != role:
        raise ValueError(
            f"quantity {name!r} has role {definition.quantity_role!r}, expected {role!r}"
        )
    return definition


def current_quantity_registry_dict() -> dict[str, Any]:
    """Return the authoritative JSON-safe Patch 20.12 registry."""

    return {
        "schema": QUANTITY_REGISTRY_SCHEMA,
        "schema_version": QUANTITY_REGISTRY_SCHEMA_VERSION,
        "quantity_roles": [
            CALIBRATABLE,
            FIXED_REGULATOR,
            PROCESS_PREDICTOR,
            NUMERICAL,
            DIAGNOSTIC,
        ],
        "calibratable_policy_roles": list(ALLOWED_CALIBRATABLE_POLICY_ROLES),
        "calibratable_policy_role_selection": POLICY_ROLE_UNSELECTED,
        "coupon_specific_parameter_tuning_permitted": False,
        "member_identity_as_policy_predictor_permitted": False,
        "shared_process_response_required_if_process_conditioned": True,
        "calibratable_parameter_order": list(CURRENT_CALIBRATABLE_PARAMETER_NAMES),
        "fixed_regulator_parameter_order": list(CURRENT_FIXED_REGULATOR_PARAMETER_NAMES),
        "process_predictor_order": list(CURRENT_PROCESS_PREDICTOR_NAMES),
        "numerical_quantity_names": list(CURRENT_NUMERICAL_QUANTITY_NAMES),
        "diagnostic_quantity_names": list(CURRENT_DIAGNOSTIC_QUANTITY_NAMES),
        "quantities": [entry.to_dict() for entry in CURRENT_QUANTITY_DEFINITIONS],
    }


__all__ = [
    "ALLOWED_CALIBRATABLE_POLICY_ROLES",
    "ALLOWED_QUANTITY_ROLES",
    "CALIBRATABLE",
    "CURRENT_CALIBRATABLE_PARAMETER_NAMES",
    "CURRENT_DIAGNOSTIC_QUANTITY_NAMES",
    "CURRENT_FIXED_REGULATOR_PARAMETER_NAMES",
    "CURRENT_NUMERICAL_QUANTITY_NAMES",
    "CURRENT_PARAMETER_UNITS",
    "CURRENT_PROCESS_PREDICTOR_NAMES",
    "CURRENT_PROCESS_PREDICTOR_UNITS",
    "CURRENT_QUANTITY_DEFINITIONS",
    "DIAGNOSTIC",
    "FIXED_REGULATOR",
    "GLOBAL",
    "NUMERICAL",
    "POLICY_ROLE_UNSELECTED",
    "PROCESS_CONDITIONED",
    "PROCESS_PREDICTOR",
    "QUANTITY_REGISTRY_SCHEMA",
    "QUANTITY_REGISTRY_SCHEMA_VERSION",
    "QuantityDefinition",
    "current_quantity_registry_dict",
    "quantity_definition",
    "require_quantity_role",
]
