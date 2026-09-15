"""AEAD ciphers backed by the `cryptography` package (OpenSSL)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from cryptography.exceptions import InvalidTag, UnsupportedAlgorithm
from cryptography.hazmat.primitives.ciphers.aead import AESGCM, AESGCMSIV, ChaCha20Poly1305

from confidential_crypto.ciphers.base import check_key, check_nonce
from confidential_crypto.errors import DecryptionError


class _OpenSslAead(Protocol):
    def encrypt(self, nonce: bytes, data: bytes, associated_data: bytes | None) -> bytes: ...
    def decrypt(self, nonce: bytes, data: bytes, associated_data: bytes | None) -> bytes: ...


class _CryptographyAead:
    """Adapter from `cryptography`'s one-shot AEAD classes to the AeadCipher protocol."""

    tag_size = 16
    production_safe = True

    def __init__(
        self,
        cipher_id: int,
        name: str,
        factory: Callable[[bytes], _OpenSslAead],
        key_size: int,
        nonce_size: int,
    ) -> None:
        self.cipher_id = cipher_id
        self.name = name
        self.key_size = key_size
        self.nonce_size = nonce_size
        self._factory = factory

    def is_available(self) -> bool:
        try:
            self._factory(bytes(self.key_size))
        except UnsupportedAlgorithm:
            return False
        return True

    def encrypt(self, key: bytes, nonce: bytes, plaintext: bytes, aad: bytes) -> bytes:
        check_key(self, key)
        check_nonce(self, nonce)
        return self._factory(key).encrypt(nonce, plaintext, aad)

    def decrypt(self, key: bytes, nonce: bytes, ciphertext: bytes, aad: bytes) -> bytes:
        check_key(self, key)
        check_nonce(self, nonce)
        try:
            return self._factory(key).decrypt(nonce, ciphertext, aad)
        except InvalidTag as exc:
            raise DecryptionError(f"{self.name}: authentication failed") from exc


AES_256_GCM = _CryptographyAead(0x01, "aes-256-gcm", AESGCM, key_size=32, nonce_size=12)
CHACHA20_POLY1305 = _CryptographyAead(
    0x02, "chacha20-poly1305", ChaCha20Poly1305, key_size=32, nonce_size=12
)
AES_256_GCM_SIV = _CryptographyAead(0x03, "aes-256-gcm-siv", AESGCMSIV, key_size=32, nonce_size=12)
