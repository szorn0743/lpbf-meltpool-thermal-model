"""Deterministic artifact-manifest and archive mechanics.

Patch 19.7.4 moves generic packaging behavior out of experiment orchestration so
solver/objective code never needs to import archive/reporting responsibilities.
The retained Patch 17.8 functions are preserved byte-for-byte in behavior and
re-exported from ``lpbf.experiments.framework`` for compatibility.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence
import zipfile

from lpbf.infrastructure import sha256_file


@dataclass(frozen=True)
class ArtifactBundleSpec:
    """Explicit file-level packaging policy for one result bundle."""

    zip_filename: str
    generated_names: tuple[str, ...]
    authority_paths: tuple[Path, ...] = ()
    manifest_filename: str | None = None
    compresslevel: int | None = None


def existing_named_paths(output: Path, names: Sequence[str]) -> tuple[Path, ...]:
    return tuple(output / name for name in names if (output / name).is_file())


def write_sha256_manifest(
    output: Path,
    names: Sequence[str],
    *,
    manifest_filename: str,
) -> Path:
    members = sorted(existing_named_paths(output, names), key=lambda path: path.name)
    lines = [f"{sha256_file(path)}  {path.name}" for path in members]
    destination = output / manifest_filename
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return destination


def artifact_tree_paths(
    root: Path,
    *,
    exclude_names: Iterable[str] = (),
) -> tuple[Path, ...]:
    excluded = frozenset(exclude_names)
    return tuple(
        path
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name not in excluded
    )


def artifact_tree_records(
    root: Path,
    *,
    exclude_names: Iterable[str] = (),
) -> list[dict[str, Any]]:
    return [
        {
            "path": path.relative_to(root).as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in artifact_tree_paths(root, exclude_names=exclude_names)
    ]


def write_zip_members(
    destination: Path,
    members: Sequence[tuple[Path, str]],
    *,
    mode: str = "w",
    compresslevel: int | None = None,
) -> Path:
    kwargs: dict[str, Any] = {
        "mode": mode,
        "compression": zipfile.ZIP_DEFLATED,
    }
    if compresslevel is not None:
        kwargs["compresslevel"] = compresslevel
    with zipfile.ZipFile(destination, **kwargs) as archive:
        for source, arcname in members:
            archive.write(source, arcname=arcname)
    return destination


def zip_artifact_tree(
    source_directory: Path,
    destination: Path,
    *,
    archive_root_name: str | None = None,
    mode: str = "x",
    compresslevel: int | None = None,
) -> Path:
    members: list[tuple[Path, str]] = []
    for path in artifact_tree_paths(source_directory):
        relative = path.relative_to(source_directory)
        arcname = (
            str(relative)
            if archive_root_name is None
            else str(Path(archive_root_name) / relative)
        )
        members.append((path, arcname))
    return write_zip_members(
        destination,
        members,
        mode=mode,
        compresslevel=compresslevel,
    )


def package_artifacts(
    output: Path,
    spec: ArtifactBundleSpec,
    *,
    generated_names: Sequence[str] | None = None,
) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    generated = list(spec.generated_names if generated_names is None else generated_names)
    if spec.manifest_filename is not None:
        write_sha256_manifest(
            output,
            generated,
            manifest_filename=spec.manifest_filename,
        )
        generated.append(spec.manifest_filename)

    destination = output / spec.zip_filename
    members = [
        (path, path.name)
        for path in existing_named_paths(output, generated)
    ]
    members.extend(
        (path, path.name)
        for path in spec.authority_paths
        if path.is_file()
    )
    return write_zip_members(
        destination,
        members,
        mode="w",
        compresslevel=spec.compresslevel,
    )


__all__ = [
    "ArtifactBundleSpec",
    "artifact_tree_paths",
    "artifact_tree_records",
    "existing_named_paths",
    "package_artifacts",
    "write_sha256_manifest",
    "write_zip_members",
    "zip_artifact_tree",
]
