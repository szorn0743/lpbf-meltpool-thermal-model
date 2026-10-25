"""Explicit execution interfaces for in-memory LPBF numerical orchestration.

Patch 20.11 replaces process-global function substitution and code-object cloning
with per-call dependency injection.  The accepted numerical implementations remain
the defaults; callers may supply narrowly scoped callables for current-model
orchestration and passive diagnostics without mutating module state.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping


HeatSourceCallable = Callable[..., tuple[Any, Any]]
ThermalStepCallable = Callable[..., Any]
TemperatureTraceCallback = Callable[[Any, float], None]
ObservationCaptureCallback = Callable[[Mapping[str, Any]], None]
MovingWindowUpdateCallback = Callable[[Mapping[str, Any]], None]


@dataclass(frozen=True)
class InMemoryExecutionInterfaces:
    """Per-call numerical and diagnostic interfaces for one in-memory run.

    ``None`` means "use the accepted-core default" for that seam.  Instances
    contain no shared mutable state and are safe to create independently for
    reordered, threaded, or process-isolated evaluations.
    """

    heat_source_for_row: HeatSourceCallable | None = None
    thermal_step_numba: ThermalStepCallable | None = None
    thermal_step_numpy: ThermalStepCallable | None = None
    temperature_trace_callback: TemperatureTraceCallback | None = None
    observation_capture_callback: ObservationCaptureCallback | None = None
    moving_window_update_callback: MovingWindowUpdateCallback | None = None


__all__ = [
    "HeatSourceCallable",
    "InMemoryExecutionInterfaces",
    "ObservationCaptureCallback",
    "MovingWindowUpdateCallback",
    "TemperatureTraceCallback",
    "ThermalStepCallable",
]
