"""Network variants: the real `prajjwal1/bert-tiny` through the fake Hub, and the full
chain against a real scratch repository when `HF_TOKEN` and `INTEGRATION_HUB_REPO_ID`
are set. Both are `slow` and skipped by default."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from consumer.app import pipeline as consumer_pipeline
from consumer.infra.hub import HfArtifactSource
from huggingface_hub import snapshot_download
from producer.app import pipeline as producer_pipeline
from producer.core.packaging import MODEL_FILE_PATTERNS
from producer.infra.hub import HfHubClient
from producer.models.settings import DEFAULT_MODEL_ID

from tests.integration.conftest import CountingKeyProvider, FakeHub

pytestmark = pytest.mark.slow

FRANCE_PROMPT = "The capital of France is [MASK]."

# Captured at import: the autouse `clean_env` fixture strips these before each test.
_TOKEN = os.environ.get("HF_TOKEN")
_REPO_ID = os.environ.get("INTEGRATION_HUB_REPO_ID")


@pytest.fixture(scope="module")
def bert_tiny_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    dest = tmp_path_factory.mktemp("bert-tiny")
    snapshot_download(DEFAULT_MODEL_ID, local_dir=dest, allow_patterns=list(MODEL_FILE_PATTERNS))
    return dest


def test_bert_tiny_end_to_end_through_fake_hub(
    bert_tiny_dir: Path,
    tmp_path: Path,
    provider: CountingKeyProvider,
    make_producer_settings: Any,
    make_consumer_settings: Any,
) -> None:
    hub = FakeHub(bert_tiny_dir, tmp_path / "hub-cache")
    producer_pipeline.run_all(make_producer_settings(model_id=DEFAULT_MODEL_ID), hub)

    predictions = consumer_pipeline.run(
        make_consumer_settings(prompt=FRANCE_PROMPT, top_k=5), hub, provider
    )

    assert len(predictions) == 5
    assert all(0.0 < p.probability <= 1.0 for p in predictions)
    assert all(p.token for p in predictions)


def test_real_hub_round_trip(
    tmp_path: Path,
    provider: CountingKeyProvider,
    make_producer_settings: Any,
    make_consumer_settings: Any,
) -> None:
    if not _TOKEN or not _REPO_ID:
        pytest.skip("set HF_TOKEN and INTEGRATION_HUB_REPO_ID to run against the real Hub")
    client = HfHubClient(_TOKEN)
    producer_settings = make_producer_settings(model_id=DEFAULT_MODEL_ID, hub_repo_id=_REPO_ID)
    producer_pipeline.run_all(producer_settings, client)

    files = set(client.list_files(_REPO_ID))
    assert {producer_settings.artifact_name, producer_settings.signature_name} <= files
    assert all(f.startswith(".") or f.endswith((".enc", ".sig")) for f in files)

    predictions = consumer_pipeline.run(
        make_consumer_settings(hub_repo_id=_REPO_ID, prompt=FRANCE_PROMPT, top_k=5, force=True),
        HfArtifactSource(_TOKEN),
        provider,
    )
    assert len(predictions) == 5
    assert provider.requests == 1
