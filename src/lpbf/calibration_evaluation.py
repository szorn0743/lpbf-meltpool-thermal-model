"""Public atomic calibration-evaluation boundary.

Calibration-facing code may import from this compatibility module. The
supported current execution surface is now centralized in
``lpbf.execution.api``; this module remains a stable import path for accepted
callers. It adds no calibration policy, objective, bounds, or optimizer
behavior.
"""
from __future__ import annotations

from lpbf.execution.api import (
    CALIBRATION_TRIAL_EVALUATION_SCHEMA,
    CALIBRATION_TRIAL_EVALUATION_SCHEMA_VERSION,
    FROZEN_CALIBRATION_WINDOW_CELLS,
    LEGACY_PATCH_22_2_PRODUCTION_WINDOW_CELLS,
    PRODUCTION_CALIBRATION_WINDOW_CELLS,
    CalibrationExecutionScope,
    CalibrationTrialEvaluation,
    evaluate_calibration_trial,
)

__all__ = [
    "CALIBRATION_TRIAL_EVALUATION_SCHEMA",
    "CALIBRATION_TRIAL_EVALUATION_SCHEMA_VERSION",
    "FROZEN_CALIBRATION_WINDOW_CELLS",
    "LEGACY_PATCH_22_2_PRODUCTION_WINDOW_CELLS",
    "PRODUCTION_CALIBRATION_WINDOW_CELLS",
    "CalibrationExecutionScope",
    "CalibrationTrialEvaluation",
    "evaluate_calibration_trial",
]
