"""Layer 1 decryption: version dispatch, wrong key, tampering, malformed input."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from confidential_crypto import encrypt

from consumer.core.decrypt import artifact_key_size, decrypt_file
from consumer.core.errors import DecryptError
from tests.conftest import CIPHER, StaticKeyProvider, encrypt_bytes


def _flip(data: bytes, index: int) -> bytes:
    mutated = bytearray(data)
    mutated[index] ^= 0x01
    return bytes(mutated)


def test_chunked_round_trip(tmp_path: Path, key: bytes, package: bytes) -> None:
    src = tmp_path / "model.enc"
    src.write_bytes(encrypt_bytes(package, key))
    assert artifact_key_size(src) == CIPHER.key_size
    decrypt_file(src, tmp_path / "out" / "model.tar", StaticKeyProvider(key))
    assert (tmp_path / "out" / "model.tar").read_bytes() == package


def test_one_shot_round_trip(tmp_path: Path, key: bytes, package: bytes) -> None:
    src = tmp_path / "model.enc"
    src.write_bytes(encrypt(package, key, CIPHER))
    decrypt_file(src, tmp_path / "model.tar", StaticKeyProvider(key))
    assert (tmp_path / "model.tar").read_bytes() == package


def test_wrong_key_fails_and_leaves_no_plaintext(tmp_path: Path, artifact: bytes) -> None:
    src = tmp_path / "model.enc"
    src.write_bytes(artifact)
    with pytest.raises(DecryptError, match="decryption failed"):
        decrypt_file(src, tmp_path / "model.tar", StaticKeyProvider(os.urandom(32)))
    assert not (tmp_path / "model.tar").exists()
    assert not (tmp_path / "model.tar.tmp").exists()


@pytest.mark.parametrize("position", ["header", "body", "tail"])
def test_tampered_artifact_fails(
    tmp_path: Path, key: bytes, artifact: bytes, position: str
) -> None:
    index = {"header": 5, "body": len(artifact) // 2, "tail": len(artifact) - 1}[position]
    src = tmp_path / "model.enc"
    src.write_bytes(_flip(artifact, index))
    with pytest.raises(DecryptError):
        decrypt_file(src, tmp_path / "model.tar", StaticKeyProvider(key))
    assert not (tmp_path / "model.tar").exists()


def test_truncated_artifact_fails(tmp_path: Path, key: bytes, artifact: bytes) -> None:
    src = tmp_path / "model.enc"
    src.write_bytes(artifact[: len(artifact) - 100])
    with pytest.raises(DecryptError):
        decrypt_file(src, tmp_path / "model.tar", StaticKeyProvider(key))


def test_not_an_artifact(tmp_path: Path, key: bytes) -> None:
    src = tmp_path / "model.enc"
    src.write_bytes(b"definitely not encrypted")
    with pytest.raises(DecryptError, match="unreadable artifact header"):
        artifact_key_size(src)
