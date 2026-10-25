"""Patch 9.9.3 reproducibility metadata for LPBF simulation outputs.

The record intentionally duplicates a compact set of scientifically critical
configuration/provenance fields that otherwise live in several parameter,
input, comparison, and HDF5 metadata locations.  It changes no numerical
physics and is written alongside the existing metadata rather than replacing it.
"""

from __future__ import annotations

from dataclasses import asdict
import hashlib
from importlib import metadata as importlib_metadata
import json
from pathlib import Path

from lpbf.paths import repository_root
import platform
from typing import TYPE_CHECKING, Any, Mapping

import h5py
import numpy as np

from lpbf.provenance.historical import load_historical_reproducibility_records
if TYPE_CHECKING:
    from lpbf.model.parameters import SimulationParameters


PATCH_VERSION = "10.1.4"
REPRODUCIBILITY_SCHEMA = "lpbf_reproducibility_metadata"
REPRODUCIBILITY_SCHEMA_VERSION = "9.9.3"
TED_CALIBRATION_VERSION = "9.6.6"
HW_PHYSICAL_CONVENTION = "H=major side; W=minor side; H>=W for nonzero footprints"
TED_REFERENCE_METHOD = (
    "TED_316L_reference(P) = "
    "ted_reference_slope * incident_power_W + ted_reference_intercept"
)
TED_CLIPPING_POLICY = (
    "clip TED reflected fraction to [0, 1]; absorptivity = 1 - clipped_fraction"
)

# Files/directories created by execution are deliberately excluded so the
# provenance hash identifies the code/configuration snapshot, not generated data.
_HASH_EXCLUDED_TOP_LEVEL = {
    ".git",
    ".pytest_cache",
    "__pycache__",
    "output",
    "reports",
    "validated_baselines",
}
_HASH_SUFFIXES = {".py", ".txt", ".ini", ".md", ".json"}
_DEPENDENCY_DISTRIBUTIONS = (
    "numpy",
    "h5py",
    "numba",
    "opencv-python",
    "matplotlib",
    "pytest",
)


def source_archive_content_sha256(root: Path | None = None) -> str:
    """Return a deterministic SHA-256 over the source/config archive contents.

    This is an archive-content identity rather than a byte-for-byte ZIP hash;
    container timestamps and generated outputs therefore do not alter it.
    """
    root = repository_root() if root is None else Path(root).resolve()
    paths: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if relative.parts and relative.parts[0] in _HASH_EXCLUDED_TOP_LEVEL:
            continue
        if path.suffix.lower() not in _HASH_SUFFIXES:
            continue
        paths.append(path)

    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        payload = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def dependency_versions() -> dict[str, str]:
    """Return the direct dependency versions used by the reproduction stack."""
    versions: dict[str, str] = {}
    for distribution in _DEPENDENCY_DISTRIBUTIONS:
        try:
            versions[distribution] = importlib_metadata.version(distribution)
        except importlib_metadata.PackageNotFoundError:
            versions[distribution] = "not_installed"
    return versions


