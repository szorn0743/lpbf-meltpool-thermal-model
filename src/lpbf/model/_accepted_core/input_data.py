"""Canonical LPBF HDF5 process-data ingestion and calibrated process records.

This module owns HDF5 channel discovery/selection, sample-frequency handling,
Laser Drive processing, scan-track IDs, TED calibration fields, and streaming.
Downstream workflows consume ``LaserInputData`` rather than reinterpreting raw
process files.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable

import h5py
import numpy as np

from lpbf.model._accepted_core.parameters import (
    TED_EMPIRICAL_CALIBRATION_PROVENANCE_11_1_0,
    SimulationParameters,
    TEDEmpiricalCalibrationProvenance,
    get_params,
)

@dataclass(frozen=True)
class LaserInputData:
    """Cleaned time-series input used by the moving-window driver."""

    time_s: np.ndarray
    laser_x_mm: np.ndarray
    laser_y_mm: np.ndarray
    pyrometer_K: np.ndarray
    commanded_power_W: np.ndarray
    spot_size_um: np.ndarray
    measured_reflectivity: np.ndarray
    laser_on: np.ndarray
    source_columns: dict[str, str | None]

    input_mode: str = "hdf5"
    input_path: str | None = None
    h5_metadata: dict[str, Any] | None = None
    h5_laser_drive_threshold_used: float = np.nan
    h5_sample_frequency_hz: float = np.nan
    ted_global_off_baseline: float = np.nan
    ted_baseline_status: str = "not_applicable"

    on_axis_ted_raw: np.ndarray | None = None
    ted_baseline_used: np.ndarray | None = None
    ted_signal_corrected: np.ndarray | None = None
    ted_reference_100pct_reflection: np.ndarray | None = None
    ted_reflected_fraction_raw: np.ndarray | None = None
    ted_reflected_fraction_used: np.ndarray | None = None
    effective_absorptivity_raw: np.ndarray | None = None
    effective_absorptivity: np.ndarray | None = None
    ted_reflection_clipped_low_flag: np.ndarray | None = None
    ted_reflection_clipped_high_flag: np.ndarray | None = None
    ted_reference_nonpositive_flag: np.ndarray | None = None
    scan_track_id: np.ndarray | None = None
    row_index: np.ndarray | None = None
    laser_drive: np.ndarray | None = None
    ted_nonfinite_flag: np.ndarray | None = None
    ted_calibration_valid_flag: np.ndarray | None = None
    ted_invalid_powered_flag: np.ndarray | None = None

    @property
    def n_rows(self) -> int:
        return int(self.time_s.size)

    def __getitem__(self, key: str) -> np.ndarray:
        """Return a named process array for simulation block consumption."""
        aliases = {"ted_effective_absorptivity": "effective_absorptivity"}
        attribute = aliases.get(key, key)
        if not hasattr(self, attribute):
            raise KeyError(key)
        value = getattr(self, attribute)
        if value is None:
            raise KeyError(key)
        return value


@dataclass(frozen=True)
class LayerTEDProcessData:
    """TED-only layer input for optical-calibration diagnostics.

    Patch 11.2 uses this narrow record so reflectivity studies can consume the
    process Laser Drive and On-Axis TED channels without loading melt-pool H/W
    measurements.  It intentionally contains no source-fit or camera fields.
    """

    time_s: np.ndarray
    row_index: np.ndarray
    laser_drive: np.ndarray
    laser_on: np.ndarray
    on_axis_ted_raw: np.ndarray
    scan_track_id: np.ndarray
    selected_laser_off_evidence_mask: np.ndarray
    ted_global_off_baseline: float
    ted_baseline_status: str
    ted_baseline_evidence: dict[str, Any]
    input_path: str
    layer_name: str
    sample_frequency_hz: float
    laser_drive_threshold_used: float
    channels_read: tuple[str, ...] = ("Laser Drive", "On-Axis TED")

    @property
    def n_rows(self) -> int:
        return int(self.time_s.size)



@dataclass(frozen=True)
class LayerTEDStructureData:
    """TED-only process record plus machine coordinates for Patch 11.2.4.

    The structure diagnostic requires X/Y position, but still must not read
    melt-pool H/W or camera-derived observations.  The nested TED record is
    produced by the established Patch 11.2 loader so baseline selection, laser
    state, scan-track identity, and row alignment remain unchanged.
    """

    ted_process: LayerTEDProcessData
    laser_x_mm: np.ndarray
    laser_y_mm: np.ndarray
    channels_read: tuple[str, ...] = (
        "Laser Drive",
        "On-Axis TED",
        "X-Machine",
        "Y-Machine",
    )

    @property
    def n_rows(self) -> int:
        return self.ted_process.n_rows


H5_CHANNEL_ALIASES: dict[str, list[str]] = {
    # Physical moving-window motion must use mapped machine coordinates in mm.
    # Do not fall back to raw X-Position/Y-Position: doing so changes the spatial
    # scale used by apply_moving_window_update() and therefore the implied speed.
    "x": ["X-Machine", "X Machine"],
    "y": ["Y-Machine", "Y Machine"],
    "ted": ["On-Axis TED", "On Axis TED", "TED", "on_axis_ted", "OnAxisTED"],
    "drive": ["Laser Drive", "Drive", "laser_drive", "LaserDrive"],
    # Discovered for metadata only. It is not used as physical source power.
    "power": ["Laser Power", "Power", "laser_power", "LaserPower"],
}

H5_FREQUENCY_ATTRIBUTE_NAMES = (
    "frequency",
    "Frequency",
    "sample_rate",
    "sample rate",
    "fs",
    "Fs",
)

# Patch 16.0 production acquisition contract. Windows-derived synchronized
# timestamps remain camera-alignment evidence only and can never drive process
# integration or trajectory-speed calculations.
PRODUCTION_DAQ_FREQUENCY_HZ = 200_000.0
PRODUCTION_DAQ_DT_S = 5.0e-6
PRODUCTION_LASER_DRIVE_THRESHOLD = 2.5
PRODUCTION_TIME_SOURCE = "fixed_200_kHz_DAQ_row_clock"
SYNCHRONIZED_TIME_DIAGNOSTIC_DATASET = "sync/data_to_gige_time"


def fixed_production_time_s(n_rows: int) -> np.ndarray:
    """Return the only permitted production process clock."""
    count = int(n_rows)
    if count < 0:
        raise ValueError("production row count must be nonnegative")
    return np.arange(count, dtype=np.float64) * PRODUCTION_DAQ_DT_S


def assert_fixed_production_time_s(time_s: np.ndarray) -> None:
    """Fail closed unless *time_s* is the exact 200 kHz row-index clock."""
    values = np.asarray(time_s, dtype=np.float64)
    if values.ndim != 1 or not np.all(np.isfinite(values)):
        raise ValueError("production time must be a finite one-dimensional array")
    expected = fixed_production_time_s(values.size)
    tolerance = (
        np.finfo(np.float64).eps
        * max(1.0, float(expected[-1]) if expected.size else 1.0)
        * 8.0
    )
    if not np.allclose(values, expected, rtol=0.0, atol=tolerance):
        raise ValueError(
            "variable or non-200-kHz production timing is forbidden; expected "
            "time_s[i] = i * 5.0e-6 s"
        )


@dataclass(frozen=True)
class _H5DatasetRef:
    """Reference metadata for a discovered HDF5 dataset."""

    key: str
    path: str
    shape: tuple[int, ...]
    dtype: str
    frequency_hz: float | None


def _normalize_h5_name(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


def _safe_float(value: object) -> float | None:
    try:
        if isinstance(value, np.ndarray):
            if value.size == 0:
                return None
            return float(np.ravel(value)[0])
        if isinstance(value, (list, tuple)):
            if not value:
                return None
            return float(value[0])
        return float(value)
    except Exception:
        return None


def _h5_frequency_hz(ds: h5py.Dataset) -> float | None:
    for attr_name in H5_FREQUENCY_ATTRIBUTE_NAMES:
        if attr_name in ds.attrs:
            frequency_hz = _safe_float(ds.attrs[attr_name])
            if frequency_hz is not None and np.isfinite(frequency_hz) and frequency_hz > 0.0:
                return float(frequency_hz)
    return None


def _iter_h5_datasets(f: h5py.File) -> list[tuple[str, h5py.Dataset]]:
    datasets: list[tuple[str, h5py.Dataset]] = []

    def visitor(name: str, obj: h5py.Group | h5py.Dataset) -> None:
        if isinstance(obj, h5py.Dataset):
            datasets.append(("/" + name, obj))

    f.visititems(visitor)
    return datasets


def _find_h5_dataset(f: h5py.File, key: str) -> _H5DatasetRef | None:
    aliases = H5_CHANNEL_ALIASES[key]
    normalized_aliases = [_normalize_h5_name(alias) for alias in aliases]
    candidates: list[tuple[int, str, h5py.Dataset]] = []

    for path, ds in _iter_h5_datasets(f):
        base = path.rsplit("/", 1)[-1]
        base_norm = _normalize_h5_name(base)
        path_norm = _normalize_h5_name(path)

        score: int | None = None
        if base_norm in normalized_aliases:
            score = 0
        elif any(path_norm.endswith(alias) for alias in normalized_aliases):
            score = 1
        elif any(alias in base_norm for alias in normalized_aliases):
            score = 2
        elif any(alias in path_norm for alias in normalized_aliases):
            score = 3

        if score is None:
            continue

        rank = score
        if len(ds.shape) != 1:
            rank += 10
        if not np.issubdtype(ds.dtype, np.number):
            rank += 20
        candidates.append((rank, path, ds))

    if not candidates:
        return None

    candidates.sort(key=lambda item: (item[0], item[1]))
    _, path, ds = candidates[0]
    return _H5DatasetRef(
        key=key,
        path=path,
        shape=tuple(int(v) for v in ds.shape),
        dtype=str(ds.dtype),
        frequency_hz=_h5_frequency_hz(ds),
    )


def _read_h5_1d_float64(f: h5py.File, ref: _H5DatasetRef) -> np.ndarray:
    data = np.asarray(f[ref.path][:])
    return np.ravel(data).astype(np.float64, copy=False)


def _sha256_file(path: Path, *, block_bytes: int = 1 << 20) -> str:
    """Return the SHA-256 digest for one file without loading it all at once."""
    digest = sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(block_bytes)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def inspect_ted_empirical_calibration_file_11_1_0(
    calibration_h5_path: Path | str,
    *,
    provenance: TEDEmpiricalCalibrationProvenance = (
        TED_EMPIRICAL_CALIBRATION_PROVENANCE_11_1_0
    ),
) -> dict[str, Any]:
    """Inspect only Patch 11.1.0 provenance of the bare-plate TED file.

    This helper intentionally does not detect pulses, assign/recover shots, fit a
    TED relation, or evaluate process-build H/W. It verifies the raw calibration
    file identity and the exact HDF5 channels/sample-rate metadata needed by the
    later deterministic reproduction step.
    """
    path = Path(calibration_h5_path)
    if not path.is_file():
        raise FileNotFoundError(f"TED calibration HDF5 file does not exist: {path}")

    actual_sha256 = _sha256_file(path)
    channel_paths = {
        "ted": provenance.ted_channel_path,
        "laser_drive": provenance.laser_drive_channel_path,
        "x_position": provenance.x_position_channel_path,
        "y_position": provenance.y_position_channel_path,
        "raw_laser_power": provenance.raw_laser_power_channel_path,
    }
    channels: dict[str, dict[str, Any]] = {}
    with h5py.File(path, "r") as h5_file:
        for key, channel_path in channel_paths.items():
            if channel_path not in h5_file:
                channels[key] = {
                    "path": channel_path,
                    "available": False,
                    "shape": None,
                    "dtype": None,
                    "sample_rate_hz": None,
                }
                continue
            dataset = h5_file[channel_path]
            if not isinstance(dataset, h5py.Dataset):
                channels[key] = {
                    "path": channel_path,
                    "available": False,
                    "shape": None,
                    "dtype": None,
                    "sample_rate_hz": None,
                    "reason": "path exists but is not a dataset",
                }
                continue
            channels[key] = {
                "path": channel_path,
                "available": True,
                "shape": [int(value) for value in dataset.shape],
                "dtype": str(dataset.dtype),
                "sample_rate_hz": _h5_frequency_hz(dataset),
            }

    required_keys = ("ted", "laser_drive", "x_position", "y_position")
    required_channels_available = all(channels[key]["available"] for key in required_keys)
    selected_rates = [channels[key]["sample_rate_hz"] for key in required_keys]
    selected_rates_valid = all(
        value is not None and np.isfinite(value) and value > 0.0
        for value in selected_rates
    )
    selected_rate_consistent = bool(
        selected_rates_valid
        and len({float(value) for value in selected_rates if value is not None}) == 1
    )
    observed_sample_rate_hz = (
        float(selected_rates[0]) if selected_rate_consistent else None
    )

    return {
        "schema": "lpbf_ted_empirical_calibration_file_provenance_11.1.0",
        "calibration_file": {
            "canonical_name": provenance.calibration_file_name,
            "inspected_name": path.name,
            "sha256": actual_sha256,
            "expected_sha256": provenance.calibration_file_sha256,
            "sha256_matches_expected": actual_sha256 == provenance.calibration_file_sha256,
            "size_bytes": int(path.stat().st_size),
        },
        "channels": channels,
        "required_channels_available": bool(required_channels_available),
        "selected_channel_sample_rates_consistent": selected_rate_consistent,
        "observed_acquisition_sample_rate_hz": observed_sample_rate_hz,
        "expected_acquisition_sample_rate_hz": float(provenance.acquisition_sample_rate_hz),
        "sample_rate_matches_expected": bool(
            observed_sample_rate_hz is not None
            and np.isclose(
                observed_sample_rate_hz,
                provenance.acquisition_sample_rate_hz,
                rtol=0.0,
                atol=0.0,
            )
        ),
        "scope": (
            "provenance inspection only; no pulse extraction, physical-power "
            "reassignment, TED fit, process H/W use, or source calibration"
        ),
    }



def load_ted_empirical_calibration_channels_11_1_1(
    calibration_h5_path: Path | str,
    *,
    provenance: TEDEmpiricalCalibrationProvenance = (
        TED_EMPIRICAL_CALIBRATION_PROVENANCE_11_1_0
    ),
) -> dict[str, np.ndarray | float]:
    """Load only the frozen bare-plate channels required by Patch 11.1.1.

    The Patch 11.1.0 file hash, required channel paths, and sample rate must pass
    before any calibration pulse extraction is allowed. Process-build H/W data
    is not discovered or loaded by this helper.
    """
    path = Path(calibration_h5_path)
    inspection = inspect_ted_empirical_calibration_file_11_1_0(
        path, provenance=provenance
    )
    if not (
        inspection["calibration_file"]["sha256_matches_expected"]
        and inspection["required_channels_available"]
        and inspection["sample_rate_matches_expected"]
    ):
        raise RuntimeError(
            "Patch 11.1.1 calibration extraction requires the authoritative "
            "Patch 11.1.0 bare-plate file and frozen channel/sample-rate provenance."
        )

    selected_paths = {
        "ted": provenance.ted_channel_path,
        "laser_drive": provenance.laser_drive_channel_path,
        "x_position": provenance.x_position_channel_path,
        "y_position": provenance.y_position_channel_path,
        "raw_laser_power": provenance.raw_laser_power_channel_path,
    }
    channels: dict[str, np.ndarray | float] = {
        "sample_rate_hz": float(provenance.acquisition_sample_rate_hz)
    }
    with h5py.File(path, "r") as h5_file:
        for key, channel_path in selected_paths.items():
            channels[key] = np.ravel(
                np.asarray(h5_file[channel_path][:], dtype=np.float64)
            )
    return channels

def resolve_h5_path(params: SimulationParameters) -> Path:
    requested = Path(params.input.h5_path_select)
    if requested.exists():
        return requested

    if not requested.is_absolute():
        candidates = [
            Path(__file__).resolve().parent / requested,
            Path.cwd() / requested,
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate

    if params.input.h5_use_file_dialog:
        try:
            import tkinter as tk
            from tkinter import filedialog

            root = tk.Tk()
            root.withdraw()
            selected = filedialog.askopenfilename(
                title="Select LPBF HDF5 input file",
                filetypes=(
                    ("HDF5 files", "*.h5 *.hdf5"),
                    ("All files", "*.*"),
                ),
            )
            root.destroy()
        except Exception as exc:
            raise FileNotFoundError(
                "HDF5 file was not found and the file-dialog selector could not be opened. "
                f"Requested path: {requested}"
            ) from exc

        if selected:
            selected_path = Path(selected)
            if selected_path.exists():
                return selected_path

    raise FileNotFoundError(
        "Could not find HDF5 input file. Edit InputControls.h5_path_select in "
        f"parameters.py or set h5_use_file_dialog=True. Requested path: {requested}"
    )


def _infer_laser_drive_threshold(drive: np.ndarray) -> float:
    finite = np.asarray(drive, dtype=float)
    finite = finite[np.isfinite(finite)]
    if finite.size == 0:
        raise ValueError(
            "Laser Drive contains no finite samples; cannot infer laser-on threshold."
        )

    finite_min = float(np.min(finite))
    finite_max = float(np.max(finite))
    if not np.isfinite(finite_min) or not np.isfinite(finite_max) or finite_max <= finite_min:
        raise ValueError(
            "Laser Drive is flat or invalid; provide InputControls.laser_drive_threshold."
        )

    return 0.5 * (finite_min + finite_max)


def _compute_scan_track_id(laser_on: np.ndarray) -> np.ndarray:
    laser_on_bool = np.asarray(laser_on, dtype=bool)
    track_ids = np.zeros(laser_on_bool.shape, dtype=int)
    current_track = 0
    previous_on = False

    for i, is_on in enumerate(laser_on_bool):
        if is_on and not previous_on:
            current_track += 1
        if is_on:
            track_ids[i] = current_track
        previous_on = bool(is_on)

    return track_ids


def _evenly_spaced_sample_indices(total_count: int, max_samples: int) -> np.ndarray:
    """Return the deterministic global sample indices used for TED baselines."""
    if total_count <= 0:
        return np.empty(0, dtype=np.int64)
    sample_count = min(int(total_count), int(max_samples))
    return np.linspace(0, total_count - 1, sample_count, dtype=np.int64)


def _contiguous_mask_runs(mask: np.ndarray) -> list[np.ndarray]:
    """Return global row indices for contiguous True runs in a 1-D mask."""
    values = np.asarray(mask, dtype=bool)
    if values.ndim != 1:
        raise ValueError("TED baseline masks must be one-dimensional.")
    indices = np.flatnonzero(values)
    if indices.size == 0:
        return []
    split_points = np.flatnonzero(np.diff(indices) > 1) + 1
    return [run for run in np.split(indices, split_points) if run.size]


def _robust_segment_outlier_flags(
    segment_statistics: list[dict[str, Any]],
    *,
    sigma_multiplier: float,
) -> dict[str, Any]:
    """Classify contaminated laser-off segments from robust median/MAD statistics."""
    finite_stats = [
        item
        for item in segment_statistics
        if item["median"] is not None and item["mad"] is not None
    ]
    if not finite_stats:
        return {
            "segment_median_center": None,
            "segment_median_mad": None,
            "segment_median_robust_sigma": None,
            "segment_mad_center": None,
            "segment_mad_mad": None,
            "segment_mad_robust_sigma": None,
            "median_outlier_segment_indices": set(),
            "dispersion_outlier_segment_indices": set(),
        }

    medians = np.asarray([item["median"] for item in finite_stats], dtype=np.float64)
    dispersions = np.asarray([item["mad"] for item in finite_stats], dtype=np.float64)

    median_center = float(np.median(medians))
    median_mad = float(np.median(np.abs(medians - median_center)))
    median_sigma = float(1.4826 * median_mad)
    dispersion_center = float(np.median(dispersions))
    dispersion_mad = float(np.median(np.abs(dispersions - dispersion_center)))
    dispersion_sigma = float(1.4826 * dispersion_mad)

    median_tolerance = (
        float(sigma_multiplier) * median_sigma
        if median_sigma > 0.0
        else np.finfo(np.float64).eps * max(1.0, abs(median_center)) * 16.0
    )
    dispersion_tolerance = (
        float(sigma_multiplier) * dispersion_sigma
        if dispersion_sigma > 0.0
        else np.finfo(np.float64).eps * max(1.0, abs(dispersion_center)) * 16.0
    )

    median_outliers: set[int] = set()
    dispersion_outliers: set[int] = set()
    for item in finite_stats:
        segment_index = int(item["segment_index"])
        if abs(float(item["median"]) - median_center) > median_tolerance:
            median_outliers.add(segment_index)
        if float(item["mad"]) - dispersion_center > dispersion_tolerance:
            dispersion_outliers.add(segment_index)

    return {
        "segment_median_center": median_center,
        "segment_median_mad": median_mad,
        "segment_median_robust_sigma": median_sigma,
        "segment_mad_center": dispersion_center,
        "segment_mad_mad": dispersion_mad,
        "segment_mad_robust_sigma": dispersion_sigma,
        "median_outlier_segment_indices": median_outliers,
        "dispersion_outlier_segment_indices": dispersion_outliers,
    }


def _summarize_ted_off_segments(
    on_axis_ted_raw: np.ndarray,
    laser_on: np.ndarray,
    *,
    max_samples: int,
) -> list[dict[str, Any]]:
    """Compute robust statistics for each contiguous physical laser-off segment."""
    raw = np.asarray(on_axis_ted_raw, dtype=np.float64)
    laser_on_bool = np.asarray(laser_on, dtype=bool)
    if raw.shape != laser_on_bool.shape or raw.ndim != 1:
        raise ValueError("TED and laser_on arrays must be row-aligned one-dimensional arrays.")

    segments: list[dict[str, Any]] = []
    for segment_index, run in enumerate(_contiguous_mask_runs(~laser_on_bool)):
        finite_values = raw[run]
        finite_values = finite_values[np.isfinite(finite_values)]
        sample_indices = _evenly_spaced_sample_indices(
            int(finite_values.size), int(max_samples)
        )
        sampled = finite_values[sample_indices] if sample_indices.size else np.empty(0)
        if sampled.size:
            median = float(np.median(sampled))
            mad = float(np.median(np.abs(sampled - median)))
        else:
            median = None
            mad = None
        segments.append(
            {
                "segment_index": int(segment_index),
                "row_start": int(run[0]),
                "row_end": int(run[-1]),
                "rows": int(run.size),
                "finite_rows": int(finite_values.size),
                "statistics_sample_rows": int(sampled.size),
                "median": median,
                "mad": mad,
            }
        )
    return segments


def _build_ted_baseline_evidence_summary(
    segment_statistics: list[dict[str, Any]],
    *,
    evidence_policy: str,
    sigma_multiplier: float,
) -> dict[str, Any]:
    """Return JSON-safe Patch 10.2.1 laser-off evidence classification."""
    robust = _robust_segment_outlier_flags(
        segment_statistics,
        sigma_multiplier=float(sigma_multiplier),
    )
    median_outliers = robust.pop("median_outlier_segment_indices")
    dispersion_outliers = robust.pop("dispersion_outlier_segment_indices")
    finite_segment_indices = {
        int(item["segment_index"])
        for item in segment_statistics
        if int(item["finite_rows"]) > 0
    }
    outlier_indices = median_outliers | dispersion_outliers
    selected_indices = finite_segment_indices - outlier_indices
    fallback_all_finite_segments = False
    fallback_reason = None
    if finite_segment_indices and not selected_indices:
        # Keep the pipeline explicit and numerically defined at this subpatch;
        # Patch 10.2.5 owns the later stop/go decision if no defensible model passes.
        selected_indices = set(finite_segment_indices)
        fallback_all_finite_segments = True
        fallback_reason = "robust filter rejected every finite laser-off segment"

    segments: list[dict[str, Any]] = []
    for item in segment_statistics:
        segment_index = int(item["segment_index"])
        median_outlier = segment_index in median_outliers
        dispersion_outlier = segment_index in dispersion_outliers
        outlier = median_outlier or dispersion_outlier
        selected = segment_index in selected_indices
        segment = dict(item)
        segment.update(
            {
                "median_outlier": bool(median_outlier),
                "dispersion_outlier": bool(dispersion_outlier),
                "outlier": bool(outlier),
                "selected_for_baseline": bool(selected),
            }
        )
        segments.append(segment)

    finite_off_rows = int(sum(int(item["finite_rows"]) for item in segment_statistics))
    selected_off_rows = int(
        sum(
            int(item["finite_rows"])
            for item in segment_statistics
            if int(item["segment_index"]) in selected_indices
        )
    )
    outlier_off_rows = int(
        sum(
            int(item["finite_rows"])
            for item in segment_statistics
            if int(item["segment_index"]) in outlier_indices
        )
    )
    return {
        "policy": str(evidence_policy),
        "uses_melt_pool_hw": False,
        "sigma_multiplier": float(sigma_multiplier),
        "physical_segment_count": int(len(segment_statistics)),
        "finite_segment_count": int(len(finite_segment_indices)),
        "selected_segment_count": int(len(selected_indices)),
        "outlier_segment_count": int(len(outlier_indices)),
        "finite_off_rows": finite_off_rows,
        "selected_off_rows": selected_off_rows,
        "outlier_off_rows": outlier_off_rows,
        "fallback_all_finite_segments": bool(fallback_all_finite_segments),
        "fallback_reason": fallback_reason,
        **robust,
        "segments": segments,
    }


def _finalize_ted_baseline(
    samples: np.ndarray,
    *,
    total_selected_finite: int,
    max_samples: int,
    evidence_summary: dict[str, Any],
) -> tuple[float, str]:
    """Compute the global median from the robustly cleaned laser-off evidence."""
    if int(evidence_summary["finite_off_rows"]) <= 0:
        return 0.0, "no_laser_off_samples; using 0.0"

    values = np.asarray(samples, dtype=np.float64)
    if values.size == 0:
        raise ValueError("TED baseline sampling produced no values.")
    baseline = float(np.median(values))
    # Preserve the established baseline-status vocabulary. Patch 10.2.1's
    # evidence cleaning is recorded separately in ted_baseline_evidence so
    # downstream callers that key off the status string do not change behavior.
    if total_selected_finite <= int(max_samples):
        status = "global_laser_off_median"
    else:
        status = (
            "global_laser_off_median_even_sample_"
            f"{values.size}_of_{total_selected_finite}"
        )
    return baseline, status


def _compute_ted_baseline(
    on_axis_ted_raw: np.ndarray,
    laser_on: np.ndarray,
    params: SimulationParameters,
) -> tuple[float, str, dict[str, Any]]:
    """Compute the Patch 10.2.1 cleaned global TED baseline evidence."""
    raw = np.asarray(on_axis_ted_raw, dtype=np.float64)
    laser_on_bool = np.asarray(laser_on, dtype=bool)
    if raw.shape != laser_on_bool.shape or raw.ndim != 1:
        raise ValueError("TED and laser_on arrays must be row-aligned one-dimensional arrays.")

    max_samples = int(params.input.h5_baseline_max_samples)
    segment_statistics = _summarize_ted_off_segments(
        raw,
        laser_on_bool,
        max_samples=max_samples,
    )
    evidence_summary = _build_ted_baseline_evidence_summary(
        segment_statistics,
        evidence_policy=str(params.input.ted_baseline_evidence_policy),
        sigma_multiplier=float(params.input.ted_off_segment_outlier_sigma_multiplier),
    )
    selected_segments = {
        int(item["segment_index"])
        for item in evidence_summary["segments"]
        if bool(item["selected_for_baseline"])
    }
    selected_values_parts: list[np.ndarray] = []
    for segment_index, run in enumerate(_contiguous_mask_runs(~laser_on_bool)):
        if segment_index not in selected_segments:
            continue
        values = raw[run]
        finite = values[np.isfinite(values)]
        if finite.size:
            selected_values_parts.append(finite)
    selected_values = (
        np.concatenate(selected_values_parts)
        if selected_values_parts
        else np.empty(0, dtype=np.float64)
    )
    indices = _evenly_spaced_sample_indices(
        int(selected_values.size),
        max_samples,
    )
    samples = selected_values[indices] if indices.size else np.empty(0, dtype=np.float64)
    baseline, status = _finalize_ted_baseline(
        samples,
        total_selected_finite=int(selected_values.size),
        max_samples=max_samples,
        evidence_summary=evidence_summary,
    )
    return baseline, status, evidence_summary


def _compute_ted_reference_scalar(params: SimulationParameters) -> float:
    """Return the existing 100%-reflection TED reference without recalibration."""
    return (
        float(params.input.ted_reference_slope) * float(params.heat_source.incident_power_W)
        + float(params.input.ted_reference_intercept)
    )


def _calibrate_ted_rows(
    on_axis_ted_raw: np.ndarray,
    laser_on: np.ndarray,
    *,
    baseline: float,
    baseline_status: str,
    reference_scalar: float,
    manual_power_W: float,
) -> dict[str, np.ndarray | float | str]:
    """Apply the canonical TED reflection/absorptivity calculation to rows.

    Non-finite TED rows are flagged and treated as invalid powered rows: their
    reflected fractions and absorptivities remain zero. Laser-off rows likewise
    remain exactly zero in all source-driving calibrated fields.
    """
    raw = np.asarray(on_axis_ted_raw, dtype=np.float64)
    laser_on_bool = np.asarray(laser_on, dtype=bool)
    if raw.shape != laser_on_bool.shape:
        raise ValueError("TED and laser_on arrays must have identical shapes.")

    corrected = raw - float(baseline)
    reference = np.full(raw.shape, float(reference_scalar), dtype=np.float64)
    baseline_used = np.full(raw.shape, float(baseline), dtype=np.float64)
    ted_nonfinite_flag = ~np.isfinite(raw)

    reference_is_positive = bool(
        np.isfinite(reference_scalar)
        and float(reference_scalar) > 0.0
        and float(manual_power_W) > 0.0
    )
    reference_nonpositive_flag = np.full(raw.shape, not reference_is_positive, dtype=bool)
    powered_valid = laser_on_bool & reference_is_positive & (~ted_nonfinite_flag)
    invalid_powered = laser_on_bool & (~powered_valid)

    reflected_fraction_raw = np.zeros(raw.shape, dtype=np.float64)
    reflected_fraction_used = np.zeros(raw.shape, dtype=np.float64)
    effective_absorptivity_raw = np.zeros(raw.shape, dtype=np.float64)
    effective_absorptivity = np.zeros(raw.shape, dtype=np.float64)
    low_clip_flag = np.zeros(raw.shape, dtype=bool)
    high_clip_flag = np.zeros(raw.shape, dtype=bool)

    if np.any(powered_valid):
        raw_fraction = corrected[powered_valid] / float(reference_scalar)
        used_fraction = np.clip(raw_fraction, 0.0, 1.0)
        reflected_fraction_raw[powered_valid] = raw_fraction
        reflected_fraction_used[powered_valid] = used_fraction
        effective_absorptivity_raw[powered_valid] = 1.0 - raw_fraction
        effective_absorptivity[powered_valid] = 1.0 - used_fraction
        low_clip_flag[powered_valid] = raw_fraction < 0.0
        high_clip_flag[powered_valid] = raw_fraction > 1.0

    return {
        "ted_global_off_baseline": float(baseline),
        "ted_baseline_status": str(baseline_status),
        "ted_baseline_used": baseline_used,
        "ted_signal_corrected": corrected,
        "ted_reference_100pct_reflection": reference,
        "ted_reflected_fraction_raw": reflected_fraction_raw,
        "ted_reflected_fraction_used": reflected_fraction_used,
        "effective_absorptivity_raw": effective_absorptivity_raw,
        "effective_absorptivity": effective_absorptivity,
        "ted_reflection_clipped_low_flag": low_clip_flag,
        "ted_reflection_clipped_high_flag": high_clip_flag,
        "ted_reference_nonpositive_flag": reference_nonpositive_flag,
        "ted_nonfinite_flag": ted_nonfinite_flag,
        "powered_valid_flag": powered_valid,
        "ted_calibration_valid_flag": powered_valid,
        "ted_invalid_powered_flag": invalid_powered,
    }


def _compute_ted_absorptivity_fields(
    on_axis_ted_raw: np.ndarray,
    laser_on: np.ndarray,
    params: SimulationParameters,
) -> dict[str, np.ndarray | float | str]:
    """Calibrate an in-memory TED series through the canonical implementation."""
    baseline, baseline_status, evidence_summary = _compute_ted_baseline(
        on_axis_ted_raw, laser_on, params
    )
    fields = _calibrate_ted_rows(
        on_axis_ted_raw,
        laser_on,
        baseline=baseline,
        baseline_status=baseline_status,
        reference_scalar=_compute_ted_reference_scalar(params),
        manual_power_W=float(params.heat_source.incident_power_W),
    )
    fields["ted_baseline_evidence_summary"] = evidence_summary
    return fields


def load_laser_h5(
    h5_path: str | Path | None = None,
    params: SimulationParameters | None = None,
) -> LaserInputData:
    """
    Load production LPBF print input on the fixed 200 kHz DAQ row clock.

    The HDF5 Laser Power channel may be discovered for metadata, but is not used
    as physical source power. Physical source power is the manual
    HeatSourceParameters.incident_power_W value.
    """
    if params is None:
        params = get_params()

    resolved_path = Path(h5_path) if h5_path is not None else resolve_h5_path(params)
    if not resolved_path.exists():
        raise FileNotFoundError(f"Could not find HDF5 input file: {resolved_path}")

    with h5py.File(resolved_path, "r") as f:
        refs = {
            "x": _find_h5_dataset(f, "x"),
            "y": _find_h5_dataset(f, "y"),
            "ted": _find_h5_dataset(f, "ted"),
            "drive": _find_h5_dataset(f, "drive"),
            "power": _find_h5_dataset(f, "power"),
        }

        missing = [key for key in ("x", "y", "ted", "drive") if refs[key] is None]
        if missing:
            raise RuntimeError(
                "HDF5 input is missing required row-aligned datasets: "
                + ", ".join(missing)
                + ". Required channels are X-Machine, Y-Machine, On-Axis TED, and Laser Drive."
            )

        x_ref = refs["x"]
        y_ref = refs["y"]
        ted_ref = refs["ted"]
        drive_ref = refs["drive"]
        assert x_ref is not None and y_ref is not None and ted_ref is not None and drive_ref is not None

        laser_x_mm = _read_h5_1d_float64(f, x_ref)
        laser_y_mm = _read_h5_1d_float64(f, y_ref)
        on_axis_ted_raw = _read_h5_1d_float64(f, ted_ref)
        drive = _read_h5_1d_float64(f, drive_ref)

    lengths = [laser_x_mm.size, laser_y_mm.size, on_axis_ted_raw.size, drive.size]
    n_rows = int(min(lengths))
    if len(set(lengths)) != 1:
        print(
            "Warning: HDF5 row-aligned channel lengths differ; trimming selected "
            f"channels to {n_rows} rows. Original lengths: {lengths}"
        )
        laser_x_mm = laser_x_mm[:n_rows]
        laser_y_mm = laser_y_mm[:n_rows]
        on_axis_ted_raw = on_axis_ted_raw[:n_rows]
        drive = drive[:n_rows]

    observed_frequencies = [
        ref.frequency_hz
        for ref in (x_ref, y_ref, ted_ref, drive_ref)
        if ref.frequency_hz is not None
    ]
    fs_hz = PRODUCTION_DAQ_FREQUENCY_HZ
    threshold = (
        PRODUCTION_LASER_DRIVE_THRESHOLD
        if params.input.laser_drive_threshold is None
        else float(params.input.laser_drive_threshold)
    )
    laser_on = drive > threshold
    scan_track_id = _compute_scan_track_id(laser_on)

    ted_fields = _compute_ted_absorptivity_fields(
        on_axis_ted_raw=on_axis_ted_raw,
        laser_on=laser_on,
        params=params,
    )
    effective_absorptivity = np.asarray(ted_fields["effective_absorptivity"], dtype=float)
    reference_nonpositive_flag = np.asarray(ted_fields["ted_reference_nonpositive_flag"], dtype=bool)
    valid_powered = np.asarray(ted_fields["powered_valid_flag"], dtype=bool)
    commanded_power_W = np.where(valid_powered, float(params.heat_source.incident_power_W), 0.0)
    spot_size_um = np.full(n_rows, float(params.input.default_spot_size_um), dtype=float)
    pyrometer_K = np.full(n_rows, np.nan, dtype=float)
    time_s = fixed_production_time_s(n_rows)

    dataset_refs = {
        key: {
            "path": ref.path,
            "shape": list(ref.shape),
            "dtype": ref.dtype,
            "frequency_hz": ref.frequency_hz,
        }
        for key, ref in refs.items()
        if ref is not None
    }
    metadata = {
        "path": str(resolved_path),
        "dataset_refs": dataset_refs,
        "loaded_rows": n_rows,
        "time_start_s": float(time_s[0]) if n_rows else np.nan,
        "time_end_s": float(time_s[-1]) if n_rows else np.nan,
        "sample_frequency_hz": fs_hz,
        "process_dt_s": PRODUCTION_DAQ_DT_S,
        "process_time_source": PRODUCTION_TIME_SOURCE,
        "observed_channel_frequency_metadata_hz": observed_frequencies,
        "observed_channel_frequency_metadata_role": "diagnostic_only",
        "configured_h5_fallback_frequency_role": "ignored_for_production_clock",
        "laser_drive_threshold_used": threshold,
        "powered_rows": int(np.count_nonzero(laser_on)),
        "scan_tracks": int(np.max(scan_track_id)) if scan_track_id.size else 0,
        "manual_laser_power_W": float(params.heat_source.incident_power_W),
        "default_spot_size_um": float(params.input.default_spot_size_um),
        "ted_reference_slope": float(params.input.ted_reference_slope),
        "ted_reference_intercept": float(params.input.ted_reference_intercept),
        "ted_reference_power_basis": "manual HeatSourceParameters.incident_power_W",
        "ted_reference_within_layer_policy": "constant scalar for constant configured incident power",
        "ted_reference_gain_dependency": "not modeled; no canonical detector-gain input",
        "ted_reference_acquisition_segment_dependency": "not modeled",
        "ted_reference_100pct_reflection_at_manual_power": float(
            np.asarray(ted_fields["ted_reference_100pct_reflection"])[0]
        ) if n_rows else np.nan,
        "ted_baseline_policy": str(params.input.ted_baseline_policy),
        "ted_baseline_evidence_policy": str(params.input.ted_baseline_evidence_policy),
        "ted_off_segment_outlier_sigma_multiplier": float(
            params.input.ted_off_segment_outlier_sigma_multiplier
        ),
        "ted_global_off_baseline": float(ted_fields["ted_global_off_baseline"]),
        "ted_baseline_status": str(ted_fields["ted_baseline_status"]),
        "ted_baseline_evidence": ted_fields["ted_baseline_evidence_summary"],
        "clipping_policy": "clip TED reflected fraction to [0, 1]; absorptivity = 1 - clipped_fraction",
        "low_clipping_events": int(np.count_nonzero(ted_fields["ted_reflection_clipped_low_flag"])),
        "high_clipping_events": int(np.count_nonzero(ted_fields["ted_reflection_clipped_high_flag"])),
        "ted_calibration_valid_powered_rows": int(np.count_nonzero(ted_fields["ted_calibration_valid_flag"])),
        "ted_invalid_powered_rows": int(np.count_nonzero(ted_fields["ted_invalid_powered_flag"])),
        "ted_invalid_powered_source_policy": "physical laser_on is retained for motion bookkeeping, but invalid powered rows are source-disabled",
        "laser_power_channel_policy": "ignored; raw analog channel is not physical source power",
    }

    data = LaserInputData(
        time_s=time_s,
        laser_x_mm=laser_x_mm,
        laser_y_mm=laser_y_mm,
        pyrometer_K=pyrometer_K,
        commanded_power_W=commanded_power_W,
        spot_size_um=spot_size_um,
        measured_reflectivity=np.asarray(ted_fields["ted_reflected_fraction_used"], dtype=float),
        laser_on=laser_on,
        source_columns={
            "time_s": "np.arange(n) * 5.0e-6",
            "laser_x_mm": x_ref.path,
            "laser_y_mm": y_ref.path,
            "pyrometer_K": None,
            "commanded_power_W": "manual HeatSourceParameters.incident_power_W only when laser_on and TED calibration-valid; otherwise 0",
            "spot_size_um": "constant InputControls.default_spot_size_um",
            "measured_reflectivity": "TED reflected_fraction_used",
            "laser_on": drive_ref.path,
            "on_axis_ted_raw": ted_ref.path,
        },
        input_mode="hdf5",
        input_path=str(resolved_path),
        h5_metadata=metadata,
        h5_laser_drive_threshold_used=float(threshold),
        h5_sample_frequency_hz=float(fs_hz),
        ted_global_off_baseline=float(ted_fields["ted_global_off_baseline"]),
        ted_baseline_status=str(ted_fields["ted_baseline_status"]),
        on_axis_ted_raw=on_axis_ted_raw,
        ted_baseline_used=np.asarray(ted_fields["ted_baseline_used"], dtype=float),
        ted_signal_corrected=np.asarray(ted_fields["ted_signal_corrected"], dtype=float),
        ted_reference_100pct_reflection=np.asarray(ted_fields["ted_reference_100pct_reflection"], dtype=float),
        ted_reflected_fraction_raw=np.asarray(ted_fields["ted_reflected_fraction_raw"], dtype=float),
        ted_reflected_fraction_used=np.asarray(ted_fields["ted_reflected_fraction_used"], dtype=float),
        effective_absorptivity_raw=np.asarray(ted_fields["effective_absorptivity_raw"], dtype=float),
        effective_absorptivity=effective_absorptivity,
        ted_reflection_clipped_low_flag=np.asarray(ted_fields["ted_reflection_clipped_low_flag"], dtype=bool),
        ted_reflection_clipped_high_flag=np.asarray(ted_fields["ted_reflection_clipped_high_flag"], dtype=bool),
        ted_reference_nonpositive_flag=reference_nonpositive_flag,
        scan_track_id=scan_track_id,
        row_index=np.arange(n_rows, dtype=np.int64),
        laser_drive=drive,
        ted_nonfinite_flag=np.asarray(ted_fields["ted_nonfinite_flag"], dtype=bool),
        ted_calibration_valid_flag=np.asarray(ted_fields["ted_calibration_valid_flag"], dtype=bool),
        ted_invalid_powered_flag=np.asarray(ted_fields["ted_invalid_powered_flag"], dtype=bool),
    )

    _print_h5_load_summary(data)
    return data


def _print_h5_load_summary(data: LaserInputData) -> None:
    metadata = data.h5_metadata or {}
    dataset_refs = metadata.get("dataset_refs", {})
    print("Loaded HDF5 moving-window input.")
    print(f"  HDF5 path:                         {metadata.get('path', data.input_path)}")
    print(f"  Rows loaded:                       {data.n_rows}")
    print(f"  Duration:                          {float(data.time_s[-1] - data.time_s[0]) if data.n_rows > 1 else 0.0:.6e} s")
    print(f"  Sample frequency:                  {metadata.get('sample_frequency_hz', data.h5_sample_frequency_hz):.6g} Hz")
    print("  Dataset paths used:")
    for key in ("x", "y", "ted", "drive"):
        ref = dataset_refs.get(key, {})
        print(f"    {key:5s}: {ref.get('path', 'not found')}")
    print(f"  Laser Drive threshold:             {metadata.get('laser_drive_threshold_used', data.h5_laser_drive_threshold_used):.6g}")
    print(f"  Powered rows:                      {metadata.get('powered_rows', int(np.count_nonzero(data.laser_on)))}")
    print(f"  Scan tracks:                       {metadata.get('scan_tracks', 0)}")
    print(f"  Manual laser power:                {metadata.get('manual_laser_power_W', np.nan):.6g} W")
    print(f"  Reference TED at manual power:     {metadata.get('ted_reference_100pct_reflection_at_manual_power', np.nan):.6g}")
    print(f"  Global off-baseline TED:           {metadata.get('ted_global_off_baseline', data.ted_global_off_baseline):.6g}")
    print(f"  Low clipping events:               {metadata.get('low_clipping_events', 0)}")
    print(f"  High clipping events:              {metadata.get('high_clipping_events', 0)}")
    print(f"  TED-valid powered rows:            {metadata.get('ted_calibration_valid_powered_rows', 0)}")
    print(f"  TED-invalid powered rows:          {metadata.get('ted_invalid_powered_rows', 0)}")



@dataclass(frozen=True)
class LayerH5ObservationTable:
    """Frame-rate experimental observations projected onto process rows.

    Each entry corresponds to one synchronization-valid GigE camera frame.
    Experimental H/W remain sourced from the process-row channels selected by
    ``gige_image_to_data_index``; no process-rate duplication is introduced.
    """

    frame_index: np.ndarray
    gige_time_s: np.ndarray
    mapped_process_row: np.ndarray
    experimental_h_pixels: np.ndarray
    experimental_w_pixels: np.ndarray

    @property
    def n_observations(self) -> int:
        return int(self.frame_index.size)


@dataclass(frozen=True)
class LayerH5ProcessData:
    """Layer HDF5 process, experimental H/W, and camera synchronization data.

    Camera-rate synchronization products are explicit fields so downstream
    comparison code does not need to recover them from generic HDF5 metadata.
    Process integration always uses the fixed 200 kHz DAQ row clock.
    Synchronized timestamps are retained only as camera-alignment diagnostics.
    """

    process: LaserInputData
    names: list[str]
    data: np.ndarray
    experimental_h_pixels: np.ndarray
    experimental_w_pixels: np.ndarray
    gige_time_s: np.ndarray | None = None
    gige_image_to_data_index: np.ndarray | None = None
    valid_gige_frame_mask: np.ndarray | None = None
    synchronization_mapping_dataset: str | None = None
    synchronization_process_time_dataset: str | None = None
    synchronization_method: str | None = None
    synchronization_version: str | None = None
    observation_table: LayerH5ObservationTable | None = None


def decode_h5_names(values: np.ndarray) -> list[str]:
    names: list[str] = []
    for value in np.asarray(values).reshape(-1):
        if isinstance(value, bytes):
            names.append(value.decode("utf-8"))
        else:
            names.append(str(value))
    return names


def load_layer_h5_ted_process_data(
    path: str | Path,
    layer_name: str,
    params: SimulationParameters,
) -> LayerTEDProcessData:
    """Load only layer Laser Drive and On-Axis TED for Patch 11.2 diagnostics.

    Melt-pool H/W rows, camera products, coordinates, and source-fit inputs are
    deliberately not read.  The returned baseline and selected off-state mask
    reproduce the Patch 10.2.1 robust laser-off evidence path.
    """
    path = Path(path)
    with h5py.File(path, "r") as h5_file:
        if layer_name not in h5_file:
            raise KeyError(f"Input HDF5 does not contain {layer_name!r}.")
        group = h5_file[layer_name]
        if "data" not in group or "names" not in group:
            raise KeyError(f"{layer_name} must contain both 'data' and 'names' datasets.")

        names = decode_h5_names(group["names"][:])
        data_dataset = group["data"]
        if data_dataset.ndim != 2 or data_dataset.shape[0] != len(names):
            raise ValueError(
                f"{layer_name}/data must have one row per entry in {layer_name}/names."
            )

        required = ("Laser Drive", "On-Axis TED")
        missing = [name for name in required if name not in names]
        if missing:
            raise KeyError(
                f"{layer_name} is missing required TED diagnostic channels: "
                + ", ".join(missing)
            )

        drive = np.asarray(data_dataset[names.index("Laser Drive"), :], dtype=np.float64)
        ted = np.asarray(data_dataset[names.index("On-Axis TED"), :], dtype=np.float64)
        sync_group = group.get("sync")
        if params.input.laser_drive_threshold is not None:
            drive_threshold = float(params.input.laser_drive_threshold)
        elif isinstance(sync_group, h5py.Group) and "data_threshold" in sync_group.attrs:
            # Historical synthetic/replay files can retain their explicit
            # synchronization threshold. Patch 16 entry points independently
            # enforce 2.5 and never delegate that decision to this attribute.
            drive_threshold = float(sync_group.attrs["data_threshold"])
        else:
            drive_threshold = PRODUCTION_LASER_DRIVE_THRESHOLD

    if drive.shape != ted.shape or drive.ndim != 1:
        raise ValueError(
            f"{layer_name} Laser Drive and On-Axis TED must be row-aligned one-dimensional channels."
        )

    laser_on = drive > drive_threshold
    scan_track_id = _compute_scan_track_id(laser_on)
    baseline, baseline_status, evidence = _compute_ted_baseline(ted, laser_on, params)

    selected_segments = {
        int(item["segment_index"])
        for item in evidence.get("segments", [])
        if isinstance(item, dict)
        and bool(item.get("selected_for_baseline", False))
        and int(item.get("finite_rows", 0)) > 0
    }
    selected_off_mask = np.zeros(ted.shape, dtype=bool)
    for segment_index, run in enumerate(_contiguous_mask_runs(~laser_on)):
        if segment_index in selected_segments:
            selected_off_mask[run] = np.isfinite(ted[run])

    sample_frequency_hz = PRODUCTION_DAQ_FREQUENCY_HZ
    row_index = np.arange(ted.size, dtype=np.int64)

    return LayerTEDProcessData(
        time_s=fixed_production_time_s(row_index.size),
        row_index=row_index,
        laser_drive=drive,
        laser_on=laser_on,
        on_axis_ted_raw=ted,
        scan_track_id=scan_track_id,
        selected_laser_off_evidence_mask=selected_off_mask,
        ted_global_off_baseline=float(baseline),
        ted_baseline_status=str(baseline_status),
        ted_baseline_evidence=evidence,
        input_path=str(path),
        layer_name=str(layer_name),
        sample_frequency_hz=sample_frequency_hz,
        laser_drive_threshold_used=float(drive_threshold),
    )



def load_layer_h5_ted_structure_data_11_2_4(
    path: str | Path,
    layer_name: str,
    params: SimulationParameters,
) -> LayerTEDStructureData:
    """Load the Patch 11.2.4 TED diagnostic channels without H/W.

    Patch 11.2.4 adds only the machine X/Y coordinates needed to examine
    spatial structure.  Baseline/TED processing is delegated to the narrow
    Patch 11.2 TED loader, and the H/W rows are never indexed or materialized.
    """
    ted_process = load_layer_h5_ted_process_data(path, layer_name, params)
    path = Path(path)
    with h5py.File(path, "r") as h5_file:
        group = h5_file[layer_name]
        names = decode_h5_names(group["names"][:])
        data_dataset = group["data"]
        required = ("X-Machine", "Y-Machine")
        missing = [name for name in required if name not in names]
        if missing:
            raise KeyError(
                f"{layer_name} is missing required Patch 11.2.4 position channels: "
                + ", ".join(missing)
            )
        x_mm = np.asarray(data_dataset[names.index("X-Machine"), :], dtype=np.float64)
        y_mm = np.asarray(data_dataset[names.index("Y-Machine"), :], dtype=np.float64)

    if x_mm.shape != y_mm.shape or x_mm.shape != ted_process.on_axis_ted_raw.shape:
        raise ValueError("Patch 11.2.4 X/Y and TED arrays must be row-aligned.")
    return LayerTEDStructureData(
        ted_process=ted_process,
        laser_x_mm=x_mm,
        laser_y_mm=y_mm,
    )




def _synchronized_process_time_diagnostics(
    group: h5py.Group,
    *,
    layer_name: str,
    n_rows: int,
) -> tuple[np.ndarray, dict[str, float | str | bool]]:
    """Inspect optional Windows-derived timestamps as diagnostics only.

    Patch 16.0 forbids this dataset from controlling integration or speed.
    Malformed values are reported and never substituted for the fixed DAQ clock.
    """
    sync_group = group.get("sync")
    if not isinstance(sync_group, h5py.Group):
        return np.empty(0, dtype=np.float64), {"available": False, "valid": False}
    if "data_to_gige_time" not in sync_group:
        return np.empty(0, dtype=np.float64), {"available": False, "valid": False}
    dataset = sync_group["data_to_gige_time"]
    if not isinstance(dataset, h5py.Dataset) or dataset.ndim != 1:
        return np.empty(0, dtype=np.float64), {
            "available": True,
            "valid": False,
            "reason": "not_one_dimensional",
        }
    if int(dataset.shape[0]) != int(n_rows):
        return np.empty(0, dtype=np.float64), {
            "available": True,
            "valid": False,
            "reason": "length_mismatch",
        }
    time_s = np.asarray(dataset[:], dtype=np.float64)
    if not np.all(np.isfinite(time_s)):
        return time_s, {"available": True, "valid": False, "reason": "nonfinite"}
    if n_rows > 1:
        dt_s = np.diff(time_s)
        if np.any(dt_s <= 0.0):
            return time_s, {
                "available": True,
                "valid": False,
                "reason": "not_strictly_increasing",
            }
        span_s = float(time_s[-1] - time_s[0])
        if not np.isfinite(span_s) or span_s <= 0.0:
            return time_s, {
                "available": True,
                "valid": False,
                "reason": "invalid_span",
            }
        effective_rate_hz = float((n_rows - 1) / span_s)
        median_dt_s = float(np.median(dt_s))
        min_dt_s = float(np.min(dt_s))
        max_dt_s = float(np.max(dt_s))
        nonuniform = not bool(
            np.allclose(dt_s, median_dt_s, rtol=1.0e-6, atol=max(1.0e-15, abs(median_dt_s) * 1.0e-9))
        )
    else:
        span_s = 0.0
        effective_rate_hz = float("nan")
        median_dt_s = float("nan")
        min_dt_s = float("nan")
        max_dt_s = float("nan")
        nonuniform = False
    return time_s, {
        "available": True,
        "valid": True,
        "diagnostic_dataset": SYNCHRONIZED_TIME_DIAGNOSTIC_DATASET,
        "role": "diagnostic_only_not_solver_clock",
        "process_time_span_s": span_s,
        "effective_process_rate_hz": effective_rate_hz,
        "median_process_dt_s": median_dt_s,
        "min_process_dt_s": min_dt_s,
        "max_process_dt_s": max_dt_s,
        "process_time_nonuniform": nonuniform,
    }


def _validate_camera_process_sync_consistency(
    *,
    layer_name: str,
    process_time_s: np.ndarray,
    gige_time_s: np.ndarray,
    gige_image_to_data_index: np.ndarray,
) -> None:
    """Validate camera-row mapping structure without using Windows time as a clock."""
    if gige_time_s.ndim != 1 or gige_image_to_data_index.ndim != 1:
        raise ValueError(f"{layer_name} camera synchronization arrays must be one-dimensional.")
    if gige_time_s.size != gige_image_to_data_index.size:
        raise ValueError(
            f"{layer_name} camera synchronization length mismatch: "
            f"gige_time has {gige_time_s.size} frames but sync/gige_image_to_data_index "
            f"has {gige_image_to_data_index.size}."
        )
    if not np.all(np.isfinite(gige_time_s)):
        raise ValueError(f"{layer_name}/gige_time contains non-finite timestamps.")
    if gige_time_s.size > 1 and np.any(np.diff(gige_time_s) <= 0.0):
        raise ValueError(f"{layer_name}/gige_time must be strictly increasing.")
    valid = gige_image_to_data_index >= 0
    mapped = gige_image_to_data_index[valid]
    if mapped.size and np.any(mapped >= process_time_s.size):
        invalid = np.unique(mapped[mapped >= process_time_s.size])
        preview = ", ".join(str(int(value)) for value in invalid[:5])
        if invalid.size > 5:
            preview += ", ..."
        raise ValueError(
            f"{layer_name} sync/gige_image_to_data_index contains mapped process "
            f"indices outside [0, {process_time_s.size - 1}]: {preview}. Negative indices are "
            "reserved for unmapped camera frames."
        )
    if mapped.size > 1 and np.any(np.diff(mapped) < 0):
        raise ValueError(
            f"{layer_name} camera/process synchronization is inconsistent: mapped process rows "
            "must be nondecreasing as gige_time increases."
        )


def load_layer_h5_process_data(
    path: str | Path,
    layer_name: str,
    params: SimulationParameters,
    *,
    require_camera_sync: bool = False,
) -> LayerH5ProcessData:
    """Load one layer and calibrate its physical process channels once.

    When ``require_camera_sync`` is true, the canonical timestamp-comparison
    inputs ``gige_time`` and ``sync/gige_image_to_data_index`` are mandatory
    and validated against the process-row count. Negative mapped indices are
    retained as explicit unmapped-frame markers.
    """
    path = Path(path)
    with h5py.File(path, "r") as h5_file:
        if layer_name not in h5_file:
            raise KeyError(f"Input HDF5 does not contain {layer_name!r}.")
        group = h5_file[layer_name]
        if "data" not in group or "names" not in group:
            raise KeyError(f"{layer_name} must contain both 'data' and 'names' datasets.")

        names = decode_h5_names(group["names"][:])
        data = np.asarray(group["data"][:], dtype=np.float64)
        if data.ndim != 2 or data.shape[0] != len(names):
            raise ValueError(
                f"{layer_name}/data must have one row per entry in {layer_name}/names."
            )

        # Camera/synchronization products are explicit layer-input fields.
        # Patch 9.2.2 selects gige_image_to_data_index as the canonical mapping
        # for timestamp-based comparison and validates it when requested.
        gige_time_s = (
            np.ravel(np.asarray(group["gige_time"][:], dtype=np.float64))
            if "gige_time" in group
            else None
        )
        sync_group = group.get("sync")
        gige_image_to_data_index = (
            np.ravel(
                np.asarray(
                    sync_group["gige_image_to_data_index"][:],
                    dtype=np.int64,
                )
            )
            if isinstance(sync_group, h5py.Group)
            and "gige_image_to_data_index" in sync_group
            else None
        )
        synchronization_mapping_dataset = (
            "sync/gige_image_to_data_index"
            if gige_image_to_data_index is not None
            else None
        )
        synchronization_method = (
            str(sync_group.attrs["method"])
            if isinstance(sync_group, h5py.Group) and "method" in sync_group.attrs
            else None
        )
        synchronization_version = (
            str(sync_group.attrs["sync_gige_to_data_version"])
            if isinstance(sync_group, h5py.Group)
            and "sync_gige_to_data_version" in sync_group.attrs
            else None
        )

        if require_camera_sync:
            if gige_time_s is None:
                raise KeyError(
                    f"{layer_name} requires 'gige_time' for timestamp-based comparison."
                )
            if gige_image_to_data_index is None:
                raise KeyError(
                    f"{layer_name} requires the canonical mapping "
                    "'sync/gige_image_to_data_index' for timestamp-based comparison."
                )

        # Machine coordinates are the only physical position channels accepted.
        required = ["Laser Drive", "On-Axis TED", "X-Machine", "Y-Machine", "H", "W"]
        missing = [name for name in required if name not in names]
        if missing:
            raise KeyError(f"{layer_name} is missing required channels: " + ", ".join(missing))
        channel = {name: data[names.index(name), :] for name in required}

        if params.input.laser_drive_threshold is not None:
            drive_threshold = float(params.input.laser_drive_threshold)
        elif isinstance(sync_group, h5py.Group) and "data_threshold" in sync_group.attrs:
            # Compatibility for historical replay fixtures only. Patch 16.0's
            # audit/runner enforces the frozen 2.5 threshold directly.
            drive_threshold = float(sync_group.attrs["data_threshold"])
        else:
            drive_threshold = PRODUCTION_LASER_DRIVE_THRESHOLD
        synchronized_process_time_s, synchronized_process_time_metadata = (
            _synchronized_process_time_diagnostics(
                group, layer_name=layer_name, n_rows=int(data.shape[1])
            )
        )

    drive = np.asarray(channel["Laser Drive"], dtype=np.float64)
    ted = np.asarray(channel["On-Axis TED"], dtype=np.float64)
    x_mm = np.asarray(channel["X-Machine"], dtype=np.float64)
    y_mm = np.asarray(channel["Y-Machine"], dtype=np.float64)
    laser_on = drive > drive_threshold
    scan_track_id = _compute_scan_track_id(laser_on)
    ted_fields = _compute_ted_absorptivity_fields(ted, laser_on, params)
    effective = np.asarray(ted_fields["effective_absorptivity"], dtype=np.float64)
    reference_nonpositive = np.asarray(ted_fields["ted_reference_nonpositive_flag"], dtype=bool)
    valid_powered = np.asarray(ted_fields["powered_valid_flag"], dtype=bool)
    n_rows = int(drive.size)
    configured_sample_frequency_hz = float(params.comparison.sample_frequency_hz)
    row_index = np.arange(n_rows, dtype=np.int64)

    synchronization_process_time_dataset: str | None = (
        SYNCHRONIZED_TIME_DIAGNOSTIC_DATASET
        if bool(synchronized_process_time_metadata.get("available"))
        else None
    )
    process_time_s = fixed_production_time_s(n_rows)
    assert_fixed_production_time_s(process_time_s)
    process_time_metadata = {
        "process_time_source": PRODUCTION_TIME_SOURCE,
        "process_time_span_s": float((n_rows - 1) * PRODUCTION_DAQ_DT_S) if n_rows else 0.0,
        "effective_process_rate_hz": PRODUCTION_DAQ_FREQUENCY_HZ,
        "median_process_dt_s": PRODUCTION_DAQ_DT_S,
        "min_process_dt_s": PRODUCTION_DAQ_DT_S,
        "max_process_dt_s": PRODUCTION_DAQ_DT_S,
        "process_time_nonuniform": False,
        "synchronized_windows_time": synchronized_process_time_metadata,
    }
    if require_camera_sync:
        assert gige_time_s is not None
        assert gige_image_to_data_index is not None
        _validate_camera_process_sync_consistency(
            layer_name=layer_name,
            process_time_s=process_time_s,
            gige_time_s=gige_time_s,
            gige_image_to_data_index=gige_image_to_data_index,
        )
    effective_process_rate_hz = PRODUCTION_DAQ_FREQUENCY_HZ

    valid_gige_frame_mask = (
        (gige_image_to_data_index >= 0) & (gige_image_to_data_index < n_rows)
        if gige_image_to_data_index is not None
        else None
    )

    observation_table: LayerH5ObservationTable | None = None
    if (
        gige_time_s is not None
        and gige_image_to_data_index is not None
        and valid_gige_frame_mask is not None
        and gige_time_s.size == gige_image_to_data_index.size
    ):
        # Patch 9.2.3: one table row per synchronization-valid camera frame.
        # Multiple camera frames mapping to one process row remain separate rows;
        # process rows without a camera frame do not create observations.
        frame_index = np.flatnonzero(valid_gige_frame_mask).astype(np.int64, copy=False)
        mapped_process_row = gige_image_to_data_index[frame_index].astype(
            np.int64, copy=False
        )
        observation_table = LayerH5ObservationTable(
            frame_index=frame_index,
            gige_time_s=gige_time_s[frame_index].astype(np.float64, copy=False),
            mapped_process_row=mapped_process_row,
            experimental_h_pixels=np.asarray(
                channel["H"][mapped_process_row], dtype=np.float64
            ),
            experimental_w_pixels=np.asarray(
                channel["W"][mapped_process_row], dtype=np.float64
            ),
        )

    process = LaserInputData(
        time_s=process_time_s,
        laser_x_mm=x_mm,
        laser_y_mm=y_mm,
        pyrometer_K=np.full(n_rows, np.nan, dtype=np.float64),
        commanded_power_W=np.where(valid_powered, float(params.heat_source.incident_power_W), 0.0),
        spot_size_um=np.full(n_rows, float(params.input.default_spot_size_um), dtype=np.float64),
        measured_reflectivity=np.asarray(ted_fields["ted_reflected_fraction_used"], dtype=np.float64),
        laser_on=laser_on,
        source_columns={
            "laser_x_mm": "X-Machine",
            "laser_y_mm": "Y-Machine",
            "laser_on": "Laser Drive",
            "on_axis_ted_raw": "On-Axis TED",
        },
        input_mode="hdf5_layer",
        input_path=str(path),
        h5_metadata={
            "path": str(path),
            "layer_name": layer_name,
            "sample_frequency_hz": effective_process_rate_hz,
            "configured_comparison_sample_frequency_hz": configured_sample_frequency_hz,
            "configured_comparison_sample_frequency_role": "metadata_only_ignored_for_production_clock",
            **process_time_metadata,
            "laser_drive_threshold_used": float(drive_threshold),
            "powered_rows": int(np.count_nonzero(laser_on)),
            "scan_tracks": int(np.max(scan_track_id)) if scan_track_id.size else 0,
            "manual_laser_power_W": float(params.heat_source.incident_power_W),
            "ted_reference_slope": float(params.input.ted_reference_slope),
            "ted_reference_intercept": float(params.input.ted_reference_intercept),
            "ted_reference_power_basis": "manual HeatSourceParameters.incident_power_W",
            "ted_reference_within_layer_policy": "constant scalar for constant configured incident power",
            "ted_reference_gain_dependency": "not modeled; no canonical detector-gain input",
            "ted_reference_acquisition_segment_dependency": "not modeled",
            "ted_reference_100pct_reflection_at_manual_power": float(
                np.asarray(ted_fields["ted_reference_100pct_reflection"])[0]
            ) if n_rows else np.nan,
            "ted_reference_method": (
                "ted_reference_slope * incident_power_W + ted_reference_intercept"
            ),
            "ted_baseline_policy": str(params.input.ted_baseline_policy),
            "ted_baseline_evidence_policy": str(params.input.ted_baseline_evidence_policy),
            "ted_off_segment_outlier_sigma_multiplier": float(
                params.input.ted_off_segment_outlier_sigma_multiplier
            ),
            "ted_global_off_baseline": float(ted_fields["ted_global_off_baseline"]),
            "ted_baseline_status": str(ted_fields["ted_baseline_status"]),
            "ted_baseline_evidence": ted_fields["ted_baseline_evidence_summary"],
            "clipping_policy": (
                "clip TED reflected fraction to [0, 1]; "
                "absorptivity = 1 - clipped_fraction"
            ),
            "low_clipping_events": int(
                np.count_nonzero(ted_fields["ted_reflection_clipped_low_flag"])
            ),
            "high_clipping_events": int(
                np.count_nonzero(ted_fields["ted_reflection_clipped_high_flag"])
            ),
            "ted_calibration_valid_powered_rows": int(
                np.count_nonzero(ted_fields["ted_calibration_valid_flag"])
            ),
            "ted_invalid_powered_rows": int(
                np.count_nonzero(ted_fields["ted_invalid_powered_flag"])
            ),
            "ted_invalid_powered_source_policy": (
                "physical laser_on is retained for motion bookkeeping, but invalid powered rows are source-disabled"
            ),
            "synchronization_mapping_dataset": synchronization_mapping_dataset,
            "synchronization_process_time_dataset": synchronization_process_time_dataset,
            "synchronization_method": synchronization_method,
            "synchronization_version": synchronization_version,
        },
        h5_laser_drive_threshold_used=float(drive_threshold),
        h5_sample_frequency_hz=effective_process_rate_hz,
        ted_global_off_baseline=float(ted_fields["ted_global_off_baseline"]),
        ted_baseline_status=str(ted_fields["ted_baseline_status"]),
        on_axis_ted_raw=ted,
        ted_baseline_used=np.asarray(ted_fields["ted_baseline_used"], dtype=np.float64),
        ted_signal_corrected=np.asarray(ted_fields["ted_signal_corrected"], dtype=np.float64),
        ted_reference_100pct_reflection=np.asarray(ted_fields["ted_reference_100pct_reflection"], dtype=np.float64),
        ted_reflected_fraction_raw=np.asarray(ted_fields["ted_reflected_fraction_raw"], dtype=np.float64),
        ted_reflected_fraction_used=np.asarray(ted_fields["ted_reflected_fraction_used"], dtype=np.float64),
        effective_absorptivity_raw=np.asarray(ted_fields["effective_absorptivity_raw"], dtype=np.float64),
        effective_absorptivity=effective,
        ted_reflection_clipped_low_flag=np.asarray(ted_fields["ted_reflection_clipped_low_flag"], dtype=bool),
        ted_reflection_clipped_high_flag=np.asarray(ted_fields["ted_reflection_clipped_high_flag"], dtype=bool),
        ted_reference_nonpositive_flag=reference_nonpositive,
        scan_track_id=scan_track_id,
        row_index=row_index,
        laser_drive=drive,
        ted_nonfinite_flag=np.asarray(ted_fields["ted_nonfinite_flag"], dtype=bool),
        ted_calibration_valid_flag=np.asarray(ted_fields["ted_calibration_valid_flag"], dtype=bool),
        ted_invalid_powered_flag=np.asarray(ted_fields["ted_invalid_powered_flag"], dtype=bool),
    )
    return LayerH5ProcessData(
        process=process,
        names=names,
        data=data,
        experimental_h_pixels=np.asarray(channel["H"], dtype=np.float64),
        experimental_w_pixels=np.asarray(channel["W"], dtype=np.float64),
        gige_time_s=gige_time_s,
        gige_image_to_data_index=gige_image_to_data_index,
        valid_gige_frame_mask=valid_gige_frame_mask,
        synchronization_mapping_dataset=synchronization_mapping_dataset,
        synchronization_process_time_dataset=synchronization_process_time_dataset,
        synchronization_method=synchronization_method,
        synchronization_version=synchronization_version,
        observation_table=observation_table,
    )


@dataclass(frozen=True)
class H5StreamContext:
    path: Path
    refs: dict[str, _H5DatasetRef]
    n_rows: int
    sample_frequency_hz: float
    laser_drive_threshold: float
    ted_global_off_baseline: float
    ted_baseline_status: str
    ted_reference_scalar: float
    metadata: dict[str, Any]


def _read_h5_block(dataset: h5py.Dataset, start: int, stop: int) -> np.ndarray:
    return np.asarray(dataset[start:stop]).reshape(-1).astype(np.float64, copy=False)


def _sample_finite_h5_range(
    dataset: h5py.Dataset,
    *,
    start: int,
    stop: int,
    finite_ordinal_targets: np.ndarray,
    block_rows: int,
) -> np.ndarray:
    """Read selected finite-value ordinals from one HDF5 row range."""
    targets = np.asarray(finite_ordinal_targets, dtype=np.int64)
    if targets.size == 0:
        return np.empty(0, dtype=np.float64)
    samples = np.empty(targets.size, dtype=np.float64)
    finite_seen = 0
    for block_start in range(int(start), int(stop), int(block_rows)):
        block_stop = min(block_start + int(block_rows), int(stop))
        values = _read_h5_block(dataset, block_start, block_stop)
        finite_values = values[np.isfinite(values)]
        finite_stop = finite_seen + int(finite_values.size)
        left = int(np.searchsorted(targets, finite_seen, side="left"))
        right = int(np.searchsorted(targets, finite_stop, side="left"))
        if right > left:
            local_indices = targets[left:right] - finite_seen
            samples[left:right] = finite_values[local_indices]
        finite_seen = finite_stop
    return samples


def _compute_ted_baseline_from_h5(
    *,
    ted_dataset: h5py.Dataset,
    drive_dataset: h5py.Dataset,
    threshold: float,
    n_rows: int,
    block_rows: int,
    params: SimulationParameters,
) -> tuple[float, str, dict[str, Any], int, int]:
    """Streaming-equivalent Patch 10.2.1 robust TED baseline calculation."""
    segment_statistics: list[dict[str, Any]] = []
    powered_rows = 0
    scan_tracks = 0
    previous_on = False

    for start in range(0, int(n_rows), int(block_rows)):
        stop = min(start + int(block_rows), int(n_rows))
        drive = _read_h5_block(drive_dataset, start, stop)
        ted = _read_h5_block(ted_dataset, start, stop)
        laser_on = drive > float(threshold)
        powered_rows += int(np.count_nonzero(laser_on))

        previous_flags = np.empty(laser_on.size, dtype=bool)
        previous_flags[0] = previous_on
        if laser_on.size > 1:
            previous_flags[1:] = laser_on[:-1]
        scan_tracks += int(np.count_nonzero(laser_on & (~previous_flags)))
        previous_on = bool(laser_on[-1])

        for local_run in _contiguous_mask_runs(~laser_on):
            row_start = start + int(local_run[0])
            row_end = start + int(local_run[-1])
            finite_rows = int(np.count_nonzero(np.isfinite(ted[local_run])))
            if segment_statistics and row_start == int(segment_statistics[-1]["row_end"]) + 1:
                segment_statistics[-1]["row_end"] = row_end
                segment_statistics[-1]["rows"] = (
                    int(segment_statistics[-1]["rows"]) + int(local_run.size)
                )
                segment_statistics[-1]["finite_rows"] = (
                    int(segment_statistics[-1]["finite_rows"]) + finite_rows
                )
            else:
                segment_statistics.append(
                    {
                        "segment_index": int(len(segment_statistics)),
                        "row_start": row_start,
                        "row_end": row_end,
                        "rows": int(local_run.size),
                        "finite_rows": finite_rows,
                        "statistics_sample_rows": 0,
                        "median": None,
                        "mad": None,
                    }
                )

    max_samples = int(params.input.h5_baseline_max_samples)
    for segment in segment_statistics:
        finite_rows = int(segment["finite_rows"])
        if finite_rows <= 0:
            continue
        targets = _evenly_spaced_sample_indices(finite_rows, max_samples)
        sampled = _sample_finite_h5_range(
            ted_dataset,
            start=int(segment["row_start"]),
            stop=int(segment["row_end"]) + 1,
            finite_ordinal_targets=targets,
            block_rows=int(block_rows),
        )
        median = float(np.median(sampled))
        segment["statistics_sample_rows"] = int(sampled.size)
        segment["median"] = median
        segment["mad"] = float(np.median(np.abs(sampled - median)))

    evidence_summary = _build_ted_baseline_evidence_summary(
        segment_statistics,
        evidence_policy=str(params.input.ted_baseline_evidence_policy),
        sigma_multiplier=float(params.input.ted_off_segment_outlier_sigma_multiplier),
    )
    selected_indices = {
        int(item["segment_index"])
        for item in evidence_summary["segments"]
        if bool(item["selected_for_baseline"])
    }
    selected_finite = int(
        sum(
            int(item["finite_rows"])
            for item in segment_statistics
            if int(item["segment_index"]) in selected_indices
        )
    )
    global_targets = _evenly_spaced_sample_indices(selected_finite, max_samples)
    baseline_samples = np.empty(global_targets.size, dtype=np.float64)
    selected_seen = 0
    for segment in segment_statistics:
        if int(segment["segment_index"]) not in selected_indices:
            continue
        finite_rows = int(segment["finite_rows"])
        selected_stop = selected_seen + finite_rows
        left = int(np.searchsorted(global_targets, selected_seen, side="left"))
        right = int(np.searchsorted(global_targets, selected_stop, side="left"))
        if right > left:
            local_targets = global_targets[left:right] - selected_seen
            baseline_samples[left:right] = _sample_finite_h5_range(
                ted_dataset,
                start=int(segment["row_start"]),
                stop=int(segment["row_end"]) + 1,
                finite_ordinal_targets=local_targets,
                block_rows=int(block_rows),
            )
        selected_seen = selected_stop

    baseline, baseline_status = _finalize_ted_baseline(
        baseline_samples,
        total_selected_finite=selected_finite,
        max_samples=max_samples,
        evidence_summary=evidence_summary,
    )
    return baseline, baseline_status, evidence_summary, powered_rows, scan_tracks


def prepare_h5_stream(
    params: SimulationParameters,
    max_rows: int | None = None,
) -> H5StreamContext:
    """Discover HDF5 channels and compute global calibration scalars in blocks."""
    path = resolve_h5_path(params)
    block_rows = int(params.output.input_block_rows)

    with h5py.File(path, "r") as h5_file:
        discovered = {
            key: _find_h5_dataset(h5_file, key)
            for key in ("x", "y", "ted", "drive", "power")
        }
        missing = [key for key in ("x", "y", "ted", "drive") if discovered[key] is None]
        if missing:
            raise RuntimeError(
                "HDF5 input is missing required row-aligned datasets: "
                + ", ".join(missing)
            )

        refs = {key: value for key, value in discovered.items() if value is not None}
        required_refs = [refs[key] for key in ("x", "y", "ted", "drive")]
        lengths = [int(ref.shape[0]) for ref in required_refs]
        n_rows = min(lengths)
        if max_rows is not None:
            n_rows = min(n_rows, int(max_rows))
        if n_rows < 1:
            raise ValueError("HDF5 input contains no rows.")

        observed_frequencies = [ref.frequency_hz for ref in required_refs if ref.frequency_hz]
        sample_frequency_hz = PRODUCTION_DAQ_FREQUENCY_HZ

        drive_dataset = h5_file[refs["drive"].path]
        threshold = (
            PRODUCTION_LASER_DRIVE_THRESHOLD
            if params.input.laser_drive_threshold is None
            else float(params.input.laser_drive_threshold)
        )

        ted_dataset = h5_file[refs["ted"].path]
        (
            baseline,
            baseline_status,
            baseline_evidence,
            powered_rows,
            scan_tracks,
        ) = _compute_ted_baseline_from_h5(
            ted_dataset=ted_dataset,
            drive_dataset=drive_dataset,
            threshold=threshold,
            n_rows=n_rows,
            block_rows=block_rows,
            params=params,
        )

    reference_scalar = _compute_ted_reference_scalar(params)
    metadata = {
        "path": str(path),
        "n_rows": n_rows,
        "sample_frequency_hz": sample_frequency_hz,
        "process_dt_s": PRODUCTION_DAQ_DT_S,
        "process_time_source": PRODUCTION_TIME_SOURCE,
        "observed_channel_frequency_metadata_hz": observed_frequencies,
        "observed_channel_frequency_metadata_role": "diagnostic_only",
        "laser_drive_threshold": threshold,
        "ted_global_off_baseline": baseline,
        "ted_baseline_status": baseline_status,
        "ted_baseline_policy": str(params.input.ted_baseline_policy),
        "ted_baseline_evidence_policy": str(params.input.ted_baseline_evidence_policy),
        "ted_off_segment_outlier_sigma_multiplier": float(
            params.input.ted_off_segment_outlier_sigma_multiplier
        ),
        "ted_baseline_evidence": baseline_evidence,
        "ted_reference_scalar": reference_scalar,
        "ted_reference_method": "ted_reference_slope * incident_power_W + ted_reference_intercept",
        "ted_reference_slope": float(params.input.ted_reference_slope),
        "ted_reference_intercept": float(params.input.ted_reference_intercept),
        "manual_laser_power_W": float(params.heat_source.incident_power_W),
        "ted_reference_power_basis": "manual HeatSourceParameters.incident_power_W",
        "ted_reference_within_layer_policy": "constant scalar for constant configured incident power",
        "ted_reference_gain_dependency": "not modeled; no canonical detector-gain input",
        "ted_reference_acquisition_segment_dependency": "not modeled",
        "powered_rows": powered_rows,
        "scan_tracks": scan_tracks,
        "dataset_refs": {
            key: {
                "path": ref.path,
                "shape": list(ref.shape),
                "dtype": ref.dtype,
                "frequency_hz": ref.frequency_hz,
            }
            for key, ref in refs.items()
        },
    }
    return H5StreamContext(
        path=path,
        refs=refs,
        n_rows=n_rows,
        sample_frequency_hz=sample_frequency_hz,
        laser_drive_threshold=threshold,
        ted_global_off_baseline=baseline,
        ted_baseline_status=baseline_status,
        ted_reference_scalar=reference_scalar,
        metadata=metadata,
    )


def iter_h5_process_blocks(
    context: H5StreamContext,
    params: SimulationParameters,
) -> Iterable[LaserInputData]:
    """Yield calibrated, row-aligned HDF5 input without loading the full print."""
    block_rows = int(params.output.input_block_rows)
    current_track = 0
    previous_on = False
    with h5py.File(context.path, "r") as h5_file:
        x_dataset = h5_file[context.refs["x"].path]
        y_dataset = h5_file[context.refs["y"].path]
        ted_dataset = h5_file[context.refs["ted"].path]
        drive_dataset = h5_file[context.refs["drive"].path]

        for start in range(0, context.n_rows, block_rows):
            stop = min(start + block_rows, context.n_rows)
            laser_x_mm = _read_h5_block(x_dataset, start, stop)
            laser_y_mm = _read_h5_block(y_dataset, start, stop)
            ted_raw = _read_h5_block(ted_dataset, start, stop)
            drive = _read_h5_block(drive_dataset, start, stop)
            laser_on = drive > context.laser_drive_threshold

            previous_flags = np.empty(laser_on.size, dtype=bool)
            previous_flags[0] = previous_on
            if laser_on.size > 1:
                previous_flags[1:] = laser_on[:-1]
            track_starts = laser_on & (~previous_flags)
            track_sequence = current_track + np.cumsum(track_starts, dtype=np.int64)
            scan_track_id = np.where(laser_on, track_sequence, 0).astype(np.int32)
            current_track += int(np.count_nonzero(track_starts))
            previous_on = bool(laser_on[-1])

            ted_fields = _calibrate_ted_rows(
                ted_raw,
                laser_on,
                baseline=context.ted_global_off_baseline,
                baseline_status=context.ted_baseline_status,
                reference_scalar=context.ted_reference_scalar,
                manual_power_W=float(params.heat_source.incident_power_W),
            )
            powered_valid = np.asarray(ted_fields["powered_valid_flag"], dtype=bool)
            used_fraction = np.asarray(ted_fields["ted_reflected_fraction_used"], dtype=np.float64)

            row_indices = np.arange(start, stop, dtype=np.int64)
            yield LaserInputData(
                time_s=row_indices.astype(np.float64) * PRODUCTION_DAQ_DT_S,
                laser_x_mm=laser_x_mm,
                laser_y_mm=laser_y_mm,
                pyrometer_K=np.full(stop - start, np.nan, dtype=np.float64),
                commanded_power_W=np.where(
                    powered_valid,
                    float(params.heat_source.incident_power_W),
                    0.0,
                ),
                spot_size_um=np.full(
                    stop - start,
                    float(params.input.default_spot_size_um),
                    dtype=np.float64,
                ),
                measured_reflectivity=used_fraction,
                laser_on=laser_on,
                source_columns={
                    "laser_x_mm": context.refs["x"].path,
                    "laser_y_mm": context.refs["y"].path,
                    "laser_on": context.refs["drive"].path,
                    "on_axis_ted_raw": context.refs["ted"].path,
                },
                input_mode="hdf5",
                input_path=str(context.path),
                h5_metadata=context.metadata,
                h5_laser_drive_threshold_used=float(context.laser_drive_threshold),
                h5_sample_frequency_hz=float(context.sample_frequency_hz),
                ted_global_off_baseline=float(context.ted_global_off_baseline),
                ted_baseline_status=str(context.ted_baseline_status),
                on_axis_ted_raw=ted_raw,
                ted_baseline_used=np.asarray(ted_fields["ted_baseline_used"], dtype=np.float64),
                ted_signal_corrected=np.asarray(ted_fields["ted_signal_corrected"], dtype=np.float64),
                ted_reference_100pct_reflection=np.asarray(ted_fields["ted_reference_100pct_reflection"], dtype=np.float64),
                ted_reflected_fraction_raw=np.asarray(ted_fields["ted_reflected_fraction_raw"], dtype=np.float64),
                ted_reflected_fraction_used=used_fraction,
                effective_absorptivity_raw=np.asarray(ted_fields["effective_absorptivity_raw"], dtype=np.float64),
                effective_absorptivity=np.asarray(ted_fields["effective_absorptivity"], dtype=np.float64),
                ted_reflection_clipped_low_flag=np.asarray(ted_fields["ted_reflection_clipped_low_flag"], dtype=bool),
                ted_reflection_clipped_high_flag=np.asarray(ted_fields["ted_reflection_clipped_high_flag"], dtype=bool),
                ted_reference_nonpositive_flag=np.asarray(ted_fields["ted_reference_nonpositive_flag"], dtype=bool),
                scan_track_id=scan_track_id,
                row_index=row_indices,
                laser_drive=drive,
                ted_nonfinite_flag=np.asarray(ted_fields["ted_nonfinite_flag"], dtype=bool),
                ted_calibration_valid_flag=np.asarray(ted_fields["ted_calibration_valid_flag"], dtype=bool),
                ted_invalid_powered_flag=np.asarray(ted_fields["ted_invalid_powered_flag"], dtype=bool),
            )
