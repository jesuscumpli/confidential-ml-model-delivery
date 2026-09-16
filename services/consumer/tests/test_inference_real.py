"""Real model: restore-and-load the same directory layout the producer packages (network)."""

from __future__ import annotations

from pathlib import Path

import pytest
from huggingface_hub import snapshot_download

from consumer.infra.inference import fill_mask, load_model

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def bert_tiny_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    dest = tmp_path_factory.mktemp("bert-tiny")
    snapshot_download(
        "prajjwal1/bert-tiny",
        local_dir=dest,
        allow_patterns=["config.json", "vocab.txt", "pytorch_model.bin"],
    )
    return dest


def test_fill_mask_on_bert_tiny(bert_tiny_dir: Path) -> None:
    loaded = load_model(bert_tiny_dir)
    predictions = fill_mask(loaded, "The capital of France is [MASK].", top_k=3)
    assert len(predictions) == 3
    assert all(0.0 < p.probability <= 1.0 for p in predictions)
    assert predictions[0].token
