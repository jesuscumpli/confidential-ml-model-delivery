"""Ports: the interfaces the application layer needs from the outside world.

Adapters live in `consumer.infra`; tests substitute fakes that satisfy the same protocol.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class ArtifactSource(Protocol):
    def fetch(self, repo_id: str, filename: str, revision: str, dest_dir: Path) -> Path:
        """Place `filename` from the repository into `dest_dir`; return its path."""


class KeyProvider(Protocol):
    def get_key(self, key_size: int) -> bytes:
        """Return exactly `key_size` raw key bytes or raise `ConfigError`."""
