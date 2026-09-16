"""Hub adapter: caching is delegated to the Hub, `force` re-downloads, errors are mapped."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from huggingface_hub.errors import EntryNotFoundError

from consumer.core.errors import DownloadError
from consumer.infra import hub


def test_fetch_uses_the_hub_cache_by_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: dict[str, Any] = {}

    def fake_download(*args: Any, **kwargs: Any) -> str:
        seen["args"] = args
        seen.update(kwargs)
        return str(tmp_path / "model.enc")

    monkeypatch.setattr(hub, "hf_hub_download", fake_download)
    result = hub.HfArtifactSource("tok").fetch("org/repo", "model.enc", "main")
    assert result == tmp_path / "model.enc"
    assert seen["args"] == ("org/repo", "model.enc")
    assert seen["revision"] == "main"
    assert "token" in seen
    assert seen["force_download"] is False


def test_fetch_forwards_force(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen: dict[str, Any] = {}

    def fake_download(*args: Any, **kwargs: Any) -> str:
        seen.update(kwargs)
        return str(tmp_path / "model.enc")

    monkeypatch.setattr(hub, "hf_hub_download", fake_download)
    hub.HfArtifactSource(None).fetch("org/repo", "model.enc", "main", force=True)
    assert seen["force_download"] is True


def test_fetch_maps_hub_errors_to_download_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_download(*args: Any, **kwargs: Any) -> str:
        raise EntryNotFoundError("missing")

    monkeypatch.setattr(hub, "hf_hub_download", fake_download)
    with pytest.raises(DownloadError, match="EntryNotFoundError"):
        hub.HfArtifactSource(None).fetch("org/repo", "model.enc", "main")
