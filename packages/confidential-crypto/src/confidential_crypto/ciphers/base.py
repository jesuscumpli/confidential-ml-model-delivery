"""Common protocol for AEAD ciphers.

Every cipher takes the caller's nonce and additional authenticated data explicitly:
nonce generation and header binding are decided by the artifact layer, not by the
primitive, so all ciphers behave identically under the conformance tests. Inputs are
any buffer (bytes, bytearray, memoryview) so callers can pass slices without copying.
"""

from __future__ import annotations

import os
from typing import Protocol, runtime_checkable

from confidential_crypto.errors import InvalidKeyError, InvalidNonceError

# Same alias as cryptography.utils.Buffer: what the OpenSSL backend accepts without copying.
Buffer = bytes | bytearray | memoryview


@runtime_checkable
class AeadCipher(Protocol):
    """Authenticated encryption with associated data."""

    cipher_id: int
    name: str
    key_size: int
    nonce_size: int
    tag_size: int
    production_safe: bool

    def is_available(self) -> bool:
        """True when the backend supports this cipher in the current environment."""
        ...

    def ciphertext_size(self, plaintext_size: int) -> int:
        """Exact ciphertext length (tag included) for a plaintext of the given length."""
        ...

    def encrypt(self, key: bytes, nonce: bytes, plaintext: Buffer, aad: bytes) -> bytes:
        """Return ciphertext with the authentication tag appended."""
        ...

    def decrypt(self, key: bytes, nonce: bytes, ciphertext: Buffer, aad: bytes) -> bytes:
        """Return plaintext; raise DecryptionError when authentication fails."""
        ...


def check_key(cipher: AeadCipher, key: bytes) -> None:
    if not isinstance(key, bytes | bytearray) or len(key) != cipher.key_size:
        raise InvalidKeyError(f"{cipher.name} requires a {cipher.key_size}-byte key")


def check_nonce(cipher: AeadCipher, nonce: bytes) -> None:
    if not isinstance(nonce, bytes | bytearray) or len(nonce) != cipher.nonce_size:
        raise InvalidNonceError(f"{cipher.name} requires a {cipher.nonce_size}-byte nonce")


def new_nonce(cipher: AeadCipher) -> bytes:
    """Fresh random nonce from the OS CSPRNG."""
    return os.urandom(cipher.nonce_size)
