"""File-to-file encryption: mode selection, round trip through the crypto package."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from confidential_crypto import decrypt, get_cipher
from confidential_crypto.errors import DecryptionError
from confidential_crypto.format import (
    ARTIFACT_VERSION_CHUNKED,
    MIN_CHUNK_SIZE,
    ArtifactHeader,
)

from producer.encrypt import EncryptionMode, encrypt_file
from producer.errors import EncryptionError

CIPHER = get_cipher("aes-256-gcm")


@pytest.fixture
def plaintext(tmp_path: Path) -> Path:
    src = tmp_path / "model.tar"
    src.write_bytes(os.urandom(2 * MIN_CHUNK_SIZE + 3))
    return src


@pytest.mark.parametrize(
    ("mode", "version"),
    [(EncryptionMode.CHUNKED, ARTIFACT_VERSION_CHUNKED), (EncryptionMode.ONE_SHOT, 1)],
)
def test_round_trip_and_version(
    plaintext: Path, tmp_path: Path, mode: EncryptionMode, version: int
) -> None:
    key = os.urandom(CIPHER.key_size)
    dst = tmp_path / "upload" / "model.enc"
    encrypt_file(plaintext, dst, key, CIPHER, mode=mode, chunk_size=MIN_CHUNK_SIZE)
    blob = dst.read_bytes()
    assert ArtifactHeader.decode(blob)[0].version == version
    assert decrypt(blob, key) == plaintext.read_bytes()
    assert dst.parent.stat().st_mode & 0o777 == 0o700


def test_default_mode_is_chunked(plaintext: Path, tmp_path: Path) -> None:
    dst = tmp_path / "model.enc"
    encrypt_file(plaintext, dst, os.urandom(CIPHER.key_size), CIPHER)
    assert ArtifactHeader.decode(dst.read_bytes())[0].version == ARTIFACT_VERSION_CHUNKED


def test_wrong_key_fails_to_decrypt(plaintext: Path, tmp_path: Path) -> None:
    dst = tmp_path / "model.enc"
    encrypt_file(plaintext, dst, os.urandom(CIPHER.key_size), CIPHER)
    with pytest.raises(DecryptionError):
        decrypt(dst.read_bytes(), os.urandom(CIPHER.key_size))


def test_bad_key_length_is_reported_without_key_bytes(plaintext: Path, tmp_path: Path) -> None:
    short_key = os.urandom(16)
    with pytest.raises(EncryptionError) as info:
        encrypt_file(plaintext, tmp_path / "model.enc", short_key, CIPHER)
    assert short_key.hex() not in str(info.value)
    assert not (tmp_path / "model.enc.tmp").exists()
