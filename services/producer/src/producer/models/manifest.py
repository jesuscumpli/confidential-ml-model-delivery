"""`manifest.json` describing the packaged model: identity plus per-file SHA-256."""

from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict, Field

MANIFEST_NAME = "manifest.json"
MANIFEST_FORMAT = 1


class FileEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", protected_namespaces=())

    path: str
    size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class Manifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", protected_namespaces=())

    format: int = Field(default=MANIFEST_FORMAT, ge=MANIFEST_FORMAT, le=MANIFEST_FORMAT)
    model_id: str
    revision: str
    files: tuple[FileEntry, ...]

    def to_json(self) -> bytes:
        # sorted keys and a fixed separator make the manifest bytes reproducible
        return (json.dumps(self.model_dump(), sort_keys=True, indent=2) + "\n").encode()

    @classmethod
    def from_json(cls, data: bytes) -> Manifest:
        return cls.model_validate_json(data)
