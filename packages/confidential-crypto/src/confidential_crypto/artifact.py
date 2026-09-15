"""High-level operations on artifacts: encrypt, decrypt, sign, verify.

Producer and consumer call only this module and `registry`; they never touch a
primitive directly.
"""

from __future__ import annotations

from confidential_crypto import registry
from confidential_crypto.ciphers.base import AeadCipher, new_nonce
from confidential_crypto.errors import FormatError, VerificationError
from confidential_crypto.format import ArtifactHeader, SignatureEnvelope
from confidential_crypto.keys import public_key_fingerprint
from confidential_crypto.signers.base import SignatureScheme


def encrypt(plaintext: bytes, key: bytes, cipher: AeadCipher) -> bytes:
    """Encrypt with a fresh random nonce; the header is bound as associated data."""
    header = ArtifactHeader(cipher_id=cipher.cipher_id, nonce=new_nonce(cipher))
    aad = header.encode()
    return aad + cipher.encrypt(key, header.nonce, plaintext, aad)


def decrypt(artifact: bytes, key: bytes, *, allow_unsafe: bool = False) -> bytes:
    """Select the cipher from the authenticated header and decrypt."""
    header, offset = ArtifactHeader.decode(artifact)
    cipher = registry.cipher_from_id(header.cipher_id, allow_unsafe=allow_unsafe)
    if len(header.nonce) != cipher.nonce_size:
        raise FormatError(f"nonce length does not match {cipher.name}")
    aad = artifact[:offset]
    return cipher.decrypt(key, header.nonce, artifact[offset:], aad)


def sign(artifact: bytes, private_key: bytes, scheme: SignatureScheme) -> bytes:
    """Return a signature envelope over the full encrypted artifact bytes."""
    fingerprint = public_key_fingerprint(scheme.public_key_from_private(private_key))
    envelope = SignatureEnvelope(
        scheme_id=scheme.scheme_id,
        key_fingerprint=fingerprint,
        signature=scheme.sign(private_key, artifact),
    )
    return envelope.encode()


def verify(
    artifact: bytes, envelope_bytes: bytes, public_key: bytes, scheme: SignatureScheme
) -> None:
    """Verify `artifact` against its envelope using the expected scheme.

    The scheme is chosen by the consumer's configuration, never by the envelope: an
    envelope declaring a different scheme is rejected before any cryptographic work.
    """
    envelope = SignatureEnvelope.decode(envelope_bytes)
    if envelope.scheme_id != scheme.scheme_id:
        raise VerificationError("signature scheme does not match the expected scheme")
    if envelope.key_fingerprint != public_key_fingerprint(public_key):
        raise VerificationError("signature was not produced by the expected public key")
    scheme.verify(public_key, artifact, envelope.signature)
