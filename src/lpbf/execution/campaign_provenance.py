"""Patch 22.4.0 campaign work-unit identity and provenance controls.

This module is deliberately non-scientific. It binds the canonical 4x6 coupon
manifest to immutable execution identities so process-pool completion order,
worker number, retries, or resume behavior cannot change scientific ownership
of a result.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping, Sequence

from lpbf.data.full_coupon_manifest import (
    ACQUISITION_SET_IDS,
    EXPECTED_MEMBER_COUNT,
    PART_NUMBERS,
    FullCouponManifest,
    load_full_coupon_manifest,
)
from lpbf.infrastructure import canonical_sha256, read_json, write_json_atomic

PATCH_VERSION = "22.4.0"
PRODUCTION_SEMANTICS_ID = (
    "patch22_3_7_laser_associated_component_beam_power_share_hw"
)
EXPECTED_SET_COUNT = 4
EXPECTED_MEMBERS_PER_SET = 6
_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


class CampaignProvenanceError(ValueError):
    """Raised when campaign identity, ordering, or result accounting is invalid."""


def _id(value: Any, field: str) -> str:
    text = str(value).strip()
    if not text or not _ID_RE.fullmatch(text):
        raise CampaignProvenanceError(
            f"{field} must be non-empty and contain only letters, numbers, '.', '_' or '-'"
        )
    return text


def _json_clone(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, sort_keys=True, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise CampaignProvenanceError("provenance values must be finite JSON-compatible data") from exc


@dataclass(frozen=True, slots=True)
class ParameterPointSpec:
    parameter_point_id: str
    values: Mapping[str, float]

    def __post_init__(self) -> None:
        object.__setattr__(self, "parameter_point_id", _id(self.parameter_point_id, "parameter_point_id"))
        normalized: dict[str, float] = {}
        for name, value in sorted(dict(self.values).items()):
            key = _id(name, "parameter name")
            if isinstance(value, bool):
                raise CampaignProvenanceError(f"parameter {key!r} must be numeric")
            try:
                number = float(value)
            except (TypeError, ValueError) as exc:
                raise CampaignProvenanceError(f"parameter {key!r} must be numeric") from exc
            if not (-float("inf") < number < float("inf")):
                raise CampaignProvenanceError(f"parameter {key!r} must be finite")
            normalized[key] = number
        object.__setattr__(self, "values", normalized)

    @property
    def sha256(self) -> str:
        return canonical_sha256({"parameter_point_id": self.parameter_point_id, "values": dict(self.values)})


@dataclass(frozen=True, slots=True)
class CampaignStageSpec:
    stage_id: str
    stage_ordinal: int
    experiment_id: str
    parameter_sweep_id: str
    parameter_points: tuple[ParameterPointSpec, ...]
    set_execution_context: Mapping[str, Mapping[str, Any]]
    acquisition_set_ids: tuple[str, ...] = ACQUISITION_SET_IDS
    replicate_id: str = "r1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "stage_id", _id(self.stage_id, "stage_id"))
        object.__setattr__(self, "experiment_id", _id(self.experiment_id, "experiment_id"))
        object.__setattr__(self, "parameter_sweep_id", _id(self.parameter_sweep_id, "parameter_sweep_id"))
        object.__setattr__(self, "replicate_id", _id(self.replicate_id, "replicate_id"))
        ordinal = int(self.stage_ordinal)
        if ordinal < 1:
            raise CampaignProvenanceError("stage_ordinal must be positive")
        object.__setattr__(self, "stage_ordinal", ordinal)
        points = tuple(self.parameter_points)
        if not points:
            raise CampaignProvenanceError("each stage must contain at least one parameter point")
        if len({p.parameter_point_id for p in points}) != len(points):
            raise CampaignProvenanceError("parameter_point_id values must be unique within a stage")
        object.__setattr__(self, "parameter_points", points)
        set_ids = tuple(str(x) for x in self.acquisition_set_ids)
        if not set_ids or len(set(set_ids)) != len(set_ids):
            raise CampaignProvenanceError("acquisition_set_ids must be non-empty and unique")
        if any(x not in ACQUISITION_SET_IDS for x in set_ids):
            raise CampaignProvenanceError("stage contains an acquisition set outside the canonical campaign")
        object.__setattr__(self, "acquisition_set_ids", set_ids)
        contexts = {str(k): _json_clone(v) for k, v in dict(self.set_execution_context).items()}
        missing = sorted(set(set_ids) - set(contexts))
        extra = sorted(set(contexts) - set(set_ids))
        if missing or extra:
            raise CampaignProvenanceError(
                f"set_execution_context must exactly cover stage acquisition sets; missing={missing}, extra={extra}"
            )
        object.__setattr__(self, "set_execution_context", contexts)


@dataclass(frozen=True, slots=True)
class CampaignWorkUnit:
    sequence_index: int
    campaign_id: str
    canonical_manifest_sha256: str
    stage_id: str
    stage_ordinal: int
    experiment_id: str
    acquisition_set_id: str
    set_ordinal: int
    set_role: str
    coupon_position: int
    member_identity: str
    portable_member_identity: str
    layer_name: str
    expected_filename: str
    input_sha256: str
    condition_id: str
    nominal_power_W: float
    nominal_speed_mm_s: float
    spot_diameter_mm: float
    source_date: str
    process_condition_provenance: Mapping[str, Any]
    parameter_sweep_id: str
    parameter_point_id: str
    parameter_values: Mapping[str, float]
    parameter_sha256: str
    set_execution_context: Mapping[str, Any]
    set_execution_context_sha256: str
    model_configuration_sha256: str
    production_semantics_id: str
    replicate_id: str
    work_unit_id: str

    def identity_record(self) -> dict[str, Any]:
        return {
            "campaign_id": self.campaign_id,
            "canonical_manifest_sha256": self.canonical_manifest_sha256,
            "stage_id": self.stage_id,
            "stage_ordinal": self.stage_ordinal,
            "experiment_id": self.experiment_id,
            "acquisition_set_id": self.acquisition_set_id,
            "set_ordinal": self.set_ordinal,
            "set_role": self.set_role,
            "coupon_position": self.coupon_position,
            "member_identity": self.member_identity,
            "portable_member_identity": self.portable_member_identity,
            "layer_name": self.layer_name,
            "expected_filename": self.expected_filename,
            "input_sha256": self.input_sha256,
            "condition_id": self.condition_id,
            "nominal_power_W": self.nominal_power_W,
            "nominal_speed_mm_s": self.nominal_speed_mm_s,
            "spot_diameter_mm": self.spot_diameter_mm,
            "source_date": self.source_date,
            "process_condition_provenance": _json_clone(self.process_condition_provenance),
            "parameter_sweep_id": self.parameter_sweep_id,
            "parameter_point_id": self.parameter_point_id,
            "parameter_values": dict(self.parameter_values),
            "parameter_sha256": self.parameter_sha256,
            "set_execution_context": _json_clone(self.set_execution_context),
            "set_execution_context_sha256": self.set_execution_context_sha256,
            "model_configuration_sha256": self.model_configuration_sha256,
            "production_semantics_id": self.production_semantics_id,
            "replicate_id": self.replicate_id,
            "work_unit_id": self.work_unit_id,
        }


@dataclass(frozen=True, slots=True)
class CampaignExecutionManifest:
    campaign_id: str
    canonical_dataset_manifest_sha256: str
    model_configuration_sha256: str
    production_semantics_id: str
    work_units: tuple[CampaignWorkUnit, ...]
    manifest_sha256: str

    @property
    def stage_ids(self) -> tuple[str, ...]:
        ordered: list[str] = []
        for unit in self.work_units:
            if unit.stage_id not in ordered:
                ordered.append(unit.stage_id)
        return tuple(ordered)

    def units_for_stage(self, stage_id: str) -> tuple[CampaignWorkUnit, ...]:
        return tuple(u for u in self.work_units if u.stage_id == stage_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "lpbf_patch22_4_0_campaign_execution_manifest",
            "schema_version": PATCH_VERSION,
            "campaign_id": self.campaign_id,
            "canonical_dataset_manifest_sha256": self.canonical_dataset_manifest_sha256,
            "model_configuration_sha256": self.model_configuration_sha256,
            "production_semantics_id": self.production_semantics_id,
            "work_unit_count": len(self.work_units),
            "stage_ids": list(self.stage_ids),
            "work_units": [u.identity_record() | {"sequence_index": u.sequence_index} for u in self.work_units],
            "manifest_sha256": self.manifest_sha256,
        }


def canonical_coupon_roster(manifest: FullCouponManifest | None = None) -> tuple[dict[str, Any], ...]:
    current = (load_full_coupon_manifest() if manifest is None else manifest).require_hash_complete()
    if len(current.enabled_members) != EXPECTED_MEMBER_COUNT:
        raise CampaignProvenanceError("canonical campaign must contain exactly 24 enabled coupons")
    raw_sets = current.raw_payload.get("acquisition_sets")
    if not isinstance(raw_sets, list):
        raise CampaignProvenanceError("canonical manifest acquisition_sets are unavailable")
    roles = {str(row["acquisition_set_id"]): str(row["role"]) for row in raw_sets}
    if tuple(roles) != ACQUISITION_SET_IDS:
        raise CampaignProvenanceError("canonical acquisition-set order has drifted")
    rows: list[dict[str, Any]] = []
    for set_ordinal, set_id in enumerate(ACQUISITION_SET_IDS, start=1):
        members = sorted(current.members_for_set(set_id), key=lambda m: m.key.part_number)
        if len(members) != EXPECTED_MEMBERS_PER_SET:
            raise CampaignProvenanceError(f"acquisition set {set_id} must contain exactly six coupons")
        if tuple(m.key.part_number for m in members) != PART_NUMBERS:
            raise CampaignProvenanceError(f"acquisition set {set_id} coupon positions must be 1..6")
        for member in members:
            process_provenance = dict(member.process_condition_provenance)
            source_date = process_provenance.get("source_date")
            if source_date is None or not str(source_date).strip():
                raise CampaignProvenanceError(
                    f"canonical member {member.key.text} is missing process_condition_provenance.source_date"
                )
            rows.append({
                "campaign_id": current.campaign_id,
                "canonical_manifest_sha256": current.canonical_identity,
                "acquisition_set_id": set_id,
                "set_ordinal": set_ordinal,
                "set_role": roles[set_id],
                "coupon_position": member.key.part_number,
                "member_identity": f"{set_id}:part_{member.key.part_number}",
                "portable_member_identity": member.portable_identity_text,
                "layer_name": member.key.layer_name,
                "expected_filename": member.expected_filename,
                "input_sha256": str(member.sha256),
                "nominal_power_W": float(member.nominal_power_W),
                "nominal_speed_mm_s": float(member.nominal_speed_mm_s),
                "spot_diameter_mm": float(member.spot_diameter_mm),
                "source_date": str(source_date),
                "process_condition_provenance": process_provenance,
                "condition_id": (
                    f"{current.campaign_id}:{set_id}:part_{member.key.part_number}:"
                    f"{member.key.layer_name}"
                ),
            })
    return tuple(rows)


def build_campaign_execution_manifest(
    stages: Sequence[CampaignStageSpec],
    *,
    model_configuration_sha256: str,
    production_semantics_id: str = PRODUCTION_SEMANTICS_ID,
    manifest: FullCouponManifest | None = None,
) -> CampaignExecutionManifest:
    model_hash = str(model_configuration_sha256).strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", model_hash):
        raise CampaignProvenanceError("model_configuration_sha256 must be a SHA-256 digest")
    semantics = _id(production_semantics_id, "production_semantics_id")
    current = (load_full_coupon_manifest() if manifest is None else manifest).require_hash_complete()
    roster = canonical_coupon_roster(current)
    stage_list = sorted(tuple(stages), key=lambda s: s.stage_ordinal)
    if not stage_list:
        raise CampaignProvenanceError("execution manifest requires at least one stage")
    if len({s.stage_id for s in stage_list}) != len(stage_list):
        raise CampaignProvenanceError("stage_id values must be unique")
    if tuple(s.stage_ordinal for s in stage_list) != tuple(range(1, len(stage_list) + 1)):
        raise CampaignProvenanceError("stage ordinals must be contiguous beginning at 1")

    units: list[CampaignWorkUnit] = []
    for stage in stage_list:
        selected = [row for row in roster if row["acquisition_set_id"] in stage.acquisition_set_ids]
        for row in selected:
            context = stage.set_execution_context[row["acquisition_set_id"]]
            context_hash = canonical_sha256(context)
            for point in stage.parameter_points:
                seed = {
                    "schema": "lpbf_patch22_4_0_work_unit_identity",
                    "schema_version": PATCH_VERSION,
                    "campaign_id": current.campaign_id,
                    "canonical_manifest_sha256": current.canonical_identity,
                    "stage_id": stage.stage_id,
                    "stage_ordinal": stage.stage_ordinal,
                    "experiment_id": stage.experiment_id,
                    "acquisition_set_id": row["acquisition_set_id"],
                    "set_ordinal": row["set_ordinal"],
                    "coupon_position": row["coupon_position"],
                    "member_identity": row["member_identity"],
                    "portable_member_identity": row["portable_member_identity"],
                    "input_sha256": row["input_sha256"],
                    "condition_id": row["condition_id"],
                    "spot_diameter_mm": row["spot_diameter_mm"],
                    "source_date": row["source_date"],
                    "process_condition_provenance": row["process_condition_provenance"],
                    "parameter_sweep_id": stage.parameter_sweep_id,
                    "parameter_point_id": point.parameter_point_id,
                    "parameter_sha256": point.sha256,
                    "set_execution_context_sha256": context_hash,
                    "model_configuration_sha256": model_hash,
                    "production_semantics_id": semantics,
                    "replicate_id": stage.replicate_id,
                }
                digest = canonical_sha256(seed)
                work_unit_id = (
                    f"S{row['set_ordinal']:02d}C{row['coupon_position']:02d}-"
                    f"{stage.stage_id}-{point.parameter_point_id}-{digest[:16]}"
                )
                units.append(CampaignWorkUnit(
                    sequence_index=len(units),
                    campaign_id=current.campaign_id,
                    canonical_manifest_sha256=current.canonical_identity,
                    stage_id=stage.stage_id,
                    stage_ordinal=stage.stage_ordinal,
                    experiment_id=stage.experiment_id,
                    acquisition_set_id=row["acquisition_set_id"],
                    set_ordinal=row["set_ordinal"],
                    set_role=row["set_role"],
                    coupon_position=row["coupon_position"],
                    member_identity=row["member_identity"],
                    portable_member_identity=row["portable_member_identity"],
                    layer_name=row["layer_name"],
                    expected_filename=row["expected_filename"],
                    input_sha256=row["input_sha256"],
                    condition_id=row["condition_id"],
                    nominal_power_W=row["nominal_power_W"],
                    nominal_speed_mm_s=row["nominal_speed_mm_s"],
                    spot_diameter_mm=row["spot_diameter_mm"],
                    source_date=row["source_date"],
                    process_condition_provenance=dict(row["process_condition_provenance"]),
                    parameter_sweep_id=stage.parameter_sweep_id,
                    parameter_point_id=point.parameter_point_id,
                    parameter_values=dict(point.values),
                    parameter_sha256=point.sha256,
                    set_execution_context=context,
                    set_execution_context_sha256=context_hash,
                    model_configuration_sha256=model_hash,
                    production_semantics_id=semantics,
                    replicate_id=stage.replicate_id,
                    work_unit_id=work_unit_id,
                ))
    ids = [u.work_unit_id for u in units]
    if len(set(ids)) != len(ids):
        raise CampaignProvenanceError("generated work_unit_id collision")
    manifest_seed = {
        "schema": "lpbf_patch22_4_0_campaign_execution_manifest",
        "schema_version": PATCH_VERSION,
        "campaign_id": current.campaign_id,
        "canonical_dataset_manifest_sha256": current.canonical_identity,
        "model_configuration_sha256": model_hash,
        "production_semantics_id": semantics,
        "work_units": [u.identity_record() | {"sequence_index": u.sequence_index} for u in units],
    }
    return CampaignExecutionManifest(
        campaign_id=current.campaign_id,
        canonical_dataset_manifest_sha256=current.canonical_identity,
        model_configuration_sha256=model_hash,
        production_semantics_id=semantics,
        work_units=tuple(units),
        manifest_sha256=canonical_sha256(manifest_seed),
    )



def simulation_job_for_work_unit(
    unit: CampaignWorkUnit,
    *,
    frame_index: int,
    window_cells: int | tuple[int, ...],
    extra_experiment_context: Mapping[str, Any] | None = None,
):
    """Bind one campaign work unit to the generic process-pool job envelope.

    Candidate coordinates come only from the frozen parameter point in the work
    unit; callers cannot silently substitute another parameter vector.
    """
    from lpbf.execution.work_units import SimulationJob

    context = {
        "campaign_manifest_sha256": unit.canonical_manifest_sha256,
        "stage_id": unit.stage_id,
        "experiment_id": unit.experiment_id,
        "acquisition_set_id": unit.acquisition_set_id,
        "coupon_position": unit.coupon_position,
        "portable_member_identity": unit.portable_member_identity,
        "input_sha256": unit.input_sha256,
        "condition_id": unit.condition_id,
        "nominal_power_W": unit.nominal_power_W,
        "nominal_speed_mm_s": unit.nominal_speed_mm_s,
        "spot_diameter_mm": unit.spot_diameter_mm,
        "source_date": unit.source_date,
        "process_condition_provenance": _json_clone(unit.process_condition_provenance),
        "parameter_sweep_id": unit.parameter_sweep_id,
        "parameter_point_id": unit.parameter_point_id,
        "parameter_sha256": unit.parameter_sha256,
    }
    if extra_experiment_context:
        for key, value in dict(extra_experiment_context).items():
            if key in context and context[key] != value:
                raise CampaignProvenanceError(f"extra context attempts to override frozen identity field {key!r}")
            context[key] = value
    return SimulationJob(
        case_index=unit.sequence_index,
        member_identity=unit.member_identity,
        frame_index=int(frame_index),
        window_cells=window_cells,
        candidate_coordinates=unit.parameter_values,
        experiment_context=context,
        work_unit_id=unit.work_unit_id,
        identity_provenance=unit.identity_record(),
    )


def authorize_stage_dispatch(
    execution_manifest: CampaignExecutionManifest,
    stage_id: str,
    completed_work_unit_ids: Iterable[str],
) -> tuple[CampaignWorkUnit, ...]:
    target = str(stage_id)
    stage_units = execution_manifest.units_for_stage(target)
    if not stage_units:
        raise CampaignProvenanceError(f"unknown stage_id: {target}")
    target_ordinal = stage_units[0].stage_ordinal
    completed = {str(x) for x in completed_work_unit_ids}
    prior = [u for u in execution_manifest.work_units if u.stage_ordinal < target_ordinal]
    missing_prior = [u.work_unit_id for u in prior if u.work_unit_id not in completed]
    if missing_prior:
        raise CampaignProvenanceError(
            f"stage {target} is not authorized; {len(missing_prior)} prior-stage work units are incomplete"
        )
    return stage_units


def deterministic_result_relative_path(unit: CampaignWorkUnit) -> Path:
    return Path(
        f"set_{unit.set_ordinal:02d}_{unit.acquisition_set_id}",
        f"coupon_{unit.coupon_position:02d}",
        unit.stage_id,
        unit.experiment_id,
        unit.parameter_sweep_id,
        unit.parameter_point_id,
        "result.json",
    )


def result_record(unit: CampaignWorkUnit, payload: Any, *, attempts: int = 1, worker_label: str | None = None) -> dict[str, Any]:
    identity = unit.identity_record()
    result = {
        "schema": "lpbf_patch22_4_0_work_unit_result",
        "schema_version": PATCH_VERSION,
        "work_unit_id": unit.work_unit_id,
        "identity": identity,
        "identity_sha256": canonical_sha256(identity),
        "attempts": int(attempts),
        "worker_label": None if worker_label is None else str(worker_label),
        "payload": _json_clone(payload),
    }
    result["result_sha256"] = canonical_sha256({k: v for k, v in result.items() if k != "result_sha256"})
    return result


def validate_result_record(unit: CampaignWorkUnit, record: Mapping[str, Any]) -> None:
    if record.get("schema") != "lpbf_patch22_4_0_work_unit_result" or record.get("schema_version") != PATCH_VERSION:
        raise CampaignProvenanceError("unexpected work-unit result schema")
    if record.get("work_unit_id") != unit.work_unit_id:
        raise CampaignProvenanceError("result work_unit_id does not match expected unit")
    expected_identity = unit.identity_record()
    if record.get("identity") != expected_identity:
        raise CampaignProvenanceError(f"result identity drift for {unit.work_unit_id}")
    if record.get("identity_sha256") != canonical_sha256(expected_identity):
        raise CampaignProvenanceError(f"result identity hash mismatch for {unit.work_unit_id}")
    expected_result_hash = canonical_sha256({k: v for k, v in dict(record).items() if k != "result_sha256"})
    if record.get("result_sha256") != expected_result_hash:
        raise CampaignProvenanceError(f"result payload hash mismatch for {unit.work_unit_id}")


def reconcile_result_records(
    execution_manifest: CampaignExecutionManifest,
    records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    expected = {u.work_unit_id: u for u in execution_manifest.work_units}
    observed_ids = [str(r.get("work_unit_id", "")) for r in records]
    counts: dict[str, int] = {}
    for wid in observed_ids:
        counts[wid] = counts.get(wid, 0) + 1
    duplicate_ids = sorted(wid for wid, count in counts.items() if count > 1)
    unexpected_ids = sorted(wid for wid in counts if wid not in expected)
    missing_ids = sorted(wid for wid in expected if wid not in counts)
    invalid_ids: list[str] = []
    if not duplicate_ids and not unexpected_ids:
        for record in records:
            wid = str(record.get("work_unit_id", ""))
            if wid in expected:
                try:
                    validate_result_record(expected[wid], record)
                except CampaignProvenanceError:
                    invalid_ids.append(wid)
    return {
        "expected_count": len(expected),
        "observed_count": len(records),
        "unique_observed_count": len(counts),
        "duplicate_work_unit_ids": duplicate_ids,
        "missing_work_unit_ids": missing_ids,
        "unexpected_work_unit_ids": unexpected_ids,
        "invalid_work_unit_ids": sorted(set(invalid_ids)),
        "pass": not (duplicate_ids or missing_ids or unexpected_ids or invalid_ids),
    }



def order_result_records_by_manifest(
    execution_manifest: CampaignExecutionManifest,
    records: Sequence[Mapping[str, Any]],
) -> tuple[Mapping[str, Any], ...]:
    reconciliation = reconcile_result_records(execution_manifest, records)
    if not reconciliation["pass"]:
        raise CampaignProvenanceError("cannot order result records until reconciliation passes")
    by_id = {str(record["work_unit_id"]): record for record in records}
    return tuple(by_id[unit.work_unit_id] for unit in execution_manifest.work_units)


def write_result_once(output_root: str | Path, unit: CampaignWorkUnit, record: Mapping[str, Any]) -> Path:
    validate_result_record(unit, record)
    destination = Path(output_root) / deterministic_result_relative_path(unit)
    if destination.exists():
        existing = read_json(destination)
        validate_result_record(unit, existing)
        if existing != dict(record):
            raise CampaignProvenanceError(
                f"valid completed result already exists with different payload: {unit.work_unit_id}"
            )
        return destination
    write_json_atomic(destination, dict(record), allow_nan=False)
    return destination


__all__ = [
    "CampaignExecutionManifest",
    "CampaignProvenanceError",
    "CampaignStageSpec",
    "CampaignWorkUnit",
    "ParameterPointSpec",
    "PRODUCTION_SEMANTICS_ID",
    "authorize_stage_dispatch",
    "build_campaign_execution_manifest",
    "canonical_coupon_roster",
    "deterministic_result_relative_path",
    "order_result_records_by_manifest",
    "reconcile_result_records",
    "result_record",
    "simulation_job_for_work_unit",
    "validate_result_record",
    "write_result_once",
]
