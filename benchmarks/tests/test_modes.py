"""Mode benchmark: all modes round-trip file to file; streaming-gcm shows its hazard."""

from __future__ import annotations

import io
import os
from pathlib import Path

import pytest
from confidential_crypto import artifact, registry
from confidential_crypto.errors import DecryptionError

from bench import modes, streaming_gcm
from bench.metrics import MIB

CHUNK = 64 * 1024


@pytest.mark.parametrize("mode", modes.MODES)
def test_round_trip_file_to_file(tmp_path: Path, mode: str) -> None:
    cipher = registry.get_cipher("aes-256-gcm")
    key = os.urandom(cipher.key_size)
    plain, enc, dec = tmp_path / "p", tmp_path / "e", tmp_path / "d"
    plain.write_bytes(os.urandom(3 * CHUNK + 11))
    modes.encrypt_file(mode, plain, enc, key, cipher, CHUNK)
    modes.decrypt_file(mode, enc, dec, key, CHUNK)
    assert dec.read_bytes() == plain.read_bytes()


def test_streaming_gcm_bytes_are_one_shot_compatible() -> None:
    """Same wire format: the shared package decrypts what the streaming encryptor wrote."""
    key = os.urandom(32)
    data = os.urandom(3 * CHUNK + 5)
    out = io.BytesIO()
    streaming_gcm.encrypt_stream(io.BytesIO(data), out, key, chunk_size=CHUNK)
    assert artifact.decrypt(out.getvalue(), key) == data


def test_streaming_gcm_releases_plaintext_before_authentication() -> None:
    """The hazard the mode table documents: output is written, then the tag check fails."""
    key = os.urandom(32)
    data = os.urandom(3 * CHUNK)
    blob = bytearray(artifact.encrypt(data, key, registry.get_cipher("aes-256-gcm")))
    blob[-1] ^= 0x01  # corrupt the tag
    out = io.BytesIO()
    with pytest.raises(DecryptionError):
        streaming_gcm.decrypt_stream(io.BytesIO(bytes(blob)), out, key, chunk_size=CHUNK)
    assert out.getvalue() == data  # every plaintext byte was already emitted


def test_run_produces_one_row_per_supported_mode() -> None:
    frame = modes.run(
        [MIB], ciphers=["aes-256-gcm", "chacha20-poly1305"], chunk=CHUNK, repeats=1,
        measure_memory=False,
    )  # fmt: skip
    assert len(frame) == 5  # 3 modes for aes, 2 for chacha (no streaming-gcm)
    assert (frame["encrypt_mib_s"] > 0).all()
    chunked = frame[frame["mode"] == "chunked"]
    one_shot = frame[frame["mode"] == "one-shot"]
    assert (chunked["overhead_bytes"] > one_shot["overhead_bytes"].max()).all()  # one tag per chunk
    assert frame.loc[frame["mode"] == "streaming-gcm", "plaintext_released_before_auth"].all()
