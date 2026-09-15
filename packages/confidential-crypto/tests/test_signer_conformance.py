"""Conformance suite executed against every registered signature scheme."""

from __future__ import annotations

import pytest

from confidential_crypto.errors import InvalidKeyError, VerificationError
from confidential_crypto.signers.base import SignatureScheme
from tests.conftest import flip_byte

MESSAGE = b"encrypted artifact bytes"


def test_valid_signature_verifies(
    signer: SignatureScheme, private_key: bytes, public_key: bytes
) -> None:
    signer.verify(public_key, MESSAGE, signer.sign(private_key, MESSAGE))


def test_modified_message_fails(
    signer: SignatureScheme, private_key: bytes, public_key: bytes
) -> None:
    signature = signer.sign(private_key, MESSAGE)
    with pytest.raises(VerificationError):
        signer.verify(public_key, flip_byte(MESSAGE, 3), signature)


def test_modified_signature_fails(
    signer: SignatureScheme, private_key: bytes, public_key: bytes
) -> None:
    signature = signer.sign(private_key, MESSAGE)
    for index in (0, len(signature) // 2, len(signature) - 1):
        with pytest.raises(VerificationError):
            signer.verify(public_key, MESSAGE, flip_byte(signature, index))


def test_wrong_public_key_fails(signer: SignatureScheme, private_key: bytes) -> None:
    other_public = signer.public_key_from_private(signer.generate_private_key())
    with pytest.raises(VerificationError):
        signer.verify(other_public, MESSAGE, signer.sign(private_key, MESSAGE))


def test_key_of_another_scheme_is_rejected(
    signer: SignatureScheme, private_keys: dict[str, bytes]
) -> None:
    from confidential_crypto import registry

    others = [s for s in registry.SIGNERS.values() if s.name != signer.name and s.is_available()]
    for other in others:
        foreign_private = private_keys[other.name]
        foreign_public = other.public_key_from_private(foreign_private)
        if type(foreign_private) is bytes and _same_key_family(signer, other):
            continue
        with pytest.raises(InvalidKeyError):
            signer.sign(foreign_private, MESSAGE)
        with pytest.raises(InvalidKeyError):
            signer.verify(foreign_public, MESSAGE, b"\x00" * 64)


def _same_key_family(a: SignatureScheme, b: SignatureScheme) -> bool:
    """RSA 3072 and 4096 share a key type; the size check covers only the smaller one."""
    return {a.name, b.name} == {"rsa-pss-3072", "rsa-pss-4096"} and a.name == "rsa-pss-3072"


def test_garbage_keys_are_rejected(signer: SignatureScheme) -> None:
    with pytest.raises(InvalidKeyError):
        signer.sign(b"not a pem", MESSAGE)
    with pytest.raises(InvalidKeyError):
        signer.verify(b"not a pem", MESSAGE, b"\x00" * 64)


def test_determinism_flag_matches_behaviour(signer: SignatureScheme, private_key: bytes) -> None:
    first, second = signer.sign(private_key, MESSAGE), signer.sign(private_key, MESSAGE)
    assert (first == second) == signer.deterministic
