"""Conformance suite executed against every registered cipher (positive and negative)."""

from __future__ import annotations

import os

import pytest

from confidential_crypto.ciphers.base import AeadCipher, new_nonce
from confidential_crypto.errors import DecryptionError, InvalidKeyError, InvalidNonceError
from tests.conftest import flip_byte


@pytest.mark.parametrize("size", [0, 1, 15, 16, 17, 1024, 1 << 20])
def test_round_trip(cipher: AeadCipher, key: bytes, size: int) -> None:
    plaintext = os.urandom(size)
    nonce = new_nonce(cipher)
    ciphertext = cipher.encrypt(key, nonce, plaintext, b"aad")
    assert cipher.decrypt(key, nonce, ciphertext, b"aad") == plaintext


def test_ciphertext_overhead_is_tag_only_or_padding(cipher: AeadCipher, key: bytes) -> None:
    plaintext = b"x" * 100
    ciphertext = cipher.encrypt(key, new_nonce(cipher), plaintext, b"")
    # AEAD primitives add exactly the tag; CBC additionally pads to the block size.
    assert cipher.tag_size <= len(ciphertext) - len(plaintext) <= cipher.tag_size + 16


def test_wrong_key_fails(cipher: AeadCipher, key: bytes) -> None:
    nonce = new_nonce(cipher)
    ciphertext = cipher.encrypt(key, nonce, b"secret", b"")
    with pytest.raises(DecryptionError):
        cipher.decrypt(os.urandom(cipher.key_size), nonce, ciphertext, b"")


def test_modified_ciphertext_fails(cipher: AeadCipher, key: bytes) -> None:
    nonce = new_nonce(cipher)
    ciphertext = cipher.encrypt(key, nonce, b"secret payload", b"")
    for index in (0, len(ciphertext) // 2, len(ciphertext) - 1):
        with pytest.raises(DecryptionError):
            cipher.decrypt(key, nonce, flip_byte(ciphertext, index), b"")


def test_modified_aad_fails(cipher: AeadCipher, key: bytes) -> None:
    nonce = new_nonce(cipher)
    ciphertext = cipher.encrypt(key, nonce, b"secret", b"header")
    with pytest.raises(DecryptionError):
        cipher.decrypt(key, nonce, ciphertext, b"HEADER")


def test_modified_nonce_fails(cipher: AeadCipher, key: bytes) -> None:
    nonce = new_nonce(cipher)
    ciphertext = cipher.encrypt(key, nonce, b"secret", b"")
    with pytest.raises(DecryptionError):
        cipher.decrypt(key, flip_byte(nonce, 0), ciphertext, b"")


def test_truncated_ciphertext_fails(cipher: AeadCipher, key: bytes) -> None:
    nonce = new_nonce(cipher)
    ciphertext = cipher.encrypt(key, nonce, b"secret", b"")
    for cut in (1, cipher.tag_size, len(ciphertext) - 1):
        with pytest.raises(DecryptionError):
            cipher.decrypt(key, nonce, ciphertext[:cut], b"")


def test_wrong_key_length_rejected(cipher: AeadCipher) -> None:
    nonce = new_nonce(cipher)
    for bad in (b"", b"\x00" * (cipher.key_size - 1), b"\x00" * (cipher.key_size + 1)):
        with pytest.raises(InvalidKeyError):
            cipher.encrypt(bad, nonce, b"", b"")
        with pytest.raises(InvalidKeyError):
            cipher.decrypt(bad, nonce, b"\x00" * 64, b"")


def test_wrong_nonce_length_rejected(cipher: AeadCipher, key: bytes) -> None:
    for bad in (b"", b"\x00" * (cipher.nonce_size - 1), b"\x00" * (cipher.nonce_size + 1)):
        with pytest.raises(InvalidNonceError):
            cipher.encrypt(key, bad, b"", b"")


def test_fresh_nonces_are_unique_and_correct_length(cipher: AeadCipher) -> None:
    nonces = {new_nonce(cipher) for _ in range(1000)}
    assert len(nonces) == 1000
    assert all(len(n) == cipher.nonce_size for n in nonces)


def test_error_messages_leak_no_key_material(cipher: AeadCipher, key: bytes) -> None:
    nonce = new_nonce(cipher)
    ciphertext = cipher.encrypt(key, nonce, b"secret", b"")
    with pytest.raises(DecryptionError) as info:
        cipher.decrypt(key, nonce, flip_byte(ciphertext, 0), b"")
    message = str(info.value)
    assert key.hex() not in message
    assert nonce.hex() not in message
