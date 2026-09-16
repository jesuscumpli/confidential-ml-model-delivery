"""Key providers implementing `consumer.core.ports.KeyProvider`: the only code that
touches Layer 1 key bytes.

`FileKeyProvider` reads the Kubernetes Secret mounted as a file (production path).
`EnvKeyProvider` exists for local development only. `CdhKeyProvider` documents the
Layer 3 design and is intentionally not implemented.
"""

from __future__ import annotations

import os
from pathlib import Path

from confidential_crypto.errors import InvalidKeyError
from confidential_crypto.keys import decode_symmetric_key, load_symmetric_key

from consumer.core.errors import ConfigError


class FileKeyProvider:
    """Reads a raw or hex key from a file, e.g. a Secret mounted at `/etc/model-key/key`."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def get_key(self, key_size: int) -> bytes:
        try:
            return load_symmetric_key(self._path, key_size)
        except InvalidKeyError as exc:
            raise ConfigError(f"key file {self._path}: {exc}") from exc


class EnvKeyProvider:
    """Reads a hex or raw key from an environment variable. Development only."""

    def __init__(self, variable: str) -> None:
        self._variable = variable

    def get_key(self, key_size: int) -> bytes:
        value = os.environ.get(self._variable)
        if value is None:
            raise ConfigError(f"environment variable {self._variable} is not set")
        try:
            return decode_symmetric_key(value.encode(), key_size)
        except InvalidKeyError as exc:
            raise ConfigError(f"environment variable {self._variable}: {exc}") from exc


class CdhKeyProvider:
    """Layer 3 design: fetch the key from the Confidential Data Hub after attestation.

    Inside a confidential VM the CDH exposes `http://127.0.0.1:8006/cdh/resource/<path>`;
    the request only succeeds when the pod's TEE evidence satisfies the KBS policy, so the
    key is released to the workload, never to the cluster operator. See `docs/layers.md`.
    """

    def __init__(self, resource_path: str) -> None:
        self._resource_path = resource_path

    def get_key(self, key_size: int) -> bytes:
        raise ConfigError("CdhKeyProvider is a Layer 3 design stub and is not implemented")
