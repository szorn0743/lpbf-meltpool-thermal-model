"""Frame records: the per-frame rows that join the camera observations of a coupon with one model trial.

* ``find_frame_file`` / ``portable_frame_rows`` locate and read a coupon's ``frame_observations.csv`` from the
  characterization directory, keeping only synchronized laser-on frames and classifying each experimental
  observation (``ELIGIBLE_FINITE_HW``, ``ELIGIBLE_ZERO_FOOTPRINT``, ``INVALID_*``, ``INELIGIBLE_NOT_OBJECTIVE``).
* ``dataset_member_context`` / ``dataset_member_from_context`` carry a ``DatasetMember`` through a worker process.
* ``frame_records_from_evaluation`` converts a completed trial of ``evaluate_calibration_trial`` into frame records
  with status ``PASS``, ``UNDEFINED`` (the model formed no prediction; never fabricated as zero), ``EXCLUDED`` (the
  scored-frame rule) or ``FAIL`` (an infrastructure failure listed by ``trial_gate_failures``).
* ``annotate_frame_records`` attaches the production-association telemetry of each observation.

``evaluate_calibration_trial`` is re-exported here and called through this module so that the field-capture
instrumentation can wrap it.

The failure codes (``PATCH_22_4_3_TRIAL_GATE_FAILURE`` ...) are recorded in the unit files of the thesis run and are
kept verbatim.
"""
from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from lpbf.calibration_contract import condition_id, member_identity
from lpbf.experiments.current_framework import evaluate_calibration_trial  # noqa: F401  (patch seam, re-exported)
from lpbf.experiments.dataset import DatasetMember
from lpbf.model.laser_component_association import POLICY_VERSION as PRODUCTION_HW_ASSOCIATION_POLICY_VERSION
from lpbf.model.production_hw import PRODUCTION_HW_DEFINITION, PRODUCTION_HW_SEMANTICS_VERSION

# A trial completes with undefined frames; they carry a reason and are excluded from residuals with coverage
# reported. "reject" is the historical all-or-nothing behavior and remains the default for old callers.
UNDEFINED_OBSERVATION_POLICY = "record_undefined"


class FrameRecordError(RuntimeError):
    """Raised when a coupon's frame table cannot be bound to its dataset member."""


