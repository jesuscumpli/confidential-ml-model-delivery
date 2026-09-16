"""Typed consumer configuration from environment variables (`CONSUMER_*`, `HF_TOKEN`).

Key bytes are never a setting: only where to find them (`key_path` / `key_env_var`,
`public_key_path`).
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from confidential_crypto import DEFAULT_SIGNER
from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class KeySource(StrEnum):
    FILE = "file"
    ENV = "env"


DEFAULT_ARTIFACT_NAME = "model.enc"
_NAME_PATTERN = r"^[A-Za-z0-9._-]+$"
SIGNATURE_SUFFIX = ".sig"


def signature_name_for(artifact_name: str) -> str:
    """`model.enc` -> `model.sig`; must match the producer's naming rule."""
    return Path(artifact_name).with_suffix(SIGNATURE_SUFFIX).name


class ConsumerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CONSUMER_", frozen=True, extra="ignore")

    hub_repo_id: str = "jesuscumpli/confidential-ml-model"
    artifact_name: str = Field(default=DEFAULT_ARTIFACT_NAME, pattern=_NAME_PATTERN)
    artifact_revision: str = "main"
    force: bool = False
    hf_token: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("HF_TOKEN", "CONSUMER_HF_TOKEN")
    )
    key_source: KeySource = KeySource.FILE
    key_path: Path = Path("var/secrets/model.key")
    key_env_var: str = "MODEL_KEY"
    verify_signature: bool = True
    public_key_path: Path = Path("var/secrets/signing.pub")
    signer: str = DEFAULT_SIGNER
    work_dir: Path | None = None
    prompt: str = "The capital of France is [MASK]."
    top_k: int = Field(default=5, ge=1, le=50)
    metrics: bool = False

    @property
    def signature_name(self) -> str:
        return signature_name_for(self.artifact_name)

    @field_validator("artifact_name")
    @classmethod
    def _artifact_name_is_not_a_signature(cls, value: str) -> str:
        if value.endswith(SIGNATURE_SUFFIX):
            raise ValueError(f"artifact name must not end with {SIGNATURE_SUFFIX}")
        return value

    def token_value(self) -> str | None:
        return None if self.hf_token is None else self.hf_token.get_secret_value()
