"""Shared fixtures: a tiny fake model directory, an in-memory Hub and clean settings."""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from producer.settings import ProducerSettings

MODEL_FILES: dict[str, bytes] = {
    "config.json": b'{"model_type": "bert", "vocab_size": 8}\n',
    "tokenizer.json": b'{"version": "1.0"}\n',
    "tokenizer_config.json": b'{"do_lower_case": true}\n',
    "vocab.txt": b"[PAD]\n[UNK]\n[CLS]\n[SEP]\n[MASK]\nhello\nworld\n.\n",
    "special_tokens_map.json": b'{"mask_token": "[MASK]"}\n',
    "model.safetensors": os.urandom(3 * 4096 + 17),
}
EXCLUDED_FILES: dict[str, bytes] = {
    "pytorch_model.bin": b"legacy pickle weights",
    "README.md": b"# not part of the artifact\n",
    ".gitattributes": b"*.safetensors filter=lfs\n",
    ".cache/huggingface/download/model.safetensors.metadata": b"etag\n",
}


def write_model_dir(root: Path, files: dict[str, bytes] = MODEL_FILES) -> Path:
    for name, data in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return root


@pytest.fixture
def tiny_model_dir(tmp_path: Path) -> Path:
    model_dir = write_model_dir(tmp_path / "model", {**MODEL_FILES, **EXCLUDED_FILES})
    return model_dir


class FakeHubClient:
    """In-memory Hub: `snapshot` copies a local directory, `upload` stores bytes."""

    def __init__(self, source_dir: Path, revision: str = "0123abcd") -> None:
        self.source_dir = source_dir
        self.revision = revision
        self.repos: dict[str, dict[str, bytes]] = {}
        self.uploads: list[tuple[Path, str, str]] = []

    def snapshot(self, model_id: str, revision: str, dest: Path) -> str:
        shutil.copytree(self.source_dir, dest, dirs_exist_ok=True)
        return self.revision

    def ensure_repo(self, repo_id: str, *, private: bool) -> None:
        self.repos.setdefault(repo_id, {})

    def upload(self, local_path: Path, repo_id: str, path_in_repo: str) -> str:
        self.uploads.append((local_path, repo_id, path_in_repo))
        self.repos[repo_id][path_in_repo] = local_path.read_bytes()
        return f"commit-{len(self.uploads)}"

    def list_files(self, repo_id: str) -> list[str]:
        return sorted(self.repos.get(repo_id, {}))


@pytest.fixture
def fake_hub(tiny_model_dir: Path) -> FakeHubClient:
    return FakeHubClient(tiny_model_dir)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Tests must not pick up the developer's real token or producer settings."""
    for name in list(os.environ):
        if name.startswith("PRODUCER_") or name == "HF_TOKEN":
            monkeypatch.delenv(name)
    yield


@pytest.fixture
def make_settings(tmp_path: Path) -> Any:
    def factory(**overrides: Any) -> ProducerSettings:
        defaults: dict[str, Any] = {"work_dir": tmp_path / "work", "hub_repo_id": "org/repo"}
        return ProducerSettings(**{**defaults, **overrides})

    return factory