def build_reproducibility_metadata(
    params: "SimulationParameters",
    *,
    comparison_metadata: Mapping[str, Any] | None = None,
    comparison_frame_count: int | None = None,
    source_hash: str | None = None,
) -> dict[str, Any]:
    """Build the complete Patch 9.9.3 reproducibility record."""
    comparison_metadata = {} if comparison_metadata is None else dict(comparison_metadata)
    historical = load_historical_reproducibility_records()
    spacing_m = float(params.grid.uniform_spacing_m(params.geometry))
    if comparison_frame_count is None:
        candidate_count = comparison_metadata.get(
            "camera_observation_frames_sampled",
            comparison_metadata.get("camera_observation_frames_total"),
        )
        comparison_frame_count = (
            None if candidate_count is None else int(candidate_count)
        )

    return {
        "schema": REPRODUCIBILITY_SCHEMA,
        "schema_version": REPRODUCIBILITY_SCHEMA_VERSION,
        "patch_version": PATCH_VERSION,
        "code_identity": {
            "method": "deterministic_source_archive_content_sha256",
            "sha256": source_archive_content_sha256() if source_hash is None else str(source_hash),
        },
        "runtime": {
            "python_version": platform.python_version(),
            "python_implementation": platform.python_implementation(),
            "dependencies": dependency_versions(),
        },
        "grid": {
            "Nx": int(params.grid.Nx),
            "Ny": int(params.grid.Ny),
            "Nz": int(params.grid.Nz),
            "dx_m": spacing_m,
            "dy_m": spacing_m,
            "dz_m": spacing_m,
            "dx_um": spacing_m * 1.0e6,
            "dy_um": spacing_m * 1.0e6,
            "dz_um": spacing_m * 1.0e6,
        },
        "time_step_s": float(params.time.dt_s),
        "hw_definition": {
            "physical_convention": HW_PHYSICAL_CONVENTION,
            "geometry_method": str(params.comparison.hw_geometry_method),
        },
        "synchronization": {
            "mapping_dataset": str(
                comparison_metadata.get("synchronization_mapping_dataset", "not_applicable")
            ),
            "method": str(
                comparison_metadata.get("synchronization_method", "not_applicable")
            ),
            "version": str(
                comparison_metadata.get("synchronization_version", "not_applicable")
            ),
        },
        "ted_calibration": {
            "version": TED_CALIBRATION_VERSION,
            "baseline_method": str(params.input.ted_baseline_policy),
            "reference_method": TED_REFERENCE_METHOD,
            "empirical_reference_target": "polished 316L plate",
            "empirical_reference_relation": "measured TED response versus incident laser power",
            "reference_plate_reflectivity_measured": False,
            "hypothetical_100_percent_return_reference_verified": False,
            "reference_slope": float(params.input.ted_reference_slope),
            "reference_intercept": float(params.input.ted_reference_intercept),
            "clipping_policy": TED_CLIPPING_POLICY,
        },
        "source_calibration_parameters": asdict(params.heat_source),
        "material_parameters": asdict(params.material),
        "thermal_history_reset_policy": asdict(params.moving_window),
        "comparison_frame_count": comparison_frame_count,
        "validated_configuration_reference": historical["validated_configuration_reference"],
        "current_validation_state": historical["current_validation_state"],
        "release_gate_assessment": historical["release_gate_assessment"],
        "patch_11_0_0_authoritative_starting_state": historical["patch_11_0_0_authoritative_starting_state"],
        "patch_11_0_1_ted_problem_statement": historical["patch_11_0_1_ted_problem_statement"],
        "patch_11_0_2_source_calibration_hard_stop": historical["patch_11_0_2_source_calibration_hard_stop"],
        "patch_12_0_0_authoritative_starting_state": historical["patch_12_0_0_authoritative_starting_state"],
        "patch_12_0_1_provisional_ted_decision": historical["patch_12_0_1_provisional_ted_decision"],
        "patch_12_0_2_provisional_ted_gate": historical["patch_12_0_2_provisional_ted_gate"],
    }


def write_reproducibility_metadata(
    h5_file: h5py.File,
    metadata: Mapping[str, Any],
) -> h5py.Group:
    """Write/replace the versioned reproducibility group in an open HDF5 file."""
    if "reproducibility" in h5_file:
        del h5_file["reproducibility"]
    group = h5_file.create_group("reproducibility")
    group.attrs["schema"] = str(metadata["schema"])
    group.attrs["schema_version"] = str(metadata["schema_version"])
    group.attrs["patch_version"] = str(metadata["patch_version"])
    group.attrs["code_identity_method"] = str(metadata["code_identity"]["method"])
    group.attrs["code_identity_sha256"] = str(metadata["code_identity"]["sha256"])
    frame_count = metadata.get("comparison_frame_count")
    group.attrs["comparison_frame_count"] = -1 if frame_count is None else int(frame_count)
    group.attrs["comparison_frame_count_convention"] = (
        "-1 means not applicable/unavailable for this output"
    )
    group.create_dataset(
        "metadata_json",
        data=np.bytes_(json.dumps(dict(metadata), sort_keys=True, separators=(",", ":"))),
    )
    return group


def read_reproducibility_metadata(h5_file: h5py.File) -> dict[str, Any]:
    """Read and decode a Patch 9.9.3 reproducibility record."""
    payload = h5_file["reproducibility/metadata_json"][()]
    if isinstance(payload, bytes):
        text = payload.decode("utf-8")
    else:
        text = bytes(payload).decode("utf-8")
    return json.loads(text)
