"""Chunked (format v2) artifacts: bounded-memory streaming with STREAM-style guarantees."""

from __future__ import annotations

import io
import os

import pytest

from confidential_crypto import artifact, registry
from confidential_crypto.ciphers.base import AeadCipher
from confidential_crypto.errors import CryptoError, DecryptionError, FormatError
from confidential_crypto.format import ARTIFACT_VERSION_CHUNKED, MIN_CHUNK_SIZE, ArtifactHeader
from tests.conftest import flip_byte

CHUNK = MIN_CHUNK_SIZE


def _encrypt(data: bytes, key: bytes, cipher: AeadCipher, chunk: int = CHUNK) -> bytes:
    out = io.BytesIO()
    artifact.encrypt_stream(io.BytesIO(data), out, key, cipher, chunk_size=chunk)
    return out.getvalue()


def _decrypt(blob: bytes, key: bytes, cipher: AeadCipher) -> bytes:
    out = io.BytesIO()
    artifact.decrypt_stream(io.BytesIO(blob), out, key, allow_unsafe=not cipher.production_safe)
    return out.getvalue()


@pytest.mark.parametrize(
    "size", [0, 1, CHUNK - 1, CHUNK, CHUNK + 1, 3 * CHUNK, 3 * CHUNK + 7], ids=str
)
def test_round_trip(cipher: AeadCipher, key: bytes, size: int) -> None:
    data = os.urandom(size)
    blob = _encrypt(data, key, cipher)
    assert _decrypt(blob, key, cipher) == data
    # the in-memory entry point dispatches on the version byte
    assert artifact.decrypt(blob, key, allow_unsafe=not cipher.production_safe) == data


def test_header_is_version_2_with_chunk_size(cipher: AeadCipher, key: bytes) -> None:
    header, _ = ArtifactHeader.decode(_encrypt(b"x", key, cipher))
    assert header.version == ARTIFACT_VERSION_CHUNKED
    assert header.chunk_size == CHUNK
    assert header.cipher_id == cipher.cipher_id
    assert len(header.nonce) == cipher.nonce_size - 5


def test_overhead_is_tag_per_chunk(key: bytes) -> None:
    cipher = registry.get_cipher("aes-256-gcm")
    data = os.urandom(3 * CHUNK)
    blob = _encrypt(data, key, cipher)
    header_len = ArtifactHeader.decode(blob)[1]
    assert len(blob) - header_len - len(data) == 3 * cipher.tag_size


def test_every_flipped_byte_is_detected(cipher: AeadCipher, key: bytes) -> None:
    data = os.urandom(2 * CHUNK + 5)
    blob = _encrypt(data, key, cipher)
    step = 61  # sample positions across header and all chunks; full scan is too slow
    for index in range(0, len(blob), step):
        with pytest.raises(CryptoError):
            _decrypt(flip_byte(blob, index), key, cipher)


def test_truncation_at_chunk_boundary_is_detected(cipher: AeadCipher, key: bytes) -> None:
    """Dropping the final chunk leaves a valid-looking stream ending on a non-last chunk."""
    blob = _encrypt(os.urandom(3 * CHUNK), key, cipher)
    header_len = ArtifactHeader.decode(blob)[1]
    full = cipher.ciphertext_size(CHUNK)
    truncated = blob[: header_len + 2 * full]
    with pytest.raises(DecryptionError):
        _decrypt(truncated, key, cipher)


def test_truncation_mid_chunk_is_detected(cipher: AeadCipher, key: bytes) -> None:
    blob = _encrypt(os.urandom(3 * CHUNK), key, cipher)
    with pytest.raises((DecryptionError, FormatError)):
        _decrypt(blob[:-10], key, cipher)


def test_reordered_chunks_are_detected(cipher: AeadCipher, key: bytes) -> None:
    blob = _encrypt(os.urandom(3 * CHUNK + 1), key, cipher)
    header_len = ArtifactHeader.decode(blob)[1]
    full = cipher.ciphertext_size(CHUNK)
    header, c0, c1, rest = (
        blob[:header_len],
        blob[header_len : header_len + full],
        blob[header_len + full : header_len + 2 * full],
        blob[header_len + 2 * full :],
    )
    with pytest.raises(DecryptionError):
        _decrypt(header + c1 + c0 + rest, key, cipher)


def test_chunk_from_another_artifact_is_detected(cipher: AeadCipher, key: bytes) -> None:
    """Same key, same position: a chunk spliced from a different artifact must fail."""
    a = _encrypt(os.urandom(2 * CHUNK + 1), key, cipher)
    b = _encrypt(os.urandom(2 * CHUNK + 1), key, cipher)
    header_len = ArtifactHeader.decode(a)[1]
    full = cipher.ciphertext_size(CHUNK)
    spliced = a[:header_len] + b[header_len : header_len + full] + a[header_len + full :]
    with pytest.raises(DecryptionError):
        _decrypt(spliced, key, cipher)


def test_chunk_size_swap_in_header_is_detected(key: bytes) -> None:
    cipher = registry.get_cipher("aes-256-gcm")
    blob = bytearray(_encrypt(os.urandom(2 * CHUNK), key, cipher))
    header_len = ArtifactHeader.decode(bytes(blob))[1]
    blob[header_len - 1] ^= 0x10  # low byte of chunk_size (big endian)
    with pytest.raises(CryptoError):
        _decrypt(bytes(blob), key, cipher)


def test_no_plaintext_written_before_authentication_fails(key: bytes) -> None:
    cipher = registry.get_cipher("aes-256-gcm")
    blob = _encrypt(os.urandom(2 * CHUNK), key, cipher)
    header_len = ArtifactHeader.decode(blob)[1]
    corrupted = flip_byte(blob, header_len + 3)  # inside chunk 0
    out = io.BytesIO()
    with pytest.raises(DecryptionError):
        artifact.decrypt_stream(io.BytesIO(corrupted), out, key)
    assert out.getvalue() == b""


def test_empty_stream_and_v1_input_are_rejected(key: bytes) -> None:
    cipher = registry.get_cipher("aes-256-gcm")
    with pytest.raises(FormatError):
        artifact.decrypt_stream(io.BytesIO(b""), io.BytesIO(), key)
    v1 = artifact.encrypt(b"x", key, cipher)
    with pytest.raises(FormatError):
        artifact.decrypt_stream(io.BytesIO(v1), io.BytesIO(), key)


def test_chunk_size_limits(key: bytes) -> None:
    cipher = registry.get_cipher("aes-256-gcm")
    with pytest.raises(FormatError):
        _encrypt(b"x", key, cipher, chunk=MIN_CHUNK_SIZE - 1)


def test_wrong_key_fails(cipher: AeadCipher, key: bytes) -> None:
    blob = _encrypt(os.urandom(CHUNK + 1), key, cipher)
    with pytest.raises(DecryptionError):
        _decrypt(blob, os.urandom(cipher.key_size), cipher)
