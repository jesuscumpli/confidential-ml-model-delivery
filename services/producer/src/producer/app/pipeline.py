"""Producer steps: package → encrypt → publish. Each step is a plain function.

Logs mention paths, sizes and commits only; never key bytes or tokens.
"""

from __future__ import annotations

import logging
from pathlib import Path

from confidential_crypto import get_cipher
from confidential_crypto.ciphers.base import AeadCipher
from confidential_crypto.errors import CryptoError, FormatError
from confidential_crypto.format import ArtifactHeader

from producer.core.encryption import encrypt_file
from producer.core.errors import ConfigError, HubError
from producer.core.packaging import package_model
from producer.core.ports import HubClient
from producer.infra.keys import read_key
from producer.models.manifest import Manifest
from producer.models.settings import ProducerSettings

log = logging.getLogger(__name__)


def run_package(settings: ProducerSettings, client: HubClient) -> Manifest:
    """Download the model and write the deterministic plaintext package."""
    log.info("downloading %s@%s", settings.model_id, settings.model_revision)
    revision = client.snapshot(settings.model_id, settings.model_revision, settings.model_dir)
    manifest = package_model(settings.model_dir, settings.model_id, revision, settings.package_path)
    log.info(
        "packaged %d files (%d bytes) at %s",
        len(manifest.files),
        settings.package_path.stat().st_size,
        settings.package_path,
    )
    return manifest


def run_encrypt(settings: ProducerSettings, package_path: Path | None = None) -> Path:
    """Encrypt the package with the key read from `settings.key_path`."""
    src = package_path or settings.package_path
    if not src.is_file():
        raise ConfigError(f"package not found: {src} (run `producer package` first)")
    cipher = resolve_cipher(settings.cipher)
    key = read_key(_require_key_path(settings), cipher)
    encrypt_file(
        src,
        settings.artifact_path,
        key,
        cipher,
        mode=settings.encryption_mode,
        chunk_size=settings.chunk_size,
    )
    log.info(
        "encrypted %s -> %s (%s, %s)",
        src,
        settings.artifact_path,
        cipher.name,
        settings.encryption_mode.value,
    )
    return settings.artifact_path


def run_publish(
    settings: ProducerSettings, client: HubClient, artifact_path: Path | None = None
) -> str:
    """Upload exactly one encrypted artifact; anything else is refused before upload."""
    src = artifact_path or settings.artifact_path
    repo_id = settings.hub_repo_id
    if repo_id is None:
        raise ConfigError("hub repository id is required (PRODUCER_HUB_REPO_ID or --repo-id)")
    _require_encrypted(src)
    client.ensure_repo(repo_id, private=settings.private_repo)
    commit = client.upload(src, repo_id, settings.artifact_name)
    log.info("published %s to %s (commit %s)", settings.artifact_name, repo_id, commit)
    return commit


def run_all(settings: ProducerSettings, client: HubClient) -> str:
    run_package(settings, client)
    artifact_path = run_encrypt(settings)
    return run_publish(settings, client, artifact_path)


def resolve_cipher(name: str) -> AeadCipher:
    try:
        return get_cipher(name)
    except CryptoError as exc:
        raise ConfigError(str(exc)) from exc


def _require_key_path(settings: ProducerSettings) -> Path:
    if settings.key_path is None:
        raise ConfigError("key path is required (PRODUCER_KEY_PATH or --key-path)")
    return settings.key_path


def _require_encrypted(path: Path) -> None:
    if not path.is_file():
        raise ConfigError(f"artifact not found: {path} (run `producer encrypt` first)")
    with path.open("rb") as stream:
        head = stream.read(ArtifactHeader.max_size())
    try:
        ArtifactHeader.decode(head)
    except FormatError as exc:
        raise HubError(f"refusing to publish {path.name}: not an encrypted artifact") from exc
