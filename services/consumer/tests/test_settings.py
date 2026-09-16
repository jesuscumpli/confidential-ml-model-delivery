"""Settings: required repo id, env parsing, secret masking, no key bytes anywhere."""

from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

from consumer.models.settings import ConsumerSettings, KeySource

TOKEN = "hf_not_a_real_token_value"  # noqa: S105 - test fixture, not a credential


def test_repo_id_is_required() -> None:
    with pytest.raises(ValidationError):
        ConsumerSettings()  # type: ignore[call-arg]


def test_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONSUMER_HUB_REPO_ID", "org/repo")
    settings = ConsumerSettings()  # type: ignore[call-arg]
    assert settings.artifact_name == "model.enc"
    assert settings.key_source is KeySource.FILE
    assert str(settings.key_path) == "/etc/model-key/key"
    assert "[MASK]" in settings.prompt


def test_token_masked_and_key_never_present(monkeypatch: pytest.MonkeyPatch, key: bytes) -> None:
    monkeypatch.setenv("CONSUMER_HUB_REPO_ID", "org/repo")
    monkeypatch.setenv("CONSUMER_KEY_SOURCE", "env")
    monkeypatch.setenv("HF_TOKEN", TOKEN)
    monkeypatch.setenv("MODEL_KEY", key.hex())
    settings = ConsumerSettings()  # type: ignore[call-arg]
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
    [{"artifact_name": "../x"}, {"top_k": 0}, {"key_source": "vault"}],
    ids=["traversal", "top_k", "key_source"],
)
def test_invalid_values(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ConsumerSettings(hub_repo_id="org/repo", **overrides)  # type: ignore[arg-type]
