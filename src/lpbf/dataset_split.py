"""The frozen data roles of the thesis (``data/dataset_split.json``).

The four roles (calibration; held out, in window; out of window, examined; out of window, blind) are stored
explicitly so that the analysis split cannot change silently. ``derive_member_roles`` recomputes them from the
calibration/held-out partition of the calibration contract and the energy-density window; the test suite asserts
that the derivation equals the stored file.
"""
from __future__ import annotations

from importlib.resources import files
import json
from typing import Any

from lpbf.calibration_contract import load_patch21_0_contract, member_identity

SPLIT_RESOURCE = "dataset_split.json"


def load_dataset_split() -> dict[str, Any]:
    payload = json.loads(files("lpbf.data").joinpath(SPLIT_RESOURCE).read_text(encoding="utf-8"))
    if payload.get("schema") != "lpbf_dataset_split":
        raise ValueError("dataset split schema drifted")
    return payload


_SPLIT = load_dataset_split()
_ROLES = _SPLIT["roles"]

HATCH_MM: float = float(_SPLIT["energy_density"]["hatch_mm"])
LAYER_MM: float = float(_SPLIT["energy_density"]["layer_mm"])
VED_WINDOW_J_MM3: tuple[float, float] = tuple(float(v) for v in _SPLIT["energy_density"]["calibration_window_J_mm3"])  # type: ignore[assignment]
CALIBRATION_MEMBERS: tuple[str, ...] = tuple(_ROLES["calibration"])
CALIBRATION_CONDITIONS: tuple[str, ...] = tuple(_SPLIT["calibration_conditions"])
IN_WINDOW_HELD_OUT: tuple[str, ...] = tuple(_ROLES["in_window_held_out"])
OUT_OF_WINDOW_EXAMINED: tuple[str, ...] = tuple(_ROLES["out_of_window_examined"])
OUT_OF_WINDOW_BLIND: tuple[str, ...] = tuple(_ROLES["out_of_window_blind"])
OUT_OF_WINDOW: tuple[str, ...] = OUT_OF_WINDOW_EXAMINED + OUT_OF_WINDOW_BLIND
EVALUATION_MEMBERS: tuple[str, ...] = IN_WINDOW_HELD_OUT + OUT_OF_WINDOW
CROSS_CAMPAIGN_HELD_OUT: str = str(_SPLIT["cross_campaign_held_out"])


def ved_j_mm3(power_W: float, speed_mm_s: float) -> float:
    return float(power_W) / (float(speed_mm_s) * HATCH_MM * LAYER_MM)


def member_records() -> dict[str, dict[str, Any]]:
    """Process conditions of all 24 members from the calibration contract (cross-checked with the process record by tests)."""

    partition = load_patch21_0_contract()["data_partition"]
    out: dict[str, dict[str, Any]] = {}
    for role, key in (("calibration", "calibration_members"), ("held_out", "validation_members")):
        for item in partition[key]:
            identity = member_identity(item["acquisition_set_id"], item["part_number"])
            out[identity] = {
                "member_identity": identity,
                "acquisition_set_id": str(item["acquisition_set_id"]),
                "condition_id": str(item["condition_id"]),
                "power_W": float(item["power_W"]),
                "speed_mm_s": float(item["speed_mm_s"]),
                "ved_J_mm3": ved_j_mm3(item["power_W"], item["speed_mm_s"]),
                "a8_role": role,
            }
    return dict(sorted(out.items()))


def derive_member_roles() -> dict[str, tuple[str, ...]]:
    """The four roles recomputed from the calibration/held-out partition and the energy-density window."""

    low, high = VED_WINDOW_J_MM3
    roles: dict[str, list[str]] = {"calibration": [], "in_window_held_out": [], "out_of_window_examined": [], "out_of_window_blind": []}
    for identity, record in member_records().items():
        inside = low <= record["ved_J_mm3"] <= high
        if record["a8_role"] == "calibration":
            roles["calibration" if inside else "out_of_window_examined"].append(identity)
        else:
            roles["in_window_held_out" if inside else "out_of_window_blind"].append(identity)
    return {name: tuple(sorted(values)) for name, values in roles.items()}


def stored_member_roles() -> dict[str, tuple[str, ...]]:
    return {name: tuple(sorted(values)) for name, values in _ROLES.items()}


__all__ = [
    "CALIBRATION_CONDITIONS",
    "CALIBRATION_MEMBERS",
    "CROSS_CAMPAIGN_HELD_OUT",
    "EVALUATION_MEMBERS",
    "HATCH_MM",
    "IN_WINDOW_HELD_OUT",
    "LAYER_MM",
    "OUT_OF_WINDOW",
    "OUT_OF_WINDOW_BLIND",
    "OUT_OF_WINDOW_EXAMINED",
    "VED_WINDOW_J_MM3",
    "derive_member_roles",
    "load_dataset_split",
    "member_records",
    "stored_member_roles",
    "ved_j_mm3",
]
