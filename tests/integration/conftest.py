"""Fixtures for the end-to-end tests: one fake Hub shared by producer and consumer, a
synthetic BERT model that loads offline, session key pairs and a counting key provider.

The producer publishes into `FakeHub` and the consumer fetches from the same object, so
the bytes the consumer verifies and decrypts are exactly the bytes the producer committed.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import pytest
from confidential_crypto import get_signer
from consumer.core.errors import DownloadError
from consumer.infra.keys import FileKeyProvider
from consumer.models.settings import ConsumerSettings
from producer.models.settings import ProducerSettings

SIGNER = get_signer("ed25519")
MODEL_ID = "org/tiny-bert"
REPO_ID = "org/confidential-model"
ARTIFACT_NAME = "model.enc"
SIGNATURE_NAME = "model.sig"
PROMPT = "hello [MASK] world"
VOCAB = [
    "[PAD]",
    "[UNK]",
    "[CLS]",
    "[SEP]",
    "[MASK]",
    "hello",
    "world",
    "the",
    "capital",
    "of",
    "france",
    "is",
    "paris",
    ".",
]


class FakeHub:
    """In-memory Hub implementing the producer's `HubClient` and the consumer's
    `ArtifactSource`; `tamper` mutates a published file in place."""

    def __init__(self, model_dir: Path, cache_dir: Path, revision: str = "0123abcd") -> None:
        self.model_dir = model_dir
        self.cache_dir = cache_dir
        self.revision = revision
        self.repos: dict[str, dict[str, bytes]] = {}
        self.commits = 0

    # producer side ---------------------------------------------------------------
    def snapshot(self, model_id: str, revision: str, dest: Path) -> str:
        shutil.copytree(self.model_dir, dest, dirs_exist_ok=True)
        return self.revision

    def ensure_repo(self, repo_id: str, *, private: bool) -> None:
        self.repos.setdefault(repo_id, {})

    def upload(self, files: Mapping[str, Path], repo_id: str) -> str:
        for path_in_repo, local_path in files.items():
            self.repos[repo_id][path_in_repo] = local_path.read_bytes()
        self.commits += 1
        return f"commit-{self.commits}"

    def list_files(self, repo_id: str) -> list[str]:
        return sorted(self.repos.get(repo_id, {}))

    # consumer side ---------------------------------------------------------------
    def fetch(self, repo_id: str, filename: str, revision: str, *, force: bool = False) -> Path:
        data = self.repos.get(repo_id, {}).get(filename)
        if data is None:
            raise DownloadError(f"cannot download {filename}@{revision} from {repo_id}: HTTP 404")
        target = self.cache_dir / repo_id / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return target

    # test helpers ----------------------------------------------------------------
    def stored(self, filename: str, repo_id: str = REPO_ID) -> bytes:
        return self.repos[repo_id][filename]

    def tamper(self, filename: str, index: int, repo_id: str = REPO_ID) -> None:
        mutated = bytearray(self.repos[repo_id][filename])
        mutated[index] ^= 0x01
        self.repos[repo_id][filename] = bytes(mutated)


class CountingKeyProvider:
    """Wraps the production `FileKeyProvider` and records how often the key was requested,
    so a test can assert the Layer 1 key is never touched when Layer 2 fails."""

    def __init__(self, path: Path) -> None:
        self._inner = FileKeyProvider(path)
        self.requests = 0

    def get_key(self, key_size: int) -> bytes:
        self.requests += 1
        return self._inner.get_key(key_size)


def build_synthetic_bert(dest: Path) -> Path:
    """A random-weight, two-layer BERT with a 14-word vocabulary in the same layout the
    producer packages (`config.json`, `model.safetensors`, tokenizer files)."""
    import torch
    from transformers import BertConfig, BertForMaskedLM, BertTokenizer

    dest.mkdir(parents=True)
    vocab_file = dest / "vocab.txt"
    vocab_file.write_text("\n".join(VOCAB) + "\n")
    torch.manual_seed(0)
    config = BertConfig(
        vocab_size=len(VOCAB),
        hidden_size=16,
        num_hidden_layers=2,
        num_attention_heads=2,
        intermediate_size=32,
        max_position_embeddings=32,
    )
    BertForMaskedLM(config).save_pretrained(dest)  # type: ignore[no-untyped-call]
    BertTokenizer(str(vocab_file), do_lower_case=True).save_pretrained(dest)
    return dest


@pytest.fixture(scope="session")
def model_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_synthetic_bert(tmp_path_factory.mktemp("model") / "tiny-bert")


@pytest.fixture(scope="session")
def key_bytes() -> bytes:
    return os.urandom(32)


@pytest.fixture(scope="session")
def signing_key_bytes() -> bytes:
    return SIGNER.generate_private_key()


@pytest.fixture
def key_path(tmp_path: Path, key_bytes: bytes) -> Path:
    path = tmp_path / "secrets" / "model.key"
    path.parent.mkdir()
    path.write_bytes(key_bytes)
    return path


@pytest.fixture
def signing_key_path(tmp_path: Path, signing_key_bytes: bytes) -> Path:
    path = tmp_path / "secrets" / "signing.key"
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(signing_key_bytes)
    return path


@pytest.fixture
def public_key_path(tmp_path: Path, signing_key_bytes: bytes) -> Path:
    path = tmp_path / "trust" / "signing.pub"
    path.parent.mkdir()
    path.write_bytes(SIGNER.public_key_from_private(signing_key_bytes))
    return path


@pytest.fixture
def hub(model_dir: Path, tmp_path: Path) -> FakeHub:
    return FakeHub(model_dir, tmp_path / "hub-cache")


@pytest.fixture
def make_producer_settings(tmp_path: Path, key_path: Path, signing_key_path: Path) -> Any:
    def factory(**overrides: Any) -> ProducerSettings:
        defaults: dict[str, Any] = {
            "model_id": MODEL_ID,
            "hub_repo_id": REPO_ID,
            "artifact_name": ARTIFACT_NAME,
            "key_path": key_path,
            "signing_key_path": signing_key_path,
            "work_dir": tmp_path / "producer",
            "chunk_size": 4096,
        }
        return ProducerSettings(**{**defaults, **overrides})

    return factory


@pytest.fixture
def make_consumer_settings(tmp_path: Path, key_path: Path, public_key_path: Path) -> Any:
    def factory(**overrides: Any) -> ConsumerSettings:
        defaults: dict[str, Any] = {
            "hub_repo_id": REPO_ID,
            "artifact_name": ARTIFACT_NAME,
            "key_path": key_path,
            "public_key_path": public_key_path,
            "work_dir": tmp_path / "consumer",
            "prompt": PROMPT,
            "top_k": 3,
        }
        return ConsumerSettings(**{**defaults, **overrides})

    return factory


@pytest.fixture
def provider(key_path: Path) -> CountingKeyProvider:
    return CountingKeyProvider(key_path)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Neither service may pick up the developer's real token or settings."""
    for name in list(os.environ):
        if name.startswith(("PRODUCER_", "CONSUMER_")) or name in {"HF_TOKEN", "MODEL_KEY"}:
            monkeypatch.delenv(name)
    yield
