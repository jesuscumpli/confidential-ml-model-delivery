"""Key generation, loading and validation. No key bytes ever appear in messages."""

from __future__ import annotations

import binascii
import hashlib
import os
from pathlib import Path

from confidential_crypto.ciphers.base import AeadCipher
from confidential_crypto.errors import InvalidKeyError


def generate_symmetric_key(cipher: AeadCipher) -> bytes:
    return os.urandom(cipher.key_size)


def decode_symmetric_key(data: bytes, key_size: int) -> bytes:
    """Accept a raw key or its hex encoding (with optional trailing newline)."""
    if len(data) == key_size:
        return bytes(data)
    text = data.strip()
    if len(text) == 2 * key_size:
        try:
            return binascii.unhexlify(text)
        except binascii.Error as exc:
            raise InvalidKeyError("key is neither raw nor valid hex") from exc
    raise InvalidKeyError(f"key must be {key_size} raw bytes or {2 * key_size} hex characters")


def load_symmetric_key(path: Path, key_size: int) -> bytes:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise InvalidKeyError(f"cannot read key file: {exc.strerror}") from exc
    return decode_symmetric_key(data, key_size)


def load_pem_key(path: Path) -> bytes:
    """Read a PEM-encoded signing key (private or public); only the path is ever reported."""
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise InvalidKeyError(f"cannot read key file: {exc.strerror}") from exc
    if b"-----BEGIN " not in data:
        raise InvalidKeyError("key file is not PEM encoded")
    return data


def public_key_fingerprint(public_key_pem: bytes) -> bytes:
    """SHA-256 over the normalised PEM so line-ending differences do not matter."""
    normalised = b"".join(public_key_pem.split())
    return hashlib.sha256(normalised).digest()
