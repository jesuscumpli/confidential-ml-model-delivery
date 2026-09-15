"""`manifest.json` describing the packaged model: identity plus per-file SHA-256."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

MANIFEST_NAME = "manifest.json"
MANIFEST_FORMAT = 1
_HASH_BLOCK = 1 << 20


@dataclass(frozen=True, slots=True)
class FileEntry:
    path: str
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class Manifest:
    model_id: str
    revision: str
    files: tuple[FileEntry, ...]

    def to_json(self) -> bytes:
        payload: dict[str, Any] = {
            "format": MANIFEST_FORMAT,
            "model_id": self.model_id,
            "revision": self.revision,
            "files": [asdict(entry) for entry in self.files],
        }
        # sorted keys and a fixed separator make the manifest bytes reproducible
        return (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode()

    @classmethod
    def from_json(cls, data: bytes) -> Manifest:
        payload = json.loads(data)
        if payload.get("format") != MANIFEST_FORMAT:
            raise ValueError(f"unsupported manifest format {payload.get('format')!r}")
        files = tuple(FileEntry(**entry) for entry in payload["files"])
        return cls(model_id=payload["model_id"], revision=payload["revision"], files=files)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(_HASH_BLOCK), b""):
            digest.update(block)
    return digest.hexdigest()
