"""Runtime probes used by the pipeline logs."""

from __future__ import annotations

import math

from consumer.infra.metrics import MIB, peak_rss_mib, throughput_mib_s


def test_peak_rss_mib_is_positive() -> None:
    assert peak_rss_mib() > 0


def test_throughput_is_infinite_for_zero_seconds() -> None:
    assert throughput_mib_s(MIB, 0.0) == math.inf


def test_throughput_scales_with_size_and_time() -> None:
    assert throughput_mib_s(2 * MIB, 2.0) == 1.0
