"""Typed producer configuration from environment variables (`PRODUCER_*`, `HF_TOKEN`).

The decryption key is never a setting: only its path is, and the bytes are read by
`producer.infra.keys` at the moment they are needed.
"""

from __future__ import annotations

from pathlib import Path

from confidential_crypto import DEFAULT_CIPHER
from confidential_crypto.artifact import DEFAULT_CHUNK_SIZE
from confidential_crypto.format import MAX_CHUNK_SIZE, MIN_CHUNK_SIZE
from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from producer.models.encryption import EncryptionMode

DEFAULT_MODEL_ID = "prajjwal1/bert-tiny"
DEFAULT_ARTIFACT_NAME = "model.enc"


class ProducerSettings(BaseSettings):
    """Environment beats defaults; the CLI passes explicit overrides as keyword arguments."""

    model_config = SettingsConfigDict(env_prefix="PRODUCER_", frozen=True, extra="ignore")

    model_id: str = DEFAULT_MODEL_ID
    model_revision: str = "main"
    hub_repo_id: str | None = "jesuscumpli/confidential-ml-model"
    hf_token: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("HF_TOKEN", "PRODUCER_HF_TOKEN")
    )
    private_repo: bool = True
    artifact_name: str = Field(default=DEFAULT_ARTIFACT_NAME, pattern=r"^[A-Za-z0-9._-]+$")
    key_path: Path | None = None
    work_dir: Path = Path("var/artifacts")
    cipher: str = DEFAULT_CIPHER
    encryption_mode: EncryptionMode = EncryptionMode.CHUNKED
    chunk_size: int = Field(default=DEFAULT_CHUNK_SIZE, ge=MIN_CHUNK_SIZE, le=MAX_CHUNK_SIZE)

    @property
    def model_dir(self) -> Path:
        return self.work_dir / "model"

    @property
    def package_path(self) -> Path:
        return self.work_dir / "model.tar"

    @property
    def artifact_path(self) -> Path:
        """Encrypted output lives in its own directory: nothing else is ever uploaded."""
        return self.work_dir / "upload" / self.artifact_name

    def token_value(self) -> str | None:
        return None if self.hf_token is None else self.hf_token.get_secret_value()
