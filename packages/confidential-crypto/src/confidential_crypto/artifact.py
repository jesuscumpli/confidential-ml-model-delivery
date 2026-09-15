"""High-level operations on artifacts: encrypt, decrypt, sign, verify.

Two encryption modes share the same header and registry:

- one-shot (format v1): whole artifact in memory, one AEAD call;
- chunked (format v2): streamed in fixed-size chunks with bounded memory, each chunk
  authenticated before its plaintext is released.

Producer and consumer call only this module and `registry`; they never touch a
primitive directly.
"""

from __future__ import annotations

import io
import os
from typing import BinaryIO

from confidential_crypto import registry
from confidential_crypto.ciphers.base import AeadCipher, new_nonce
from confidential_crypto.errors import FormatError, VerificationError
from confidential_crypto.format import (
    ARTIFACT_VERSION_CHUNKED,
    CHUNK_NONCE_SUFFIX,
    ArtifactHeader,
    SignatureEnvelope,
    chunk_aad,
    chunk_nonce,
)
from confidential_crypto.keys import public_key_fingerprint
from confidential_crypto.signers.base import SignatureScheme

DEFAULT_CHUNK_SIZE = 1 << 20
_MAX_CHUNKS = 1 << 32


def encrypt_parts(plaintext: bytes, key: bytes, cipher: AeadCipher) -> tuple[bytes, bytes]:
    """One-shot encrypt with a fresh random nonce; return (header, ciphertext) unjoined.

    Callers that stream to a file write the two parts back to back and avoid one full
    copy of the ciphertext. The header is bound as associated data.
    """
    header = ArtifactHeader(cipher_id=cipher.cipher_id, nonce=new_nonce(cipher))
    aad = header.encode()
    return aad, cipher.encrypt(key, header.nonce, plaintext, aad)


def encrypt(plaintext: bytes, key: bytes, cipher: AeadCipher) -> bytes:
    """Convenience form of `encrypt_parts` returning one contiguous artifact."""
    header, ciphertext = encrypt_parts(plaintext, key, cipher)
    return header + ciphertext


def decrypt(artifact: bytes, key: bytes, *, allow_unsafe: bool = False) -> bytes:
    """Decrypt an in-memory artifact of either version."""
    header, offset = ArtifactHeader.decode(artifact)
    if header.chunked:
        out = io.BytesIO()
        decrypt_stream(io.BytesIO(artifact), out, key, allow_unsafe=allow_unsafe)
        return out.getvalue()
    cipher = _resolve(header, allow_unsafe)
    view = memoryview(artifact)  # zero-copy split: the ciphertext is not duplicated
    return cipher.decrypt(key, header.nonce, view[offset:], bytes(view[:offset]))


def encrypt_stream(
    src: BinaryIO,
    dst: BinaryIO,
    key: bytes,
    cipher: AeadCipher,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> None:
    """Chunked encrypt from one binary stream to another with O(chunk_size) memory."""
    prefix = os.urandom(cipher.nonce_size - CHUNK_NONCE_SUFFIX)
    header = ArtifactHeader(
        cipher_id=cipher.cipher_id,
        nonce=prefix,
        version=ARTIFACT_VERSION_CHUNKED,
        chunk_size=chunk_size,
    )
    header_bytes = header.encode()
    dst.write(header_bytes)
    counter = 0
    pending = src.read(chunk_size)
    while True:
        following = src.read(chunk_size)
        last = len(following) == 0
        if counter >= _MAX_CHUNKS:
            raise FormatError("input exceeds the maximum number of chunks")
        nonce = chunk_nonce(prefix, counter, last)
        dst.write(cipher.encrypt(key, nonce, pending, chunk_aad(header_bytes, counter, last)))
        if last:
            return
        pending, counter = following, counter + 1


def decrypt_stream(src: BinaryIO, dst: BinaryIO, key: bytes, *, allow_unsafe: bool = False) -> None:
    """Chunked decrypt; each chunk is authenticated before any of its plaintext is written.

    Truncation at a chunk boundary, reordering, and a chunk from another artifact all
    fail authentication because position and last flag are part of the nonce and AAD.
    """
    head = src.read(ArtifactHeader.max_size())
    header, offset = ArtifactHeader.decode(head)
    if not header.chunked or header.chunk_size is None:
        raise FormatError("decrypt_stream needs a chunked (version 2) artifact")
    cipher = _resolve(header, allow_unsafe)
    if len(header.nonce) != cipher.nonce_size - CHUNK_NONCE_SUFFIX:
        raise FormatError(f"nonce prefix length does not match {cipher.name}")
    header_bytes = head[:offset]
    full_chunk = cipher.ciphertext_size(header.chunk_size)
    counter = 0
    pending = head[offset:] + src.read(full_chunk - (len(head) - offset))
    if len(pending) == 0:
        raise FormatError("chunked artifact has no chunks")
    while True:
        following = src.read(full_chunk)
        last = len(following) == 0
        if not last and len(pending) != full_chunk:
            raise FormatError("short chunk before the end of the artifact")
        nonce = chunk_nonce(header.nonce, counter, last)
        dst.write(cipher.decrypt(key, nonce, pending, chunk_aad(header_bytes, counter, last)))
        if last:
            return
        pending, counter = following, counter + 1


def _resolve(header: ArtifactHeader, allow_unsafe: bool) -> AeadCipher:
    cipher = registry.cipher_from_id(header.cipher_id, allow_unsafe=allow_unsafe)
    if not header.chunked and len(header.nonce) != cipher.nonce_size:
        raise FormatError(f"nonce length does not match {cipher.name}")
    return cipher


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
