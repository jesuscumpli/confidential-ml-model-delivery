"""Measurement helpers: timing, ciphertext statistics and peak memory."""

from __future__ import annotations

import math
import statistics
import subprocess
import sys
import time
from collections.abc import Callable

import numpy as np

MIB = 1 << 20


def median_seconds(fn: Callable[[], object], repeats: int) -> float:
    """Median wall-clock time of `fn` over `repeats` runs after one warm-up call."""
    fn()
    samples = []
    for _ in range(repeats):
        start = time.perf_counter()
        fn()
        samples.append(time.perf_counter() - start)
    return statistics.median(samples)


def throughput_mib_s(size_bytes: int, seconds: float) -> float:
    return (size_bytes / MIB) / seconds if seconds > 0 else math.inf


def _byte_histogram(data: bytes) -> np.ndarray[tuple[int], np.dtype[np.int64]]:
    """Single C-speed pass over a zero-copy view; no Python-level iteration."""
    view = np.frombuffer(data, dtype=np.uint8)
    return np.bincount(view, minlength=256)


def shannon_entropy_bits_per_byte(data: bytes) -> float:
    """Entropy of the byte distribution; 8.0 is the maximum for uniform bytes."""
    if not data:
        return 0.0
    probabilities = _byte_histogram(data) / len(data)
    nonzero = probabilities[probabilities > 0]
    return float(-(nonzero * np.log2(nonzero)).sum())


def chi_square_uniformity(data: bytes) -> float:
    """Chi-square statistic against a uniform byte distribution (255 degrees of freedom).

    Values near 255 are consistent with uniform bytes; a healthy ciphertext lands
    roughly in the 210-310 range for large samples.
    """
    if not data:
        return 0.0
    expected = len(data) / 256
    return float((((_byte_histogram(data) - expected) ** 2) / expected).sum())


def peak_rss_mib() -> float:
    """High-water RSS of this process from /proc, in MiB.

    Not `getrusage().ru_maxrss`: on Linux an exec'd child inherits the parent's RSS
    at fork time in that counter, so a large parent (a notebook kernel holding data)
    would hide the child's own peak. `VmHWM` belongs to the current address space only.
    """
    with open("/proc/self/status", encoding="ascii") as status:
        for line in status:
            if line.startswith("VmHWM:"):
                return int(line.split()[1]) / 1024
    raise RuntimeError("VmHWM not found in /proc/self/status")


def peak_rss_mib_in_subprocess(module: str, *args: str) -> float:
    """Run `python -m module args...` and return its peak RSS in MiB.

    Peak memory is measured in a fresh interpreter so allocations by the native
    backends (OpenSSL, libsodium) are included and runs do not contaminate each other.
    """
    result = subprocess.run(  # noqa: S603 - fixed interpreter and module, no shell
        [sys.executable, "-m", module, *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(result.stdout.strip().splitlines()[-1])
