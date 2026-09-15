"""CLI and pipeline: argument validation, exit codes, fake-Hub publishing invariants."""

from __future__ import annotations

import os
import tarfile
from pathlib import Path
from typing import Any

import pytest
from confidential_crypto import decrypt
from confidential_crypto.format import ARTIFACT_VERSION_CHUNKED, ArtifactHeader

from producer import pipeline
from producer.cli import main
from producer.errors import ConfigError, HubError
from producer.manifest import MANIFEST_NAME
from tests.conftest import MODEL_FILES, FakeHubClient


@pytest.fixture
def key_path(tmp_path: Path) -> Path:
    path = tmp_path / "model.key"
    path.write_bytes(os.urandom(32))
    return path


def _cli(fake_hub: FakeHubClient, *argv: str) -> int:
    return main(list(argv), client_factory=lambda _: fake_hub)


@pytest.mark.parametrize("command", ["gen-key", "package", "encrypt", "publish", "run"])
def test_help_for_every_subcommand(command: str, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as info:
        main([command, "--help"])
    assert info.value.code == 0
    assert command in capsys.readouterr().out


def test_unknown_command_is_usage_error() -> None:
    with pytest.raises(SystemExit) as info:
        main(["frobnicate"])
    assert info.value.code == 2


def test_unknown_cipher_is_rejected_by_parser(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as info:
        main(["gen-key", "--out", "k", "--cipher", "rot13"])
    assert info.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


def test_evaluation_only_cipher_is_not_offered(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["gen-key", "--help"])
    assert "aes-256-cbc-hmac-sha256" not in capsys.readouterr().out


def test_encrypt_without_key_path_fails(
    fake_hub: FakeHubClient, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _cli(fake_hub, "package", "--work-dir", str(tmp_path / "w")) == 0
    assert _cli(fake_hub, "encrypt", "--work-dir", str(tmp_path / "w")) == ConfigError.exit_code
    assert "key path is required" in capsys.readouterr().err


def test_encrypt_without_package_fails(
    fake_hub: FakeHubClient, tmp_path: Path, key_path: Path
) -> None:
    code = _cli(fake_hub, "encrypt", "--work-dir", str(tmp_path), "--key-path", str(key_path))
    assert code == ConfigError.exit_code


def test_publish_without_repo_id_fails(
    fake_hub: FakeHubClient, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _cli(fake_hub, "publish", "--work-dir", str(tmp_path)) == ConfigError.exit_code
    assert "repository id is required" in capsys.readouterr().err


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
