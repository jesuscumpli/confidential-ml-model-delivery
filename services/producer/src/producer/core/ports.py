"""Ports: the interfaces the application layer needs from the outside world.

Adapters live in `producer.infra`; tests substitute fakes that satisfy the same protocol.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class HubClient(Protocol):
    def snapshot(self, model_id: str, revision: str, dest: Path) -> str:
        """Download the allow-listed model files into `dest`; return the resolved commit."""

    def ensure_repo(self, repo_id: str, *, private: bool) -> None: ...

    def upload(self, local_path: Path, repo_id: str, path_in_repo: str) -> str:
        """Upload one file; return the resulting commit identifier."""

    def list_files(self, repo_id: str) -> list[str]: ...
