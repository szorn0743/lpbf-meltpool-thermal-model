"""Patch 21.3.0 hierarchical experimental-observation characterization.

This module is deliberately separate from the Patch 21.3 coarse-search path.
It reads the canonical HDF5 camera/process products, writes portable
frame/track/coupon/condition/set summaries, and never enters the thermal
solver or selects parameters.

The extraction layer is read-only and intentionally does not call the thermal
loader's strict synchronization path.  A characterization run must preserve
unmapped and out-of-range camera frames in its inventory so that exclusions
remain auditable.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Mapping, Sequence
import zipfile

import h5py
import numpy as np

from lpbf.data.full_coupon_manifest import (
    DEFAULT_LAYER_NAME,
    FULL_COUPON_MANIFEST_PATH,
    FullCouponManifest,
    FullCouponManifestError,
    ResolvedCouponMember,
    load_full_coupon_manifest,
    resolve_manifest_files,
    select_manifest_members,
)
from lpbf.infrastructure import (
    canonical_sha256,
    sha256_file,
    utc_now_iso,
    write_csv_rows,
    write_json,
    write_json_atomic,
)
from lpbf.model.input_data import (
    PRODUCTION_DAQ_DT_S,
    PRODUCTION_DAQ_FREQUENCY_HZ,
    PRODUCTION_LASER_DRIVE_THRESHOLD,
    compute_scan_track_id,
    decode_h5_names,
)


PATCH_VERSION = "21.3.0"
PATCH_LABEL = "21.3.0"
CHARACTERIZATION_SCHEMA = "lpbf_patch21_3_0_hierarchical_observation_characterization"
CONTRACT_SCHEMA = "lpbf_patch21_3_0_characterization_contract"
RUN_MANIFEST_FILENAME = "PATCH_21_3_0_CHARACTERIZATION_RUN_MANIFEST.json"
FRAME_FILENAME = "frame_observations.csv"
TRACK_FILENAME = "scan_tracks.csv"
COUPON_FILENAME = "coupon_summary.json"
MEMBER_AUDIT_FILENAME = "member_audit.json"
MEMBER_STATUS_FILENAME = "member_status.json"
MEMBER_INDEX_FILENAME = "PATCH_21_3_0_MEMBER_INDEX.csv"
TRACK_INDEX_FILENAME = "PATCH_21_3_0_TRACK_INDEX.csv"
COUPON_SUMMARY_FILENAME = "PATCH_21_3_0_COUPON_SUMMARIES.csv"
CONDITION_SUMMARY_FILENAME = "PATCH_21_3_0_EXACT_CONDITION_SUMMARIES.csv"
SET_SUMMARY_FILENAME = "PATCH_21_3_0_COUPON_SET_SUMMARIES.csv"
SYNC_AUDIT_FILENAME = "PATCH_21_3_0_SYNCHRONIZATION_AUDIT.json"
SCHEMA_REPORT_FILENAME = "PATCH_21_3_0_CHARACTERIZATION_SCHEMA.json"
STATUS_FILENAME = "PATCH_21_3_0_CHARACTERIZATION_STATUS.json"

_MEMBER_TOKEN = re.compile(r"^(?P<set>[0-9]{8})[:/]?(?:part[_-]?)?(?P<part>[0-9]+)$")


class CharacterizationError(RuntimeError):
    """Fail-closed error for the Patch 21.3.0 local characterization contract."""


@dataclass(frozen=True)
class CharacterizationContract:
    """Frozen extraction and aggregation definitions for Patch 21.3.0."""

    layer_name: str = DEFAULT_LAYER_NAME
    image_brightness_threshold: int = 150
    experimental_pixel_size_um: float = 8.0
    laser_drive_threshold: float = PRODUCTION_LASER_DRIVE_THRESHOLD
    process_dt_s: float = PRODUCTION_DAQ_DT_S
    process_frequency_hz: float = PRODUCTION_DAQ_FREQUENCY_HZ
    zero_footprint_policy: str = (
        "retain_if_mapped_laser_on_and_finite_nonnegative_hw; report_explicitly"
    )
    eligible_frame_policy: str = (
        "synchronization-valid_mapped_laser-on_frame_with_finite_nonnegative_H_and_W"
    )
    track_weight_policy: str = "equal_track_weight_within_coupon"
    coupon_weight_policy: str = "equal_coupon_weight_within_exact_condition"
    condition_weight_policy: str = "equal_unique_calibration_condition_weight"
    raw_camera_images_copied: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": CONTRACT_SCHEMA,
            "schema_version": PATCH_VERSION,
            "layer_name": self.layer_name,
            "image_brightness_threshold": int(self.image_brightness_threshold),
            "experimental_measurement_source": (
                "canonical H/W channels already generated for each valid camera frame; "
                "raw camera images are not required for this characterization branch"
            ),
            "experimental_pixel_size_um": float(self.experimental_pixel_size_um),
            "physical_unit_conversion": {
                "H_um": "H_pixels * experimental_pixel_size_um",
                "W_um": "W_pixels * experimental_pixel_size_um",
                "H_mm": "H_um / 1000",
                "W_mm": "W_um / 1000",
            },
            "laser_state": {
                "threshold": float(self.laser_drive_threshold),
                "definition": "Laser Drive > threshold",
                "process_clock": "fixed_200_kHz_DAQ_row_clock",
                "process_dt_s": float(self.process_dt_s),
                "process_frequency_hz": float(self.process_frequency_hz),
                "track_definition": "contiguous powered process-row interval",
            },
            "zero_footprint_policy": self.zero_footprint_policy,
            "eligible_frame_policy": self.eligible_frame_policy,
            "weighting": {
                "frame_within_track": "mean_frame_contribution_within_track",
                "track_within_coupon": self.track_weight_policy,
                "coupon_within_condition": self.coupon_weight_policy,
                "condition_within_objective": self.condition_weight_policy,
            },
            "raw_camera_images_copied": bool(self.raw_camera_images_copied),
            "parameter_selection_performed": False,
            "thermal_simulation_performed": False,
            "validation_used": False,
        }


@dataclass(frozen=True)
class CharacterizationMemberResult:
    """Portable in-memory result for one manifest-bound HDF5 member."""

    resolved: ResolvedCouponMember
    frame_rows: tuple[dict[str, Any], ...]
    track_rows: tuple[dict[str, Any], ...]
    coupon_row: dict[str, Any]
    audit: dict[str, Any]


def _as_python(value: Any) -> Any:
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _as_python(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_as_python(v) for v in value]
    return value


def _finite_or_none(value: Any) -> float | None:
    number = float(value)
    return number if np.isfinite(number) else None


def _safe_mean(values: Sequence[float]) -> float | None:
    return float(np.mean(values)) if values else None


def _safe_median(values: Sequence[float]) -> float | None:
    return float(np.median(values)) if values else None


def _safe_std(values: Sequence[float]) -> float | None:
    if not values:
        return None
    return float(np.std(values, ddof=1)) if len(values) > 1 else 0.0


def _safe_quantile(values: Sequence[float], q: float) -> float | None:
    return float(np.quantile(np.asarray(values, dtype=np.float64), q)) if values else None


def _slope(x_values: Sequence[float], y_values: Sequence[float]) -> tuple[float | None, float | None]:
    if len(x_values) < 2 or len(y_values) != len(x_values):
        return None, None
    x = np.asarray(x_values, dtype=np.float64)
    y = np.asarray(y_values, dtype=np.float64)
    centered = x - float(np.mean(x))
    denominator = float(np.dot(centered, centered))
    if denominator <= 0.0:
        return None, None
    slope = float(np.dot(centered, y - float(np.mean(y))) / denominator)
    fitted = float(np.mean(y)) + slope * centered
    residual = y - fitted
    total = float(np.dot(y - float(np.mean(y)), y - float(np.mean(y))))
    r2 = 0.0 if total <= 0.0 else float(1.0 - np.dot(residual, residual) / total)
    return slope, r2


def _track_bounds(track_ids: np.ndarray) -> dict[int, tuple[int, int]]:
    bounds: dict[int, tuple[int, int]] = {}
    for track_id in sorted(int(v) for v in np.unique(track_ids) if int(v) > 0):
        indices = np.flatnonzero(track_ids == track_id)
        bounds[track_id] = (int(indices[0]), int(indices[-1]))
    return bounds


def _stats(prefix: str, values: Sequence[float]) -> dict[str, Any]:
    return {
        f"{prefix}_count": int(len(values)),
        f"{prefix}_mean": _safe_mean(values),
        f"{prefix}_median": _safe_median(values),
        f"{prefix}_std": _safe_std(values),
        f"{prefix}_min": float(min(values)) if values else None,
        f"{prefix}_max": float(max(values)) if values else None,
        f"{prefix}_q05": _safe_quantile(values, 0.05),
        f"{prefix}_q25": _safe_quantile(values, 0.25),
        f"{prefix}_q75": _safe_quantile(values, 0.75),
        f"{prefix}_q95": _safe_quantile(values, 0.95),
    }


def _member_identity(resolved: ResolvedCouponMember) -> dict[str, Any]:
    member = resolved.member
    return {
        "campaign_id": member.key.campaign_id,
        "acquisition_set_id": member.key.acquisition_set_id,
        "part_number": int(member.key.part_number),
        "layer_name": member.key.layer_name,
        "expected_filename": member.expected_filename,
        "file_sha256": resolved.actual_sha256,
        "nominal_power_W": float(member.nominal_power_W),
        "nominal_speed_mm_s": float(member.nominal_speed_mm_s),
        "spot_diameter_mm": float(member.spot_diameter_mm),
        "candidate_replicate_group": member.candidate_replicate_group,
        "sweep_group": member.sweep_group,
    }


def _load_required_member_arrays(
    path: Path,
    *,
    contract: CharacterizationContract,
) -> dict[str, Any]:
    """Read only the required channels and synchronization products."""
    with h5py.File(path, "r") as h5_file:
        if contract.layer_name not in h5_file or not isinstance(h5_file[contract.layer_name], h5py.Group):
            raise CharacterizationError(f"required layer {contract.layer_name!r} is absent")
        group = h5_file[contract.layer_name]
        if "names" not in group or "data" not in group:
            raise CharacterizationError("layer must contain 'names' and 'data' datasets")
        names = decode_h5_names(group["names"][:])
        data = group["data"]
        if data.ndim != 2 or data.shape[0] != len(names):
            raise CharacterizationError("layer data must have one row per channel name")
        required = ("Laser Drive", "H", "W")
        missing = [name for name in required if name not in names]
        if missing:
            raise CharacterizationError("missing required characterization channel(s): " + ", ".join(missing))

        arrays = {
            name: np.asarray(data[names.index(name), :], dtype=np.float64).reshape(-1)
            for name in required
        }
        gige_time = (
            np.asarray(group["gige_time"][:], dtype=np.float64).reshape(-1)
            if "gige_time" in group
            else None
        )
        sync = group.get("sync")
        mapping = (
            np.asarray(sync["gige_image_to_data_index"][:]).reshape(-1)
            if isinstance(sync, h5py.Group) and "gige_image_to_data_index" in sync
            else None
        )
        sync_time = (
            np.asarray(sync["data_to_gige_time"][:], dtype=np.float64).reshape(-1)
            if isinstance(sync, h5py.Group) and "data_to_gige_time" in sync
            else None
        )
        sync_attrs = {}
        if isinstance(sync, h5py.Group):
            for key in ("method", "sync_gige_to_data_version"):
                if key in sync.attrs:
                    value = sync.attrs[key]
                    if isinstance(value, bytes):
                        value = value.decode("utf-8", errors="replace")
                    sync_attrs[key] = str(value)

    if gige_time is None or mapping is None:
        raise CharacterizationError(
            "required camera synchronization products 'gige_time' and "
            "'sync/gige_image_to_data_index' are absent"
        )
    if gige_time.size != mapping.size:
        raise CharacterizationError(
            f"camera synchronization length mismatch: gige_time={gige_time.size}, mapping={mapping.size}"
        )
    if mapping.size and not np.issubdtype(mapping.dtype, np.integer):
        if not np.all(np.isfinite(mapping)) or not np.all(mapping == np.rint(mapping)):
            raise CharacterizationError("camera mapping must contain finite integer-valued rows")
        mapping = np.rint(mapping).astype(np.int64)
    else:
        mapping = mapping.astype(np.int64, copy=False)
    if not np.all(np.isfinite(gige_time)):
        raise CharacterizationError("gige_time contains non-finite timestamps")
    if gige_time.size > 1 and np.any(np.diff(gige_time) <= 0.0):
        raise CharacterizationError("gige_time must be strictly increasing")
    drive = arrays["Laser Drive"]
    finite_drive = np.isfinite(drive)
    laser_on = finite_drive & (drive > float(contract.laser_drive_threshold))
    track_ids = compute_scan_track_id(laser_on)
    return {
        "names": names,
        "n_process_rows": int(drive.size),
        "laser_drive": drive,
        "h_pixels": arrays["H"],
        "w_pixels": arrays["W"],
        "gige_time_s": gige_time,
        "mapping": mapping,
        "laser_on": laser_on,
        "scan_track_id": track_ids,
        "sync_time_s": sync_time,
        "sync_attrs": sync_attrs,
        "nonfinite_process_counts": {
            name: int(np.count_nonzero(~np.isfinite(values)))
            for name, values in arrays.items()
        },
    }


def _frame_rows(
    arrays: Mapping[str, Any],
    *,
    resolved: ResolvedCouponMember,
    contract: CharacterizationContract,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    mapping = np.asarray(arrays["mapping"], dtype=np.int64)
    gige_time = np.asarray(arrays["gige_time_s"], dtype=np.float64)
    n_rows = int(arrays["n_process_rows"])
    drive = np.asarray(arrays["laser_drive"], dtype=np.float64)
    h_process = np.asarray(arrays["h_pixels"], dtype=np.float64)
    w_process = np.asarray(arrays["w_pixels"], dtype=np.float64)
    track_ids = np.asarray(arrays["scan_track_id"], dtype=np.int64)
    valid_mapping = (mapping >= 0) & (mapping < n_rows)
    mapped_rows = mapping[valid_mapping]
    repeated_unique = 0
    repeated_extra = 0
    if mapped_rows.size:
        _, counts = np.unique(mapped_rows, return_counts=True)
        repeated_unique = int(np.count_nonzero(counts > 1))
        repeated_extra = int(np.sum(counts[counts > 1] - 1))

    rows: list[dict[str, Any]] = []
    for frame_index in range(mapping.size):
        mapped = int(mapping[frame_index])
        row: dict[str, Any] = {
            "schema": CHARACTERIZATION_SCHEMA,
            "schema_version": PATCH_VERSION,
            "campaign_id": resolved.member.key.campaign_id,
            "acquisition_set_id": resolved.member.key.acquisition_set_id,
            "part_number": int(resolved.member.key.part_number),
            "layer_name": resolved.member.key.layer_name,
            "portable_member_identity": resolved.member.portable_identity_text,
            "frame_index": int(frame_index),
            "gige_time_s": _finite_or_none(gige_time[frame_index]),
            "mapped_process_row": mapped if 0 <= mapped < n_rows else None,
            "mapping_status": (
                "valid_mapped"
                if 0 <= mapped < n_rows
                else "unmapped_negative"
                if mapped < 0
                else "mapped_out_of_range"
            ),
            "laser_drive": None,
            "laser_on": False,
            "scan_track_id": 0,
            "H_pixels": None,
            "W_pixels": None,
            "H_um": None,
            "W_um": None,
            "H_mm": None,
            "W_mm": None,
            "hw_status": "not_mapped",
            "eligible_melt_pool_observation": False,
            "eligibility_reason": "not_mapped",
        }
        if 0 <= mapped < n_rows:
            h_value = float(h_process[mapped])
            w_value = float(w_process[mapped])
            laser_value = float(drive[mapped])
            laser_on = bool(arrays["laser_on"][mapped])
            track_id = int(track_ids[mapped])
            finite_hw = bool(np.isfinite(h_value) and np.isfinite(w_value))
            nonnegative_hw = bool(finite_hw and h_value >= 0.0 and w_value >= 0.0)
            zero_footprint = bool(nonnegative_hw and (h_value == 0.0 or w_value == 0.0))
            if not finite_hw:
                hw_status = "nonfinite"
            elif h_value < 0.0 or w_value < 0.0:
                hw_status = "negative"
            elif zero_footprint:
                hw_status = "zero_footprint"
            else:
                hw_status = "positive"
            eligible = bool(laser_on and nonnegative_hw and track_id > 0)
            if not finite_hw or h_value < 0.0 or w_value < 0.0:
                reason = "invalid_H_or_W"
            elif not laser_on:
                reason = "laser_off"
            elif track_id <= 0:
                reason = "powered_row_without_track"
            elif zero_footprint:
                reason = "eligible_zero_footprint"
            else:
                reason = "eligible_positive_H_W"
            row.update(
                {
                    "laser_drive": _finite_or_none(laser_value),
                    "laser_on": laser_on,
                    "scan_track_id": track_id,
                    "H_pixels": _finite_or_none(h_value),
                    "W_pixels": _finite_or_none(w_value),
                    "H_um": float(h_value * contract.experimental_pixel_size_um) if np.isfinite(h_value) else None,
                    "W_um": float(w_value * contract.experimental_pixel_size_um) if np.isfinite(w_value) else None,
                    "H_mm": float(h_value * contract.experimental_pixel_size_um / 1000.0) if np.isfinite(h_value) else None,
                    "W_mm": float(w_value * contract.experimental_pixel_size_um / 1000.0) if np.isfinite(w_value) else None,
                    "hw_status": hw_status,
                    "eligible_melt_pool_observation": eligible,
                    "eligibility_reason": reason,
                }
            )
        rows.append(row)

    audit = {
        "raw_camera_frame_count": int(mapping.size),
        "synchronization_valid_frame_count": int(np.count_nonzero(valid_mapping)),
        "unmapped_camera_frame_count": int(np.count_nonzero(mapping < 0)),
        "out_of_range_mapped_frame_count": int(np.count_nonzero(mapping >= n_rows)),
        "repeated_mapped_process_row_unique_count": repeated_unique,
        "repeated_mapped_process_row_extra_frame_count": repeated_extra,
        "laser_on_mapped_frame_count": int(sum(bool(row["laser_on"]) for row in rows if row["mapping_status"] == "valid_mapped")),
        "eligible_melt_pool_frame_count": int(sum(bool(row["eligible_melt_pool_observation"]) for row in rows)),
        "positive_H_W_frame_count": int(sum(row["eligibility_reason"] == "eligible_positive_H_W" for row in rows)),
        "zero_footprint_frame_count": int(sum(row["eligibility_reason"] == "eligible_zero_footprint" for row in rows)),
        "invalid_H_W_frame_count": int(sum(row["hw_status"] in {"nonfinite", "negative"} for row in rows)),
        "laser_off_mapped_frame_count": int(sum(row["eligibility_reason"] == "laser_off" for row in rows)),
        "process_rows_outside_camera_window": int(np.count_nonzero(mapping >= n_rows)),
        "camera_timestamp_finite": bool(np.all(np.isfinite(gige_time))),
        "camera_timestamp_strictly_increasing": bool(gige_time.size < 2 or np.all(np.diff(gige_time) > 0.0)),
        "expected_mapping_rule": "negative values are unmapped; nonnegative values index process rows",
    }
    return rows, audit


def _track_rows(
    frame_rows: Sequence[Mapping[str, Any]],
    arrays: Mapping[str, Any],
    *,
    resolved: ResolvedCouponMember,
    contract: CharacterizationContract,
) -> list[dict[str, Any]]:
    track_ids = np.asarray(arrays["scan_track_id"], dtype=np.int64)
    bounds = _track_bounds(track_ids)
    by_track: dict[int, list[Mapping[str, Any]]] = {track: [] for track in bounds}
    for row in frame_rows:
        track = int(row["scan_track_id"])
        if track > 0 and row["mapping_status"] == "valid_mapped":
            by_track.setdefault(track, []).append(row)

    out: list[dict[str, Any]] = []
    for track_id in sorted(bounds):
        start, end = bounds[track_id]
        mapped = by_track.get(track_id, [])
        if not mapped:
            continue
        eligible = [row for row in mapped if bool(row["eligible_melt_pool_observation"])]
        h = [float(row["H_pixels"]) for row in eligible if row["H_pixels"] is not None]
        w = [float(row["W_pixels"]) for row in eligible if row["W_pixels"] is not None]
        h_um = [value * contract.experimental_pixel_size_um for value in h]
        w_um = [value * contract.experimental_pixel_size_um for value in w]
        mapped_times = [float(row["gige_time_s"]) for row in mapped if row["gige_time_s"] is not None]
        row: dict[str, Any] = {
            "schema": CHARACTERIZATION_SCHEMA,
            "schema_version": PATCH_VERSION,
            "campaign_id": resolved.member.key.campaign_id,
            "acquisition_set_id": resolved.member.key.acquisition_set_id,
            "part_number": int(resolved.member.key.part_number),
            "layer_name": resolved.member.key.layer_name,
            "portable_member_identity": resolved.member.portable_identity_text,
            "scan_track_id": int(track_id),
            "process_row_start": int(start),
            "process_row_end": int(end),
            "process_row_count": int(end - start + 1),
            "track_duration_s": float((end - start) * contract.process_dt_s),
            "mapped_camera_frame_count": int(len(mapped)),
            "mapped_camera_duration_s": float(max(mapped_times) - min(mapped_times)) if len(mapped_times) > 1 else 0.0 if mapped_times else None,
            "eligible_frame_count": int(len(eligible)),
            "positive_H_W_frame_count": int(sum(row["eligibility_reason"] == "eligible_positive_H_W" for row in eligible)),
            "zero_footprint_frame_count": int(sum(row["eligibility_reason"] == "eligible_zero_footprint" for row in eligible)),
            "zero_footprint_fraction": float(sum(row["eligibility_reason"] == "eligible_zero_footprint" for row in eligible) / len(eligible)) if eligible else None,
            "observation_bearing": bool(mapped),
            "minimum_frame_requirement": "none_for_characterization; insufficient_frame_tracks_are_retained_and_flagged",
            "residuals_available": False,
            "simulated_H_pixels": None,
            "simulated_W_pixels": None,
        }
        row.update(_stats("H_pixels", h))
        row.update(_stats("W_pixels", w))
        row.update(_stats("H_um", h_um))
        row.update(_stats("W_um", w_um))
        h_slope, h_r2 = _slope([float(item["mapped_process_row"]) for item in eligible], h)
        w_slope, w_r2 = _slope([float(item["mapped_process_row"]) for item in eligible], w)
        row.update(
            {
                "H_temporal_slope_pixels_per_process_row": h_slope,
                "W_temporal_slope_pixels_per_process_row": w_slope,
                "H_temporal_trend_r2": h_r2,
                "W_temporal_trend_r2": w_r2,
                "temporal_trend_frame_count": int(len(eligible)),
            }
        )
        for label, index in (("early", 0), ("middle", (len(eligible) - 1) // 2), ("late", -1)):
            if eligible:
                selected = eligible[index]
                row[f"{label}_frame_index"] = int(selected["frame_index"])
                row[f"{label}_mapped_process_row"] = int(selected["mapped_process_row"])
                row[f"{label}_H_pixels"] = selected["H_pixels"]
                row[f"{label}_W_pixels"] = selected["W_pixels"]
            else:
                row[f"{label}_frame_index"] = None
                row[f"{label}_mapped_process_row"] = None
                row[f"{label}_H_pixels"] = None
                row[f"{label}_W_pixels"] = None
        out.append(row)
    return out


def _coupon_row(
    frame_rows: Sequence[Mapping[str, Any]],
    track_rows: Sequence[Mapping[str, Any]],
    *,
    resolved: ResolvedCouponMember,
    contract: CharacterizationContract,
) -> dict[str, Any]:
    eligible = [row for row in frame_rows if bool(row["eligible_melt_pool_observation"])]
    tracks = [row for row in track_rows if int(row["eligible_frame_count"]) > 0]
    h = [float(row["H_pixels"]) for row in eligible if row["H_pixels"] is not None]
    w = [float(row["W_pixels"]) for row in eligible if row["W_pixels"] is not None]
    track_h = [float(row["H_pixels_mean"]) for row in tracks if row["H_pixels_mean"] is not None]
    track_w = [float(row["W_pixels_mean"]) for row in tracks if row["W_pixels_mean"] is not None]
    track_ids = [float(row["scan_track_id"]) for row in tracks]
    h_track_slope, h_track_r2 = _slope(track_ids, track_h)
    w_track_slope, w_track_r2 = _slope(track_ids, track_w)
    member = resolved.member
    row: dict[str, Any] = {
        "schema": CHARACTERIZATION_SCHEMA,
        "schema_version": PATCH_VERSION,
        "campaign_id": member.key.campaign_id,
        "acquisition_set_id": member.key.acquisition_set_id,
        "part_number": int(member.key.part_number),
        "layer_name": member.key.layer_name,
        "portable_member_identity": resolved.member.portable_identity_text,
        "file_sha256": resolved.actual_sha256,
        "filename": member.expected_filename,
        "power_W": float(member.nominal_power_W),
        "speed_mm_s": float(member.nominal_speed_mm_s),
        "candidate_replicate_group": member.candidate_replicate_group,
        "sweep_group": member.sweep_group,
        "raw_frame_count": int(len(frame_rows)),
        "synchronization_valid_frame_count": int(sum(row["mapping_status"] == "valid_mapped" for row in frame_rows)),
        "eligible_frame_count": int(len(eligible)),
        "positive_H_W_frame_count": int(sum(row["eligibility_reason"] == "eligible_positive_H_W" for row in eligible)),
        "zero_footprint_frame_count": int(sum(row["eligibility_reason"] == "eligible_zero_footprint" for row in eligible)),
        "observation_bearing_track_count": int(len(track_rows)),
        "eligible_track_count": int(len(tracks)),
        "equal_track_weighted_H_pixels": _safe_mean(track_h),
        "equal_track_weighted_W_pixels": _safe_mean(track_w),
        "pooled_frame_H_pixels_mean": _safe_mean(h),
        "pooled_frame_W_pixels_mean": _safe_mean(w),
        "pooled_frame_H_pixels_median": _safe_median(h),
        "pooled_frame_W_pixels_median": _safe_median(w),
        "track_to_track_H_pixels_std": _safe_std(track_h),
        "track_to_track_W_pixels_std": _safe_std(track_w),
        "within_track_H_pixels_std_mean": _safe_mean([float(row["H_pixels_std"]) for row in tracks if row["H_pixels_std"] is not None]),
        "within_track_W_pixels_std_mean": _safe_mean([float(row["W_pixels_std"]) for row in tracks if row["W_pixels_std"] is not None]),
        "H_track_evolution_slope_pixels_per_track": h_track_slope,
        "W_track_evolution_slope_pixels_per_track": w_track_slope,
        "H_track_evolution_r2": h_track_r2,
        "W_track_evolution_r2": w_track_r2,
    }
    for name in (
        "equal_track_weighted_H_pixels",
        "equal_track_weighted_W_pixels",
        "pooled_frame_H_pixels_mean",
        "pooled_frame_W_pixels_mean",
        "pooled_frame_H_pixels_median",
        "pooled_frame_W_pixels_median",
        "track_to_track_H_pixels_std",
        "track_to_track_W_pixels_std",
        "within_track_H_pixels_std_mean",
        "within_track_W_pixels_std_mean",
    ):
        value = row[name]
        row[name.replace("_pixels", "_um")] = None if value is None else float(value) * contract.experimental_pixel_size_um
        row[name.replace("_pixels", "_mm")] = None if value is None else float(value) * contract.experimental_pixel_size_um / 1000.0
    row.update(_stats("eligible_H_pixels", h))
    row.update(_stats("eligible_W_pixels", w))
    row.update(_stats("eligible_H_um", [value * contract.experimental_pixel_size_um for value in h]))
    row.update(_stats("eligible_W_um", [value * contract.experimental_pixel_size_um for value in w]))
    return row


def characterize_member(
    resolved: ResolvedCouponMember,
    *,
    contract: CharacterizationContract = CharacterizationContract(),
) -> CharacterizationMemberResult:
    """Characterize one exact manifest-bound HDF5 member without simulation."""
    if str(contract.layer_name) != str(resolved.member.key.layer_name):
        raise CharacterizationError(
            "characterization layer does not match the canonical member identity: "
            f"{contract.layer_name!r} != {resolved.member.key.layer_name!r}"
        )
    arrays = _load_required_member_arrays(resolved.path, contract=contract)
    frame_rows, sync_audit = _frame_rows(arrays, resolved=resolved, contract=contract)
    track_rows = _track_rows(frame_rows, arrays, resolved=resolved, contract=contract)
    coupon_row = _coupon_row(frame_rows, track_rows, resolved=resolved, contract=contract)
    powered_rows = int(np.count_nonzero(arrays["laser_on"]))
    track_count = int(np.max(arrays["scan_track_id"])) if arrays["scan_track_id"].size else 0
    audit = {
        "schema": CHARACTERIZATION_SCHEMA,
        "schema_version": PATCH_VERSION,
        "status": "PASS",
        "member": _member_identity(resolved),
        "input_file_size_bytes": int(resolved.path.stat().st_size),
        "input_file_sha256": sha256_file(resolved.path),
        "hdf5_schema": {
            "layer_name": contract.layer_name,
            "process_row_count": int(arrays["n_process_rows"]),
            "channel_names": list(arrays["names"]),
            "required_channels": ["Laser Drive", "H", "W"],
            "camera_timestamp_dataset": f"{contract.layer_name}/gige_time",
            "mapping_dataset": f"{contract.layer_name}/sync/gige_image_to_data_index",
            "synchronized_process_time_dataset": f"{contract.layer_name}/sync/data_to_gige_time",
        },
        "laser_state": {
            "threshold": float(contract.laser_drive_threshold),
            "definition": "Laser Drive > 2.5 V",
            "powered_process_row_count": powered_rows,
            "scan_track_count": track_count,
            "observation_bearing_track_count": int(len(track_rows)),
        },
        "camera_sync": sync_audit,
        "synchronization_metadata": {
            "method": arrays["sync_attrs"].get("method"),
            "version": arrays["sync_attrs"].get("sync_gige_to_data_version"),
            "diagnostic_process_time_available": arrays["sync_time_s"] is not None,
            "diagnostic_process_time_row_aligned": bool(
                arrays["sync_time_s"] is not None
                and arrays["sync_time_s"].size == arrays["n_process_rows"]
            ),
        },
        "measurement_validity": {
            "rule": contract.eligible_frame_policy,
            "zero_footprint_policy": contract.zero_footprint_policy,
            "H_W_units_native": "pixels",
            "H_W_units_physical": "um and mm",
            "experimental_pixel_size_um": float(contract.experimental_pixel_size_um),
            **{key: value for key, value in sync_audit.items() if key.endswith("_frame_count") or key.endswith("_count")},
        },
        "process_channel_nonfinite_counts": arrays["nonfinite_process_counts"],
        "raw_camera_images_copied": False,
        "thermal_simulation_performed": False,
        "parameter_selection_performed": False,
        "validation_used": False,
    }
    return CharacterizationMemberResult(
        resolved=resolved,
        frame_rows=tuple(_as_python(row) for row in frame_rows),
        track_rows=tuple(_as_python(row) for row in track_rows),
        coupon_row=_as_python(coupon_row),
        audit=_as_python(audit),
    )


def _group_key(row: Mapping[str, Any]) -> tuple[float, float]:
    return float(row["power_W"]), float(row["speed_mm_s"])


def _aggregate_rows(
    coupon_rows: Sequence[Mapping[str, Any]],
    *,
    resolved_members: Sequence[ResolvedCouponMember],
    requested_member_count: int,
    level: str,
    experimental_pixel_size_um: float = 8.0,
) -> list[dict[str, Any]]:
    if level == "condition":
        groups: dict[tuple[float, float], list[Mapping[str, Any]]] = {}
        for row in coupon_rows:
            groups.setdefault(_group_key(row), []).append(row)
        expected: dict[tuple[float, float], int] = {}
        for member in resolved_members:
            expected.setdefault((float(member.member.nominal_power_W), float(member.member.nominal_speed_mm_s)), 0)
            expected[_group_key({"power_W": member.member.nominal_power_W, "speed_mm_s": member.member.nominal_speed_mm_s})] += 1
        rows: list[dict[str, Any]] = []
        for (power, speed), members in sorted(expected.items()):
            successful = groups.get((power, speed), [])
            rows.append(_aggregate_group(
                successful,
                group_fields={
                    "exact_condition_id": f"P{power:g}_V{speed:g}",
                    "power_W": power,
                    "speed_mm_s": speed,
                    "acquisition_set_ids": sorted({str(row["acquisition_set_id"]) for row in successful}),
                },
                expected_count=members,
                level="exact_nominal_process_condition",
                experimental_pixel_size_um=experimental_pixel_size_um,
            ))
        return rows
    groups_by_set: dict[str, list[Mapping[str, Any]]] = {}
    for row in coupon_rows:
        groups_by_set.setdefault(str(row["acquisition_set_id"]), []).append(row)
    expected_by_set: dict[str, list[ResolvedCouponMember]] = {}
    for member in resolved_members:
        expected_by_set.setdefault(str(member.member.key.acquisition_set_id), []).append(member)
    return [
        _aggregate_group(
            groups_by_set.get(set_id, []),
            group_fields={
                "acquisition_set_id": set_id,
                "condition_count": len({
                    (float(member.member.nominal_power_W), float(member.member.nominal_speed_mm_s))
                    for member in expected_by_set[set_id]
                }),
            },
            expected_count=len(expected_by_set[set_id]),
            level="acquisition_set",
            experimental_pixel_size_um=experimental_pixel_size_um,
        )
        for set_id in sorted(expected_by_set)
    ]


def _aggregate_group(
    rows: Sequence[Mapping[str, Any]],
    *,
    group_fields: Mapping[str, Any],
    expected_count: int,
    level: str,
    experimental_pixel_size_um: float = 8.0,
) -> dict[str, Any]:
    h_values = [float(row["equal_track_weighted_H_pixels"]) for row in rows if row["equal_track_weighted_H_pixels"] is not None]
    w_values = [float(row["equal_track_weighted_W_pixels"]) for row in rows if row["equal_track_weighted_W_pixels"] is not None]
    result: dict[str, Any] = {
        "schema": CHARACTERIZATION_SCHEMA,
        "schema_version": PATCH_VERSION,
        "aggregation_level": level,
        **dict(group_fields),
        "expected_coupon_count": int(expected_count),
        "successful_coupon_count": int(len(rows)),
        "failed_or_unavailable_coupon_count": int(max(0, expected_count - len(rows))),
        "equal_coupon_weighted_H_pixels": _safe_mean(h_values),
        "equal_coupon_weighted_W_pixels": _safe_mean(w_values),
        "coupon_to_coupon_H_pixels_std": _safe_std(h_values),
        "coupon_to_coupon_W_pixels_std": _safe_std(w_values),
        "contributing_frame_count": int(sum(int(row["eligible_frame_count"]) for row in rows)),
        "contributing_track_count": int(sum(int(row["eligible_track_count"]) for row in rows)),
        "member_identities": sorted(str(row["portable_member_identity"]) for row in rows),
    }
    for name in (
        "equal_coupon_weighted_H_pixels",
        "equal_coupon_weighted_W_pixels",
        "coupon_to_coupon_H_pixels_std",
        "coupon_to_coupon_W_pixels_std",
    ):
        value = result[name]
        result[name.replace("_pixels", "_um")] = (
            None if value is None else float(value) * experimental_pixel_size_um
        )
        result[name.replace("_pixels", "_mm")] = (
            None if value is None else float(value) * experimental_pixel_size_um / 1000.0
        )
    return result


def _member_directory_name(resolved: ResolvedCouponMember) -> str:
    member = resolved.member
    return f"{member.key.acquisition_set_id}_part_{member.key.part_number}_{member.key.layer_name}"


def _read_json(path: Path) -> dict[str, Any]:
    import json

    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise CharacterizationError(f"expected JSON object: {path}")
    return value


def _write_member_result(output: Path, result: CharacterizationMemberResult) -> None:
    member_dir = output / "members" / _member_directory_name(result.resolved)
    member_dir.mkdir(parents=True, exist_ok=True)
    write_csv_rows(member_dir / FRAME_FILENAME, list(result.frame_rows))
    write_csv_rows(member_dir / TRACK_FILENAME, list(result.track_rows))
    write_json(member_dir / COUPON_FILENAME, result.coupon_row)
    write_json(member_dir / MEMBER_AUDIT_FILENAME, result.audit)
    write_json(member_dir / MEMBER_STATUS_FILENAME, {
        "schema": "lpbf_patch21_3_0_member_status",
        "schema_version": PATCH_VERSION,
        "status": "PASS",
        "portable_member_identity": result.resolved.member.portable_identity_text,
        "file_sha256": result.resolved.actual_sha256,
        "frame_file": FRAME_FILENAME,
        "track_file": TRACK_FILENAME,
        "coupon_file": COUPON_FILENAME,
        "audit_file": MEMBER_AUDIT_FILENAME,
    })


def _read_csv_rows(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _load_resumable_member(
    output: Path,
    resolved: ResolvedCouponMember,
) -> tuple[dict[str, Any], tuple[dict[str, Any], ...], dict[str, Any]] | None:
    member_dir = output / "members" / _member_directory_name(resolved)
    status_path = member_dir / MEMBER_STATUS_FILENAME
    coupon_path = member_dir / COUPON_FILENAME
    track_path = member_dir / TRACK_FILENAME
    audit_path = member_dir / MEMBER_AUDIT_FILENAME
    if not status_path.is_file() or not coupon_path.is_file() or not track_path.is_file() or not audit_path.is_file():
        return None
    try:
        status = _read_json(status_path)
        if status.get("status") != "PASS" or status.get("file_sha256") != resolved.actual_sha256:
            return None
        return _read_json(coupon_path), tuple(_read_csv_rows(track_path)), _read_json(audit_path)
    except Exception:
        return None


def _write_aggregate_outputs(
    output: Path,
    *,
    resolved: Sequence[ResolvedCouponMember],
    successful: Sequence[CharacterizationMemberResult],
    failures: Sequence[Mapping[str, Any]],
    contract: CharacterizationContract,
) -> None:
    coupon_rows = [dict(result.coupon_row) for result in successful]
    write_csv_rows(output / COUPON_SUMMARY_FILENAME, coupon_rows)
    write_csv_rows(output / MEMBER_INDEX_FILENAME, [
        {
            "portable_member_identity": member.member.portable_identity_text,
            "acquisition_set_id": member.member.key.acquisition_set_id,
            "part_number": int(member.member.key.part_number),
            "filename": member.member.expected_filename,
            "file_sha256": member.actual_sha256,
            "status": "PASS" if any(result.resolved.member.portable_identity_text == member.member.portable_identity_text for result in successful) else "FAIL",
            "member_directory": _member_directory_name(member),
        }
        for member in resolved
    ] + [dict(item) for item in failures])
    track_rows = [track for result in successful for track in result.track_rows]
    write_csv_rows(output / TRACK_INDEX_FILENAME, track_rows)
    write_csv_rows(output / CONDITION_SUMMARY_FILENAME, _aggregate_rows(
        coupon_rows,
        resolved_members=resolved,
        requested_member_count=len(resolved),
        level="condition",
        experimental_pixel_size_um=contract.experimental_pixel_size_um,
    ))
    write_csv_rows(output / SET_SUMMARY_FILENAME, _aggregate_rows(
        coupon_rows,
        resolved_members=resolved,
        requested_member_count=len(resolved),
        level="set",
        experimental_pixel_size_um=contract.experimental_pixel_size_um,
    ))
    sync_records = []
    for result in successful:
        record = dict(result.audit)
        record["member"] = _member_identity(result.resolved)
        sync_records.append({
            "member": record["member"],
            "camera_sync": record["camera_sync"],
            "synchronization_metadata": record["synchronization_metadata"],
        })
    write_json(output / SYNC_AUDIT_FILENAME, {
        "schema": "lpbf_patch21_3_0_synchronization_audit",
        "schema_version": PATCH_VERSION,
        "records": sync_records,
        "failures": list(failures),
    })
    write_json(output / SCHEMA_REPORT_FILENAME, {
        "schema": CHARACTERIZATION_SCHEMA,
        "schema_version": PATCH_VERSION,
        "contract": contract.to_dict(),
        "output_files": {
            "frame_observations": "members/*/frame_observations.csv",
            "scan_tracks": "members/*/scan_tracks.csv",
            "coupon_summaries": COUPON_SUMMARY_FILENAME,
            "exact_condition_summaries": CONDITION_SUMMARY_FILENAME,
            "coupon_set_summaries": SET_SUMMARY_FILENAME,
            "synchronization_audit": SYNC_AUDIT_FILENAME,
            "member_index": MEMBER_INDEX_FILENAME,
            "track_index": TRACK_INDEX_FILENAME,
        },
        "frame_columns": [
            "frame_index", "gige_time_s", "mapped_process_row", "mapping_status",
            "laser_drive", "laser_on", "scan_track_id", "H_pixels", "W_pixels",
            "H_um", "W_um", "H_mm", "W_mm", "hw_status",
            "eligible_melt_pool_observation", "eligibility_reason",
        ],
        "model_comparison_columns_reserved": [
            "simulated_H_pixels", "simulated_W_pixels", "H_residual_pixels", "W_residual_pixels",
        ],
        "raw_hdf5_or_camera_images_included": False,
    })


def _parse_member_token(token: str) -> tuple[str, int]:
    match = _MEMBER_TOKEN.fullmatch(str(token).strip())
    if not match:
        raise CharacterizationError(
            "--member must use SET:PART or SET/part_PART syntax, for example 20260730:1"
        )
    return match.group("set"), int(match.group("part"))


def _select_resolved_members(
    *,
    data_directory: str | Path,
    manifest_path: str | Path,
    acquisition_set: str | None,
    member_token: str | None,
) -> tuple[FullCouponManifest, tuple[ResolvedCouponMember, ...]]:
    manifest = load_full_coupon_manifest(manifest_path).require_hash_complete()
    if member_token is not None:
        set_id, part = _parse_member_token(member_token)
        members = select_manifest_members(manifest, acquisition_set_ids=(set_id,), parts=(part,))
    elif acquisition_set is not None:
        members = select_manifest_members(manifest, acquisition_set_ids=(str(acquisition_set),))
    else:
        members = manifest.enabled_members
    resolved = resolve_manifest_files(
        data_directory,
        manifest=manifest,
        members=members,
        require_exact_directory_membership=(len(members) == len(manifest.enabled_members)),
    )
    return manifest, resolved


def _run_manifest(
    *,
    manifest: FullCouponManifest,
    resolved: Sequence[ResolvedCouponMember],
    contract: CharacterizationContract,
) -> dict[str, Any]:
    selection = [
        {
            **_member_identity(member),
            "runtime_path_excluded_from_identity": True,
        }
        for member in resolved
    ]
    return {
        "schema": "lpbf_patch21_3_0_characterization_run_manifest",
        "schema_version": PATCH_VERSION,
        "patch": PATCH_LABEL,
        "generated_at_utc": utc_now_iso(),
        "canonical_manifest_identity": manifest.canonical_identity,
        "manifest_state": manifest.manifest_state,
        "code_identity": {
            "characterization_module_sha256": sha256_file(Path(__file__)),
            "identity_scope": "Patch 21.3.0 characterization module bytes",
        },
        "contract": contract.to_dict(),
        "contract_identity": canonical_sha256(contract.to_dict()),
        "selected_member_count": len(selection),
        "selected_members": selection,
        "selection_identity": canonical_sha256(selection),
        "raw_hdf5_copied": False,
        "camera_images_copied": False,
        "thermal_simulation_performed": False,
        "parameter_selection_performed": False,
        "validation_used": False,
    }


def _write_handoff_zip(output: Path) -> Path:
    archive = output.with_name(output.name + ".zip")
    if archive.exists():
        archive.unlink()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as handle:
        for path in sorted(output.rglob("*")):
            if path.is_file():
                handle.write(path, path.relative_to(output.parent))
    return archive


def run_characterization(
    *,
    data_directory: str | Path,
    output_directory: str | Path,
    manifest_path: str | Path = FULL_COUPON_MANIFEST_PATH,
    acquisition_set: str | None = None,
    member_token: str | None = None,
    resume: bool = False,
    continue_on_member_error: bool = False,
    write_handoff_zip: bool = True,
    contract: CharacterizationContract = CharacterizationContract(),
) -> dict[str, Any]:
    """Run the local read-only characterization and write portable summaries."""
    if acquisition_set is not None and member_token is not None:
        raise CharacterizationError("choose either --acquisition-set or --member, not both")
    manifest, resolved = _select_resolved_members(
        data_directory=data_directory,
        manifest_path=manifest_path,
        acquisition_set=acquisition_set,
        member_token=member_token,
    )
    output = Path(output_directory).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    run_manifest = _run_manifest(manifest=manifest, resolved=resolved, contract=contract)
    run_manifest_path = output / RUN_MANIFEST_FILENAME
    if resume and run_manifest_path.is_file():
        previous = _read_json(run_manifest_path)
        if previous.get("selection_identity") != run_manifest["selection_identity"]:
            raise CharacterizationError("--resume selection does not match the existing run manifest")
        if previous.get("contract_identity") != run_manifest["contract_identity"]:
            raise CharacterizationError("--resume contract does not match the existing run manifest")
        run_manifest["resumed_from_generated_at_utc"] = previous.get("generated_at_utc")
    else:
        write_json(run_manifest_path, run_manifest)

    successful: list[CharacterizationMemberResult] = []
    failures: list[dict[str, Any]] = []
    resumed_count = 0
    for resolved_member in resolved:
        prior = _load_resumable_member(output, resolved_member) if resume else None
        if prior is not None:
            prior_coupon, prior_tracks, prior_audit = prior
            resumed_count += 1
            successful.append(
                CharacterizationMemberResult(
                    resolved=resolved_member,
                    frame_rows=tuple(),
                    track_rows=prior_tracks,
                    coupon_row=prior_coupon,
                    audit={**prior_audit, "resumed": True},
                )
            )
            continue
        try:
            result = characterize_member(resolved_member, contract=contract)
            _write_member_result(output, result)
            successful.append(result)
        except Exception as exc:
            failure = {
                "portable_member_identity": resolved_member.member.portable_identity_text,
                "acquisition_set_id": resolved_member.member.key.acquisition_set_id,
                "part_number": int(resolved_member.member.key.part_number),
                "filename": resolved_member.member.expected_filename,
                "file_sha256": resolved_member.actual_sha256,
                "status": "FAIL",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "thermal_simulation_performed": False,
            }
            failures.append(failure)
            member_dir = output / "members" / _member_directory_name(resolved_member)
            member_dir.mkdir(parents=True, exist_ok=True)
            write_json(member_dir / MEMBER_AUDIT_FILENAME, failure)
            write_json(member_dir / MEMBER_STATUS_FILENAME, failure)
            if not continue_on_member_error:
                break
        write_json_atomic(output / STATUS_FILENAME, {
            "schema": "lpbf_patch21_3_0_characterization_status",
            "schema_version": PATCH_VERSION,
            "status": "RUNNING",
            "selected_member_count": len(resolved),
            "completed_member_count": len(successful) + len(failures),
            "successful_member_count": len(successful),
            "failed_member_count": len(failures),
            "resumed_member_count": resumed_count,
            "output_directory": str(output),
            "generated_at_utc": utc_now_iso(),
        })

    stopped_early = bool(
        len(successful) + len(failures) < len(resolved)
        and not continue_on_member_error
    )
    _write_aggregate_outputs(
        output,
        resolved=resolved,
        successful=successful,
        failures=failures,
        contract=contract,
    )
    passed = not failures and len(successful) == len(resolved)
    status = (
        "PASS_PATCH_21_3_0_LOCAL_CHARACTERIZATION_INFRASTRUCTURE_READY"
        if passed
        else "FAIL_CLOSED_PATCH_21_3_0_LOCAL_CHARACTERIZATION"
    )
    final = {
        "schema": "lpbf_patch21_3_0_characterization_status",
        "schema_version": PATCH_VERSION,
        "status": status,
        "exit_criterion_met": bool(passed),
        "selected_member_count": len(resolved),
        "completed_member_count": len(successful) + len(failures),
        "successful_member_count": len(successful),
        "failed_member_count": len(failures),
        "resumed_member_count": resumed_count,
        "continue_on_member_error": bool(continue_on_member_error),
        "stopped_early_after_member_failure": stopped_early,
        "canonical_manifest_identity": manifest.canonical_identity,
        "selection_identity": run_manifest["selection_identity"],
        "contract_identity": run_manifest["contract_identity"],
        "output_files": [
            RUN_MANIFEST_FILENAME,
            MEMBER_INDEX_FILENAME,
            TRACK_INDEX_FILENAME,
            COUPON_SUMMARY_FILENAME,
            CONDITION_SUMMARY_FILENAME,
            SET_SUMMARY_FILENAME,
            SYNC_AUDIT_FILENAME,
            SCHEMA_REPORT_FILENAME,
            STATUS_FILENAME,
        ],
        "failures": failures,
        "thermal_simulation_performed": False,
        "parameter_selection_performed": False,
        "validation_used": False,
        "generated_at_utc": utc_now_iso(),
    }
    write_json(output / STATUS_FILENAME, final)
    if write_handoff_zip:
        archive = _write_handoff_zip(output)
        final["handoff_zip"] = str(archive)
        final["output_files"] = [*final["output_files"], archive.name]
        write_json(output / STATUS_FILENAME, final)
    return final


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Patch 21.3.0 read-only hierarchical H/W characterization over local HDF5 coupon files."
    )
    parser.add_argument("--data-dir", required=True, help="Directory containing canonical coupon HDF5 files")
    parser.add_argument("--output-dir", required=True, help="Portable characterization output directory")
    parser.add_argument("--manifest", default=str(FULL_COUPON_MANIFEST_PATH), help="Canonical full-coupon manifest")
    parser.add_argument("--acquisition-set", help="Process one acquisition set, for example 20260730")
    parser.add_argument("--member", help="Process one member, for example 20260730:1")
    parser.add_argument("--layer-name", default=DEFAULT_LAYER_NAME, help="HDF5 layer name")
    parser.add_argument("--resume", action="store_true", help="Resume completed member outputs with matching identities")
    parser.add_argument("--continue-on-member-error", action="store_true", help="Record a member failure and continue to later members")
    parser.add_argument("--no-handoff-zip", action="store_true", help="Do not create the portable handoff ZIP")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    contract = CharacterizationContract(layer_name=str(args.layer_name))
    try:
        status = run_characterization(
            data_directory=args.data_dir,
            output_directory=args.output_dir,
            manifest_path=args.manifest,
            acquisition_set=args.acquisition_set,
            member_token=args.member,
            resume=bool(args.resume),
            continue_on_member_error=bool(args.continue_on_member_error),
            write_handoff_zip=not bool(args.no_handoff_zip),
            contract=contract,
        )
    except (CharacterizationError, FullCouponManifestError, OSError, KeyError, ValueError) as exc:
        raise SystemExit(f"FAIL_CLOSED_PATCH_21_3_0_LOCAL_CHARACTERIZATION: {exc}") from exc
    print(status["status"])
    print(f"Completed members: {status['successful_member_count']}/{status['selected_member_count']}")
    print(f"Wrote: {Path(args.output_dir).expanduser().resolve() / STATUS_FILENAME}")
    return 0 if status["exit_criterion_met"] else 2


__all__ = [
    "CHARACTERIZATION_SCHEMA",
    "CharacterizationContract",
    "CharacterizationError",
    "CharacterizationMemberResult",
    "characterize_member",
    "run_characterization",
]


if __name__ == "__main__":
    raise SystemExit(main())
