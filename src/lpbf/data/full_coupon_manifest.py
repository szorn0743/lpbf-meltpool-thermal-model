"""Canonical full-coupon dataset authority introduced by Patch 20.8.

The portable dataset identity is manifest-owned and is independent of any local
filesystem root.  Local HDF5 paths enter only through explicit runtime
``data_directory`` arguments.  File resolution is exact-name and SHA-256
verified; broad part-number globbing is not an accepted identity mechanism.

Patch 20.8 supports bootstrap-state manifests for controlled local identity
audits, but the accepted checked-in manifest is hash-complete.  Any custom or
bootstrap manifest used for execution still fails closed unless every selected
member carries a concrete SHA-256 identity.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import re
from typing import Any, Iterable, Mapping, Sequence

from lpbf.infrastructure import canonical_sha256, read_json, sha256_file


FULL_COUPON_MANIFEST_SCHEMA = "lpbf_full_coupon_dataset_manifest"
FULL_COUPON_MANIFEST_SCHEMA_VERSION = "20.8.0"
FULL_COUPON_MANIFEST_PATH = Path(__file__).with_name("full_coupon_dataset_manifest.json")
CAMPAIGN_ID = "lpbf_2026_full_coupon_campaign"
ACQUISITION_SET_IDS = ("20260730", "20260731", "20260904", "20260910")
PART_NUMBERS = (1, 2, 3, 4, 5, 6)
DEFAULT_LAYER_NAME = "layer53"
EXPECTED_MEMBER_COUNT = 24
EXPECTED_SPOT_DIAMETER_MM = 0.08
LEGACY_ACCEPTED_SET_ID = "20260731"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class FullCouponManifestError(ValueError):
    """Raised when canonical dataset metadata or file identity is invalid."""


@dataclass(frozen=True, order=True)
class DatasetMemberKey:
    """Campaign-qualified scientific member identity excluding the file hash."""

    campaign_id: str
    acquisition_set_id: str
    part_number: int
    layer_name: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "campaign_id": self.campaign_id,
            "acquisition_set_id": self.acquisition_set_id,
            "part_number": self.part_number,
            "layer_name": self.layer_name,
        }

    @property
    def text(self) -> str:
        return (
            f"{self.campaign_id}:{self.acquisition_set_id}:"
            f"part_{self.part_number}:{self.layer_name}"
        )


@dataclass(frozen=True)
class FullCouponMember:
    """One validated member of the canonical 24-member campaign contract."""

    key: DatasetMemberKey
    expected_filename: str
    sha256: str | None
    hash_identity_state: str
    nominal_power_W: float
    nominal_speed_mm_s: float
    spot_diameter_mm: float
    supplied_power_density_J_mm2: float | None
    supplied_power_density_J_mm3: float | None
    enabled: bool
    measurement_validity_state: str
    candidate_replicate_group: str | None
    sweep_group: str | None
    process_condition_provenance: Mapping[str, Any]

    @property
    def portable_identity(self) -> dict[str, Any]:
        return {**self.key.to_dict(), "file_sha256": self.sha256}

    @property
    def portable_identity_text(self) -> str:
        digest = self.sha256 if self.sha256 is not None else "UNRESOLVED_SHA256"
        return f"{self.key.text}:{digest}"

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.key.to_dict(),
            "expected_filename": self.expected_filename,
            "sha256": self.sha256,
            "hash_identity_state": self.hash_identity_state,
            "nominal_power_W": self.nominal_power_W,
            "nominal_speed_mm_s": self.nominal_speed_mm_s,
            "spot_diameter_mm": self.spot_diameter_mm,
            "supplied_power_density_J_mm2": self.supplied_power_density_J_mm2,
            "supplied_power_density_J_mm3": self.supplied_power_density_J_mm3,
            "enabled": self.enabled,
            "measurement_validity_state": self.measurement_validity_state,
            "candidate_replicate_group": self.candidate_replicate_group,
            "sweep_group": self.sweep_group,
            "process_condition_provenance": dict(self.process_condition_provenance),
        }


@dataclass(frozen=True)
class FullCouponManifest:
    """Validated campaign contract plus deterministic manifest identity."""

    campaign_id: str
    manifest_state: str
    members: tuple[FullCouponMember, ...]
    raw_payload: Mapping[str, Any]
    canonical_identity: str

    @property
    def enabled_members(self) -> tuple[FullCouponMember, ...]:
        return tuple(member for member in self.members if member.enabled)

    @property
    def unresolved_members(self) -> tuple[FullCouponMember, ...]:
        return tuple(member for member in self.enabled_members if member.sha256 is None)

    @property
    def is_hash_complete(self) -> bool:
        return not self.unresolved_members

    def members_for_set(self, acquisition_set_id: str) -> tuple[FullCouponMember, ...]:
        return tuple(
            member
            for member in self.enabled_members
            if member.key.acquisition_set_id == str(acquisition_set_id)
        )

    def member(self, acquisition_set_id: str, part_number: int, *, layer_name: str = DEFAULT_LAYER_NAME) -> FullCouponMember:
        matches = [
            member
            for member in self.enabled_members
            if member.key.acquisition_set_id == str(acquisition_set_id)
            and member.key.part_number == int(part_number)
            and member.key.layer_name == str(layer_name)
        ]
        if len(matches) != 1:
            raise KeyError(
                f"expected exactly one canonical member for set={acquisition_set_id!r}, "
                f"part={part_number}, layer={layer_name!r}; found {len(matches)}"
            )
        return matches[0]

    def require_hash_complete(self) -> "FullCouponManifest":
        if self.unresolved_members:
            missing = [member.key.text for member in self.unresolved_members]
            raise FullCouponManifestError(
                "canonical full-coupon manifest is not hash-complete; run the Patch 20.8 "
                "local manifest bootstrap/integrity audit first. Unresolved members: "
                + ", ".join(missing)
            )
        return self


@dataclass(frozen=True)
class ResolvedCouponMember:
    """One exact-name, hash-verified runtime file binding."""

    member: FullCouponMember
    path: Path
    actual_sha256: str

    @property
    def portable_identity(self) -> dict[str, Any]:
        return self.member.portable_identity

    def to_dict(self, *, include_runtime_path: bool = True) -> dict[str, Any]:
        result = {
            "portable_identity": self.portable_identity,
            "expected_filename": self.member.expected_filename,
            "actual_sha256": self.actual_sha256,
        }
        if include_runtime_path:
            result["runtime_path"] = str(self.path)
        return result


def _require_text(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FullCouponManifestError(f"{field} must be a non-empty string")
    return value.strip()


def _require_positive_float(value: Any, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FullCouponManifestError(f"{field} must be a positive finite number")
    number = float(value)
    if not math.isfinite(number) or number <= 0.0:
        raise FullCouponManifestError(f"{field} must be a positive finite number")
    return number


def _optional_positive_float(value: Any, *, field: str) -> float | None:
    if value is None:
        return None
    return _require_positive_float(value, field=field)


def _normalize_sha256(value: Any, *, field: str, allow_unresolved: bool) -> str | None:
    if value is None:
        if allow_unresolved:
            return None
        raise FullCouponManifestError(f"{field} must contain a concrete SHA-256 digest")
    text = str(value).strip().lower()
    if not _SHA256_RE.fullmatch(text):
        raise FullCouponManifestError(f"{field} must be 64 lowercase hexadecimal characters")
    return text


def _parse_member(raw: Mapping[str, Any], *, allow_unresolved_hashes: bool) -> FullCouponMember:
    required = {
        "campaign_id",
        "acquisition_set_id",
        "part_number",
        "layer_name",
        "expected_filename",
        "sha256",
        "hash_identity_state",
        "nominal_power_W",
        "nominal_speed_mm_s",
        "spot_diameter_mm",
        "supplied_power_density_J_mm2",
        "supplied_power_density_J_mm3",
        "enabled",
        "measurement_validity_state",
        "candidate_replicate_group",
        "sweep_group",
        "process_condition_provenance",
    }
    missing = sorted(required - set(raw))
    if missing:
        raise FullCouponManifestError(
            "canonical member is missing required field(s): " + ", ".join(missing)
        )
    unknown = sorted(set(raw) - required)
    if unknown:
        raise FullCouponManifestError(
            "canonical member contains unsupported field(s): " + ", ".join(unknown)
        )

    campaign_id = _require_text(raw["campaign_id"], field="campaign_id")
    acquisition_set_id = _require_text(raw["acquisition_set_id"], field="acquisition_set_id")
    part = raw["part_number"]
    if isinstance(part, bool) or not isinstance(part, int) or part <= 0:
        raise FullCouponManifestError("part_number must be a positive integer")
    layer_name = _require_text(raw["layer_name"], field="layer_name")
    expected_filename = _require_text(raw["expected_filename"], field="expected_filename")
    if Path(expected_filename).name != expected_filename:
        raise FullCouponManifestError(
            f"expected_filename must be a basename, not a path: {expected_filename!r}"
        )
    expected_name = f"part_{part}_{acquisition_set_id}.h5"
    if expected_filename != expected_name:
        raise FullCouponManifestError(
            f"member {acquisition_set_id}/part_{part}: expected_filename must be {expected_name!r}"
        )
    sha = _normalize_sha256(
        raw["sha256"],
        field=f"{acquisition_set_id}/part_{part}.sha256",
        allow_unresolved=allow_unresolved_hashes,
    )
    hash_state = _require_text(raw["hash_identity_state"], field="hash_identity_state")
    if sha is None and "pending" not in hash_state.lower():
        raise FullCouponManifestError(
            f"{acquisition_set_id}/part_{part}: unresolved sha256 requires a pending hash_identity_state"
        )

    enabled = raw["enabled"]
    if not isinstance(enabled, bool):
        raise FullCouponManifestError("enabled must be boolean")
    measurement = _require_text(
        raw["measurement_validity_state"], field="measurement_validity_state"
    )
    replicate = raw["candidate_replicate_group"]
    if replicate is not None:
        replicate = _require_text(replicate, field="candidate_replicate_group")
    sweep = raw["sweep_group"]
    if sweep is not None:
        sweep = _require_text(sweep, field="sweep_group")
    provenance = raw["process_condition_provenance"]
    if not isinstance(provenance, Mapping) or not provenance:
        raise FullCouponManifestError(
            "process_condition_provenance must be a non-empty JSON object"
        )

    return FullCouponMember(
        key=DatasetMemberKey(
            campaign_id=campaign_id,
            acquisition_set_id=acquisition_set_id,
            part_number=int(part),
            layer_name=layer_name,
        ),
        expected_filename=expected_filename,
        sha256=sha,
        hash_identity_state=hash_state,
        nominal_power_W=_require_positive_float(raw["nominal_power_W"], field="nominal_power_W"),
        nominal_speed_mm_s=_require_positive_float(raw["nominal_speed_mm_s"], field="nominal_speed_mm_s"),
        spot_diameter_mm=_require_positive_float(raw["spot_diameter_mm"], field="spot_diameter_mm"),
        supplied_power_density_J_mm2=_optional_positive_float(
            raw["supplied_power_density_J_mm2"], field="supplied_power_density_J_mm2"
        ),
        supplied_power_density_J_mm3=_optional_positive_float(
            raw["supplied_power_density_J_mm3"], field="supplied_power_density_J_mm3"
        ),
        enabled=enabled,
        measurement_validity_state=measurement,
        candidate_replicate_group=replicate,
        sweep_group=sweep,
        process_condition_provenance=dict(provenance),
    )


def validate_full_coupon_manifest_payload(
    payload: Mapping[str, Any],
    *,
    require_complete_hashes: bool = True,
) -> FullCouponManifest:
    """Validate a canonical campaign manifest and return its typed representation."""

    if not isinstance(payload, Mapping):
        raise FullCouponManifestError("full-coupon manifest root must be a JSON object")
    if payload.get("schema") != FULL_COUPON_MANIFEST_SCHEMA:
        raise FullCouponManifestError(
            f"manifest schema must be {FULL_COUPON_MANIFEST_SCHEMA!r}"
        )
    if payload.get("schema_version") != FULL_COUPON_MANIFEST_SCHEMA_VERSION:
        raise FullCouponManifestError(
            f"manifest schema_version must be {FULL_COUPON_MANIFEST_SCHEMA_VERSION!r}"
        )
    campaign_id = _require_text(payload.get("campaign_id"), field="campaign_id")
    if campaign_id != CAMPAIGN_ID:
        raise FullCouponManifestError(f"campaign_id must be {CAMPAIGN_ID!r}")
    manifest_state = _require_text(payload.get("manifest_state"), field="manifest_state")

    raw_members = payload.get("members")
    if not isinstance(raw_members, Sequence) or isinstance(raw_members, (str, bytes)):
        raise FullCouponManifestError("manifest members must be a JSON array")
    if len(raw_members) != EXPECTED_MEMBER_COUNT:
        raise FullCouponManifestError(
            f"canonical manifest must contain exactly {EXPECTED_MEMBER_COUNT} members"
        )

    members: list[FullCouponMember] = []
    seen_keys: set[DatasetMemberKey] = set()
    seen_filenames: set[str] = set()
    seen_hashes: set[str] = set()
    for index, raw in enumerate(raw_members):
        if not isinstance(raw, Mapping):
            raise FullCouponManifestError(f"member entry {index} must be a JSON object")
        member = _parse_member(raw, allow_unresolved_hashes=not require_complete_hashes)
        if member.key.campaign_id != campaign_id:
            raise FullCouponManifestError(
                f"member {member.key.text}: campaign_id differs from manifest campaign"
            )
        if member.key in seen_keys:
            raise FullCouponManifestError(f"duplicate member key: {member.key.text}")
        seen_keys.add(member.key)
        if member.expected_filename in seen_filenames:
            raise FullCouponManifestError(
                f"duplicate expected filename: {member.expected_filename}"
            )
        seen_filenames.add(member.expected_filename)
        if member.sha256 is not None:
            if member.sha256 in seen_hashes:
                raise FullCouponManifestError(
                    f"duplicate file SHA-256 identity: {member.sha256}"
                )
            seen_hashes.add(member.sha256)
        members.append(member)

    expected_keys = {
        DatasetMemberKey(CAMPAIGN_ID, set_id, part, DEFAULT_LAYER_NAME)
        for set_id in ACQUISITION_SET_IDS
        for part in PART_NUMBERS
    }
    if seen_keys != expected_keys:
        missing = sorted(key.text for key in expected_keys - seen_keys)
        extra = sorted(key.text for key in seen_keys - expected_keys)
        raise FullCouponManifestError(
            f"canonical member key coverage mismatch; missing={missing}, unexpected={extra}"
        )

    enabled = [member for member in members if member.enabled]
    if len(enabled) != EXPECTED_MEMBER_COUNT:
        raise FullCouponManifestError("all 24 Patch 20.8 canonical members must be enabled")
    for set_id in ACQUISITION_SET_IDS:
        count = sum(m.key.acquisition_set_id == set_id for m in enabled)
        if count != len(PART_NUMBERS):
            raise FullCouponManifestError(
                f"acquisition set {set_id} must contain exactly six enabled members"
            )
    if any(
        not math.isclose(
            member.spot_diameter_mm,
            EXPECTED_SPOT_DIAMETER_MM,
            rel_tol=0.0,
            abs_tol=1.0e-15,
        )
        for member in enabled
    ):
        raise FullCouponManifestError(
            "Patch 20.8 supplied campaign must retain nominal 0.08 mm spot diameter for every member"
        )

    detached = dict(payload)
    identity_payload = dict(detached)
    identity_payload.pop("manifest_identity", None)
    identity = canonical_sha256(identity_payload)
    declared_identity = payload.get("manifest_identity")
    if declared_identity is not None and str(declared_identity) != identity:
        raise FullCouponManifestError("manifest_identity does not match canonical manifest payload")

    result = FullCouponManifest(
        campaign_id=campaign_id,
        manifest_state=manifest_state,
        members=tuple(
            sorted(
                members,
                key=lambda m: (
                    ACQUISITION_SET_IDS.index(m.key.acquisition_set_id),
                    m.key.part_number,
                    m.key.layer_name,
                ),
            )
        ),
        raw_payload=dict(payload),
        canonical_identity=identity,
    )
    if require_complete_hashes:
        result.require_hash_complete()
    return result


def load_full_coupon_manifest(
    path: str | Path = FULL_COUPON_MANIFEST_PATH,
    *,
    require_complete_hashes: bool = True,
) -> FullCouponManifest:
    """Load the package-owned canonical manifest.

    Execution callers should keep ``require_complete_hashes=True``.  The local
    Patch 20.8 bootstrap runner is the intentional exception and loads the
    bootstrap-state manifest with ``False`` so it can populate missing hashes.
    """

    resolved = Path(path)
    payload = read_json(resolved)
    return validate_full_coupon_manifest_payload(
        payload,
        require_complete_hashes=require_complete_hashes,
    )


def select_manifest_members(
    manifest: FullCouponManifest,
    *,
    acquisition_set_ids: Iterable[str] | None = None,
    parts: Iterable[int] | None = None,
    require_hashes: bool = True,
) -> tuple[FullCouponMember, ...]:
    """Select members without weakening campaign-qualified identity semantics."""

    allowed_sets = None if acquisition_set_ids is None else {str(v) for v in acquisition_set_ids}
    allowed_parts = None if parts is None else {int(v) for v in parts}
    selected = tuple(
        member
        for member in manifest.enabled_members
        if (allowed_sets is None or member.key.acquisition_set_id in allowed_sets)
        and (allowed_parts is None or member.key.part_number in allowed_parts)
    )
    if not selected:
        raise FullCouponManifestError("canonical manifest selection produced zero members")
    if require_hashes:
        unresolved = [member.key.text for member in selected if member.sha256 is None]
        if unresolved:
            raise FullCouponManifestError(
                "selected canonical member(s) lack SHA-256 identity: " + ", ".join(unresolved)
            )
    return selected


def resolve_manifest_files(
    data_directory: str | Path,
    *,
    manifest: FullCouponManifest | None = None,
    members: Sequence[FullCouponMember] | None = None,
    require_exact_directory_membership: bool = False,
) -> tuple[ResolvedCouponMember, ...]:
    """Bind manifest members to exact filenames and verify every SHA-256.

    No globbing is used.  If ``require_exact_directory_membership`` is true,
    the directory must contain exactly the selected HDF5 filenames and no other
    direct ``.h5`` files.
    """

    root = Path(data_directory).expanduser().resolve()
    if not root.is_dir():
        raise FullCouponManifestError(f"coupon data directory does not exist: {root}")
    current = load_full_coupon_manifest() if manifest is None else manifest
    selected = (
        select_manifest_members(current, require_hashes=True)
        if members is None
        else tuple(members)
    )
    if not selected:
        raise FullCouponManifestError("at least one manifest member is required for resolution")
    unresolved = [member.key.text for member in selected if member.sha256 is None]
    if unresolved:
        raise FullCouponManifestError(
            "cannot resolve canonical files with unresolved SHA-256 identities: "
            + ", ".join(unresolved)
        )

    expected_names = {member.expected_filename for member in selected}
    if require_exact_directory_membership:
        observed_names = {
            path.name
            for path in root.iterdir()
            if path.is_file() and path.suffix.lower() == ".h5"
        }
        if observed_names != expected_names:
            missing = sorted(expected_names - observed_names)
            unexpected = sorted(observed_names - expected_names)
            raise FullCouponManifestError(
                f"HDF5 directory membership mismatch; missing={missing}, unexpected={unexpected}"
            )

    resolved: list[ResolvedCouponMember] = []
    seen_paths: set[Path] = set()
    for member in selected:
        path = (root / member.expected_filename).resolve()
        if path.parent != root:
            raise FullCouponManifestError(
                f"canonical expected filename escapes runtime data directory: {member.expected_filename}"
            )
        if not path.is_file():
            raise FullCouponManifestError(
                f"canonical member file is missing: {member.expected_filename}"
            )
        if path in seen_paths:
            raise FullCouponManifestError(f"duplicate runtime file binding: {path.name}")
        seen_paths.add(path)
        actual = sha256_file(path)
        if actual != member.sha256:
            raise FullCouponManifestError(
                f"SHA-256 mismatch for {member.expected_filename}: {actual} != {member.sha256}"
            )
        resolved.append(ResolvedCouponMember(member=member, path=path, actual_sha256=actual))
    return tuple(resolved)


def validate_patch16_registry_semantics(
    registry_payload: Mapping[str, Any],
    manifest: FullCouponManifest,
) -> None:
    """Require the accepted Patch 16 six-member registry to match 20260731.

    This function exists for compatibility/audit only.  It never supplies
    process conditions to current execution.
    """

    rows = registry_payload.get("coupons")
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        raise FullCouponManifestError("Patch 16 registry coupons must be an array")
    by_part = {member.key.part_number: member for member in manifest.members_for_set(LEGACY_ACCEPTED_SET_ID)}
    if set(by_part) != set(PART_NUMBERS):
        raise FullCouponManifestError("canonical 20260731 set is incomplete")
    if len(rows) != len(PART_NUMBERS):
        raise FullCouponManifestError("Patch 16 registry must contain exactly six members")
    for row in rows:
        if not isinstance(row, Mapping):
            raise FullCouponManifestError("Patch 16 registry coupon row must be an object")
        part = int(row.get("coupon_id", -1))
        if part not in by_part:
            raise FullCouponManifestError(f"Patch 16 registry contains unexpected coupon_id {part}")
        current = by_part[part]
        comparisons = {
            "laser_power_W": (float(row["laser_power_W"]), current.nominal_power_W),
            "scan_speed_mm_s": (float(row["scan_speed_mm_s"]), current.nominal_speed_mm_s),
            "spot_diameter_mm": (float(row["spot_diameter_mm"]), current.spot_diameter_mm),
        }
        for field, (legacy, canonical) in comparisons.items():
            if not math.isclose(legacy, canonical, rel_tol=0.0, abs_tol=1.0e-12):
                raise FullCouponManifestError(
                    f"legacy/current process-condition conflict for 20260731 part {part}: "
                    f"{field} {legacy} != {canonical}"
                )
        legacy_hash = _normalize_sha256(
            row.get("sha256"), field=f"Patch16 coupon {part}.sha256", allow_unresolved=False
        )
        if legacy_hash != current.sha256:
            raise FullCouponManifestError(
                f"legacy/current SHA-256 conflict for 20260731 part {part}"
            )


def validate_patch13_manifest_semantics(
    legacy_payload: Mapping[str, Any],
    manifest: FullCouponManifest,
) -> None:
    """Detect semantic conflicts in the superseded Patch 13 process mapping.

    The Patch 13 manifest remains historical/read-compatibility evidence.  Any
    attempt to use its process mapping as if it were current must pass this
    semantic comparison; the known conflicting historical payload therefore
    fails closed rather than silently overriding the canonical campaign data.
    """

    rows = legacy_payload.get("coupons")
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        raise FullCouponManifestError("Patch 13 coupon manifest coupons must be an array")
    by_part = {member.key.part_number: member for member in manifest.members_for_set(LEGACY_ACCEPTED_SET_ID)}
    for row in rows:
        if not isinstance(row, Mapping):
            raise FullCouponManifestError("Patch 13 coupon row must be an object")
        part = int(row.get("coupon_id", -1))
        if part not in by_part:
            raise FullCouponManifestError(f"Patch 13 manifest contains unexpected coupon_id {part}")
        current = by_part[part]
        checks = {
            "power_W": (float(row["power_W"]), current.nominal_power_W),
            "travel_speed_mm_s": (float(row["travel_speed_mm_s"]), current.nominal_speed_mm_s),
            "spot_size_mm": (float(row["spot_size_mm"]), current.spot_diameter_mm),
        }
        for field, (legacy, canonical) in checks.items():
            if not math.isclose(legacy, canonical, rel_tol=0.0, abs_tol=1.0e-12):
                raise FullCouponManifestError(
                    f"legacy/current process-condition conflict for 20260731 part {part}: "
                    f"{field} {legacy} != {canonical}"
                )


__all__ = [
    "ACQUISITION_SET_IDS",
    "CAMPAIGN_ID",
    "DEFAULT_LAYER_NAME",
    "EXPECTED_MEMBER_COUNT",
    "EXPECTED_SPOT_DIAMETER_MM",
    "FULL_COUPON_MANIFEST_PATH",
    "FULL_COUPON_MANIFEST_SCHEMA",
    "FULL_COUPON_MANIFEST_SCHEMA_VERSION",
    "LEGACY_ACCEPTED_SET_ID",
    "PART_NUMBERS",
    "DatasetMemberKey",
    "FullCouponManifest",
    "FullCouponManifestError",
    "FullCouponMember",
    "ResolvedCouponMember",
    "load_full_coupon_manifest",
    "resolve_manifest_files",
    "select_manifest_members",
    "validate_full_coupon_manifest_payload",
    "validate_patch13_manifest_semantics",
    "validate_patch16_registry_semantics",
]
