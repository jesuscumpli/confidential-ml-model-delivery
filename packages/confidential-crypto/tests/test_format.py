"""Binary format parsing: headers and envelopes must fail closed on any malformation."""

from __future__ import annotations

import pytest

from confidential_crypto.errors import FormatError
from confidential_crypto.format import (
    ARTIFACT_MAGIC,
    FINGERPRINT_SIZE,
    ArtifactHeader,
    SignatureEnvelope,
)


def test_header_round_trip() -> None:
    header = ArtifactHeader(cipher_id=0x01, nonce=b"\x01" * 12)
    encoded = header.encode()
    decoded, offset = ArtifactHeader.decode(encoded + b"ciphertext")
    assert decoded == header
    assert offset == len(encoded)


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"CML",
        b"XXXX\x01\x01\x0c" + b"\x00" * 12,
        b"CMLD\x02\x01\x0c" + b"\x00" * 12,
        b"CMLD\x01\x01\x00",
        b"CMLD\x01\x01\x0c" + b"\x00" * 11,
    ],
    ids=["empty", "short", "bad-magic", "bad-version", "zero-nonce", "truncated-nonce"],
)
def test_malformed_header_rejected(data: bytes) -> None:
    with pytest.raises(FormatError):
        ArtifactHeader.decode(data)


def test_header_encode_validates_fields() -> None:
    with pytest.raises(FormatError):
        ArtifactHeader(cipher_id=256, nonce=b"\x00" * 12).encode()
    with pytest.raises(FormatError):
        ArtifactHeader(cipher_id=1, nonce=b"").encode()


def test_header_starts_with_magic() -> None:
    assert ArtifactHeader(cipher_id=1, nonce=b"\x00" * 12).encode().startswith(ARTIFACT_MAGIC)


def test_envelope_round_trip() -> None:
    envelope = SignatureEnvelope(
        scheme_id=0x01, key_fingerprint=b"\xab" * FINGERPRINT_SIZE, signature=b"\x01" * 64
    )
    assert SignatureEnvelope.decode(envelope.encode()) == envelope


def test_envelope_rejects_trailing_or_missing_bytes() -> None:
    encoded = SignatureEnvelope(
        scheme_id=1, key_fingerprint=b"\x00" * FINGERPRINT_SIZE, signature=b"\x01" * 64
    ).encode()
    with pytest.raises(FormatError):
        SignatureEnvelope.decode(encoded + b"\x00")
    with pytest.raises(FormatError):
        SignatureEnvelope.decode(encoded[:-1])


@pytest.mark.parametrize(
    "data",
    [b"", b"CMLS", b"XXXX\x01\x01" + b"\x00" * 36 + b"\x00", b"CMLS\x09\x01" + b"\x00" * 36],
    ids=["empty", "short", "bad-magic", "bad-version"],
)
def test_malformed_envelope_rejected(data: bytes) -> None:
    with pytest.raises(FormatError):
        SignatureEnvelope.decode(data)
