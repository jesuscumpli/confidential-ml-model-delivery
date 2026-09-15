"""Key files: creation permissions, overwrite refusal, loading, no leakage."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest
from confidential_crypto import get_cipher

from producer.errors import ConfigError
from producer.keys import read_key, write_new_key

CIPHER = get_cipher("aes-256-gcm")


def test_write_new_key_creates_owner_only_raw_key(tmp_path: Path) -> None:
    path = tmp_path / "keys" / "model.key"
    write_new_key(path, CIPHER)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert len(path.read_bytes()) == CIPHER.key_size
    assert read_key(path, CIPHER) == path.read_bytes()


def test_write_new_key_refuses_overwrite(tmp_path: Path) -> None:
    path = tmp_path / "model.key"
    path.write_bytes(b"existing")
    with pytest.raises(ConfigError, match="refusing to overwrite"):
        write_new_key(path, CIPHER)
    assert path.read_bytes() == b"existing"


def test_read_key_accepts_hex(tmp_path: Path) -> None:
    raw = os.urandom(CIPHER.key_size)
    path = tmp_path / "model.key"
    path.write_text(raw.hex() + "\n")
    assert read_key(path, CIPHER) == raw


def test_read_key_wrong_length_has_no_key_bytes_in_message(tmp_path: Path) -> None:
    raw = os.urandom(20)
    path = tmp_path / "model.key"
    path.write_bytes(raw)
    with pytest.raises(ConfigError) as info:
        read_key(path, CIPHER)
    assert raw.hex() not in str(info.value)
    assert repr(raw) not in str(info.value)


def test_read_key_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="cannot read key file"):
        read_key(tmp_path / "missing.key", CIPHER)
