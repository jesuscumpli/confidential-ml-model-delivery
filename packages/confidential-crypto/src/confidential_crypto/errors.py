"""Exception hierarchy for the crypto core.

Messages never include key material, nonces or ciphertext bytes.
"""


class CryptoError(Exception):
    """Base class for every error raised by this package."""


class FormatError(CryptoError):
    """Encrypted artifact or signature envelope is malformed or unsupported."""


class InvalidKeyError(CryptoError):
    """Key has the wrong length, type or encoding for the selected algorithm."""


class InvalidNonceError(CryptoError):
    """Nonce has the wrong length for the selected cipher."""


class DecryptionError(CryptoError):
    """Authentication failed: wrong key, tampered ciphertext or tampered header."""


class VerificationError(CryptoError):
    """Signature verification failed."""


class UnknownAlgorithmError(CryptoError):
    """Algorithm name or wire id is not registered."""


class UnsafeAlgorithmError(CryptoError):
    """Algorithm is registered for evaluation only and was not explicitly allowed."""


class UnavailableAlgorithmError(CryptoError):
    """Algorithm is registered but its backend is missing in this environment."""
