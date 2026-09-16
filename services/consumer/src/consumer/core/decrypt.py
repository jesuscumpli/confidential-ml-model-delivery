"""Layer 1: decrypt the artifact file-to-file, dispatching on the authenticated version."""

from __future__ import annotations

import os
from pathlib import Path

from confidential_crypto import artifact, registry
from confidential_crypto.errors import CryptoError
from confidential_crypto.format import ArtifactHeader

from consumer.core.errors import DecryptError
from consumer.core.ports import KeyProvider


def artifact_key_size(path: Path) -> int:
    """Key size the artifact needs, read from its header; no decryption happens here."""
    try:
        with path.open("rb") as stream:
            head = stream.read(ArtifactHeader.max_size())
        header, _ = ArtifactHeader.decode(head)
        return registry.cipher_from_id(header.cipher_id).key_size
    except CryptoError as exc:
        raise DecryptError(f"unreadable artifact header: {exc}") from exc
    except OSError as exc:
        raise DecryptError(f"cannot read the artifact: {exc}") from exc


def decrypt_file(src: Path, dst: Path, provider: KeyProvider) -> ArtifactHeader:
    """Chunked (v2) artifacts stream with O(chunk) memory; one-shot (v1) load fully.

    Returns the authenticated header so callers can report which mode was used.

    The plaintext is written to a temporary file and renamed only after every chunk
    authenticated, so a partially verified package never sits at `dst`.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dst.with_name(dst.name + ".tmp")
    try:
        with src.open("rb") as inp:
            head = inp.read(ArtifactHeader.max_size())
            header, _ = ArtifactHeader.decode(head)
            key = provider.get_key(registry.cipher_from_id(header.cipher_id).key_size)
            inp.seek(0)
            with tmp_path.open("wb") as out:
                if header.chunked:
                    artifact.decrypt_stream(inp, out, key)
                else:
                    out.write(artifact.decrypt(inp.read(), key))
        os.replace(tmp_path, dst)
        return header
    except (CryptoError, OSError) as exc:
        raise DecryptError(f"decryption failed: {exc}") from exc
    finally:
        tmp_path.unlink(missing_ok=True)
