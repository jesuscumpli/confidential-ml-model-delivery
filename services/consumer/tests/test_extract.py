"""Safe extraction: path traversal, links, manifest consistency."""

from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path

import pytest

from consumer.core.errors import ExtractionError
from consumer.core.extract import restore_package
from tests.conftest import PACKAGE_FILES, build_package


def _tar_with(members: list[tarfile.TarInfo], payloads: dict[str, bytes]) -> bytes:
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w") as tar:
        for info in members:
            data = payloads.get(info.name, b"")
            info.size = len(data) if info.isfile() else 0
            tar.addfile(info, io.BytesIO(data) if info.isfile() else None)
    return out.getvalue()


def _manifest_of(blob: bytes) -> bytes:
    with tarfile.open(fileobj=io.BytesIO(blob)) as tar:
        stream = tar.extractfile("manifest.json")
        assert stream is not None
        return stream.read()


def _member(name: str, kind: bytes = tarfile.REGTYPE, link: str = "") -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.type = kind
    info.linkname = link
    return info


def test_restore_verifies_manifest(tmp_path: Path, package: bytes) -> None:
    (tmp_path / "model.tar").write_bytes(package)
    manifest = restore_package(tmp_path / "model.tar", tmp_path / "model")
    assert manifest.model_id == "org/model"
    for name, data in PACKAGE_FILES.items():
        assert (tmp_path / "model" / name).read_bytes() == data


@pytest.mark.parametrize(
    "bad",
    [
        _member("../escape.txt"),
        _member("/abs/config.json"),
        _member("link.txt", tarfile.SYMTYPE, "/etc/passwd"),
        _member("hard.txt", tarfile.LNKTYPE, "config.json"),
        _member("dir/", tarfile.DIRTYPE),
    ],
    ids=["traversal", "absolute", "symlink", "hardlink", "directory"],
)
def test_unsafe_members_are_rejected(tmp_path: Path, bad: tarfile.TarInfo) -> None:
    manifest = json.dumps({"format": 1, "model_id": "m", "revision": "r", "files": []}).encode()
    blob = _tar_with([_member("manifest.json"), bad], {"manifest.json": manifest})
    (tmp_path / "model.tar").write_bytes(blob)
    with pytest.raises(ExtractionError):
        restore_package(tmp_path / "model.tar", tmp_path / "model")
    assert not any((tmp_path / "model").iterdir())


def test_manifest_must_be_first(tmp_path: Path) -> None:
    blob = _tar_with([_member("config.json")], {"config.json": b"{}"})
    (tmp_path / "model.tar").write_bytes(blob)
    with pytest.raises(ExtractionError, match="must start with manifest.json"):
        restore_package(tmp_path / "model.tar", tmp_path / "model")


def test_unsupported_manifest_format(tmp_path: Path) -> None:
    manifest = json.dumps({"format": 999, "model_id": "m", "revision": "r", "files": []}).encode()
    blob = _tar_with([_member("manifest.json")], {"manifest.json": manifest})
    (tmp_path / "model.tar").write_bytes(blob)
    with pytest.raises(ExtractionError, match="unsupported manifest format"):
        restore_package(tmp_path / "model.tar", tmp_path / "model")


def test_manifest_missing_identity_fields(tmp_path: Path) -> None:
    manifest = json.dumps({"format": 1, "files": []}).encode()
    blob = _tar_with([_member("manifest.json")], {"manifest.json": manifest})
    (tmp_path / "model.tar").write_bytes(blob)
    with pytest.raises(ExtractionError, match="malformed"):
        restore_package(tmp_path / "model.tar", tmp_path / "model")


def test_extra_member_not_in_manifest(tmp_path: Path) -> None:
    files = dict(PACKAGE_FILES)
    manifest = json.loads(_manifest_of(build_package(files)))
    manifest["files"] = manifest["files"][:-1]  # last member is now unlisted
    tampered = build_package(files, manifest=json.dumps(manifest).encode())
    (tmp_path / "model.tar").write_bytes(tampered)
    with pytest.raises(ExtractionError, match="do not match the manifest"):
        restore_package(tmp_path / "model.tar", tmp_path / "model")


def test_hash_mismatch(tmp_path: Path, package: bytes) -> None:
    manifest_blob = _manifest_of(package)
    files = dict(PACKAGE_FILES)
    files["vocab.txt"] = b"changed"
    (tmp_path / "model.tar").write_bytes(build_package(files, manifest=manifest_blob))
    with pytest.raises(ExtractionError, match="does not match the manifest"):
        restore_package(tmp_path / "model.tar", tmp_path / "model")


def test_not_a_tar(tmp_path: Path) -> None:
    (tmp_path / "model.tar").write_bytes(b"garbage")
    with pytest.raises(ExtractionError, match="not a valid tar"):
        restore_package(tmp_path / "model.tar", tmp_path / "model")
