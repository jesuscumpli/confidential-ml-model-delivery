"""Consumer flow: download → verify (Layer 2) → decrypt (Layer 1) → restore → load → infer.

Order is enforced by the types: `decrypt_file` only accepts the `VerifiedArtifact`
that `verify_file` returns, so no decryption key is read before the signature
checked out. The plaintext package only exists inside the private work directory;
the Hub download (ciphertext and signature) stays in the Hub cache, which may live
on ordinary disk because it holds nothing secret.
"""

from __future__ import annotations

import logging
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from confidential_crypto import get_signer, registry
from confidential_crypto.errors import CryptoError
from confidential_crypto.signers.base import SignatureScheme

from consumer.core.decrypt import decrypt_file
from consumer.core.errors import ConfigError
from consumer.core.extract import restore_package
from consumer.core.ports import ArtifactSource, KeyProvider
from consumer.core.verify import VerifiedArtifact, unverified, verify_file
from consumer.infra.inference import fill_mask, load_model
from consumer.infra.keys import EnvKeyProvider, FileKeyProvider, read_public_key
from consumer.infra.metrics import peak_rss_mib, throughput_mib_s
from consumer.models.inference import Prediction
from consumer.models.settings import ConsumerSettings, KeySource

log = logging.getLogger(__name__)


def run(
    settings: ConsumerSettings, source: ArtifactSource, provider: KeyProvider
) -> list[Prediction]:
    with _work_dir(settings.work_dir) as work:
        artifact_path = source.fetch(
            settings.hub_repo_id,
            settings.artifact_name,
            settings.artifact_revision,
            force=settings.force,
        )
        log.info("artifact %s (%d bytes)", settings.artifact_name, artifact_path.stat().st_size)
        verified = _verify(settings, source, artifact_path)
        package_path = work / "model.tar"
        started = time.perf_counter()
        header = decrypt_file(verified, package_path, provider)
        elapsed = time.perf_counter() - started
        log.info(
            "decrypted artifact to plaintext package (%d bytes, %s, %s)%s",
            package_path.stat().st_size,
            registry.cipher_from_id(header.cipher_id).name,
            "chunked" if header.chunked else "one-shot",
            _metrics_suffix(artifact_path.stat().st_size, elapsed) if settings.metrics else "",
        )
        model_dir = work / "model"
        manifest = restore_package(package_path, model_dir)
        # The tar is plaintext too: drop it as soon as the files are restored so the
        # work directory (a tmpfs in Kubernetes) holds a single copy of the model.
        package_path.unlink()
        log.info(
            "restored %s@%s (%d files, manifest verified)",
            manifest.model_id,
            manifest.revision,
            len(manifest.files),
        )
        loaded = load_model(model_dir)
        log.info("model loaded: %s", type(loaded.model).__name__)
        return fill_mask(loaded, settings.prompt, settings.top_k)


def _metrics_suffix(size_bytes: int, elapsed: float) -> str:
    """Elapsed time, throughput and process peak RSS, appended when metrics are on."""
    return (
        f" in {elapsed:.2f}s "
        f"({throughput_mib_s(size_bytes, elapsed):.1f} MiB/s, peak RSS {peak_rss_mib():.1f} MiB)"
    )


def _verify(
    settings: ConsumerSettings, source: ArtifactSource, artifact_path: Path
) -> VerifiedArtifact:
    """Layer 2 gate: fetch the signature and check it with the mounted public key."""
    if not settings.verify_signature:
        log.warning("signature verification disabled: artifact authenticity is NOT checked")
        return unverified(artifact_path)
    signature_path = source.fetch(
        settings.hub_repo_id,
        settings.signature_name,
        settings.artifact_revision,
        force=settings.force,
    )
    scheme = _resolve_signer(settings.signer)
    verified = verify_file(
        artifact_path, signature_path, read_public_key(settings.public_key_path), scheme
    )
    log.info("signature %s verified (%s)", settings.signature_name, scheme.name)
    return verified


def _resolve_signer(name: str) -> SignatureScheme:
    try:
        return get_signer(name)
    except CryptoError as exc:
        raise ConfigError(str(exc)) from exc


def key_provider_for(settings: ConsumerSettings) -> KeyProvider:
    if settings.key_source is KeySource.ENV:
        return EnvKeyProvider(settings.key_env_var)
    return FileKeyProvider(settings.key_path)


@contextmanager
def _work_dir(configured: Path | None) -> Iterator[Path]:
    """A private (0700) directory that is removed on exit unless the user chose it."""
    if configured is not None:
        configured.mkdir(parents=True, exist_ok=True, mode=0o700)
        yield configured
        return
    with tempfile.TemporaryDirectory(prefix="consumer-") as tmp:
        yield Path(tmp)
