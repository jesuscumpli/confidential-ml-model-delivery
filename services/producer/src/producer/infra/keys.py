"""Key files: the symmetric key and the signing key pair, generated to user-given paths
and read back when needed.

Key bytes never leave this module through logs, stdout or exception messages.
"""

from __future__ import annotations

import os
from pathlib import Path

from confidential_crypto.ciphers.base import AeadCipher
from confidential_crypto.errors import InvalidKeyError
from confidential_crypto.keys import generate_symmetric_key, load_pem_key, load_symmetric_key
from confidential_crypto.signers.base import SignatureScheme

from producer.core.errors import ConfigError

_PRIVATE_FILE_MODE = 0o600
_PUBLIC_FILE_MODE = 0o644


def write_new_key(path: Path, cipher: AeadCipher) -> None:
    """Create `path` with a fresh raw key; refuse to overwrite an existing file."""
    _write_new(path, generate_symmetric_key(cipher), _PRIVATE_FILE_MODE)


def write_new_signing_keypair(
    private_path: Path, public_path: Path, scheme: SignatureScheme
) -> None:
    """Create a PEM private key (0600) and its public key (0644); never overwrite."""
    private_pem = scheme.generate_private_key()
    _write_new(private_path, private_pem, _PRIVATE_FILE_MODE)
    _write_new(public_path, scheme.public_key_from_private(private_pem), _PUBLIC_FILE_MODE)


def read_signing_key(path: Path) -> bytes:
    try:
        return load_pem_key(path)
    except InvalidKeyError as exc:
        raise ConfigError(f"invalid signing key file {path}: {exc}") from exc


def _write_new(path: Path, data: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    except FileExistsError as exc:
        raise ConfigError(f"refusing to overwrite existing key file: {path}") from exc
    except OSError as exc:
        raise ConfigError(f"cannot create key file {path}: {exc.strerror}") from exc
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)


def read_key(path: Path, cipher: AeadCipher) -> bytes:
    try:
        return load_symmetric_key(path, cipher.key_size)
    except InvalidKeyError as exc:
        raise ConfigError(f"invalid key file {path}: {exc}") from exc
