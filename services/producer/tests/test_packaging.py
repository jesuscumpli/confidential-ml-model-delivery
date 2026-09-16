"""Deterministic packaging: allow-list, manifest, tar metadata and reproducibility."""

from __future__ import annotations

import hashlib
import os
import tarfile
import time
from pathlib import Path, PurePosixPath

import pytest

from producer.core.errors import PackagingError
from producer.core.packaging import collect_files, package_model, sha256_file
from producer.models.manifest import MANIFEST_NAME, Manifest
from tests.conftest import MODEL_FILES, write_model_dir


def _package(model_dir: Path, out: Path) -> Manifest:
    return package_model(model_dir, "org/model", "deadbeef", out)


def test_collect_files_applies_allow_list_and_prefers_safetensors(tiny_model_dir: Path) -> None:
    assert collect_files(tiny_model_dir) == sorted(PurePosixPath(n) for n in MODEL_FILES)


def test_collect_files_keeps_legacy_weights_without_safetensors(tmp_path: Path) -> None:
    files = {k: v for k, v in MODEL_FILES.items() if k != "model.safetensors"}
    files["pytorch_model.bin"] = b"weights"
    model_dir = write_model_dir(tmp_path / "m", files)
    assert PurePosixPath("pytorch_model.bin") in collect_files(model_dir)


def test_collect_files_rejects_symlink(tiny_model_dir: Path) -> None:
    (tiny_model_dir / "config.json").unlink()
    (tiny_model_dir / "config.json").symlink_to(tiny_model_dir / "vocab.txt")
    with pytest.raises(PackagingError, match="non-regular"):
        collect_files(tiny_model_dir)


def test_collect_files_missing_dir(tmp_path: Path) -> None:
    with pytest.raises(PackagingError, match="does not exist"):
        collect_files(tmp_path / "nope")


def test_package_requires_model_files(tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()
    with pytest.raises(PackagingError, match="no packageable"):
        _package(tmp_path / "empty", tmp_path / "out.tar")


def test_manifest_is_first_entry_and_matches_files(tiny_model_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "model.tar"
    manifest = _package(tiny_model_dir, out)
    with tarfile.open(out) as tar:
        names = tar.getnames()
        stream = tar.extractfile(MANIFEST_NAME)
        assert stream is not None
        parsed = Manifest.from_json(stream.read())
    assert names[0] == MANIFEST_NAME
    assert names[1:] == [entry.path for entry in manifest.files]
    assert parsed == manifest
    assert parsed.model_id == "org/model" and parsed.revision == "deadbeef"
    for entry in manifest.files:
        assert entry.sha256 == hashlib.sha256(MODEL_FILES[entry.path]).hexdigest()
        assert entry.size == len(MODEL_FILES[entry.path])


def test_tar_entries_are_normalised(tiny_model_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "model.tar"
    _package(tiny_model_dir, out)
    with tarfile.open(out) as tar:
        for info in tar.getmembers():
            assert info.isfile()
            assert (info.mtime, info.uid, info.gid, info.uname, info.gname) == (0, 0, 0, "", "")
            assert info.mode == 0o644
            assert not info.name.startswith("/") and ".." not in info.name.split("/")


def test_package_is_reproducible(tmp_path: Path) -> None:
    first = write_model_dir(tmp_path / "a", MODEL_FILES)
    second = write_model_dir(tmp_path / "b", dict(reversed(list(MODEL_FILES.items()))))
    old = time.time() - 86400
    for path in second.iterdir():
        os.utime(path, (old, old))
    _package(first, tmp_path / "a.tar")
    _package(second, tmp_path / "b.tar")
    assert sha256_file(tmp_path / "a.tar") == sha256_file(tmp_path / "b.tar")


def test_content_change_changes_package_hash(tiny_model_dir: Path, tmp_path: Path) -> None:
    _package(tiny_model_dir, tmp_path / "a.tar")
    (tiny_model_dir / "vocab.txt").write_bytes(b"changed\n")
    _package(tiny_model_dir, tmp_path / "b.tar")
    assert sha256_file(tmp_path / "a.tar") != sha256_file(tmp_path / "b.tar")


def test_extracted_package_matches_source(tiny_model_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "model.tar"
    _package(tiny_model_dir, out)
    restored = tmp_path / "restored"
    with tarfile.open(out) as tar:
        tar.extractall(restored, filter="data")
    for name, data in MODEL_FILES.items():
        assert (restored / name).read_bytes() == data
    assert not (restored / "pytorch_model.bin").exists()
    assert not (restored / ".cache").exists()


def test_no_temp_file_left_behind(tiny_model_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "out" / "model.tar"
    _package(tiny_model_dir, out)
    assert sorted(p.name for p in out.parent.iterdir()) == ["model.tar"]
