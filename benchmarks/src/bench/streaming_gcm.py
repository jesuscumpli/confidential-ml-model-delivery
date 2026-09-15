"""Evaluation-only comparator: incremental AES-GCM producing format-v1 bytes.

Shows what "streaming without changing the wire format" costs. `cryptography`'s
incremental GCM API emits exactly the same ciphertext||tag as the one-shot call, so
memory drops to O(chunk) on both sides, but on decryption the plaintext is produced
*before* the tag is checked. The consumer would have to quarantine the output until
`finalize_with_tag` succeeds; any bug there releases unauthenticated plaintext.
This is why it lives in `bench/` and not in the shared package.
"""

from __future__ import annotations

from typing import BinaryIO

from confidential_crypto.ciphers.base import new_nonce
from confidential_crypto.errors import DecryptionError, FormatError
from confidential_crypto.format import ArtifactHeader
from confidential_crypto.registry import get_cipher
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

_TAG = 16
_CIPHER = get_cipher("aes-256-gcm")


def encrypt_stream(src: BinaryIO, dst: BinaryIO, key: bytes, *, chunk_size: int) -> None:
    header = ArtifactHeader(cipher_id=_CIPHER.cipher_id, nonce=new_nonce(_CIPHER))
    aad = header.encode()
    encryptor = Cipher(algorithms.AES(key), modes.GCM(header.nonce)).encryptor()
    encryptor.authenticate_additional_data(aad)
    dst.write(aad)
    while chunk := src.read(chunk_size):
        dst.write(encryptor.update(chunk))
    encryptor.finalize()
    dst.write(encryptor.tag)


def decrypt_stream(src: BinaryIO, dst: BinaryIO, key: bytes, *, chunk_size: int) -> None:
    """Writes plaintext to `dst` as it goes; raises only at the end if the tag is wrong."""
    src.seek(0, 2)
    total = src.tell()
    src.seek(0)
    head = src.read(ArtifactHeader.max_size())
    header, offset = ArtifactHeader.decode(head)
    if header.chunked or header.cipher_id != _CIPHER.cipher_id:
        raise FormatError("streaming-gcm handles version 1 AES-GCM artifacts only")
    body_len = total - offset - _TAG
    if body_len < 0:
        raise FormatError("artifact shorter than header plus tag")
    decryptor = Cipher(algorithms.AES(key), modes.GCM(header.nonce)).decryptor()
    decryptor.authenticate_additional_data(head[:offset])
    src.seek(offset)
    remaining = body_len
    while remaining > 0:
        chunk = src.read(min(chunk_size, remaining))
        remaining -= len(chunk)
        dst.write(decryptor.update(chunk))  # unauthenticated plaintext leaves here
    tag = src.read(_TAG)
    try:
        decryptor.finalize_with_tag(tag)
    except InvalidTag as exc:
        raise DecryptionError("aes-256-gcm: authentication failed (after output)") from exc
