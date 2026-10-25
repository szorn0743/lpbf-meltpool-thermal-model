"""Dataset resolution and identity for the supported current API.

This module owns campaign/member resolution only. It does not construct
thermal runtimes, evaluate observations, or write reports.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from lpbf.data.coupon_inputs import CouponCondition
from lpbf.data.full_coupon_manifest import (
    CAMPAIGN_ID,
    DEFAULT_LAYER_NAME,
    LEGACY_ACCEPTED_SET_ID,
    FullCouponManifest,
    FullCouponManifestError,
    load_full_coupon_manifest,
    resolve_manifest_files,
)
from lpbf.model.parameter_policy import ProcessCondition

from .errors import CurrentExperimentFrameworkError


@dataclass(frozen=True)
class DatasetMember:
    """One campaign-qualified, hash-bound current-experiment dataset member."""

    set_id: int
    dataset_member_id: int
    coupon_position: int
    path: Path
    sha256: str
    power_W: float
    nominal_speed_mm_s: float
    spot_diameter_mm: float
    campaign_id: str = CAMPAIGN_ID
    acquisition_set_id: str = LEGACY_ACCEPTED_SET_ID
    layer_name: str = DEFAULT_LAYER_NAME
    expected_filename: str | None = None
    source_date: str | None = None
    process_condition_provenance: Mapping[str, Any] = field(default_factory=dict)

    @property
    def portable_identity(self) -> dict[str, Any]:
        return {
            "campaign_id": str(self.campaign_id),
            "acquisition_set_id": str(self.acquisition_set_id),
            "part_number": int(self.coupon_position),
            "layer_name": str(self.layer_name),
            "file_sha256": str(self.sha256),
        }

    @property
    def portable_identity_text(self) -> str:
        digest = str(self.sha256) if self.sha256 else "UNRESOLVED_SHA256"
        return (
            f"{self.campaign_id}:{self.acquisition_set_id}:"
            f"part_{int(self.coupon_position)}:{self.layer_name}:{digest}"
        )

    @property
    def condition(self) -> CouponCondition:
        return CouponCondition(
            coupon_id=int(self.coupon_position),
            power_W=float(self.power_W),
            nominal_speed_mm_s=float(self.nominal_speed_mm_s),
            spot_diameter_mm=float(self.spot_diameter_mm),
            sha256=str(self.sha256),
            campaign_id=str(self.campaign_id),
            acquisition_set_id=str(self.acquisition_set_id),
            layer_name=str(self.layer_name),
            expected_filename=self.expected_filename,
        )

    @property
    def process_condition(self) -> ProcessCondition:
        return ProcessCondition(
            condition_id=(
                f"{self.campaign_id}:{self.acquisition_set_id}:"
                f"part_{int(self.coupon_position)}:{self.layer_name}"
            ),
            power_W=float(self.power_W),
            speed_mm_s=float(self.nominal_speed_mm_s),
        )


def _dataset_member_from_resolved(item: Any, *, set_ordinal: int) -> DatasetMember:
    member = item.member
    return DatasetMember(
        set_id=int(set_ordinal),
        dataset_member_id=int(member.key.part_number),
        coupon_position=int(member.key.part_number),
        path=item.path,
        sha256=item.actual_sha256,
        power_W=member.nominal_power_W,
        nominal_speed_mm_s=member.nominal_speed_mm_s,
        spot_diameter_mm=member.spot_diameter_mm,
        campaign_id=member.key.campaign_id,
        acquisition_set_id=member.key.acquisition_set_id,
        layer_name=member.key.layer_name,
        expected_filename=member.expected_filename,
        source_date=(
            None
            if member.process_condition_provenance.get("source_date") is None
            else str(member.process_condition_provenance["source_date"])
        ),
        process_condition_provenance=dict(member.process_condition_provenance),
    )


def resolve_full_coupon_members(
    data_directory: str | Path,
    *,
    manifest: FullCouponManifest | None = None,
) -> tuple[DatasetMember, ...]:
    """Resolve all 24 canonical members, failing closed until hashes are complete."""

    try:
        current = load_full_coupon_manifest() if manifest is None else manifest.require_hash_complete()
        resolved = resolve_manifest_files(
            data_directory,
            manifest=current,
            members=current.enabled_members,
            require_exact_directory_membership=True,
        )
    except FullCouponManifestError as exc:
        raise CurrentExperimentFrameworkError(str(exc)) from exc
    set_ordinals = {set_id: index + 1 for index, set_id in enumerate(
        ("20260730", "20260731", "20260904", "20260910")
    )}
    return tuple(
        _dataset_member_from_resolved(
            item, set_ordinal=set_ordinals[item.member.key.acquisition_set_id]
        )
        for item in resolved
    )


__all__ = [
    "DatasetMember",
    "resolve_full_coupon_members",
]
