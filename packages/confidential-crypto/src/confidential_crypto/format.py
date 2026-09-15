"""Binary formats: encrypted artifact header and signature envelope.

Encrypted artifact (version 1):

    magic "CMLD" | version u8 | cipher_id u8 | nonce_len u8 | nonce | ciphertext+tag

The whole header (up to and including the nonce) is passed to the cipher as
associated data, so a modified `cipher_id` or nonce fails authentication instead
of silently selecting another algorithm.

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
ARTIFACT_VERSION = 1
_ARTIFACT_FIXED = struct.Struct(">4sBBB")

SIGNATURE_MAGIC = b"CMLS"
SIGNATURE_VERSION = 1
FINGERPRINT_SIZE = 32
_SIGNATURE_FIXED = struct.Struct(f">4sBB{FINGERPRINT_SIZE}sI")
_MAX_SIGNATURE_SIZE = 1 << 16


@dataclass(frozen=True)
class ArtifactHeader:
    cipher_id: int
    nonce: bytes

    def encode(self) -> bytes:
        if not 0 <= self.cipher_id <= 0xFF:
            raise FormatError("cipher id does not fit in one byte")
        if not 1 <= len(self.nonce) <= 0xFF:
            raise FormatError("nonce length must be between 1 and 255 bytes")
        return (
            _ARTIFACT_FIXED.pack(ARTIFACT_MAGIC, ARTIFACT_VERSION, self.cipher_id, len(self.nonce))
            + self.nonce
        )

    @classmethod
    def decode(cls, data: bytes) -> tuple[ArtifactHeader, int]:
        """Parse a header from the start of `data`; return it with the header length."""
        if len(data) < _ARTIFACT_FIXED.size:
            raise FormatError("artifact is too short to contain a header")
        magic, version, cipher_id, nonce_len = _ARTIFACT_FIXED.unpack_from(data)
        if magic != ARTIFACT_MAGIC:
            raise FormatError("not an encrypted artifact (bad magic)")
        if version != ARTIFACT_VERSION:
            raise FormatError(f"unsupported artifact version {version}")
        if nonce_len == 0:
            raise FormatError("nonce length must not be zero")
        end = _ARTIFACT_FIXED.size + nonce_len
        if len(data) < end:
            raise FormatError("artifact is truncated inside the nonce")
        return cls(cipher_id=cipher_id, nonce=bytes(data[_ARTIFACT_FIXED.size : end])), end


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
