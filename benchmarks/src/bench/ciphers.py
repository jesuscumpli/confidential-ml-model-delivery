"""Cipher benchmark: throughput, memory, overhead, ciphertext statistics, tamper check.

Memory discipline: one input size lives in memory at a time, only one ciphertext is
held, and the tamper check runs on a small separate sample, so the harness peak is
~3x the largest input (plaintext + ciphertext + one transient copy, the one-shot API's
own floor), not a multiple of the sum of all sizes.
"""

from __future__ import annotations

import os
import warnings
from collections.abc import Iterator, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd
import psutil
from confidential_crypto import artifact, registry
from confidential_crypto.ciphers.base import AeadCipher
from confidential_crypto.errors import CryptoError

from bench import metrics

DEFAULT_SIZES = (1 * metrics.MIB, 16 * metrics.MIB)
_TAMPER_SAMPLE = 64 * 1024
_MEMORY_FACTOR = 3  # plaintext + ciphertext + one transient copy, worst case


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


def _tamper_detected(cipher: AeadCipher, key: bytes, unsafe: bool) -> bool:
    """Size-independent property, so it is checked on a small sample."""
    mutated = bytearray(artifact.encrypt(os.urandom(_TAMPER_SAMPLE), key, cipher))
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
    size = len(plaintext)
    encrypt_s = metrics.median_seconds(lambda: artifact.encrypt(plaintext, key, cipher), repeats)
    blob = artifact.encrypt(plaintext, key, cipher)
    decrypt_s = metrics.median_seconds(
        lambda: artifact.decrypt(blob, key, allow_unsafe=unsafe), repeats
    )
    entropy = metrics.shannon_entropy_bits_per_byte(blob)
    chi_square = metrics.chi_square_uniformity(blob)
    overhead = len(blob) - size
    peak = (
        metrics.peak_rss_mib_in_subprocess("bench.memprobe", cipher.name, str(size))
        if measure_memory
        else float("nan")
    )
    return CipherResult(
        cipher=cipher.name,
        production_safe=cipher.production_safe,
        size_bytes=size,
        encrypt_mib_s=metrics.throughput_mib_s(size, encrypt_s),
        decrypt_mib_s=metrics.throughput_mib_s(size, decrypt_s),
        peak_rss_mib=peak,
        overhead_bytes=overhead,
        key_bytes=cipher.key_size,
        nonce_bytes=cipher.nonce_size,
        tag_bytes=cipher.tag_size,
        entropy_bits_per_byte=entropy,
        chi_square=chi_square,
        tamper_detected=_tamper_detected(cipher, key, unsafe),
    )


def _inputs(sizes: Sequence[int], artifact_path: Path | None) -> Iterator[bytes]:
    """Yield one input at a time; skip sizes that cannot fit with the one-shot overhead."""
    planned: list[tuple[str, int]] = [(f"{s / metrics.MIB:g} MiB random", s) for s in sizes]
    if artifact_path is not None:
        planned.append((f"artifact {artifact_path.name}", artifact_path.stat().st_size))
    for label, size in planned:
        available = psutil.virtual_memory().available
        if size * _MEMORY_FACTOR > available:
            warnings.warn(
                f"skipping {label}: needs ~{size * _MEMORY_FACTOR / metrics.MIB:.0f} MiB, "
                f"{available / metrics.MIB:.0f} MiB available",
                stacklevel=3,
            )
            continue
        if label.startswith("artifact"):
            yield artifact_path.read_bytes()  # type: ignore[union-attr]
        else:
            yield os.urandom(size)


def run(
    sizes: Sequence[int] = DEFAULT_SIZES,
    *,
    repeats: int = 5,
    artifact_path: Path | None = None,
    measure_memory: bool = True,
) -> pd.DataFrame:
    """Benchmark every available cipher (evaluation-only ones included) at each size."""
    rows = []
    for data in _inputs(sizes, artifact_path):
        for cipher in registry.available_ciphers(include_unsafe=True):
            result = benchmark_cipher(cipher, data, repeats=repeats, measure_memory=measure_memory)
            rows.append(asdict(result))
        del data
    return pd.DataFrame(rows)
