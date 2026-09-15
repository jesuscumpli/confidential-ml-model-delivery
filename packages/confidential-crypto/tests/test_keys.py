"""Key helpers: generation, raw/hex loading and error hygiene."""

from __future__ import annotations

from pathlib import Path

import pytest

from confidential_crypto import keys, registry
from confidential_crypto.errors import InvalidKeyError


def test_generate_key_has_cipher_size() -> None:
    cipher = registry.get_cipher("aes-256-gcm")
    assert len(keys.generate_symmetric_key(cipher)) == cipher.key_size


def test_load_raw_and_hex(tmp_path: Path) -> None:
    raw = bytes(range(32))
    (tmp_path / "raw.key").write_bytes(raw)
    (tmp_path / "hex.key").write_text(raw.hex() + "\n")
    assert keys.load_symmetric_key(tmp_path / "raw.key", 32) == raw
    assert keys.load_symmetric_key(tmp_path / "hex.key", 32) == raw


@pytest.mark.parametrize("data", [b"", b"\x00" * 31, b"\x00" * 33, b"zz" * 32])
def test_bad_key_material_rejected(data: bytes) -> None:
    with pytest.raises(InvalidKeyError) as info:
        keys.decode_symmetric_key(data, 32)
    assert not data or data.hex() not in str(info.value)


def test_missing_key_file(tmp_path: Path) -> None:
    with pytest.raises(InvalidKeyError):
        keys.load_symmetric_key(tmp_path / "missing.key", 32)


def test_fingerprint_ignores_line_endings() -> None:
    pem = b"-----BEGIN PUBLIC KEY-----\nabc\n-----END PUBLIC KEY-----\n"
    crlf = pem.replace(b"\n", b"\r\n")
    assert keys.public_key_fingerprint(pem) == keys.public_key_fingerprint(crlf)
