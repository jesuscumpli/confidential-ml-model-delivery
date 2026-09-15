"""Signature schemes backed by the `cryptography` package (OpenSSL)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, mldsa, padding, rsa

from confidential_crypto.errors import InvalidKeyError, VerificationError

_RSA_MIN_BITS = 3072


class _CryptographyScheme:
    """Adapter from `cryptography` key objects to the SignatureScheme protocol."""

    production_safe = True

    def __init__(
        self,
        scheme_id: int,
        name: str,
        *,
        generate: Callable[[], Any],
        private_type: type,
        public_type: type,
        sign: Callable[[Any, bytes], bytes],
        verify: Callable[[Any, bytes, bytes], None],
        deterministic: bool,
        min_bits: int | None = None,
    ) -> None:
        self.scheme_id = scheme_id
        self.name = name
        self.deterministic = deterministic
        self._generate = generate
        self._private_type = private_type
        self._public_type = public_type
        self._sign = sign
        self._verify = verify
        self._min_bits = min_bits

    def is_available(self) -> bool:
        try:
            self._generate()
        except UnsupportedAlgorithm:
            return False
        return True

    def generate_private_key(self) -> bytes:
        key = self._generate()
        pem: bytes = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        return pem

    def _load_private(self, private_key: bytes) -> Any:
        try:
            key = serialization.load_pem_private_key(private_key, password=None)
        except (ValueError, TypeError, UnsupportedAlgorithm) as exc:
            raise InvalidKeyError(f"{self.name}: private key is not a valid PEM") from exc
        self._check_type(key, self._private_type)
        return key

    def _load_public(self, public_key: bytes) -> Any:
        try:
            key = serialization.load_pem_public_key(public_key)
        except (ValueError, UnsupportedAlgorithm) as exc:
            raise InvalidKeyError(f"{self.name}: public key is not a valid PEM") from exc
        self._check_type(key, self._public_type)
        return key

    def _check_type(self, key: Any, expected: type) -> None:
        if not isinstance(key, expected):
            raise InvalidKeyError(f"{self.name}: key does not belong to this scheme")
        if self._min_bits is not None and getattr(key, "key_size", 0) < self._min_bits:
            raise InvalidKeyError(f"{self.name}: key must be at least {self._min_bits} bits")

    def public_key_from_private(self, private_key: bytes) -> bytes:
        pem: bytes = (
            self._load_private(private_key)
            .public_key()
            .public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
            )
        )
        return pem

    def sign(self, private_key: bytes, message: bytes) -> bytes:
        return self._sign(self._load_private(private_key), message)

    def verify(self, public_key: bytes, message: bytes, signature: bytes) -> None:
        key = self._load_public(public_key)
        try:
            self._verify(key, message, signature)
        except InvalidSignature as exc:
            raise VerificationError(f"{self.name}: signature is invalid") from exc


_ECDSA_SHA256 = ec.ECDSA(hashes.SHA256())
_PSS = padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH)


def _generate_rsa(bits: int) -> Callable[[], rsa.RSAPrivateKey]:
    return lambda: rsa.generate_private_key(public_exponent=65537, key_size=bits)


ED25519 = _CryptographyScheme(
    0x01,
    "ed25519",
    generate=ed25519.Ed25519PrivateKey.generate,
    private_type=ed25519.Ed25519PrivateKey,
    public_type=ed25519.Ed25519PublicKey,
    sign=lambda k, m: k.sign(m),
    verify=lambda k, m, s: k.verify(s, m),
    deterministic=True,
)

ECDSA_P256 = _CryptographyScheme(
    0x02,
    "ecdsa-p256",
    generate=lambda: ec.generate_private_key(ec.SECP256R1()),
    private_type=ec.EllipticCurvePrivateKey,
    public_type=ec.EllipticCurvePublicKey,
    sign=lambda k, m: k.sign(m, _ECDSA_SHA256),
    verify=lambda k, m, s: k.verify(s, m, _ECDSA_SHA256),
    deterministic=False,
)

RSA_PSS_3072 = _CryptographyScheme(
    0x03,
    "rsa-pss-3072",
    generate=_generate_rsa(3072),
    private_type=rsa.RSAPrivateKey,
    public_type=rsa.RSAPublicKey,
    sign=lambda k, m: k.sign(m, _PSS, hashes.SHA256()),
    verify=lambda k, m, s: k.verify(s, m, _PSS, hashes.SHA256()),
    deterministic=False,
    min_bits=_RSA_MIN_BITS,
)

RSA_PSS_4096 = _CryptographyScheme(
    0x04,
    "rsa-pss-4096",
    generate=_generate_rsa(4096),
    private_type=rsa.RSAPrivateKey,
    public_type=rsa.RSAPublicKey,
    sign=lambda k, m: k.sign(m, _PSS, hashes.SHA256()),
    verify=lambda k, m, s: k.verify(s, m, _PSS, hashes.SHA256()),
    deterministic=False,
    min_bits=4096,
)

ML_DSA_65 = _CryptographyScheme(
    0x05,
    "ml-dsa-65",
    generate=mldsa.MLDSA65PrivateKey.generate,
    private_type=mldsa.MLDSA65PrivateKey,
    public_type=mldsa.MLDSA65PublicKey,
    sign=lambda k, m: k.sign(m),
    verify=lambda k, m, s: k.verify(s, m),
    deterministic=False,
)
