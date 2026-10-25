"""Shared errors for the supported current-experiment execution surface."""
from __future__ import annotations


class CurrentExperimentFrameworkError(RuntimeError):
    """Fail-closed error for generic current experiment execution mechanics."""


__all__ = ["CurrentExperimentFrameworkError"]
