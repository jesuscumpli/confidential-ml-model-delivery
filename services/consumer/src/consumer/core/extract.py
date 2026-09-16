"""Safe restoration of the model package: guarded tar extraction plus manifest check."""

from __future__ import annotations

import hashlib
import tarfile
from pathlib import Path, PurePosixPath

from pydantic import ValidationError

from consumer.core.errors import ExtractionError
from consumer.models.manifest import MANIFEST_FORMAT, MANIFEST_NAME, FileEntry, Manifest

_HASH_BLOCK = 1 << 20


def restore_package(tar_path: Path, dest: Path) -> Manifest:
    """Extract regular files only, then verify every file against `manifest.json`.

    Returns the parsed manifest. Absolute names, `..`, links, devices and any member
    not listed in the manifest are rejected before anything is written.
    """
    dest.mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(tar_path) as tar:
            members = tar.getmembers()
            for member in members:
                _check_member(member)
            manifest = _read_manifest(tar, members)
            by_path = {entry.path: entry for entry in manifest.files}
            for member in members[1:]:
                _extract_verified(tar, member, dest, by_path[member.name])
    except tarfile.TarError as exc:
        raise ExtractionError(f"package is not a valid tar archive: {exc}") from exc
    return manifest


def _check_member(member: tarfile.TarInfo) -> None:
    name = PurePosixPath(member.name)
    if name.is_absolute() or ".." in name.parts:
        raise ExtractionError(f"unsafe member path in package: {member.name}")
    if not member.isfile():
        raise ExtractionError(f"refusing non-regular member in package: {member.name}")


def _read_manifest(tar: tarfile.TarFile, members: list[tarfile.TarInfo]) -> Manifest:
    if not members or members[0].name != MANIFEST_NAME:
        raise ExtractionError(f"package must start with {MANIFEST_NAME}")
    stream = tar.extractfile(members[0])
    if stream is None:
        raise ExtractionError(f"{MANIFEST_NAME} is not readable")
    try:
        manifest = Manifest.model_validate_json(stream.read())
    except ValidationError as exc:
        raise ExtractionError(f"{MANIFEST_NAME} is malformed") from exc
    if manifest.format != MANIFEST_FORMAT:
        raise ExtractionError(f"unsupported manifest format {manifest.format!r}")
    if {m.name for m in members[1:]} != manifest.paths:
        raise ExtractionError("package members do not match the manifest file list")
    return manifest


def _extract_verified(
    tar: tarfile.TarFile, member: tarfile.TarInfo, dest: Path, entry: FileEntry
) -> None:
    """Stream `member` to `dest` while hashing it, so one pass both writes and verifies."""
    stream = tar.extractfile(member)
    if stream is None:
        raise ExtractionError(f"cannot read member in package: {member.name}")
    path = dest / member.name
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    size = 0
    with path.open("wb") as out:
        for block in iter(lambda: stream.read(_HASH_BLOCK), b""):
            size += len(block)
            digest.update(block)
            out.write(block)
    if size != entry.size or digest.hexdigest() != entry.sha256:
        raise ExtractionError(f"restored file does not match the manifest: {entry.path}")
