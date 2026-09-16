"""Runtime probes for pipeline step logs: throughput and process peak RSS."""

from __future__ import annotations

import math

MIB = 1 << 20


def throughput_mib_s(size_bytes: int, seconds: float) -> float:
    """Average throughput in MiB/s; infinite when the step was instantaneous."""
    return (size_bytes / MIB) / seconds if seconds > 0 else math.inf


def peak_rss_mib() -> float:
    """Process high-water RSS in MiB, read from `/proc/self/status` (`VmHWM`).

    The same probe the benchmarks use: unlike `getrusage().ru_maxrss` it belongs
    to the current address space, and unlike current RSS it never decreases.
    """
    with open("/proc/self/status", encoding="ascii") as status:
        for line in status:
            if line.startswith("VmHWM:"):
                return int(line.split()[1]) / 1024
    raise RuntimeError("VmHWM not found in /proc/self/status")
