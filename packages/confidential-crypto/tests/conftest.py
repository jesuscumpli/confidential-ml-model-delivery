"""Shared fixtures: every registered cipher and signer, including evaluation-only ones."""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from confidential_crypto import registry
from confidential_crypto.ciphers.base import AeadCipher
from confidential_crypto.signers.base import SignatureScheme

ALL_CIPHERS = list(registry.CIPHERS.values())
ALL_SIGNERS = list(registry.SIGNERS.values())


@pytest.fixture(params=ALL_CIPHERS, ids=lambda c: c.name)
def cipher(request: pytest.FixtureRequest) -> Iterator[AeadCipher]:
    selected: AeadCipher = request.param
    if not selected.is_available():
        pytest.skip(f"{selected.name} backend not available")
    yield selected


@pytest.fixture(params=ALL_SIGNERS, ids=lambda s: s.name)
def signer(request: pytest.FixtureRequest) -> Iterator[SignatureScheme]:
    selected: SignatureScheme = request.param
    if not selected.is_available():
        pytest.skip(f"{selected.name} backend not available")
    yield selected


@pytest.fixture
def key(cipher: AeadCipher) -> bytes:
    return os.urandom(cipher.key_size)


@pytest.fixture(scope="session")
def private_keys() -> dict[str, bytes]:
    """Generated once per session: RSA and ML-DSA key generation is slow."""
    return {s.name: s.generate_private_key() for s in ALL_SIGNERS if s.is_available()}


@pytest.fixture
def private_key(signer: SignatureScheme, private_keys: dict[str, bytes]) -> bytes:
    return private_keys[signer.name]


@pytest.fixture
def public_key(signer: SignatureScheme, private_key: bytes) -> bytes:
    return signer.public_key_from_private(private_key)


def flip_byte(data: bytes, index: int) -> bytes:
    mutated = bytearray(data)
    mutated[index] ^= 0x01
    return bytes(mutated)
