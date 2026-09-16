"""Shared fixtures: a fake package, its encrypted artifact, fake Hub source and key providers."""

from __future__ import annotations

import hashlib
import io
import json
import os
import tarfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from confidential_crypto import encrypt_stream, get_cipher

CIPHER = get_cipher("aes-256-gcm")
PACKAGE_FILES: dict[str, bytes] = {
    "config.json": b'{"hidden_size": 8}\n',
    "vocab.txt": b"[PAD]\n[UNK]\n[CLS]\n[SEP]\n[MASK]\nhello\n",
    "pytorch_model.bin": os.urandom(5000),
}


def build_package(files: dict[str, bytes], *, manifest: bytes | None = None) -> bytes:
    """Producer-compatible tar: manifest first, regular files, normalised metadata."""
    if manifest is None:
        entries = [
            {"path": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            for name, data in files.items()
        ]
        payload = {"format": 1, "model_id": "org/model", "revision": "abc", "files": entries}
        manifest = json.dumps(payload, sort_keys=True).encode()
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w", format=tarfile.GNU_FORMAT) as tar:
        for name, data in [("manifest.json", manifest), *files.items()]:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return out.getvalue()


def encrypt_bytes(plaintext: bytes, key: bytes) -> bytes:
    out = io.BytesIO()
    encrypt_stream(io.BytesIO(plaintext), out, key, CIPHER, chunk_size=4096)
    return out.getvalue()


class StaticKeyProvider:
    def __init__(self, key: bytes) -> None:
        self.key = key

    def get_key(self, key_size: int) -> bytes:
        return self.key


class FakeArtifactSource:
    """Serves in-memory bytes from a local directory, mimicking the Hub cache."""

    def __init__(self, files: dict[str, bytes], root: Path) -> None:
        self.files = files
        self.root = root
        self.calls: list[tuple[str, str, str, bool]] = []

    def fetch(self, repo_id: str, filename: str, revision: str, *, force: bool = False) -> Path:
        self.calls.append((repo_id, filename, revision, force))
        target = self.root / filename
        if force or not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(self.files[filename])
        return target


@pytest.fixture
def key() -> bytes:
    return os.urandom(CIPHER.key_size)


@pytest.fixture
def package() -> bytes:
    return build_package(PACKAGE_FILES)


@pytest.fixture
def artifact(package: bytes, key: bytes) -> bytes:
    return encrypt_bytes(package, key)


@pytest.fixture
def source(artifact: bytes, tmp_path: Path) -> FakeArtifactSource:
    return FakeArtifactSource({"model.enc": artifact}, tmp_path / "cache")


@pytest.fixture
def provider(key: bytes) -> StaticKeyProvider:
    return StaticKeyProvider(key)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name in list(os.environ):
        if name.startswith("CONSUMER_") or name in {"HF_TOKEN", "MODEL_KEY"}:
            monkeypatch.delenv(name)
    yield
