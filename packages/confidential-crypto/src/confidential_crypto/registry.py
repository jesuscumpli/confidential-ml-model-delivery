"""Factory for ciphers and signature schemes, by name or by wire id.

Algorithms flagged `production_safe = False` exist only for the evaluation phase and
are refused unless the caller passes `allow_unsafe=True`.
"""

from __future__ import annotations

from collections.abc import Mapping

from confidential_crypto.ciphers.aead_cryptography import (
    AES_256_GCM,
    AES_256_GCM_SIV,
    CHACHA20_POLY1305,
)
from confidential_crypto.ciphers.aes_cbc_hmac import AES_256_CBC_HMAC_SHA256
from confidential_crypto.ciphers.base import AeadCipher
from confidential_crypto.ciphers.xchacha20_poly1305 import XCHACHA20_POLY1305
from confidential_crypto.errors import (
    UnavailableAlgorithmError,
    UnknownAlgorithmError,
    UnsafeAlgorithmError,
)
from confidential_crypto.signers.base import SignatureScheme
from confidential_crypto.signers.schemes_cryptography import (
    ECDSA_P256,
    ED25519,
    ML_DSA_65,
    RSA_PSS_3072,
    RSA_PSS_4096,
)

DEFAULT_CIPHER = "aes-256-gcm"
DEFAULT_SIGNER = "ed25519"

_CIPHERS: tuple[AeadCipher, ...] = (
    AES_256_GCM,
    CHACHA20_POLY1305,
    AES_256_GCM_SIV,
    XCHACHA20_POLY1305,
    AES_256_CBC_HMAC_SHA256,
)
_SIGNERS: tuple[SignatureScheme, ...] = (
    ED25519,
    ECDSA_P256,
    RSA_PSS_3072,
    RSA_PSS_4096,
    ML_DSA_65,
)

CIPHERS: Mapping[str, AeadCipher] = {c.name: c for c in _CIPHERS}
SIGNERS: Mapping[str, SignatureScheme] = {s.name: s for s in _SIGNERS}
_CIPHERS_BY_ID: Mapping[int, AeadCipher] = {c.cipher_id: c for c in _CIPHERS}
_SIGNERS_BY_ID: Mapping[int, SignatureScheme] = {s.scheme_id: s for s in _SIGNERS}


def _guard(kind: str, algorithm: AeadCipher | SignatureScheme, allow_unsafe: bool) -> None:
    if not algorithm.production_safe and not allow_unsafe:
        raise UnsafeAlgorithmError(f"{kind} '{algorithm.name}' is for evaluation only")
    if not algorithm.is_available():
        raise UnavailableAlgorithmError(f"{kind} '{algorithm.name}' backend is not installed")


def get_cipher(name: str, *, allow_unsafe: bool = False) -> AeadCipher:
    cipher = CIPHERS.get(name)
    if cipher is None:
        raise UnknownAlgorithmError(f"unknown cipher '{name}'")
    _guard("cipher", cipher, allow_unsafe)
    return cipher


def cipher_from_id(cipher_id: int, *, allow_unsafe: bool = False) -> AeadCipher:
    cipher = _CIPHERS_BY_ID.get(cipher_id)
    if cipher is None:
        raise UnknownAlgorithmError(f"unknown cipher id {cipher_id:#04x}")
    _guard("cipher", cipher, allow_unsafe)
    return cipher


def get_signer(name: str, *, allow_unsafe: bool = False) -> SignatureScheme:
    signer = SIGNERS.get(name)
    if signer is None:
        raise UnknownAlgorithmError(f"unknown signature scheme '{name}'")
    _guard("signature scheme", signer, allow_unsafe)
    return signer


def signer_from_id(scheme_id: int, *, allow_unsafe: bool = False) -> SignatureScheme:
    signer = _SIGNERS_BY_ID.get(scheme_id)
    if signer is None:
        raise UnknownAlgorithmError(f"unknown signature scheme id {scheme_id:#04x}")
    _guard("signature scheme", signer, allow_unsafe)
    return signer


def available_ciphers(*, include_unsafe: bool = False) -> list[AeadCipher]:
    return [c for c in _CIPHERS if c.is_available() and (c.production_safe or include_unsafe)]


def available_signers(*, include_unsafe: bool = False) -> list[SignatureScheme]:
    return [s for s in _SIGNERS if s.is_available() and (s.production_safe or include_unsafe)]
