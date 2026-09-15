"""Statistics helpers must behave on known distributions."""

from __future__ import annotations

import os

from bench import metrics


def test_entropy_bounds() -> None:
    assert metrics.shannon_entropy_bits_per_byte(b"") == 0.0
    assert metrics.shannon_entropy_bits_per_byte(b"\x00" * 1000) == 0.0
    assert metrics.shannon_entropy_bits_per_byte(bytes(range(256)) * 4) == 8.0
    assert metrics.shannon_entropy_bits_per_byte(os.urandom(1 << 16)) > 7.99


def test_chi_square_distinguishes_uniform_from_constant() -> None:
    uniform = metrics.chi_square_uniformity(bytes(range(256)) * 16)
    constant = metrics.chi_square_uniformity(b"\x00" * 4096)
    assert uniform == 0.0
    assert constant > 100_000


def test_throughput() -> None:
    assert metrics.throughput_mib_s(metrics.MIB, 1.0) == 1.0
    assert metrics.throughput_mib_s(metrics.MIB, 0.0) == float("inf")


def test_median_seconds_runs_function() -> None:
    calls = 0

    def fn() -> None:
        nonlocal calls
        calls += 1

    assert metrics.median_seconds(fn, repeats=3) >= 0.0
    assert calls == 4  # one warm-up plus three measured runs


def test_peak_rss_probe_scales_with_input() -> None:
    small = metrics.peak_rss_mib_in_subprocess("bench.memprobe", "aes-256-gcm", str(metrics.MIB))
    large = metrics.peak_rss_mib_in_subprocess(
        "bench.memprobe", "aes-256-gcm", str(32 * metrics.MIB)
    )
    assert large - small > 31  # at least the extra plaintext, whatever the copies cost
