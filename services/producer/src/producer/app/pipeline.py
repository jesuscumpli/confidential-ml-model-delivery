"""Producer steps: package → encrypt → sign → publish. Each step is a plain function.

Logs mention paths, sizes and commits only; never key bytes or tokens.
"""

from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path

from confidential_crypto import get_cipher, get_signer
from confidential_crypto.ciphers.base import AeadCipher
from confidential_crypto.errors import CryptoError, FormatError
from confidential_crypto.format import ArtifactHeader, SignatureEnvelope
from confidential_crypto.signers.base import SignatureScheme

from producer.core.encryption import encrypt_file
from producer.core.errors import ConfigError, HubError
from producer.core.packaging import package_model
from producer.core.ports import HubClient
from producer.core.signing import sign_file
from producer.infra.keys import read_key, read_signing_key
from producer.infra.metrics import peak_rss_mib, throughput_mib_s
from producer.models.manifest import Manifest
from producer.models.settings import ProducerSettings

log = logging.getLogger(__name__)


def run_package(settings: ProducerSettings, client: HubClient) -> Manifest:
    """Download the model and write the deterministic plaintext package."""
    log.info("downloading %s@%s", settings.model_id, settings.model_revision)
    _reset_dir(settings.model_dir)
    revision = client.snapshot(settings.model_id, settings.model_revision, settings.model_dir)
    manifest = package_model(settings.model_dir, settings.model_id, revision, settings.package_path)
    log.info(
        "packaged %d files (%d bytes) at %s",
        len(manifest.files),
        settings.package_path.stat().st_size,
        settings.package_path,
    )
    return manifest


def _reset_dir(path: Path) -> None:
    """Empty the download directory: `snapshot_download` merges into it, so a previous
    model's files would otherwise be packaged alongside the new one."""
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def run_encrypt(settings: ProducerSettings, package_path: Path | None = None) -> Path:
    """Encrypt the package with the key read from `settings.key_path`."""
    src = package_path or settings.package_path
    if not src.is_file():
        raise ConfigError(f"package not found: {src} (run `producer package` first)")
    cipher = resolve_cipher(settings.cipher)
    key = read_key(_require_key_path(settings), cipher)
    started = time.perf_counter()
    encrypt_file(
        src,
        settings.artifact_path,
        key,
        cipher,
        mode=settings.encryption_mode,
        chunk_size=settings.chunk_size,
    )
    elapsed = time.perf_counter() - started
    log.info(
        "encrypted %s -> %s (%s, %s)%s",
        src,
        settings.artifact_path,
        cipher.name,
        settings.encryption_mode.value,
        _metrics_suffix(src.stat().st_size, elapsed) if settings.metrics else "",
    )
    return settings.artifact_path


def _metrics_suffix(size_bytes: int, elapsed: float) -> str:
    """Elapsed time, throughput and process peak RSS, appended when metrics are on."""
    return (
        f" in {elapsed:.2f}s "
        f"({throughput_mib_s(size_bytes, elapsed):.1f} MiB/s, peak RSS {peak_rss_mib():.1f} MiB)"
    )


def run_sign(settings: ProducerSettings, artifact_path: Path | None = None) -> Path:
    """Sign the encrypted artifact with the private key at `settings.signing_key_path`."""
    src = artifact_path or settings.artifact_path
    _require_encrypted(src)
    scheme = resolve_signer(settings.signer)
    private_key = read_signing_key(_require_signing_key_path(settings))
    sign_file(src, settings.signature_path, private_key, scheme)
    log.info("signed %s -> %s (%s)", src, settings.signature_path, scheme.name)
    return settings.signature_path


def run_publish(
    settings: ProducerSettings, client: HubClient, artifact_path: Path | None = None
) -> str:
    """Upload the encrypted artifact and its signature; anything else is refused.

    With `sign` enabled (the default) a missing signature aborts the publish, so an
    unsigned artifact never reaches the Hub by accident.
    """
    src = artifact_path or settings.artifact_path
    repo_id = settings.hub_repo_id
    if repo_id is None:
        raise ConfigError("hub repository id is required (PRODUCER_HUB_REPO_ID or --repo-id)")
    _require_encrypted(src)
    files = {settings.artifact_name: src}
    if settings.sign:
        _require_signature(settings.signature_path)
        files[settings.signature_name] = settings.signature_path
    else:
        log.warning("publishing %s without a signature (Layer 2 disabled)", settings.artifact_name)
    client.ensure_repo(repo_id, private=settings.private_repo)
    commit = client.upload(files, repo_id)
    log.info("published %s to %s (commit %s)", ", ".join(files), repo_id, commit)
    return commit


def run_all(settings: ProducerSettings, client: HubClient) -> str:
    run_package(settings, client)
    artifact_path = run_encrypt(settings)
    if settings.sign:
        run_sign(settings, artifact_path)
    return run_publish(settings, client, artifact_path)


def resolve_cipher(name: str) -> AeadCipher:
    try:
        return get_cipher(name)
    except CryptoError as exc:
        raise ConfigError(str(exc)) from exc


def resolve_signer(name: str) -> SignatureScheme:
    try:
        return get_signer(name)
    except CryptoError as exc:
        raise ConfigError(str(exc)) from exc


def _require_key_path(settings: ProducerSettings) -> Path:
    if settings.key_path is None:
        raise ConfigError("key path is required (PRODUCER_KEY_PATH or --key-path)")
    return settings.key_path


def _require_signing_key_path(settings: ProducerSettings) -> Path:
    if settings.signing_key_path is None:
        raise ConfigError(
            "signing key path is required (PRODUCER_SIGNING_KEY_PATH or --signing-key-path)"
        )
    return settings.signing_key_path


def _require_signature(path: Path) -> None:
    if not path.is_file():
        raise ConfigError(f"signature not found: {path} (run `producer sign` first, or --no-sign)")
    try:
        SignatureEnvelope.decode(path.read_bytes())
    except FormatError as exc:
        raise HubError(f"refusing to publish {path.name}: not a signature envelope") from exc


def _require_encrypted(path: Path) -> None:
    if not path.is_file():
        raise ConfigError(f"artifact not found: {path} (run `producer encrypt` first)")
    with path.open("rb") as stream:
        head = stream.read(ArtifactHeader.max_size())
    try:
        ArtifactHeader.decode(head)
    except FormatError as exc:
        raise HubError(f"refusing to publish {path.name}: not an encrypted artifact") from exc
