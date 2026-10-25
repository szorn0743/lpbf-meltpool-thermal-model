"""Supported LPBF melt-pool comparison adapter.

Patch 22.3.5 keeps the exact-source-frozen thermal/numerical comparison core
unchanged while promoting laser-associated-component H/W at the supported
in-memory observation boundary.  Historical accepted-core entry points remain
available only behind the private ``_accepted_core`` package.
"""
from __future__ import annotations

from lpbf.model._accepted_core.comparison import (
    AbsorbedPowerTreatment,
    UnenclosedLiquidusContourError,
    compute_top_surface_min_area_rect_hw_pixels,
    preload_layer_melt_pool_comparison,
    prepare_in_memory_calibration_trial_workspace,
)
from lpbf.model.production_hw import (
    LaserAssociatedHWEvaluationError,
    PRODUCTION_HW_DEFINITION,
    PRODUCTION_HW_SEMANTICS_VERSION,
    run_in_memory_layer_melt_pool_comparison,
    run_layer_melt_pool_comparison,
)

__all__ = [
    "AbsorbedPowerTreatment",
    "LaserAssociatedHWEvaluationError",
    "PRODUCTION_HW_DEFINITION",
    "PRODUCTION_HW_SEMANTICS_VERSION",
    "UnenclosedLiquidusContourError",
    "compute_top_surface_min_area_rect_hw_pixels",
    "preload_layer_melt_pool_comparison",
    "prepare_in_memory_calibration_trial_workspace",
    "run_in_memory_layer_melt_pool_comparison",
    "run_layer_melt_pool_comparison",
]
