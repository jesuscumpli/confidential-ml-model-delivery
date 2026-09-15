"""Deterministic model packaging: allow-listed files into a reproducible tar.

Reproducibility rules: entries sorted by path, `manifest.json` first, mtime 0,
uid/gid 0, empty owner names, fixed mode, relative POSIX names only.
"""

from __future__ import annotations

import fnmatch
import io
import os
import tarfile
from pathlib import Path, PurePosixPath

from producer.errors import PackagingError
from producer.manifest import MANIFEST_NAME, FileEntry, Manifest, sha256_file

MODEL_FILE_PATTERNS: tuple[str, ...] = (
    "config.json",
    "generation_config.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.txt",
    "merges.txt",
    "special_tokens_map.json",
    "*.safetensors",
    "pytorch_model.bin",
)
_LEGACY_WEIGHTS = "pytorch_model.bin"
_SAFETENSORS_SUFFIX = ".safetensors"
# huggingface_hub keeps download metadata under local_dir/.cache; it is not model data
_EXCLUDED_DIRS = frozenset({".cache"})
_FILE_MODE = 0o644


def collect_files(model_dir: Path) -> list[PurePosixPath]:
    """Return the relative paths to package, sorted, after applying the allow-list."""
    if not model_dir.is_dir():
        raise PackagingError(f"model directory does not exist: {model_dir}")
    selected: list[PurePosixPath] = []
    for root, dirs, names in os.walk(model_dir):
        dirs[:] = sorted(d for d in dirs if d not in _EXCLUDED_DIRS)
        for name in names:
            full = Path(root) / name
            relative = PurePosixPath(full.relative_to(model_dir).as_posix())
            if not _allowed(relative):
                continue
            if full.is_symlink() or not full.is_file():
                raise PackagingError(f"refusing non-regular file in model directory: {relative}")
            selected.append(relative)
    return sorted(_prefer_safetensors(selected))


def build_manifest(
    model_dir: Path, files: list[PurePosixPath], model_id: str, revision: str
) -> Manifest:
    entries = tuple(
        FileEntry(
            path=str(relative),
            size=(model_dir / relative).stat().st_size,
            sha256=sha256_file(model_dir / relative),
        )
        for relative in files
    )
    return Manifest(model_id=model_id, revision=revision, files=entries)


def write_package(model_dir: Path, manifest: Manifest, out_path: Path) -> None:
    """Write the tar atomically: a partial file never sits at `out_path`."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_name(out_path.name + ".tmp")
    try:
        with tarfile.open(tmp_path, mode="w", format=tarfile.GNU_FORMAT) as tar:
            _add_bytes(tar, MANIFEST_NAME, manifest.to_json())
            for entry in manifest.files:
                _add_file(tar, model_dir / entry.path, entry)
        os.replace(tmp_path, out_path)
    finally:
        tmp_path.unlink(missing_ok=True)


def package_model(model_dir: Path, model_id: str, revision: str, out_path: Path) -> Manifest:
    files = collect_files(model_dir)
    if not files:
        raise PackagingError(f"no packageable model files found under {model_dir}")
    manifest = build_manifest(model_dir, files, model_id, revision)
    write_package(model_dir, manifest, out_path)
    return manifest


def _allowed(relative: PurePosixPath) -> bool:
    if relative.is_absolute() or ".." in relative.parts:
        raise PackagingError(f"refusing unsafe path in model directory: {relative}")
    return any(fnmatch.fnmatchcase(relative.name, pattern) for pattern in MODEL_FILE_PATTERNS)


def _prefer_safetensors(files: list[PurePosixPath]) -> list[PurePosixPath]:
    """Drop the legacy pickle weights when the same model ships safetensors."""
    if any(f.suffix == _SAFETENSORS_SUFFIX for f in files):
        return [f for f in files if f.name != _LEGACY_WEIGHTS]
    return files


def _tar_info(name: str, size: int) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.size = size
    info.mtime = 0
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    info.mode = _FILE_MODE
    info.type = tarfile.REGTYPE
    return info


def _add_bytes(tar: tarfile.TarFile, name: str, data: bytes) -> None:
    tar.addfile(_tar_info(name, len(data)), io.BytesIO(data))


def _add_file(tar: tarfile.TarFile, path: Path, entry: FileEntry) -> None:
    with path.open("rb") as stream:
        tar.addfile(_tar_info(entry.path, entry.size), stream)
