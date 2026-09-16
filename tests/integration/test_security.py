"""Negative paths across both services, one per threat: every attack on what the Hub
serves is caught before the model loads, at the layer that is supposed to catch it,
and the exit code names that layer.

`CountingKeyProvider.requests` proves the Layer 1 key is never read while Layer 2 fails.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from consumer.cli.main import main as consumer_main
from consumer.core.errors import DecryptError, DownloadError, SignatureError
from producer.app import pipeline as producer_pipeline

from tests.integration.conftest import (
    ARTIFACT_NAME,
    PROMPT,
    REPO_ID,
    SIGNATURE_NAME,
    SIGNER,
    CountingKeyProvider,
    FakeHub,
)

# Deep inside the ciphertext, past any header the Hub or the consumer could reject early
_BODY_OFFSET = 512


@pytest.fixture
def published(hub: FakeHub, make_producer_settings: Any) -> FakeHub:
    producer_pipeline.run_all(make_producer_settings(), hub)
    return hub


def _consume(
    hub: FakeHub,
    provider: CountingKeyProvider,
    work_dir: Path,
    public_key_path: Path,
    *extra: str,
) -> int:
    argv = [
        "--repo-id",
        REPO_ID,
        "--public-key-path",
        str(public_key_path),
        "--prompt",
        PROMPT,
        "--work-dir",
        str(work_dir),
        *extra,
    ]
    return consumer_main(argv, source=hub, provider=provider)


def _assert_nothing_decrypted(work_dir: Path) -> None:
    assert not (work_dir / "model.tar").exists()
    assert not (work_dir / "model").exists()


def test_tampered_artifact_fails_signature_before_key_is_read(
    published: FakeHub, provider: CountingKeyProvider, tmp_path: Path, public_key_path: Path
) -> None:
    published.tamper(ARTIFACT_NAME, _BODY_OFFSET)
    work = tmp_path / "consumer"

    assert _consume(published, provider, work, public_key_path) == SignatureError.exit_code
    assert provider.requests == 0
    _assert_nothing_decrypted(work)


def test_tampered_signature_is_rejected(
    published: FakeHub, provider: CountingKeyProvider, tmp_path: Path, public_key_path: Path
) -> None:
    published.tamper(SIGNATURE_NAME, len(published.stored(SIGNATURE_NAME)) - 1)
    work = tmp_path / "consumer"

    assert _consume(published, provider, work, public_key_path) == SignatureError.exit_code
    assert provider.requests == 0
    _assert_nothing_decrypted(work)


def test_signature_from_another_publish_does_not_transfer(
    published: FakeHub,
    provider: CountingKeyProvider,
    tmp_path: Path,
    public_key_path: Path,
    make_producer_settings: Any,
) -> None:
    """A genuine signature by the trusted key, but over a different ciphertext."""
    second = make_producer_settings(hub_repo_id="org/second")
    producer_pipeline.run_encrypt(second)  # fresh nonce: new ciphertext for the same package
    producer_pipeline.run_sign(second)
    producer_pipeline.run_publish(second, published)
    published.repos[REPO_ID][SIGNATURE_NAME] = published.stored(SIGNATURE_NAME, "org/second")
    work = tmp_path / "consumer"

    assert _consume(published, provider, work, public_key_path) == SignatureError.exit_code
    assert provider.requests == 0
    _assert_nothing_decrypted(work)


def test_untrusted_public_key_rejects_a_genuine_artifact(
    published: FakeHub, provider: CountingKeyProvider, tmp_path: Path
) -> None:
    other_public = tmp_path / "other.pub"
    other_public.write_bytes(SIGNER.public_key_from_private(SIGNER.generate_private_key()))
    work = tmp_path / "consumer"

    assert _consume(published, provider, work, other_public) == SignatureError.exit_code
    assert provider.requests == 0
    _assert_nothing_decrypted(work)


def test_wrong_decryption_key_fails_after_signature_passes(
    published: FakeHub, tmp_path: Path, public_key_path: Path
) -> None:
    wrong_key = tmp_path / "wrong.key"
    wrong_key.write_bytes(os.urandom(32))
    provider = CountingKeyProvider(wrong_key)
    work = tmp_path / "consumer"

    assert _consume(published, provider, work, public_key_path) == DecryptError.exit_code
    assert provider.requests == 1
    assert not (work / "model").exists()


def test_layer_1_alone_still_detects_tampering(
    published: FakeHub, provider: CountingKeyProvider, tmp_path: Path, public_key_path: Path
) -> None:
    """With verification disabled the AEAD tag catches the change, but only after the
    key was handed out: this is the gap Layer 2 closes."""
    published.tamper(ARTIFACT_NAME, _BODY_OFFSET)
    work = tmp_path / "consumer"

    code = _consume(published, provider, work, public_key_path, "--no-verify")

    assert code == DecryptError.exit_code
    assert provider.requests == 1
    assert not (work / "model").exists()


def test_unsigned_publish_is_refused_by_a_verifying_consumer(
    hub: FakeHub,
    provider: CountingKeyProvider,
    tmp_path: Path,
    public_key_path: Path,
    make_producer_settings: Any,
) -> None:
    producer_pipeline.run_all(make_producer_settings(sign=False), hub)
    assert hub.list_files(REPO_ID) == [ARTIFACT_NAME]
    work = tmp_path / "consumer"

    assert _consume(hub, provider, work, public_key_path) == DownloadError.exit_code
    assert provider.requests == 0
    _assert_nothing_decrypted(work)


def test_unsigned_publish_still_works_with_layer_1_only(
    hub: FakeHub,
    provider: CountingKeyProvider,
    tmp_path: Path,
    public_key_path: Path,
    make_producer_settings: Any,
) -> None:
    producer_pipeline.run_all(make_producer_settings(sign=False), hub)
    work = tmp_path / "consumer"

    assert _consume(hub, provider, work, public_key_path, "--no-verify") == 0
    assert provider.requests == 1
