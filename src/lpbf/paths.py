"""Repository-relative path helpers for the source-checkout LPBF application.

The current codebase is still distributed with scientific reference artifacts
outside ``src/lpbf``.  Centralizing this resolution removes dependence on the
process working directory while keeping those immutable artifacts in place.
"""
from __future__ import annotations

import os
from pathlib import Path


def repository_root() -> Path:
    """Return the LPBF repository/checkpoint root without using the CWD."""
    override = os.environ.get("LPBF_REPOSITORY_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    return Path(__file__).resolve().parents[2]


def repository_path(*parts: str) -> Path:
    """Return a path beneath the repository/checkpoint root."""
    return repository_root().joinpath(*parts)


__all__ = ["repository_root", "repository_path"]
