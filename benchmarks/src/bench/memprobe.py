"""Subprocess entry point: encrypt+decrypt once and print the peak RSS delta in MiB.

The delta covers plaintext, ciphertext and decrypted copy, i.e. the working set a
one-shot in-memory design needs for an artifact of the given size.

Invoked by `metrics.peak_rss_mib_in_subprocess`; not meant to be called directly.
"""

from __future__ import annotations

import os
import resource
import sys

from confidential_crypto import artifact, registry


def _maxrss_mib() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def main() -> None:
    cipher_name, size = sys.argv[1], int(sys.argv[2])
    cipher = registry.get_cipher(cipher_name, allow_unsafe=True)
    key = os.urandom(cipher.key_size)
    artifact.decrypt(artifact.encrypt(b"warm-up", key, cipher), key, allow_unsafe=True)
    baseline = _maxrss_mib()  # after backend page-in, before the plaintext
    plaintext = os.urandom(size)
    blob = artifact.encrypt(plaintext, key, cipher)
    restored = artifact.decrypt(blob, key, allow_unsafe=True)
    if restored != plaintext:
        raise SystemExit("round-trip mismatch")
    print(f"{_maxrss_mib() - baseline:.2f}")


if __name__ == "__main__":
    main()
