"""Read-compatible six-coupon facade over the Patch 20.8 canonical authority.

The accepted 20260731 six-member locus remains available to historical current
experiments through this module.  Process conditions and file identities are
now sourced exclusively from ``full_coupon_dataset_manifest.json``.  The
superseded Patch 16 registry remains immutable evidence and is not an execution
source.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from lpbf.data.full_coupon_manifest import (
    FULL_COUPON_MANIFEST_PATH,
    LEGACY_ACCEPTED_SET_ID,
    FullCouponManifestError,
    load_full_coupon_manifest,
    resolve_manifest_files,
    select_manifest_members,
)


# Read compatibility for callers that import this symbol.  It intentionally
# points to the canonical authority, not the superseded Patch 16 registry.
CURRENT_COUPON_REGISTRY_PATH = FULL_COUPON_MANIFEST_PATH
EXPECTED_COUPON_IDS = (1, 2, 3, 4, 5, 6)


class CouponInputError(RuntimeError):
    """Raised when current coupon metadata or authoritative input identity fails."""


@dataclass(frozen=True)
class CouponCondition:
    coupon_id: int
    power_W: float
    nominal_speed_mm_s: float
    spot_diameter_mm: float
    sha256: str
    campaign_id: str = "lpbf_2026_full_coupon_campaign"
    acquisition_set_id: str = LEGACY_ACCEPTED_SET_ID
    layer_name: str = "layer53"
    expected_filename: str | None = None


def load_authoritative_coupon_conditions(
    manifest_path: str | Path = FULL_COUPON_MANIFEST_PATH,
) -> dict[int, CouponCondition]:
    """Return the accepted six-position 20260731 view of the canonical manifest.

    The full manifest may still be in Patch 20.8 bootstrap state because the 18
    newly supplied files are not locally available here.  This compatibility
    view is permitted because all six 20260731 members already carry accepted
    concrete SHA-256 identities.
    """

    try:
        manifest = load_full_coupon_manifest(manifest_path, require_complete_hashes=False)
        members = select_manifest_members(
            manifest,
            acquisition_set_ids=(LEGACY_ACCEPTED_SET_ID,),
            require_hashes=True,
        )
    except FullCouponManifestError as exc:
        raise CouponInputError(str(exc)) from exc

    out = {
        member.key.part_number: CouponCondition(
            coupon_id=member.key.part_number,
            power_W=member.nominal_power_W,
            nominal_speed_mm_s=member.nominal_speed_mm_s,
            spot_diameter_mm=member.spot_diameter_mm,
            sha256=str(member.sha256),
            campaign_id=member.key.campaign_id,
            acquisition_set_id=member.key.acquisition_set_id,
            layer_name=member.key.layer_name,
            expected_filename=member.expected_filename,
        )
        for member in members
    }
    if set(out) != set(EXPECTED_COUPON_IDS):
        raise CouponInputError("Canonical 20260731 set must contain Coupons 1-6 exactly")
    return out


def discover_authoritative_coupon_files(
    data_directory: str | Path,
    *,
    conditions: dict[int, CouponCondition] | None = None,
) -> dict[int, Path]:
    """Resolve the accepted six files by exact canonical filename and SHA-256.

    ``conditions`` is retained for API compatibility.  When supplied, it is
    checked against the canonical mapping and cannot override it.
    """

    try:
        manifest = load_full_coupon_manifest(require_complete_hashes=False)
        members = select_manifest_members(
            manifest,
            acquisition_set_ids=(LEGACY_ACCEPTED_SET_ID,),
            require_hashes=True,
        )
        canonical = load_authoritative_coupon_conditions()
        if conditions is not None:
            if set(conditions) != set(canonical):
                raise CouponInputError("Supplied coupon conditions do not cover Coupons 1-6 exactly")
            for coupon_id, expected in canonical.items():
                supplied = conditions[coupon_id]
                if supplied != expected:
                    raise CouponInputError(
                        f"Coupon {coupon_id}: supplied condition conflicts with canonical dataset authority"
                    )
        resolved = resolve_manifest_files(
            data_directory,
            manifest=manifest,
            members=members,
            require_exact_directory_membership=False,
        )
    except FullCouponManifestError as exc:
        raise CouponInputError(str(exc)) from exc
    return {item.member.key.part_number: item.path for item in resolved}
