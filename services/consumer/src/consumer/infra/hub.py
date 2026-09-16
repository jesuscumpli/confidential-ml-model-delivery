"""Hugging Face Hub adapter implementing `consumer.core.ports.ArtifactSource`."""

from __future__ import annotations

from pathlib import Path

from huggingface_hub import hf_hub_download
from huggingface_hub.errors import EntryNotFoundError, HfHubHTTPError

from consumer.core.errors import DownloadError


class HfArtifactSource:
    def __init__(self, token: str | None) -> None:
        self._token = token

    def fetch(self, repo_id: str, filename: str, revision: str, dest_dir: Path) -> Path:
        try:
            downloaded = hf_hub_download(
                repo_id, filename, revision=revision, cache_dir=dest_dir, token=self._token
            )
        except (HfHubHTTPError, EntryNotFoundError, OSError) as exc:
            raise DownloadError(
                f"cannot download {filename}@{revision} from {repo_id}: {_status(exc)}"
            ) from exc
        return Path(downloaded)


def _status(exc: HfHubHTTPError | EntryNotFoundError | OSError) -> str:
    if isinstance(exc, HfHubHTTPError):
        return "no response" if exc.response is None else f"HTTP {exc.response.status_code}"
    return type(exc).__name__
