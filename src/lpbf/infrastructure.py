"""Shared non-scientific infrastructure utilities for current LPBF workflows.

Patch 17.2 centralizes behaviorally equivalent filesystem, serialization,
hashing, timestamp, CSV, and scalar-normalization helpers here.  The module is
intentionally small and dependency-light so experiment/scientific modules do
not need to import one another for generic infrastructure.
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence, TypeVar
from uuid import uuid4


_JSON_OBJECT_ERROR = TypeVar("_JSON_OBJECT_ERROR", bound=Exception)


def utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string at second precision."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def utc_now_iso_microseconds() -> str:
    """Return current UTC time in the legacy microsecond-precision ISO form."""
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


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


def read_json_object(
    path: Path | str,
    *,
    error_type: type[_JSON_OBJECT_ERROR] = ValueError,
) -> dict[str, Any]:
    """Read a UTF-8 JSON file and require a top-level object.

    ``error_type`` lets patch modules preserve their existing domain-specific
    exception type without duplicating the JSON loading/shape check itself.
    """
    resolved = Path(path)
    value = read_json(resolved)
    if not isinstance(value, dict):
        raise error_type(f"Expected JSON object: {resolved}")
    return value


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


def write_json_exclusive(
    path: Path | str,
    value: Mapping[str, Any],
    *,
    allow_nan: bool = False,
    create_parent: bool = False,
    fsync: bool = False,
) -> None:
    """Create a deterministic JSON file without overwriting an existing path."""
    resolved = Path(path)
    if create_parent:
        resolved.parent.mkdir(parents=True, exist_ok=True)
    with resolved.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=allow_nan)
        handle.write("\n")
        if fsync:
            handle.flush()
            os.fsync(handle.fileno())


def write_json_atomic_unique(
    path: Path | str,
    value: Mapping[str, Any],
    *,
    allow_nan: bool = False,
    fsync: bool = False,
) -> None:
    """Atomically replace JSON using an exclusive, unique sibling temporary file."""
    resolved = Path(path)
    temporary = resolved.with_name(f".{resolved.name}.{uuid4().hex[:12]}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True, allow_nan=allow_nan)
            handle.write("\n")
            if fsync:
                handle.flush()
                os.fsync(handle.fileno())
        os.replace(temporary, resolved)
    finally:
        if temporary.exists():
            temporary.unlink()


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


def write_csv_exclusive(
    path: Path | str,
    *,
    fieldnames: Sequence[str],
    rows: Iterable[Mapping[str, Any]],
    create_parent: bool = False,
    fsync: bool = False,
) -> None:
    """Create a CSV file without overwrite using explicit field order.

    This preserves the create-only reporting semantics used by current LPBF
    experiment outputs while allowing each workflow to choose durability.
    """
    resolved = Path(path)
    if create_parent:
        resolved.parent.mkdir(parents=True, exist_ok=True)
    with resolved.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames), extrasaction="raise")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
        if fsync:
            handle.flush()
            os.fsync(handle.fileno())


def finite_float(value: Any) -> float | None:
    """Convert a value to finite ``float`` or return ``None``."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None
