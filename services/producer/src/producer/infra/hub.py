"""Hugging Face Hub adapter implementing `producer.core.ports.HubClient`."""

from __future__ import annotations

from pathlib import Path

from huggingface_hub import HfApi, snapshot_download
from huggingface_hub.errors import HfHubHTTPError

from producer.core.errors import HubError
from producer.core.packaging import MODEL_FILE_PATTERNS


class HfHubClient:
    """Real client. The token is passed to `HfApi` once and never echoed in errors."""

    def __init__(self, token: str | None) -> None:
        self._token = token
        self._api = HfApi(token=token)

    def snapshot(self, model_id: str, revision: str, dest: Path) -> str:
        try:
            info = self._api.model_info(model_id, revision=revision)
            snapshot_download(
                model_id,
                revision=info.sha,
                local_dir=dest,
                allow_patterns=list(MODEL_FILE_PATTERNS),
                token=self._token,
            )
        except HfHubHTTPError as exc:
            raise HubError(f"cannot download {model_id}@{revision}: {_reason(exc)}") from exc
        if info.sha is None:
            raise HubError(f"Hub returned no commit for {model_id}@{revision}")
        return info.sha

    def ensure_repo(self, repo_id: str, *, private: bool) -> None:
        try:
            self._api.create_repo(repo_id, private=private, exist_ok=True)
        except HfHubHTTPError as exc:
            raise HubError(f"cannot create or access {repo_id}: {_reason(exc)}") from exc

    def upload(self, local_path: Path, repo_id: str, path_in_repo: str) -> str:
        try:
            commit = self._api.upload_file(
                path_or_fileobj=local_path,
                path_in_repo=path_in_repo,
                repo_id=repo_id,
                commit_message=f"Publish encrypted artifact {path_in_repo}",
            )
        except HfHubHTTPError as exc:
            raise HubError(f"cannot upload {path_in_repo} to {repo_id}: {_reason(exc)}") from exc
        return str(commit.oid)

    def list_files(self, repo_id: str) -> list[str]:
        try:
            return self._api.list_repo_files(repo_id)
        except HfHubHTTPError as exc:
            raise HubError(f"cannot list {repo_id}: {_reason(exc)}") from exc


def _reason(exc: HfHubHTTPError) -> str:
    """HTTP status and reason only: response bodies may echo request headers."""
    response = exc.response
    if response is None:
        return "no response"
    return f"HTTP {response.status_code}"
