"""End-to-end with fakes: exit codes per stage and no plaintext outside the work dir."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from consumer.cli.main import main
from consumer.core.errors import (
    ConfigError,
    DecryptError,
    DownloadError,
    ExtractionError,
    ModelLoadError,
)
from tests.conftest import FakeArtifactSource, StaticKeyProvider, encrypt_bytes


def test_missing_repo_id_is_config_error(
    source: FakeArtifactSource, provider: StaticKeyProvider
) -> None:
    assert main([], source=source, provider=provider) == ConfigError.exit_code


def test_wrong_key_exit_code(source: FakeArtifactSource) -> None:
    code = main(
        ["--repo-id", "org/repo"], source=source, provider=StaticKeyProvider(os.urandom(32))
    )
    assert code == DecryptError.exit_code


def test_missing_key_file_exit_code(
    monkeypatch: pytest.MonkeyPatch, source: FakeArtifactSource, tmp_path: Path
) -> None:
    monkeypatch.setenv("CONSUMER_KEY_PATH", str(tmp_path / "absent"))
    assert main(["--repo-id", "org/repo"], source=source) == ConfigError.exit_code


def test_download_failure_exit_code(provider: StaticKeyProvider) -> None:
    class FailingSource:
        def fetch(self, repo_id: str, filename: str, revision: str, dest_dir: Path) -> Path:
            raise DownloadError("HTTP 404")

    assert (
        main(["--repo-id", "org/repo"], source=FailingSource(), provider=provider)
        == DownloadError.exit_code
    )


def test_bad_package_exit_code(key: bytes, provider: StaticKeyProvider) -> None:
    source = FakeArtifactSource({"model.enc": encrypt_bytes(b"not a tar", key)})
    assert (
        main(["--repo-id", "org/repo"], source=source, provider=provider)
        == ExtractionError.exit_code
    )


def test_model_load_failure_exit_code_and_cleanup(
    source: FakeArtifactSource,
    provider: StaticKeyProvider,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fake package is not a loadable model; the plaintext stays inside the work dir."""
    monkeypatch.setenv("CONSUMER_WORK_DIR", str(tmp_path / "work"))
    code = main(["--repo-id", "org/repo"], source=source, provider=provider)
    assert code == ModelLoadError.exit_code
    assert (tmp_path / "work").stat().st_mode & 0o777 == 0o700
    assert sorted(p.name for p in (tmp_path / "work").iterdir()) == [
        "model",
        "model.enc",
        "model.tar",
    ]
    assert source.calls == [("org/repo", "model.enc", "main")]


def test_temporary_work_dir_is_removed(
    source: FakeArtifactSource, provider: StaticKeyProvider
) -> None:
    before = set(Path("/tmp").glob("consumer-*"))  # noqa: S108 - inspecting tempdir prefix
    main(["--repo-id", "org/repo"], source=source, provider=provider)
    assert set(Path("/tmp").glob("consumer-*")) == before  # noqa: S108


def test_help_lists_options_with_defaults(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--help"]) == 0
    out = capsys.readouterr().out  # rich wraps at terminal width: check fragments only
    assert "--key-source" in out
    assert "/etc/model-key/key" in out
    assert "CONSUMER_PROMPT" in out


def test_unknown_key_source_is_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--repo-id", "org/repo", "--key-source", "vault"]) == 2
    assert "Invalid value" in capsys.readouterr().err


def test_top_k_out_of_range_is_config_error(
    source: FakeArtifactSource, provider: StaticKeyProvider
) -> None:
    code = main(["--repo-id", "org/repo", "--top-k", "0"], source=source, provider=provider)
    assert code == ConfigError.exit_code
