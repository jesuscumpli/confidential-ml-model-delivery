"""Layer 2: verify the artifact's signature before anything else touches it.

`decrypt_file` accepts only a `VerifiedArtifact`, and the only ways to obtain one are
`verify_file` (signature checked) or the explicit, logged `unverified` escape hatch,
so the "verify before decrypt" order is enforced by the types, not by convention.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from confidential_crypto import artifact
from confidential_crypto.errors import CryptoError
from confidential_crypto.signers.base import SignatureScheme

from consumer.core.errors import SignatureError


@dataclass(frozen=True, slots=True)
class VerifiedArtifact:
    """An artifact path that passed Layer 2, or explicitly skipped it (`verified=False`)."""

    path: Path
    verified: bool


def verify_file(
    artifact_path: Path, signature_path: Path, public_key: bytes, scheme: SignatureScheme
) -> VerifiedArtifact:
    """Check the envelope at `signature_path` against the artifact with the trusted key.

    Every failure (malformed envelope, scheme or key mismatch, modified bytes) raises
    `SignatureError`; no decryption key is read and nothing is decrypted.
    """
    try:
        envelope = signature_path.read_bytes()
        with artifact_path.open("rb") as stream:
            artifact.verify_stream(stream, envelope, public_key, scheme)
    except CryptoError as exc:
        raise SignatureError(f"signature verification failed: {exc}") from exc
    except OSError as exc:
        raise SignatureError(f"cannot read artifact or signature: {exc.strerror}") from exc
    return VerifiedArtifact(artifact_path, verified=True)


def unverified(artifact_path: Path) -> VerifiedArtifact:
    """Skip Layer 2 on purpose (development only); the pipeline logs a warning."""
    return VerifiedArtifact(artifact_path, verified=False)
