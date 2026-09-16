"""CLI and pipeline: argument validation, exit codes, fake-Hub publishing invariants."""

from __future__ import annotations

import logging
import os
import tarfile
from pathlib import Path
from typing import Any

import pytest
from confidential_crypto import decrypt
from confidential_crypto.format import ARTIFACT_VERSION_CHUNKED, ArtifactHeader

from producer.app import pipeline
from producer.cli.main import main
from producer.core.errors import ConfigError, HubError
from producer.models.manifest import MANIFEST_NAME
from tests.conftest import MODEL_FILES, FakeHubClient


@pytest.fixture
def key_path(tmp_path: Path) -> Path:
    path = tmp_path / "model.key"
    path.write_bytes(os.urandom(32))
    return path


def _cli(fake_hub: FakeHubClient, *argv: str) -> int:
    return main(list(argv), client_factory=lambda _: fake_hub)


@pytest.mark.parametrize("command", ["gen-key", "package", "encrypt", "publish", "run", "config"])
def test_help_for_every_subcommand(command: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert main([command, "--help"]) == 0
    assert command in capsys.readouterr().out


def test_help_shows_defaults_and_env_vars(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["encrypt", "--help"]) == 0
    out = capsys.readouterr().out
    assert "default: chunked" in out
    assert "PRODUCER_ENCRYPTION_MODE" in out


def test_unknown_command_is_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["frobnicate"]) == 2
    assert "No such command" in capsys.readouterr().err


def test_unknown_cipher_is_rejected_by_parser(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["gen-key", "--out", "k", "--cipher", "rot13"]) == 2
    assert "is not one of" in capsys.readouterr().err


def test_unknown_mode_is_rejected_by_parser(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["encrypt", "--mode", "streaming"]) == 2
    assert "Invalid value" in capsys.readouterr().err


def test_evaluation_only_cipher_is_not_offered(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["gen-key", "--help"]) == 0
    assert "aes-256-cbc-hmac-sha256" not in capsys.readouterr().out


def test_out_of_range_chunk_size_is_config_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["encrypt", "--chunk-size", "1"]) == ConfigError.exit_code
    assert "chunk_size" in capsys.readouterr().err


