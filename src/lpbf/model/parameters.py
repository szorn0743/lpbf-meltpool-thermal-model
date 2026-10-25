"""Supported current LPBF parameter API.

Patch 20.2 routes current execution through the package-native accepted core
while preserving the root Patch 16.6 implementation as immutable provenance.
This module exposes only current parameter dataclasses and the supported default
constructor; historical calibration/provenance declarations are not exported.
"""
from __future__ import annotations

from lpbf.model._accepted_core.parameters import (
    BoundaryConditions,
    Geometry,
    Grid,
    HeatSourceParameters,
    InitialCondition,
    InputControls,
    MaterialProperties,
    MeltPoolComparisonControls,
    MovingWindowControls,
    OutputControls,
    SimulationParameters,
    TimeControls,
    get_params as _frozen_get_params,
)


__all__ = (
    "BoundaryConditions",
    "Geometry",
    "Grid",
    "HeatSourceParameters",
    "InitialCondition",
    "InputControls",
    "MaterialProperties",
    "MeltPoolComparisonControls",
    "MovingWindowControls",
    "OutputControls",
    "SimulationParameters",
    "TimeControls",
    "get_model_parameters",
)


FROZEN_IMPLEMENTATION_MODULE = "lpbf.model._accepted_core.parameters"


def get_model_parameters() -> SimulationParameters:
    """Return the validated current default scientific parameter object.

    The object is deliberately obtained from the frozen Patch 16 implementation
    so type identity, defaults, validation behavior, and numerical semantics are
    unchanged.  The indirection establishes a current supported API without
    copying or editing freeze-protected scientific definitions.
    """
    return _frozen_get_params()
