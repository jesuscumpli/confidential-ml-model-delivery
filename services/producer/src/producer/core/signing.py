"""Layer 2: sign the encrypted artifact file-to-file with the configured scheme."""

from __future__ import annotations

import os
from pathlib import Path

from confidential_crypto import artifact
from confidential_crypto.errors import CryptoError
from confidential_crypto.signers.base import SignatureScheme

from producer.core.errors import SigningError


def sign_file(src: Path, dst: Path, private_key: bytes, scheme: SignatureScheme) -> None:
    """Write the signature envelope of `src` atomically next to it."""
    dst.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp_path = dst.with_name(dst.name + ".tmp")
    try:
        with src.open("rb") as inp:
            envelope = artifact.sign_stream(inp, private_key, scheme)
        tmp_path.write_bytes(envelope)
        os.replace(tmp_path, dst)
    except CryptoError as exc:
        raise SigningError(f"signing failed: {exc}") from exc
    finally:
        tmp_path.unlink(missing_ok=True)
