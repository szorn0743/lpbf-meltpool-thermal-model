"""Shared non-scientific infrastructure utilities: filesystem, serialization, hashing, timestamps, CSV.

The module is intentionally small and dependency-light so experiment/scientific modules do
not need to import one another for generic infrastructure.
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any, Mapping, Sequence


def utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string at second precision."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def git_metadata(root: Path | str) -> dict[str, Any]:
    """Commit and worktree state of a git checkout, or ``None`` values when git or ``.git`` is unavailable.

    Git is an additional verification aid only: nothing in the package requires it, and a source ZIP without a
    ``.git`` directory records ``{"commit": None, "worktree_dirty": None}``.
    """

    def run(*args: str) -> str | None:
        try:
            return subprocess.run(["git", *args], capture_output=True, text=True, check=True, cwd=str(root)).stdout
        except (OSError, subprocess.CalledProcessError):
            return None

    commit = run("rev-parse", "HEAD")
    if commit is None:
        return {"commit": None, "worktree_dirty": None}
    status = run("status", "--porcelain", "--untracked-files=no")
    return {"commit": commit.strip(), "worktree_dirty": None if status is None else bool(status.strip())}


def validated_workers(workers: Any, error_type: type[Exception] = ValueError) -> int:
    """A worker count must be a positive integer (``True`` is not one)."""
    if isinstance(workers, bool) or not isinstance(workers, int) or workers < 1:
        raise error_type(f"workers must be a positive integer, got {workers!r}")
    return workers


def sha256_file(path: Path | str, block_bytes: int = 1 << 20) -> str:
    """Return the SHA-256 hex digest of a file without loading it all at once."""
    resolved = Path(path)
    digest = hashlib.sha256()
    with resolved.open("rb") as handle:
        for chunk in iter(lambda: handle.read(block_bytes), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_bytes(value: Any, *, allow_nan: bool = False) -> bytes:
    """Return deterministic canonical JSON bytes for a JSON-compatible value."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=allow_nan,
    ).encode("utf-8")


def canonical_sha256(value: Any, *, allow_nan: bool = False) -> str:
    """Hash a JSON-compatible value using the shared canonical JSON form."""
    return hashlib.sha256(canonical_json_bytes(value, allow_nan=allow_nan)).hexdigest()


def read_json(path: Path | str) -> Any:
    """Read and decode one UTF-8 JSON file without imposing root-shape policy."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: Path | str, value: Mapping[str, Any]) -> None:
    """Write deterministic, human-readable UTF-8 JSON with a final newline."""
    resolved = Path(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )




def write_json_atomic(
    path: Path | str,
    value: Mapping[str, Any],
    *,
    allow_nan: bool = True,
) -> None:
    """Write readable JSON through a sibling ``.tmp`` file then replace atomically."""
    resolved = Path(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    tmp = resolved.with_suffix(resolved.suffix + ".tmp")
    tmp.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=allow_nan) + "\n",
        encoding="utf-8",
    )
    tmp.replace(resolved)


def flatten_csv_value(value: Any) -> Any:
    """Serialize structured cell values using the existing deterministic JSON form."""
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, sort_keys=True, allow_nan=False)
    return value


def write_csv_rows(path: Path | str, rows: Sequence[Mapping[str, Any]]) -> None:
    """Write mapping rows using first-seen field order and flattened values."""
    resolved = Path(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with resolved.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: flatten_csv_value(row.get(key)) for key in fields})
