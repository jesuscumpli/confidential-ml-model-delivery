"""Cipher benchmark: throughput, memory, overhead, ciphertext statistics, tamper check."""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd
from confidential_crypto import artifact, registry
from confidential_crypto.ciphers.base import AeadCipher
from confidential_crypto.errors import CryptoError

from bench import metrics

DEFAULT_SIZES = (1 * metrics.MIB, 16 * metrics.MIB)


@dataclass(frozen=True)
class CipherResult:
    cipher: str
    production_safe: bool
    size_bytes: int
    encrypt_mib_s: float
    decrypt_mib_s: float
    peak_rss_mib: float
    overhead_bytes: int
    key_bytes: int
    nonce_bytes: int
    tag_bytes: int
    entropy_bits_per_byte: float
    chi_square: float
    tamper_detected: bool


def _tamper_detected(blob: bytes, key: bytes, unsafe: bool) -> bool:
    mutated = bytearray(blob)
    mutated[len(mutated) // 2] ^= 0x01
    try:
        artifact.decrypt(bytes(mutated), key, allow_unsafe=unsafe)
    except CryptoError:
        return True
    return False


def benchmark_cipher(
    cipher: AeadCipher, plaintext: bytes, *, repeats: int, measure_memory: bool
) -> CipherResult:
    key = os.urandom(cipher.key_size)
    unsafe = not cipher.production_safe
    blob = artifact.encrypt(plaintext, key, cipher)
    encrypt_s = metrics.median_seconds(lambda: artifact.encrypt(plaintext, key, cipher), repeats)
    decrypt_s = metrics.median_seconds(
        lambda: artifact.decrypt(blob, key, allow_unsafe=unsafe), repeats
    )
    peak = (
        metrics.peak_rss_mib_in_subprocess("bench.memprobe", cipher.name, str(len(plaintext)))
        if measure_memory
        else float("nan")
    )
    return CipherResult(
        cipher=cipher.name,
        production_safe=cipher.production_safe,
        size_bytes=len(plaintext),
        encrypt_mib_s=metrics.throughput_mib_s(len(plaintext), encrypt_s),
        decrypt_mib_s=metrics.throughput_mib_s(len(plaintext), decrypt_s),
        peak_rss_mib=peak,
        overhead_bytes=len(blob) - len(plaintext),
        key_bytes=cipher.key_size,
        nonce_bytes=cipher.nonce_size,
        tag_bytes=cipher.tag_size,
        entropy_bits_per_byte=metrics.shannon_entropy_bits_per_byte(blob),
        chi_square=metrics.chi_square_uniformity(blob),
        tamper_detected=_tamper_detected(blob, key, unsafe),
    )


def run(
    sizes: Sequence[int] = DEFAULT_SIZES,
    *,
    repeats: int = 5,
    artifact_path: Path | None = None,
    measure_memory: bool = True,
) -> pd.DataFrame:
    """Benchmark every available cipher (evaluation-only ones included) at each size."""
    inputs: list[bytes] = [os.urandom(size) for size in sizes]
    if artifact_path is not None:
        inputs.append(artifact_path.read_bytes())
    rows = [
        asdict(benchmark_cipher(c, data, repeats=repeats, measure_memory=measure_memory))
        for data in inputs
        for c in registry.available_ciphers(include_unsafe=True)
    ]
    return pd.DataFrame(rows)
