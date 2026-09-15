"""Encryption mode benchmark: one-shot (v1) vs chunked (v2) vs streaming GCM (v1 bytes).

All modes run file-to-file so the comparison reflects what producer and consumer
actually do. Memory is measured per (mode, cipher, size) in a subprocess.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd
from confidential_crypto import artifact, registry
from confidential_crypto.ciphers.base import AeadCipher

from bench import metrics, streaming_gcm

MODES = ("one-shot", "chunked", "streaming-gcm")
DEFAULT_CHUNK = artifact.DEFAULT_CHUNK_SIZE
DEFAULT_SIZES = (16 * metrics.MIB, 64 * metrics.MIB, 256 * metrics.MIB)


@dataclass(frozen=True)
class ModeResult:
    mode: str
    cipher: str
    size_bytes: int
    chunk_bytes: int
    encrypt_mib_s: float
    decrypt_mib_s: float
    peak_rss_encrypt_mib: float
    peak_rss_decrypt_mib: float
    overhead_bytes: int
    plaintext_released_before_auth: bool


def encrypt_file(
    mode: str, src: Path, dst: Path, key: bytes, cipher: AeadCipher, chunk: int
) -> None:
    if mode == "one-shot":
        header, body = artifact.encrypt_parts(src.read_bytes(), key, cipher)
        with dst.open("wb") as out:
            out.write(header)
            out.write(body)
    elif mode == "chunked":
        with src.open("rb") as inp, dst.open("wb") as out:
            artifact.encrypt_stream(inp, out, key, cipher, chunk_size=chunk)
    elif mode == "streaming-gcm":
        with src.open("rb") as inp, dst.open("wb") as out:
            streaming_gcm.encrypt_stream(inp, out, key, chunk_size=chunk)
    else:
        raise ValueError(f"unknown mode {mode}")


def decrypt_file(mode: str, src: Path, dst: Path, key: bytes, chunk: int) -> None:
    unsafe = True  # evaluation covers non-production ciphers too
    if mode == "one-shot":
        dst.write_bytes(artifact.decrypt(src.read_bytes(), key, allow_unsafe=unsafe))
    elif mode == "chunked":
        with src.open("rb") as inp, dst.open("wb") as out:
            artifact.decrypt_stream(inp, out, key, allow_unsafe=unsafe)
    elif mode == "streaming-gcm":
        with src.open("rb") as inp, dst.open("wb") as out:
            streaming_gcm.decrypt_stream(inp, out, key, chunk_size=chunk)
    else:
        raise ValueError(f"unknown mode {mode}")


def supports(mode: str, cipher: AeadCipher) -> bool:
    return mode != "streaming-gcm" or cipher.name == "aes-256-gcm"


def benchmark_mode(
    mode: str,
    cipher: AeadCipher,
    plain: Path,
    workdir: Path,
    *,
    chunk: int,
    repeats: int,
    measure_memory: bool,
) -> ModeResult:
    key = os.urandom(cipher.key_size)
    size = plain.stat().st_size
    enc, dec = workdir / "artifact.enc", workdir / "artifact.dec"
    encrypt_s = metrics.median_seconds(
        lambda: encrypt_file(mode, plain, enc, key, cipher, chunk), repeats
    )
    decrypt_s = metrics.median_seconds(lambda: decrypt_file(mode, enc, dec, key, chunk), repeats)
    if dec.read_bytes() != plain.read_bytes():
        raise RuntimeError(f"{mode}/{cipher.name}: round-trip mismatch")
    peak_enc = peak_dec = float("nan")
    if measure_memory:
        key_file = workdir / "bench.key"  # throwaway benchmark key, never a real one
        key_file.write_bytes(key)
        key_file.chmod(0o600)
        args = (mode, cipher.name, str(key_file), str(chunk))
        peak_enc = metrics.peak_rss_mib_in_subprocess(
            "bench.modeprobe", "encrypt", *args, str(plain), str(workdir / "probe.enc")
        )
        peak_dec = metrics.peak_rss_mib_in_subprocess(
            "bench.modeprobe", "decrypt", *args, str(enc), str(workdir / "probe.dec")
        )
    return ModeResult(
        mode=mode,
        cipher=cipher.name,
        size_bytes=size,
        chunk_bytes=chunk,
        encrypt_mib_s=metrics.throughput_mib_s(size, encrypt_s),
        decrypt_mib_s=metrics.throughput_mib_s(size, decrypt_s),
        peak_rss_encrypt_mib=peak_enc,
        peak_rss_decrypt_mib=peak_dec,
        overhead_bytes=enc.stat().st_size - size,
        plaintext_released_before_auth=mode == "streaming-gcm",
    )


def run(
    sizes: Sequence[int] = DEFAULT_SIZES,
    *,
    ciphers: Sequence[str] = ("aes-256-gcm", "chacha20-poly1305"),
    chunk: int = DEFAULT_CHUNK,
    repeats: int = 3,
    artifact_path: Path | None = None,
    measure_memory: bool = True,
) -> pd.DataFrame:
    """Compare modes for the given ciphers at each size; inputs live on disk, one at a time."""
    selected = [registry.get_cipher(name, allow_unsafe=True) for name in ciphers]
    rows = []
    with tempfile.TemporaryDirectory(prefix="bench-modes-") as tmp:
        workdir = Path(tmp)
        plain = workdir / "plain.bin"
        inputs: list[tuple[int, Path | None]] = [(s, None) for s in sizes]
        if artifact_path is not None:
            inputs.append((artifact_path.stat().st_size, artifact_path))
        for size, source in inputs:
            if source is None:
                _write_random(plain, size)
                source = plain
            for cipher in selected:
                for mode in MODES:
                    if not supports(mode, cipher):
                        continue
                    result = benchmark_mode(
                        mode, cipher, source, workdir,
                        chunk=chunk, repeats=repeats, measure_memory=measure_memory,
                    )  # fmt: skip
                    rows.append(asdict(result))
    return pd.DataFrame(rows)


def _write_random(path: Path, size: int, block: int = 8 * metrics.MIB) -> None:
    with path.open("wb") as out:
        remaining = size
        while remaining > 0:
            out.write(os.urandom(min(block, remaining)))
            remaining -= min(block, remaining)
