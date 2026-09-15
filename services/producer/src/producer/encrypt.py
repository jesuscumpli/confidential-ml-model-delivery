"""Layer 1: encrypt the plaintext package file-to-file with the configured cipher."""

from __future__ import annotations

import os
from enum import StrEnum
from pathlib import Path

from confidential_crypto import artifact
from confidential_crypto.ciphers.base import AeadCipher
from confidential_crypto.errors import CryptoError

from producer.errors import EncryptionError


class EncryptionMode(StrEnum):
    """Chunked (format v2) is the production default; one-shot (v1) suits small models."""

    CHUNKED = "chunked"
    ONE_SHOT = "one-shot"


def encrypt_file(
    src: Path,
    dst: Path,
    key: bytes,
    cipher: AeadCipher,
    *,
    mode: EncryptionMode = EncryptionMode.CHUNKED,
    chunk_size: int = artifact.DEFAULT_CHUNK_SIZE,
) -> None:
    """Write the encrypted artifact atomically; the destination dir is owner-only."""
    dst.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp_path = dst.with_name(dst.name + ".tmp")
    try:
        with src.open("rb") as inp, tmp_path.open("wb") as out:
            if mode is EncryptionMode.CHUNKED:
                artifact.encrypt_stream(inp, out, key, cipher, chunk_size=chunk_size)
            else:
                header, ciphertext = artifact.encrypt_parts(inp.read(), key, cipher)
                out.write(header)
                out.write(ciphertext)
        os.replace(tmp_path, dst)
    except CryptoError as exc:
        raise EncryptionError(f"encryption failed: {exc}") from exc
    finally:
        tmp_path.unlink(missing_ok=True)
