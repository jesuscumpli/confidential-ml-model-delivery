"""Real Hub round trip, only when credentials and a scratch repository are provided."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from confidential_crypto import get_signer

from producer.app.pipeline import run_all
from producer.infra.hub import HfHubClient
from producer.models.settings import ProducerSettings

pytestmark = pytest.mark.slow

# Captured at import: the autouse `clean_env` fixture strips these before each test.
_TOKEN = os.environ.get("HF_TOKEN")
_REPO_ID = os.environ.get("PRODUCER_TEST_REPO_ID")


@pytest.fixture
def real_settings(tmp_path: Path) -> ProducerSettings:
    if not _TOKEN or not _REPO_ID:
        pytest.skip("set HF_TOKEN and PRODUCER_TEST_REPO_ID to run the real Hub test")
    key_path = tmp_path / "model.key"
    key_path.write_bytes(os.urandom(32))
    signing_key_path = tmp_path / "signing.key"
    signing_key_path.write_bytes(get_signer("ed25519").generate_private_key())
    return ProducerSettings(
        hub_repo_id=_REPO_ID,
        key_path=key_path,
        signing_key_path=signing_key_path,
        work_dir=tmp_path / "work",
    )


def test_publish_to_real_repo_contains_only_artifact_and_signature(
    real_settings: ProducerSettings,
) -> None:
    client = HfHubClient(_TOKEN)
    run_all(real_settings, client)
    files = client.list_files(real_settings.hub_repo_id or "")
    expected = {real_settings.artifact_name, real_settings.signature_name}
    assert expected <= set(files)
    assert all(f in expected or f.startswith(".") for f in files)
