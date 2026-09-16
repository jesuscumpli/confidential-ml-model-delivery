"""End-to-end artifact operations: encrypt/decrypt and sign/verify through the registry."""

from __future__ import annotations

import hashlib
import io
import os

import pytest

from confidential_crypto import artifact, registry
from confidential_crypto.ciphers.base import AeadCipher
from confidential_crypto.errors import (
    DecryptionError,
    FormatError,
    UnknownAlgorithmError,
    UnsafeAlgorithmError,
    VerificationError,
)
from confidential_crypto.format import ArtifactHeader, SignatureEnvelope
from confidential_crypto.keys import public_key_fingerprint
from confidential_crypto.signers.base import SignatureScheme
from tests.conftest import flip_byte


def test_round_trip_through_registry(cipher: AeadCipher, key: bytes) -> None:
    plaintext = os.urandom(4096)
    blob = artifact.encrypt(plaintext, key, cipher)
    assert artifact.decrypt(blob, key, allow_unsafe=not cipher.production_safe) == plaintext


def test_header_declares_cipher_and_nonce(cipher: AeadCipher, key: bytes) -> None:
    blob = artifact.encrypt(b"x", key, cipher)
    header, _ = ArtifactHeader.decode(blob)
    assert header.cipher_id == cipher.cipher_id
    assert len(header.nonce) == cipher.nonce_size


def test_two_encryptions_differ(cipher: AeadCipher, key: bytes) -> None:
    assert artifact.encrypt(b"same", key, cipher) != artifact.encrypt(b"same", key, cipher)


def test_cipher_id_swap_fails_authentication(key: bytes) -> None:
    """Header is AAD: changing the declared cipher must not just pick another cipher."""
    aes, chacha = registry.get_cipher("aes-256-gcm"), registry.get_cipher("chacha20-poly1305")
    blob = artifact.encrypt(b"secret", key, aes)
    swapped = bytearray(blob)
    swapped[5] = chacha.cipher_id
    with pytest.raises(DecryptionError):
        artifact.decrypt(bytes(swapped), key)


def test_unknown_cipher_id_rejected(key: bytes) -> None:
    blob = bytearray(artifact.encrypt(b"secret", key, registry.get_cipher("aes-256-gcm")))
    blob[5] = 0xEE
    with pytest.raises(UnknownAlgorithmError):
        artifact.decrypt(bytes(blob), key)


def test_unsafe_cipher_refused_on_decrypt_by_default() -> None:
    cbc = registry.get_cipher("aes-256-cbc-hmac-sha256", allow_unsafe=True)
    key = os.urandom(cbc.key_size)
    blob = artifact.encrypt(b"secret", key, cbc)
    with pytest.raises(UnsafeAlgorithmError):
        artifact.decrypt(blob, key)


def test_tampered_artifact_fails(cipher: AeadCipher, key: bytes) -> None:
    blob = artifact.encrypt(b"secret payload", key, cipher)
    unsafe = not cipher.production_safe
    for index in range(len(blob)):
        with pytest.raises((DecryptionError, FormatError, UnknownAlgorithmError)):
            artifact.decrypt(flip_byte(blob, index), key, allow_unsafe=unsafe)


def test_sign_and_verify(signer: SignatureScheme, private_key: bytes, public_key: bytes) -> None:
    blob = os.urandom(256)
    envelope = artifact.sign(blob, private_key, signer)
    artifact.verify(blob, envelope, public_key, signer)


def test_verify_rejects_modified_artifact(
    signer: SignatureScheme, private_key: bytes, public_key: bytes
) -> None:
    blob = os.urandom(256)
    envelope = artifact.sign(blob, private_key, signer)
    with pytest.raises(VerificationError):
        artifact.verify(flip_byte(blob, 100), envelope, public_key, signer)


def test_verify_rejects_modified_signature(
    signer: SignatureScheme, private_key: bytes, public_key: bytes
) -> None:
    blob = os.urandom(256)
    envelope = artifact.sign(blob, private_key, signer)
    with pytest.raises(VerificationError):
        artifact.verify(blob, flip_byte(envelope, len(envelope) - 1), public_key, signer)


def test_verify_rejects_wrong_public_key(signer: SignatureScheme, private_key: bytes) -> None:
    blob = os.urandom(256)
    envelope = artifact.sign(blob, private_key, signer)
    other_public = signer.public_key_from_private(signer.generate_private_key())
    with pytest.raises(VerificationError, match="expected public key"):
        artifact.verify(blob, envelope, other_public, signer)


def test_verify_rejects_scheme_mismatch(private_keys: dict[str, bytes]) -> None:
    ed, ec = registry.get_signer("ed25519"), registry.get_signer("ecdsa-p256")
    blob = os.urandom(256)
    envelope = artifact.sign(blob, private_keys[ed.name], ed)
    ec_public = ec.public_key_from_private(private_keys[ec.name])
    with pytest.raises(VerificationError, match="scheme"):
        artifact.verify(blob, envelope, ec_public, ec)


def test_verify_rejects_malformed_envelope(signer: SignatureScheme, public_key: bytes) -> None:
    with pytest.raises(FormatError):
        artifact.verify(b"blob", b"garbage", public_key, signer)


def test_sign_stream_matches_in_memory_sign(private_keys: dict[str, bytes]) -> None:
    """Both entry points sign the same message, so envelopes are interchangeable."""
    ed = registry.get_signer("ed25519")
    blob = os.urandom(3 * (1 << 20) + 7)  # spans several digest reads
    envelope = artifact.sign_stream(io.BytesIO(blob), private_keys[ed.name], ed)
    assert envelope == artifact.sign(blob, private_keys[ed.name], ed)
    public = ed.public_key_from_private(private_keys[ed.name])
    artifact.verify_stream(io.BytesIO(blob), envelope, public, ed)
    with pytest.raises(VerificationError):
        artifact.verify_stream(io.BytesIO(flip_byte(blob, len(blob) - 1)), envelope, public, ed)


def test_signature_does_not_cover_raw_digest(private_keys: dict[str, bytes]) -> None:
    """A signature over the bare SHA-256 must not verify: the domain prefix is required."""
    ed = registry.get_signer("ed25519")
    blob = os.urandom(64)
    private = private_keys[ed.name]
    public = ed.public_key_from_private(private)
    bare = ed.sign(private, hashlib.sha256(blob).digest())
    envelope = SignatureEnvelope(
        scheme_id=ed.scheme_id,
        key_fingerprint=public_key_fingerprint(public),
        signature=bare,
    ).encode()
    with pytest.raises(VerificationError):
        artifact.verify(blob, envelope, public, ed)
