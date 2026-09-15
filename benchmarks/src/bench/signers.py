"""Signature benchmark: key generation, signing and verification time, sizes."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass

import pandas as pd
from confidential_crypto import registry
from confidential_crypto.signers.base import SignatureScheme

from bench import metrics

DEFAULT_MESSAGE_SIZE = 16 * metrics.MIB


@dataclass(frozen=True)
class SignerResult:
    scheme: str
    production_safe: bool
    message_bytes: int
    keygen_ms: float
    sign_ms: float
    verify_ms: float
    public_key_pem_bytes: int
    signature_bytes: int
    deterministic: bool


def benchmark_signer(scheme: SignatureScheme, message: bytes, *, repeats: int) -> SignerResult:
    keygen_s = metrics.median_seconds(scheme.generate_private_key, max(1, repeats // 2))
    private_key = scheme.generate_private_key()
    public_key = scheme.public_key_from_private(private_key)
    signature = scheme.sign(private_key, message)
    sign_s = metrics.median_seconds(lambda: scheme.sign(private_key, message), repeats)
    verify_s = metrics.median_seconds(
        lambda: scheme.verify(public_key, message, signature), repeats
    )
    return SignerResult(
        scheme=scheme.name,
        production_safe=scheme.production_safe,
        message_bytes=len(message),
        keygen_ms=keygen_s * 1000,
        sign_ms=sign_s * 1000,
        verify_ms=verify_s * 1000,
        public_key_pem_bytes=len(public_key),
        signature_bytes=len(signature),
        deterministic=scheme.deterministic,
    )


def run(message_size: int = DEFAULT_MESSAGE_SIZE, *, repeats: int = 5) -> pd.DataFrame:
    message = os.urandom(message_size)
    rows = [
        asdict(benchmark_signer(s, message, repeats=repeats))
        for s in registry.available_signers(include_unsafe=True)
    ]
    return pd.DataFrame(rows)
