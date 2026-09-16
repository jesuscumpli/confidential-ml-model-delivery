"""Settings: defaults, env parsing, secret masking, no key bytes anywhere."""

from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

from consumer.models.settings import ConsumerSettings, KeySource

TOKEN = "hf_not_a_real_token_value"  # noqa: S105 - test fixture, not a credential


def test_repo_id_defaults_and_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    assert ConsumerSettings().hub_repo_id == "jesuscumpli/confidential-ml-model"
    monkeypatch.setenv("CONSUMER_HUB_REPO_ID", "org/repo")
    assert ConsumerSettings().hub_repo_id == "org/repo"


def test_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONSUMER_HUB_REPO_ID", "org/repo")
    settings = ConsumerSettings()
    assert settings.artifact_name == "model.enc"
    assert settings.force is False
    assert settings.key_source is KeySource.FILE
    assert str(settings.key_path) == "var/secrets/model.key"
    assert "[MASK]" in settings.prompt
    assert settings.metrics is False
    assert settings.verify_signature is True
    assert settings.signature_name == "model.sig"
    assert settings.signer == "ed25519"


def test_token_masked_and_key_never_present(monkeypatch: pytest.MonkeyPatch, key: bytes) -> None:
    monkeypatch.setenv("CONSUMER_HUB_REPO_ID", "org/repo")
    monkeypatch.setenv("CONSUMER_KEY_SOURCE", "env")
    monkeypatch.setenv("HF_TOKEN", TOKEN)
    monkeypatch.setenv("MODEL_KEY", key.hex())
    settings = ConsumerSettings()
    assert isinstance(settings.hf_token, SecretStr)
    for rendering in (
        str(settings),
        repr(settings),
        settings.model_dump_json(),
        str(settings.model_dump()),
    ):
        assert TOKEN not in rendering
        assert key.hex() not in rendering


@pytest.mark.parametrize(
    "overrides",
    [
        {"artifact_name": "../x"},
        {"artifact_name": "model.sig"},
        {"top_k": 0},
        {"key_source": "vault"},
    ],
    ids=["traversal", "signature_suffix", "top_k", "key_source"],
)
def test_invalid_values(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ConsumerSettings(hub_repo_id="org/repo", **overrides)  # type: ignore[arg-type]


def test_signature_name_derives_from_artifact_name() -> None:
    settings = ConsumerSettings(hub_repo_id="org/repo", artifact_name="distilbert.v2.enc")
    assert settings.signature_name == "distilbert.v2.sig"
