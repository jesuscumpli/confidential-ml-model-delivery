"""Common protocol for signature schemes.

Keys cross the protocol boundary as PEM bytes (PKCS#8 private, SubjectPublicKeyInfo
public) so every scheme serialises the same way and the consumer never needs
scheme-specific key handling.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class SignatureScheme(Protocol):
    """Asymmetric signature scheme."""

    scheme_id: int
    name: str
    production_safe: bool
    deterministic: bool

    def is_available(self) -> bool: ...

    def generate_private_key(self) -> bytes:
        """Return a new private key as PEM (PKCS#8, unencrypted)."""
        ...

    def public_key_from_private(self, private_key: bytes) -> bytes:
        """Return the matching public key as PEM (SubjectPublicKeyInfo)."""
        ...

    def sign(self, private_key: bytes, message: bytes) -> bytes: ...

    def verify(self, public_key: bytes, message: bytes, signature: bytes) -> None:
        """Raise VerificationError when the signature is not valid for the message."""
        ...
