"""Typed consumer configuration from environment variables (`CONSUMER_*`, `HF_TOKEN`).

Key bytes are never a setting: only where to find them (`key_path` / `key_env_var`).
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class KeySource(StrEnum):
    FILE = "file"
    ENV = "env"


DEFAULT_ARTIFACT_NAME = "model.enc"


class ConsumerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CONSUMER_", frozen=True, extra="ignore")

    hub_repo_id: str
    artifact_name: str = Field(default=DEFAULT_ARTIFACT_NAME, pattern=r"^[A-Za-z0-9._-]+$")
    artifact_revision: str = "main"
    hf_token: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("HF_TOKEN", "CONSUMER_HF_TOKEN")
    )
    key_source: KeySource = KeySource.FILE
    key_path: Path = Path("/etc/model-key/key")
    key_env_var: str = "MODEL_KEY"
    work_dir: Path | None = None
    prompt: str = "The capital of France is [MASK]."
    top_k: int = Field(default=5, ge=1, le=50)

    def token_value(self) -> str | None:
        return None if self.hf_token is None else self.hf_token.get_secret_value()
