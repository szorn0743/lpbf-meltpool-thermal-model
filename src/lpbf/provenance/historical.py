"""Immutable historical-provenance compatibility records used by current output metadata.

Patch 17.4 separates historical checkpoint evidence from executable runtime
configuration.  The records loaded here are descriptive provenance compatibility projections;
they are not consulted to select model parameters, solver behavior, process
timing, observation semantics, or calibration values.
"""

from __future__ import annotations

import json
from pathlib import Path

from lpbf.paths import repository_path
from typing import Any, Mapping

from lpbf.infrastructure import canonical_sha256, read_json


HISTORICAL_REPRODUCIBILITY_SCHEMA = "lpbf_historical_reproducibility_records"
HISTORICAL_REPRODUCIBILITY_SCHEMA_VERSION = "17.4A"
HISTORICAL_REPRODUCIBILITY_PATH = (
    repository_path("provenance", "historical_reproducibility_records.json")
)

_REQUIRED_RECORD_KEYS = frozenset(
    {
        "validated_configuration_reference",
        "current_validation_state",
        "release_gate_assessment",
        "patch_11_0_0_authoritative_starting_state",
        "patch_11_0_1_ted_problem_statement",
        "patch_11_0_2_source_calibration_hard_stop",
        "patch_12_0_0_authoritative_starting_state",
        "patch_12_0_1_provisional_ted_decision",
        "patch_12_0_2_provisional_ted_gate",
    }
)


class HistoricalProvenanceError(ValueError):
    """Raised when an immutable historical-provenance snapshot is malformed."""


def load_historical_reproducibility_records(
    path: str | Path | None = None,
    *,
    verify_integrity: bool = True,
) -> dict[str, Any]:
    """Load detached legacy provenance used only for reproducibility metadata.

    No historical report tree is traversed.  Integrity is checked against the
    canonical hash embedded in the snapshot itself.
    """
    source = HISTORICAL_REPRODUCIBILITY_PATH if path is None else Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"historical reproducibility snapshot not found: {source}")

    try:
        payload = read_json(source)
    except json.JSONDecodeError as exc:
        raise HistoricalProvenanceError(
            f"invalid JSON in historical reproducibility snapshot {source}: {exc.msg}"
        ) from exc
    if not isinstance(payload, Mapping):
        raise HistoricalProvenanceError("historical provenance root must be a JSON object")
    if payload.get("schema") != HISTORICAL_REPRODUCIBILITY_SCHEMA:
        raise HistoricalProvenanceError(
            f"unexpected historical provenance schema: {payload.get('schema')!r}"
        )
    if payload.get("schema_version") != HISTORICAL_REPRODUCIBILITY_SCHEMA_VERSION:
        raise HistoricalProvenanceError(
            "unexpected historical provenance schema_version: "
            f"{payload.get('schema_version')!r}"
        )

    records = payload.get("records")
    if not isinstance(records, Mapping):
        raise HistoricalProvenanceError("historical provenance records must be a JSON object")
    missing = sorted(_REQUIRED_RECORD_KEYS - set(records))
    unexpected = sorted(set(records) - _REQUIRED_RECORD_KEYS)
    if missing or unexpected:
        raise HistoricalProvenanceError(
            "historical provenance record-key mismatch; "
            f"missing={missing}, unexpected={unexpected}"
        )

    integrity = payload.get("integrity")
    if not isinstance(integrity, Mapping):
        raise HistoricalProvenanceError("historical provenance integrity must be a JSON object")
    expected = str(integrity.get("records_canonical_sha256", ""))
    if len(expected) != 64:
        raise HistoricalProvenanceError(
            "historical provenance records_canonical_sha256 must be a 64-character digest"
        )
    try:
        int(expected, 16)
    except ValueError as exc:
        raise HistoricalProvenanceError(
            "historical provenance records_canonical_sha256 must be hexadecimal"
        ) from exc

    if verify_integrity:
        actual = canonical_sha256(records, allow_nan=True)
        if actual != expected:
            raise HistoricalProvenanceError(
                "historical reproducibility snapshot failed its canonical SHA-256 integrity check"
            )

    # JSON round-trip guarantees callers cannot mutate shared module state.
    return json.loads(json.dumps(records))
