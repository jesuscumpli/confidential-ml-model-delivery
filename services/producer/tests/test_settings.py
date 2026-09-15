"""Settings: environment parsing, validation and secret masking."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr, ValidationError

from producer.encrypt import EncryptionMode
from producer.settings import ProducerSettings

TOKEN = "hf_not_a_real_token_value"  # noqa: S105 - test fixture, not a credential


def test_defaults_are_chunked_aes_gcm() -> None:
    settings = ProducerSettings()
    assert settings.cipher == "aes-256-gcm"
    assert settings.encryption_mode is EncryptionMode.CHUNKED
    assert settings.artifact_name == "model.enc"
    assert settings.hf_token is None
    assert settings.artifact_path == Path("artifacts/upload/model.enc")


def test_environment_is_read(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRODUCER_MODEL_ID", "org/other")
    monkeypatch.setenv("PRODUCER_ENCRYPTION_MODE", "one-shot")
    monkeypatch.setenv("PRODUCER_KEY_PATH", "/keys/model.key")
    monkeypatch.setenv("HF_TOKEN", TOKEN)
    settings = ProducerSettings()
    assert settings.model_id == "org/other"
    assert settings.encryption_mode is EncryptionMode.ONE_SHOT
    assert settings.key_path == Path("/keys/model.key")
    assert isinstance(settings.hf_token, SecretStr)
    assert settings.token_value() == TOKEN


def test_explicit_arguments_override_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRODUCER_MODEL_ID", "org/env")
    assert ProducerSettings(model_id="org/arg").model_id == "org/arg"


def test_token_is_masked_everywhere(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HF_TOKEN", TOKEN)
    settings = ProducerSettings()
    for rendering in (str(settings), repr(settings), settings.model_dump_json()):
        assert TOKEN not in rendering


@pytest.mark.parametrize(
    "overrides",
    [
        {"encryption_mode": "streaming"},
        {"chunk_size": 1},
        {"artifact_name": "../model.enc"},
        {"artifact_name": "dir/model.enc"},
    ],
    ids=["mode", "chunk-size", "traversal", "nested"],
)
def test_invalid_values_are_rejected(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        ProducerSettings(**overrides)


def test_settings_are_immutable() -> None:
    settings = ProducerSettings()
    with pytest.raises(ValidationError):
        settings.model_id = "x"
