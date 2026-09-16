"""Key providers: file (mounted Secret), environment (dev only), CDH stub."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from consumer.core.errors import ConfigError
from consumer.infra.keys import CdhKeyProvider, EnvKeyProvider, FileKeyProvider


def test_file_provider_reads_raw_and_hex(tmp_path: Path, key: bytes) -> None:
    (tmp_path / "raw").write_bytes(key)
    (tmp_path / "hex").write_text(key.hex() + "\n")
    assert FileKeyProvider(tmp_path / "raw").get_key(32) == key
    assert FileKeyProvider(tmp_path / "hex").get_key(32) == key


def test_file_provider_missing_secret(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="cannot read key file"):
        FileKeyProvider(tmp_path / "missing").get_key(32)


def test_file_provider_wrong_length_hides_bytes(tmp_path: Path) -> None:
    short = os.urandom(12)
    (tmp_path / "key").write_bytes(short)
    with pytest.raises(ConfigError) as info:
        FileKeyProvider(tmp_path / "key").get_key(32)
    assert short.hex() not in str(info.value) and repr(short) not in str(info.value)


def test_env_provider(monkeypatch: pytest.MonkeyPatch, key: bytes) -> None:
    monkeypatch.setenv("MODEL_KEY", key.hex())
    assert EnvKeyProvider("MODEL_KEY").get_key(32) == key


def test_env_provider_unset() -> None:
    with pytest.raises(ConfigError, match="not set"):
        EnvKeyProvider("MODEL_KEY").get_key(32)


def test_cdh_provider_is_a_documented_stub() -> None:
    with pytest.raises(ConfigError, match="Layer 3"):
        CdhKeyProvider("default/model-key/1").get_key(32)