def _json_safe(value: Any) -> Any:
    """Return finite JSON-compatible diagnostics without fabricating scientific values."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    # NumPy scalar-like values are normalized through float/int where possible.
    try:
        if hasattr(value, "item"):
            return _json_safe(value.item())
    except Exception:
        pass
    return str(value)


def _parse_bool(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes"}


def _optional_float(value: Any) -> float | None:
    if value in (None, "", "None"):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return number


def _csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, float):
        return repr(value)
    return value


def _find_frame_file(source: Path, member: DatasetMember) -> Path:
    expected_set = str(member.acquisition_set_id)
    expected_part = int(member.coupon_position)
    expected_portable_identity = member.portable_identity_text
    direct_names = (
        f"{expected_set}_part_{expected_part}_{member.layer_name}",
        f"{expected_set}_part_{expected_part}",
    )
    candidates = {
        root / "members" / name / "frame_observations.csv"
        for root in (source, source / "patch21_3_0_characterization")
        for name in direct_names
        if (root / "members" / name / "frame_observations.csv").is_file()
    }
    candidates.update(source.rglob("frame_observations.csv"))
    matching_member: list[Path] = []
    matching_portable_identity: list[Path] = []
    for path in sorted(candidates):
        try:
            with path.open("r", encoding="utf-8", newline="") as handle:
                row = next(csv.DictReader(handle), None)
            if not row:
                continue
            if (
                str(row.get("acquisition_set_id")) == expected_set
                and int(float(row.get("part_number"))) == expected_part
            ):
                matching_member.append(path)
                if str(row.get("portable_member_identity")) == expected_portable_identity:
                    matching_portable_identity.append(path)
        except (OSError, StopIteration, TypeError, ValueError, csv.Error):
            continue
    if len(matching_portable_identity) == 1:
        return matching_portable_identity[0]
    if len(matching_portable_identity) > 1:
        raise FrameRecordError(
            "ambiguous portable frame characterization files for "
            f"{expected_set}:part_{expected_part}: "
            + ", ".join(str(path) for path in matching_portable_identity)
        )
    if matching_member:
        raise FrameRecordError(
            "portable frame characterization identity mismatch for "
            f"{expected_set}:part_{expected_part}; expected {expected_portable_identity}"
        )
    raise FrameRecordError(
        f"portable frame_observations.csv is missing for {expected_set}:part_{expected_part}"
    )


def _portable_frame_rows(path: Path, member: DatasetMember) -> list[dict[str, Any]]:
    required = {
        "acquisition_set_id",
        "part_number",
        "portable_member_identity",
        "frame_index",
        "mapping_status",
        "laser_on",
        "scan_track_id",
        "H_pixels",
        "W_pixels",
        "hw_status",
        "eligible_melt_pool_observation",
    }
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = set(reader.fieldnames or ())
        missing = required - columns
        if missing:
            raise FrameRecordError(
                f"frame table {path} is missing columns: {sorted(missing)}"
            )
        output: list[dict[str, Any]] = []
        canonical = member_identity(member.acquisition_set_id, member.coupon_position)
        for raw in reader:
            observed_identity = str(raw.get("portable_member_identity") or "").strip()
            if observed_identity != member.portable_identity_text:
                raise FrameRecordError(
                    f"frame row portable_member_identity mismatch in {path}: "
                    f"{observed_identity!r} != {member.portable_identity_text!r}"
                )
            try:
                observed_set = str(raw.get("acquisition_set_id"))
                observed_part = int(float(raw.get("part_number")))
            except (TypeError, ValueError) as exc:
                raise FrameRecordError(
                    f"frame row has malformed coupon identity in {path}"
                ) from exc
            if observed_set != str(member.acquisition_set_id) or observed_part != int(
                member.coupon_position
            ):
                raise FrameRecordError(
                    f"frame row coupon identity mismatch in {path}: "
                    f"{observed_set}:part_{observed_part} != "
                    f"{member.acquisition_set_id}:part_{member.coupon_position}"
                )
            if str(raw.get("mapping_status")) != "valid_mapped" or not _parse_bool(
                raw.get("laser_on")
            ):
                continue
            hw_status = str(raw.get("hw_status") or "")
            eligible = _parse_bool(raw.get("eligible_melt_pool_observation"))
            h = _optional_float(raw.get("H_pixels"))
            w = _optional_float(raw.get("W_pixels"))
            if eligible:
                observation_status = (
                    "ELIGIBLE_ZERO_FOOTPRINT"
                    if hw_status == "zero_footprint" or h == 0.0 or w == 0.0
                    else "ELIGIBLE_FINITE_HW"
                )
            elif hw_status == "nonfinite":
                observation_status = "INVALID_NONFINITE_HW"
            elif hw_status == "negative":
                observation_status = "INVALID_NEGATIVE_HW"
            else:
                observation_status = "INELIGIBLE_NOT_OBJECTIVE"
            output.append(
                {
                    "member_identity": canonical,
                    "portable_member_identity": str(raw["portable_member_identity"]),
                    "acquisition_set_id": str(raw["acquisition_set_id"]),
                    "part_number": int(float(raw["part_number"])),
                    "power_W": float(member.power_W),
                    "speed_mm_s": float(member.nominal_speed_mm_s),
                    "spot_diameter_mm": float(member.spot_diameter_mm),
                    "source_date": member.source_date,
                    "process_condition_provenance": dict(
                        member.process_condition_provenance
                    ),
                    "exact_condition_id": condition_id(
                        member.power_W, member.nominal_speed_mm_s
                    ),
                    "scan_track_id": str(raw["scan_track_id"]),
                    "frame_index": int(float(raw["frame_index"])),
                    "experimental_H_pixels": h,
                    "experimental_W_pixels": w,
                    "observation_eligible": bool(eligible),
                    "observation_status": observation_status,
                    "source_observation_status": hw_status,
                    "status": "PASS",
                    "failure": None,
                }
            )
    if not output:
        raise FrameRecordError(f"no mapped laser-on frame rows found in {path}")
    return output


def _dataset_member_context(member: DatasetMember) -> dict[str, Any]:
    return {
        "set_id": int(member.set_id),
        "dataset_member_id": int(member.dataset_member_id),
        "coupon_position": int(member.coupon_position),
        "path": str(Path(member.path).resolve()),
        "sha256": str(member.sha256),
        "power_W": float(member.power_W),
        "nominal_speed_mm_s": float(member.nominal_speed_mm_s),
        "spot_diameter_mm": float(member.spot_diameter_mm),
        "campaign_id": str(member.campaign_id),
        "acquisition_set_id": str(member.acquisition_set_id),
        "layer_name": str(member.layer_name),
        "expected_filename": member.expected_filename,
        "portable_member_identity": member.portable_identity_text,
        "source_date": member.source_date,
        "process_condition_provenance": dict(member.process_condition_provenance),
    }


def _dataset_member_from_context(value: Mapping[str, Any]) -> DatasetMember:
    return DatasetMember(
        set_id=int(value["set_id"]),
        dataset_member_id=int(value["dataset_member_id"]),
        coupon_position=int(value["coupon_position"]),
        path=Path(str(value["path"])),
        sha256=str(value["sha256"]),
        power_W=float(value["power_W"]),
        nominal_speed_mm_s=float(value["nominal_speed_mm_s"]),
        spot_diameter_mm=float(value["spot_diameter_mm"]),
        campaign_id=str(value["campaign_id"]),
        acquisition_set_id=str(value["acquisition_set_id"]),
        layer_name=str(value["layer_name"]),
        expected_filename=(
            None
            if value.get("expected_filename") is None
            else str(value["expected_filename"])
        ),
        source_date=(
            None if value.get("source_date") is None else str(value["source_date"])
        ),
        process_condition_provenance=dict(
            value.get("process_condition_provenance") or {}
        ),
    )


def _trial_gate_failures(
    evaluation: Mapping[str, Any],
    expected_frame_count: int,
    *,
    undefined_observation_policy: str = "reject",
) -> list[str]:
    failures: list[str] = []
    if evaluation.get("status") != "PASS" or evaluation.get("stage") != "complete":
        failures.append("atomic_evaluator_not_complete_pass")
    observations = list(evaluation.get("observations") or [])
    if len(observations) != expected_frame_count:
        failures.append("all_observation_count_mismatch")
    seen_frames: set[int] = set()
    for observation in observations:
        try:
            frame_index = int(observation["frame_index"])
            exp_h = float(observation["experimental_H_pixels"])
            exp_w = float(observation["experimental_W_pixels"])
            sim_h = float(observation["simulated_H_pixels"])
            sim_w = float(observation["simulated_W_pixels"])
            if frame_index in seen_frames:
                failures.append("duplicate_evaluated_frame_index")
            seen_frames.add(frame_index)
            if not all(math.isfinite(v) for v in (exp_h, exp_w)):
                failures.append("nonfinite_primary_observation")
            if not all(math.isfinite(v) for v in (sim_h, sim_w)):
                # An explicitly undefined frame is allowed under record_undefined.
                undefined = str(observation.get("observation_status") or "").startswith("UNDEFINED_")
                if not (undefined_observation_policy == UNDEFINED_OBSERVATION_POLICY and undefined):
                    failures.append("nonfinite_primary_observation")
                continue
            if sim_h < 0.0 or sim_w < 0.0:
                failures.append("negative_simulated_H_or_W")
            if (sim_h == 0.0) != (sim_w == 0.0):
                failures.append("partial_zero_simulated_footprint")
        except (KeyError, TypeError, ValueError):
            failures.append("malformed_all_observation_record")
    trace = dict(evaluation.get("temperature_trace") or {})
    telemetry = dict(evaluation.get("execution_telemetry") or {})
    energy = dict(evaluation.get("energy_accounting") or {})
    try:
        if int(trace["thermal_substep_count"]) <= 0:
            failures.append("thermal_substep_count_invalid")
        if int(trace["thermal_substep_count"]) != int(telemetry["directional_step_count"]):
            failures.append("thermal_trace_telemetry_mismatch")
    except (KeyError, TypeError, ValueError):
        failures.append("thermal_trace_or_telemetry_missing")
    try:
        if abs(float(energy["energy_balance_relative_error"])) > 1.0e-9:
            failures.append("energy_balance_relative_error")
    except (KeyError, TypeError, ValueError):
        failures.append("energy_accounting_missing_or_nonnumeric")
    if not isinstance(evaluation.get("high_temperature_diagnostics"), Mapping):
        failures.append("high_temperature_diagnostics_missing")
    if telemetry.get("temperature_clipping_used") is not False:
        failures.append("temperature_clipping_used_or_unreported")
    if telemetry.get("every_substep_temperature_trace_complete") is not True:
        failures.append("every_substep_temperature_trace_incomplete")
    if telemetry.get("production_hw_semantics_version") != PRODUCTION_HW_SEMANTICS_VERSION:
        failures.append("production_hw_semantics_version_drift")
    if telemetry.get("production_hw_definition") != PRODUCTION_HW_DEFINITION:
        failures.append("production_hw_definition_missing_or_drifted")
    if telemetry.get("production_hw_association_policy_version") != (
        PRODUCTION_HW_ASSOCIATION_POLICY_VERSION
    ):
        failures.append("production_hw_association_policy_version_missing_or_drifted")
    if evaluation.get("temperature_clipping_permitted") is not False:
        failures.append("evaluation_temperature_clipping_contract_drift")
    return sorted(set(failures))


def _row_is_scored(row: Mapping[str, Any]) -> bool:
    if "scored_frame" in row:
        return bool(row["scored_frame"])
    return bool(row.get("observation_eligible"))


def _frame_records_from_evaluation(
    evaluation: Mapping[str, Any],
    *,
    base_rows: Sequence[Mapping[str, Any]],
    undefined_observation_policy: str = "reject",
) -> tuple[list[dict[str, Any]], list[str]]:
    scored_rows = [row for row in base_rows if _row_is_scored(row)]
    failures = _trial_gate_failures(
        evaluation, len(scored_rows), undefined_observation_policy=undefined_observation_policy
    )
    atomic_failure = dict(evaluation.get("failure") or {})
    if failures:
        failure_record = {
            "code": "PATCH_22_4_3_TRIAL_GATE_FAILURE",
            "gate_failures": failures,
            "atomic_failure": atomic_failure or None,
        }
        rows = []
        for base in base_rows:
            row = dict(base)
            row["status"] = "FAIL"
            row["failure"] = failure_record
            row.pop("simulated_H_pixels", None)
            row.pop("simulated_W_pixels", None)
            rows.append(row)
        return rows, failures

    observations = {
        int(row["frame_index"]): dict(row)
        for row in list(evaluation.get("observations") or [])
        if isinstance(row, Mapping) and row.get("frame_index") is not None
    }
    records: list[dict[str, Any]] = []
    for base in base_rows:
        row = dict(base)
        eligible = bool(row.get("observation_eligible"))
        if eligible and not _row_is_scored(row):
            # Excluded by the scored-frame rule; retained without H/W.
            row.pop("simulated_H_pixels", None)
            row.pop("simulated_W_pixels", None)
            row["status"] = "EXCLUDED"
            row["failure"] = None
            records.append(row)
            continue
        if eligible:
            observation = observations.get(int(row["frame_index"]))
            if observation is None:
                failure_record = {
                    "code": "PATCH_22_4_3_MISSING_SIMULATED_FRAME_RECORD",
                    "frame_index": row["frame_index"],
                }
                failed_rows = []
                for failed_base in base_rows:
                    failed = dict(failed_base)
                    failed["status"] = "FAIL"
                    failed["failure"] = failure_record
                    failed_rows.append(failed)
                return failed_rows, ["missing_simulated_frame_record"]
            status = str(observation.get("observation_status") or "SCORED")
            if status.startswith("UNDEFINED_"):
                # Undefined stays undefined; never fabricated as zero.
                row["simulated_H_pixels"] = None
                row["simulated_W_pixels"] = None
                row["status"] = "UNDEFINED"
                row["undefined_reason"] = str(
                    observation.get("undefined_reason") or status[len("UNDEFINED_"):]
                )
                row["failure"] = None
                records.append(row)
                continue
            row["simulated_H_pixels"] = observation.get("simulated_H_pixels")
            row["simulated_W_pixels"] = observation.get("simulated_W_pixels")
        row["status"] = "PASS"
        row["failure"] = None
        records.append(row)
    return records, []


def _annotate_frame_records(records: Sequence[dict[str, Any]], evaluation: Mapping[str, Any]) -> None:
    """Attach production-association telemetry from the evaluator's observations to each frame record.

    The evaluator's own per-frame status (``SCORED`` / ``UNDEFINED_<reason>``) is stored as
    ``evaluator_observation_status``. ``observation_status`` belongs to the experimental side of the
    frame row (``ELIGIBLE_FINITE_HW`` ...) and is what the hierarchical objective validates; it must
    not be overwritten here.
    """

    observations = {
        int(item["frame_index"]): item
        for item in list(evaluation.get("observations") or [])
        if isinstance(item, Mapping) and item.get("frame_index") is not None
    }
    for record in records:
        observation = observations.get(int(record["frame_index"])) if record.get("status") in ("PASS", "UNDEFINED") else None
        diagnostics = (observation or {}).get("observation_diagnostics") or {}
        record.update(
            {
                "production_status": diagnostics.get("production_hw_association_status"),
                "production_mode": diagnostics.get("production_hw_association_mode"),
                "production_selected_label": diagnostics.get("production_hw_association_selected_label"),
                "production_beam_share": diagnostics.get("production_hw_association_beam_share"),
                "production_contains_beam_cell": diagnostics.get("production_hw_association_contains_beam_cell"),
                "production_component_status": diagnostics.get("production_hw_component_status"),
                "melt_classification": None if observation is None else observation.get("melt_classification"),
                "evaluator_observation_status": None if observation is None else observation.get("observation_status"),
            }
        )


# Public names (the leading-underscore spellings are kept as aliases: the calibration runner and its tests use them).
find_frame_file = _find_frame_file
portable_frame_rows = _portable_frame_rows
dataset_member_context = _dataset_member_context
dataset_member_from_context = _dataset_member_from_context
trial_gate_failures = _trial_gate_failures
frame_records_from_evaluation = _frame_records_from_evaluation
annotate_frame_records = _annotate_frame_records
json_safe = _json_safe

__all__ = [
    "FrameRecordError",
    "UNDEFINED_OBSERVATION_POLICY",
    "annotate_frame_records",
    "dataset_member_context",
    "dataset_member_from_context",
    "evaluate_calibration_trial",
    "find_frame_file",
    "frame_records_from_evaluation",
    "json_safe",
    "portable_frame_rows",
    "trial_gate_failures",
]
