"""Happy path across both services: package → encrypt → sign → publish (fake Hub) →
download → verify → decrypt → restore → load → fill-mask inference."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from confidential_crypto.format import (
    ARTIFACT_VERSION_CHUNKED,
    ARTIFACT_VERSION_ONESHOT,
    ArtifactHeader,
    SignatureEnvelope,
)
from consumer.app import pipeline as consumer_pipeline
from consumer.cli.main import main as consumer_main
from producer.app import pipeline as producer_pipeline
from producer.cli.main import main as producer_main
from producer.core.packaging import collect_files
from producer.models.encryption import EncryptionMode

from tests.integration.conftest import (
    ARTIFACT_NAME,
    MODEL_ID,
    PROMPT,
    REPO_ID,
    SIGNATURE_NAME,
    VOCAB,
    CountingKeyProvider,
    FakeHub,
)


@pytest.mark.parametrize(
    ("mode", "version"),
    [
        (EncryptionMode.CHUNKED, ARTIFACT_VERSION_CHUNKED),
        (EncryptionMode.ONE_SHOT, ARTIFACT_VERSION_ONESHOT),
    ],
)
def test_full_flow_through_pipelines(
    mode: EncryptionMode,
    version: int,
    hub: FakeHub,
    provider: CountingKeyProvider,
    make_producer_settings: Any,
    make_consumer_settings: Any,
) -> None:
    producer_pipeline.run_all(make_producer_settings(encryption_mode=mode), hub)

    assert hub.list_files(REPO_ID) == [ARTIFACT_NAME, SIGNATURE_NAME]
    header, _ = ArtifactHeader.decode(hub.stored(ARTIFACT_NAME))
    assert header.version == version
    SignatureEnvelope.decode(hub.stored(SIGNATURE_NAME))

    predictions = consumer_pipeline.run(make_consumer_settings(), hub, provider)

    assert len(predictions) == 3
    assert all(0.0 < p.probability <= 1.0 for p in predictions)
    assert all(p.token in VOCAB for p in predictions)
    assert provider.requests == 1


def test_consumer_restores_exactly_the_packaged_files(
    hub: FakeHub,
    provider: CountingKeyProvider,
    model_dir: Path,
    make_producer_settings: Any,
    make_consumer_settings: Any,
) -> None:
    producer_pipeline.run_all(make_producer_settings(), hub)
    consumer_settings = make_consumer_settings()
    consumer_pipeline.run(consumer_settings, hub, provider)

    restored = consumer_settings.work_dir / "model"
    packaged = [str(path) for path in collect_files(model_dir)]
    assert packaged
    restored_files = sorted(
        p.relative_to(restored).as_posix() for p in restored.rglob("*") if p.is_file()
    )
    assert restored_files == packaged
    for relative in packaged:
        assert (restored / relative).read_bytes() == (model_dir / relative).read_bytes()


def test_hub_never_receives_plaintext(
    hub: FakeHub, model_dir: Path, make_producer_settings: Any
) -> None:
    producer_pipeline.run_all(make_producer_settings(), hub)

    config = (model_dir / "config.json").read_bytes()
    for name in hub.list_files(REPO_ID):
        stored = hub.stored(name)
        assert config not in stored
        assert b"manifest.json" not in stored
        assert MODEL_ID.encode() not in stored


def test_package_is_reproducible(hub: FakeHub, make_producer_settings: Any) -> None:
    settings = make_producer_settings()
    producer_pipeline.run_package(settings, hub)
    first = settings.package_path.read_bytes()
    producer_pipeline.run_package(settings, hub)
    assert settings.package_path.read_bytes() == first


def test_full_flow_through_clis(
    hub: FakeHub,
    tmp_path: Path,
    key_path: Path,
    signing_key_path: Path,
    public_key_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Both CLIs with real settings parsing and the production `FileKeyProvider`."""
    producer_argv = [
        "run",
        "--model-id",
        MODEL_ID,
        "--repo-id",
        REPO_ID,
        "--key-path",
        str(key_path),
        "--signing-key-path",
        str(signing_key_path),
        "--work-dir",
        str(tmp_path / "producer"),
        "--chunk-size",
        "4096",
    ]
    assert producer_main(producer_argv, client_factory=lambda _: hub) == 0
    assert hub.list_files(REPO_ID) == [ARTIFACT_NAME, SIGNATURE_NAME]

    consumer_argv = [
        "--repo-id",
        REPO_ID,
        "--key-path",
        str(key_path),
        "--public-key-path",
        str(public_key_path),
        "--prompt",
        PROMPT,
        "--top-k",
        "2",
        "--work-dir",
        str(tmp_path / "consumer"),
    ]
    assert consumer_main(consumer_argv, source=hub) == 0

    out = capsys.readouterr().out
    assert f"prompt: {PROMPT}" in out
    assert key_path.read_bytes().hex() not in out
