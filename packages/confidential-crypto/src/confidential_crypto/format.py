"""Binary formats: encrypted artifact header (v1 one-shot, v2 chunked) and signature envelope.

Encrypted artifact, version 1 (one-shot):

    magic "CMLD" | version=1 u8 | cipher_id u8 | nonce_len u8 | nonce | ciphertext+tag

Encrypted artifact, version 2 (chunked, STREAM construction):

    magic "CMLD" | version=2 u8 | cipher_id u8 | prefix_len u8 | nonce_prefix | chunk_size u32
    chunk_0 | chunk_1 | ... | chunk_last

    chunk_i = AEAD(key, nonce_i, plaintext_i, aad_i)
    nonce_i = nonce_prefix || counter_i (u32 BE) || last_flag (u8)
    aad_i   = header || counter_i (u32 BE) || last_flag (u8)

Every chunk holds exactly `chunk_size` plaintext bytes except the last one. The
counter makes each chunk nonce unique and position-bound (no reordering), the last
flag makes truncation at a chunk boundary detectable, and the header inside the AAD
binds the cipher id and chunk size exactly as in version 1.

In both versions the header (everything before the ciphertext) is associated data,
so a modified `cipher_id` or nonce fails authentication instead of silently
selecting another algorithm.

Signature envelope (version 1):

    magic "CMLS" | version u8 | scheme_id u8 | key_fingerprint 32B | sig_len u32 | signature

`key_fingerprint` is SHA-256 of the verifying public key PEM; it lets the consumer
detect a key mismatch before attempting verification.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from confidential_crypto.errors import FormatError

ARTIFACT_MAGIC = b"CMLD"
ARTIFACT_VERSION_ONESHOT = 1
ARTIFACT_VERSION_CHUNKED = 2
_ARTIFACT_FIXED = struct.Struct(">4sBBB")
_CHUNK_SIZE_FIELD = struct.Struct(">I")
CHUNK_COUNTER_SIZE = 4  # u32 counter
CHUNK_FLAG_SIZE = 1  # u8 last flag
CHUNK_NONCE_SUFFIX = CHUNK_COUNTER_SIZE + CHUNK_FLAG_SIZE
MIN_CHUNK_SIZE = 4096
MAX_CHUNK_SIZE = 1 << 30

SIGNATURE_MAGIC = b"CMLS"
SIGNATURE_VERSION = 1
FINGERPRINT_SIZE = 32
_SIGNATURE_FIXED = struct.Struct(f">4sBB{FINGERPRINT_SIZE}sI")
_MAX_SIGNATURE_SIZE = 1 << 16


@dataclass(frozen=True)
class ArtifactHeader:
    """Header of either artifact version.

    `nonce` is the full nonce for version 1 and the random nonce prefix for version 2;
    `chunk_size` is set only for version 2.
    """

    cipher_id: int
    nonce: bytes
    version: int = ARTIFACT_VERSION_ONESHOT
    chunk_size: int | None = None

    @property
    def chunked(self) -> bool:
        return self.version == ARTIFACT_VERSION_CHUNKED

    def encode(self) -> bytes:
        if not 0 <= self.cipher_id <= 0xFF:
            raise FormatError("cipher id does not fit in one byte")
        if not 1 <= len(self.nonce) <= 0xFF:
            raise FormatError("nonce length must be between 1 and 255 bytes")
        fixed = _ARTIFACT_FIXED.pack(ARTIFACT_MAGIC, self.version, self.cipher_id, len(self.nonce))
        if self.version == ARTIFACT_VERSION_ONESHOT:
            if self.chunk_size is not None:
                raise FormatError("version 1 headers carry no chunk size")
            return fixed + self.nonce
        if self.version == ARTIFACT_VERSION_CHUNKED:
            if self.chunk_size is None or not MIN_CHUNK_SIZE <= self.chunk_size <= MAX_CHUNK_SIZE:
                raise FormatError("version 2 headers need a chunk size within limits")
            return fixed + self.nonce + _CHUNK_SIZE_FIELD.pack(self.chunk_size)
        raise FormatError(f"unsupported artifact version {self.version}")

    @classmethod
    def decode(cls, data: bytes) -> tuple[ArtifactHeader, int]:
        """Parse a header from the start of `data`; return it with the header length."""
        if len(data) < _ARTIFACT_FIXED.size:
            raise FormatError("artifact is too short to contain a header")
        magic, version, cipher_id, nonce_len = _ARTIFACT_FIXED.unpack_from(data)
        if magic != ARTIFACT_MAGIC:
            raise FormatError("not an encrypted artifact (bad magic)")
        if version not in (ARTIFACT_VERSION_ONESHOT, ARTIFACT_VERSION_CHUNKED):
            raise FormatError(f"unsupported artifact version {version}")
        if nonce_len == 0:
            raise FormatError("nonce length must not be zero")
        end = _ARTIFACT_FIXED.size + nonce_len
        if len(data) < end:
            raise FormatError("artifact is truncated inside the nonce")
        nonce = bytes(data[_ARTIFACT_FIXED.size : end])
        if version == ARTIFACT_VERSION_ONESHOT:
            return cls(cipher_id=cipher_id, nonce=nonce), end
        if len(data) < end + _CHUNK_SIZE_FIELD.size:
            raise FormatError("artifact is truncated inside the chunk size")
        (chunk_size,) = _CHUNK_SIZE_FIELD.unpack_from(data, end)
        if not MIN_CHUNK_SIZE <= chunk_size <= MAX_CHUNK_SIZE:
            raise FormatError("chunk size is out of range")
        end += _CHUNK_SIZE_FIELD.size
        return cls(cipher_id=cipher_id, nonce=nonce, version=version, chunk_size=chunk_size), end

    @classmethod
    def max_size(cls) -> int:
        """Upper bound of an encoded header, for reading it from a stream."""
        return _ARTIFACT_FIXED.size + 0xFF + _CHUNK_SIZE_FIELD.size


def chunk_nonce(prefix: bytes, counter: int, last: bool) -> bytes:
    return prefix + counter.to_bytes(CHUNK_COUNTER_SIZE, "big") + bytes([int(last)])


def chunk_aad(header_bytes: bytes, counter: int, last: bool) -> bytes:
    return header_bytes + counter.to_bytes(CHUNK_COUNTER_SIZE, "big") + bytes([int(last)])


@dataclass(frozen=True)
class SignatureEnvelope:
    scheme_id: int
    key_fingerprint: bytes
    signature: bytes

    def encode(self) -> bytes:
        if not 0 <= self.scheme_id <= 0xFF:
            raise FormatError("scheme id does not fit in one byte")
        if len(self.key_fingerprint) != FINGERPRINT_SIZE:
            raise FormatError(f"fingerprint must be {FINGERPRINT_SIZE} bytes")
        if not 1 <= len(self.signature) <= _MAX_SIGNATURE_SIZE:
            raise FormatError("signature length is out of range")
        return (
            _SIGNATURE_FIXED.pack(
                SIGNATURE_MAGIC,
                SIGNATURE_VERSION,
                self.scheme_id,
                self.key_fingerprint,
                len(self.signature),
            )
            + self.signature
        )

    @classmethod
    def decode(cls, data: bytes) -> SignatureEnvelope:
        if len(data) < _SIGNATURE_FIXED.size:
            raise FormatError("signature envelope is too short")
        magic, version, scheme_id, fingerprint, sig_len = _SIGNATURE_FIXED.unpack_from(data)
        if magic != SIGNATURE_MAGIC:
            raise FormatError("not a signature envelope (bad magic)")
        if version != SIGNATURE_VERSION:
            raise FormatError(f"unsupported signature envelope version {version}")
        if sig_len == 0 or sig_len > _MAX_SIGNATURE_SIZE:
            raise FormatError("signature length is out of range")
        if len(data) != _SIGNATURE_FIXED.size + sig_len:
            raise FormatError("signature envelope length does not match its declared size")
        return cls(
            scheme_id=scheme_id,
            key_fingerprint=bytes(fingerprint),
            signature=bytes(data[_SIGNATURE_FIXED.size :]),
        )
