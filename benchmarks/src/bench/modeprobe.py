"""Subprocess entry point: one file-to-file encrypt or decrypt, print peak RSS delta in MiB.

Usage: python -m bench.modeprobe {encrypt|decrypt} MODE CIPHER KEY_FILE CHUNK SRC DST

Encrypt and decrypt run in separate interpreters because the peak is a high-water
mark: measuring both in one process would hide the decrypt peak behind the encrypt one.
"""

from __future__ import annotations

import sys
from pathlib import Path

from confidential_crypto import registry

from bench import metrics, modes


def main() -> None:
    op, mode, cipher_name, key_file, chunk, src, dst = sys.argv[1:8]
    cipher = registry.get_cipher(cipher_name, allow_unsafe=True)
    key = Path(key_file).read_bytes()
    src_path, dst_path = Path(src), Path(dst)
    # warm-up on a tiny input so backend page-in does not count
    tiny_plain, tiny_enc, tiny_dec = (
        dst_path.with_suffix(f".tiny{s}") for s in ("", ".enc", ".dec")
    )
    tiny_plain.write_bytes(b"warm-up")
    modes.encrypt_file(mode, tiny_plain, tiny_enc, key, cipher, int(chunk))
    modes.decrypt_file(mode, tiny_enc, tiny_dec, key, int(chunk))
    baseline = metrics.peak_rss_mib()
    if op == "encrypt":
        modes.encrypt_file(mode, src_path, dst_path, key, cipher, int(chunk))
    else:
        modes.decrypt_file(mode, src_path, dst_path, key, int(chunk))
    print(f"{max(0.0, metrics.peak_rss_mib() - baseline):.2f}")
    for path in (tiny_plain, tiny_enc, tiny_dec, dst_path):
        path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
