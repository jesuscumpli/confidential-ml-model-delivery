"""Registry behaviour: lookups, ids, safety flags and defaults."""

from __future__ import annotations

import pytest

from confidential_crypto import registry
from confidential_crypto.errors import UnknownAlgorithmError, UnsafeAlgorithmError


def test_defaults_are_production_safe_and_available() -> None:
    assert registry.get_cipher(registry.DEFAULT_CIPHER).production_safe
    assert registry.get_signer(registry.DEFAULT_SIGNER).production_safe


def test_ids_are_unique() -> None:
    cipher_ids = [c.cipher_id for c in registry.CIPHERS.values()]
    scheme_ids = [s.scheme_id for s in registry.SIGNERS.values()]
    assert len(cipher_ids) == len(set(cipher_ids))
    assert len(scheme_ids) == len(set(scheme_ids))


def test_lookup_by_id_matches_lookup_by_name() -> None:
    for cipher in registry.available_ciphers(include_unsafe=True):
        assert registry.cipher_from_id(cipher.cipher_id, allow_unsafe=True) is cipher
    for signer in registry.available_signers(include_unsafe=True):
        assert registry.signer_from_id(signer.scheme_id, allow_unsafe=True) is signer


def test_unknown_names_and_ids() -> None:
    with pytest.raises(UnknownAlgorithmError):
        registry.get_cipher("rot13")
    with pytest.raises(UnknownAlgorithmError):
        registry.cipher_from_id(0xEE)
    with pytest.raises(UnknownAlgorithmError):
        registry.get_signer("hmac")
    with pytest.raises(UnknownAlgorithmError):
        registry.signer_from_id(0xEE)


def test_unsafe_algorithms_require_explicit_opt_in() -> None:
    with pytest.raises(UnsafeAlgorithmError):
        registry.get_cipher("aes-256-cbc-hmac-sha256")
    cbc = registry.get_cipher("aes-256-cbc-hmac-sha256", allow_unsafe=True)
    assert cbc.production_safe is False
    assert all(c.production_safe for c in registry.available_ciphers())
