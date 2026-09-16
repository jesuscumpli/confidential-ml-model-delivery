"""Shared cryptographic core: artifact format, algorithm registry, ciphers and signers.

Producer and consumer both depend on this package so that the encrypted artifact
format and the algorithm registry are identical on both sides.
"""

from confidential_crypto.artifact import (
    decrypt,
    decrypt_stream,
    encrypt,
    encrypt_parts,
    encrypt_stream,
    sign,
    sign_stream,
    verify,
    verify_stream,
)
from confidential_crypto.registry import DEFAULT_CIPHER, DEFAULT_SIGNER, get_cipher, get_signer

__version__ = "0.1.0"

__all__ = [
    "DEFAULT_CIPHER",
    "DEFAULT_SIGNER",
    "__version__",
    "decrypt",
    "decrypt_stream",
    "encrypt",
    "encrypt_parts",
    "encrypt_stream",
    "get_cipher",
    "get_signer",
    "sign",
    "sign_stream",
    "verify",
    "verify_stream",
]
