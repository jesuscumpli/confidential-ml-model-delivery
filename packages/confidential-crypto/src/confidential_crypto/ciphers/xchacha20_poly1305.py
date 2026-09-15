"""XChaCha20-Poly1305 via PyNaCl (libsodium). Evaluation extra: 192-bit nonce."""

from __future__ import annotations

import importlib
from types import ModuleType

from confidential_crypto.ciphers.base import check_key, check_nonce
from confidential_crypto.errors import DecryptionError, UnavailableAlgorithmError


def _load_nacl() -> ModuleType | None:
    try:
        return importlib.import_module("nacl.bindings")
    except ImportError:  # extra not installed
        return None


class XChaCha20Poly1305:
    cipher_id = 0x04
    name = "xchacha20-poly1305"
    key_size = 32
    nonce_size = 24
    tag_size = 16
    production_safe = True

    def __init__(self) -> None:
        self._nacl = _load_nacl()
        self._auth_error: type[Exception] = (
            importlib.import_module("nacl.exceptions").CryptoError if self._nacl else Exception
        )

    def is_available(self) -> bool:
        return self._nacl is not None

    def _backend(self) -> ModuleType:
        if self._nacl is None:
            raise UnavailableAlgorithmError(f"{self.name} requires the 'bench' extra (PyNaCl)")
        return self._nacl

    def encrypt(self, key: bytes, nonce: bytes, plaintext: bytes, aad: bytes) -> bytes:
        check_key(self, key)
        check_nonce(self, nonce)
        out: bytes = self._backend().crypto_aead_xchacha20poly1305_ietf_encrypt(
            plaintext, aad, nonce, key
        )
        return out

    def decrypt(self, key: bytes, nonce: bytes, ciphertext: bytes, aad: bytes) -> bytes:
        check_key(self, key)
        check_nonce(self, nonce)
        nacl = self._backend()
        try:
            out: bytes = nacl.crypto_aead_xchacha20poly1305_ietf_decrypt(
                ciphertext, aad, nonce, key
            )
        except (self._auth_error, ValueError) as exc:  # ValueError: shorter than the tag
            raise DecryptionError(f"{self.name}: authentication failed") from exc
        return out


XCHACHA20_POLY1305 = XChaCha20Poly1305()
