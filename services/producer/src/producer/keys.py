"""Symmetric key files: generated to a user-given path, read back for encryption.

Key bytes never leave this module through logs, stdout or exception messages.
"""

from __future__ import annotations

import os
from pathlib import Path

from confidential_crypto.ciphers.base import AeadCipher
from confidential_crypto.errors import InvalidKeyError
from confidential_crypto.keys import generate_symmetric_key, load_symmetric_key

from producer.errors import ConfigError

_KEY_FILE_MODE = 0o600


def write_new_key(path: Path, cipher: AeadCipher) -> None:
    """Create `path` with a fresh raw key; refuse to overwrite an existing file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, _KEY_FILE_MODE)
    except FileExistsError as exc:
        raise ConfigError(f"refusing to overwrite existing key file: {path}") from exc
    except OSError as exc:
        raise ConfigError(f"cannot create key file {path}: {exc.strerror}") from exc
    with os.fdopen(fd, "wb") as stream:
        stream.write(generate_symmetric_key(cipher))


def read_key(path: Path, cipher: AeadCipher) -> bytes:
    try:
        return load_symmetric_key(path, cipher.key_size)
    except InvalidKeyError as exc:
        raise ConfigError(f"invalid key file {path}: {exc}") from exc
