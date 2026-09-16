"""`manifest.json` as written by the producer: identity plus per-file SHA-256.

Validation is strict on purpose: the manifest is the consumer's only description of
what the restored package must contain.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

MANIFEST_NAME = "manifest.json"
MANIFEST_FORMAT = 1


class FileEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore", strict=True)

    path: str
    size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class Manifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore", strict=True, protected_namespaces=())

    format: int
    model_id: str
    revision: str
    files: tuple[FileEntry, ...]

    @property
    def paths(self) -> set[str]:
        return {entry.path for entry in self.files}