def test_config_masks_token(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("HF_TOKEN", "hf_secret_token_value")
    assert main(["config", "--repo-id", "org/repo", "--mode", "one-shot"]) == 0
    out = capsys.readouterr().out
    assert "hf_secret_token_value" not in out
    assert "one-shot" in out
    assert "org/repo (private)" in out


def test_config_reports_metrics_toggle(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["config", "--repo-id", "org/repo", "--metrics"]) == 0
    row = [line for line in capsys.readouterr().out.splitlines() if "metrics" in line]
    assert any("on" in line for line in row)


def test_encrypt_without_key_path_fails(fake_hub: FakeHubClient, make_settings: Any) -> None:
    settings = make_settings(key_path=None)
    pipeline.run_package(settings, fake_hub)
    with pytest.raises(ConfigError, match="key path is required"):
        pipeline.run_encrypt(settings)


def test_encrypt_with_missing_key_file_fails(
    fake_hub: FakeHubClient, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    work = tmp_path / "w"
    assert _cli(fake_hub, "package", "--work-dir", str(work)) == 0
    missing = tmp_path / "missing.key"
    code = _cli(fake_hub, "encrypt", "--work-dir", str(work), "--key-path", str(missing))
    assert code == ConfigError.exit_code
    assert "invalid key file" in capsys.readouterr().err


def test_encrypt_without_package_fails(
    fake_hub: FakeHubClient, tmp_path: Path, key_path: Path
) -> None:
    code = _cli(fake_hub, "encrypt", "--work-dir", str(tmp_path), "--key-path", str(key_path))
    assert code == ConfigError.exit_code


def test_publish_without_repo_id_fails(fake_hub: FakeHubClient, make_settings: Any) -> None:
    settings = make_settings(hub_repo_id=None)
    with pytest.raises(ConfigError, match="repository id is required"):
        pipeline.run_publish(settings, fake_hub)


def test_gen_key_never_prints_key(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "model.key"
    assert main(["gen-key", "--out", str(out)]) == 0
    captured = capsys.readouterr()
    assert out.read_bytes().hex() not in captured.out + captured.err
    assert main(["gen-key", "--out", str(out)]) == ConfigError.exit_code


def test_run_publishes_only_the_encrypted_artifact(
    fake_hub: FakeHubClient, tmp_path: Path, key_path: Path
) -> None:
    work = tmp_path / "work"
    code = _cli(
        fake_hub,
        "run",
        "--work-dir", str(work),
        "--key-path", str(key_path),
        "--repo-id", "org/repo",
        "--model-id", "org/model",
    )  # fmt: skip
    assert code == 0
    assert fake_hub.list_files("org/repo") == ["model.enc"]
    assert [p.name for p in (work / "upload").iterdir()] == ["model.enc"]

    blob = fake_hub.repos["org/repo"]["model.enc"]
    assert ArtifactHeader.decode(blob)[0].version == ARTIFACT_VERSION_CHUNKED
    assert decrypt(blob, key_path.read_bytes()) == (work / "model.tar").read_bytes()
    for name, data in MODEL_FILES.items():
        assert data not in blob, name


def test_one_shot_mode_is_selectable_per_artifact(
    fake_hub: FakeHubClient, tmp_path: Path, key_path: Path, make_settings: Any
) -> None:
    settings = make_settings(key_path=key_path, encryption_mode="one-shot")
    pipeline.run_package(settings, fake_hub)
    artifact_path = pipeline.run_encrypt(settings)
    assert ArtifactHeader.decode(artifact_path.read_bytes())[0].version == 1


def test_encrypt_omits_metrics_by_default(
    fake_hub: FakeHubClient,
    key_path: Path,
    make_settings: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = make_settings(key_path=key_path)
    pipeline.run_package(settings, fake_hub)
    with caplog.at_level(logging.INFO, logger="producer.app.pipeline"):
        pipeline.run_encrypt(settings)
    assert "encrypted" in caplog.text
    assert "MiB/s" not in caplog.text


def test_encrypt_logs_metrics_when_enabled(
    fake_hub: FakeHubClient,
    key_path: Path,
    make_settings: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = make_settings(key_path=key_path, metrics=True)
    pipeline.run_package(settings, fake_hub)
    with caplog.at_level(logging.INFO, logger="producer.app.pipeline"):
        pipeline.run_encrypt(settings)
    assert "MiB/s" in caplog.text
    assert "peak RSS" in caplog.text


def test_publish_refuses_plaintext(
    fake_hub: FakeHubClient, tmp_path: Path, make_settings: Any
) -> None:
    settings = make_settings()
    pipeline.run_package(settings, fake_hub)
    with tarfile.open(settings.package_path) as tar:
        assert tar.getnames()[0] == MANIFEST_NAME
    with pytest.raises(HubError, match="not an encrypted artifact"):
        pipeline.run_publish(settings, fake_hub, settings.package_path)
    assert fake_hub.uploads == []


def test_publish_reports_hub_error_exit_code(
    fake_hub: FakeHubClient, tmp_path: Path, make_settings: Any
) -> None:
    settings = make_settings()
    pipeline.run_package(settings, fake_hub)
    plaintext_in_upload_dir = settings.work_dir / "upload" / "model.tar"
    plaintext_in_upload_dir.parent.mkdir()
    plaintext_in_upload_dir.write_bytes(settings.package_path.read_bytes())
    code = _cli(
        fake_hub,
        "publish",
        "--work-dir", str(settings.work_dir),
        "--repo-id", "org/repo",
        "--artifact-name", "model.tar",
    )  # fmt: skip
    assert code == HubError.exit_code
    assert fake_hub.uploads == []


def test_interactive_run_accepts_defaults(
    fake_hub: FakeHubClient,
    tmp_path: Path,
    key_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pressing Enter on every prompt keeps the flags given on the command line."""
    monkeypatch.setattr("typer.prompt", lambda *_, default=None, **__: default)
    monkeypatch.setattr("typer.confirm", lambda *_, default=None, **__: default)
    code = _cli(
        fake_hub,
        "run", "--interactive",
        "--work-dir", str(tmp_path / "work"),
        "--key-path", str(key_path),
        "--repo-id", "org/repo",
        "--mode", "one-shot",
    )  # fmt: skip
    assert code == 0
    blob = fake_hub.repos["org/repo"]["model.enc"]
    assert ArtifactHeader.decode(blob)[0].version == 1
