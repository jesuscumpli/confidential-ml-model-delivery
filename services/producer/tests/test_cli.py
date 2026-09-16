"""CLI and pipeline: argument validation, exit codes, fake-Hub publishing invariants."""

from __future__ import annotations

import logging
import tarfile
from pathlib import Path
from typing import Any

import pytest
from confidential_crypto import decrypt, get_signer, verify
from confidential_crypto.format import ARTIFACT_VERSION_CHUNKED, ArtifactHeader

from producer.app import pipeline
from producer.cli.main import main
from producer.core.errors import ConfigError, HubError, SigningError
from producer.models.manifest import MANIFEST_NAME
from tests.conftest import MODEL_FILES, FakeHubClient, write_model_dir


def _cli(fake_hub: FakeHubClient, *argv: str) -> int:
    return main(list(argv), client_factory=lambda _: fake_hub)


@pytest.mark.parametrize(
    "command",
    ["gen-key", "gen-signing-keypair", "package", "encrypt", "sign", "publish", "run", "config"],
)
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


def test_run_publishes_only_the_encrypted_artifact_and_its_signature(
    fake_hub: FakeHubClient, tmp_path: Path, key_path: Path, signing_key_path: Path
) -> None:
    work = tmp_path / "work"
    code = _cli(
        fake_hub,
        "run",
        "--work-dir", str(work),
        "--key-path", str(key_path),
        "--signing-key-path", str(signing_key_path),
        "--repo-id", "org/repo",
        "--model-id", "org/model",
    )  # fmt: skip
    assert code == 0
    assert fake_hub.list_files("org/repo") == ["model.enc", "model.sig"]
    assert len(fake_hub.uploads) == 1, "artifact and signature land in one commit"
    assert sorted(p.name for p in (work / "upload").iterdir()) == ["model.enc", "model.sig"]

    blob = fake_hub.repos["org/repo"]["model.enc"]
    assert ArtifactHeader.decode(blob)[0].version == ARTIFACT_VERSION_CHUNKED
    assert decrypt(blob, key_path.read_bytes()) == (work / "model.tar").read_bytes()
    for name, data in MODEL_FILES.items():
        assert data not in blob, name

    signer = get_signer("ed25519")
    public_key = signer.public_key_from_private(signing_key_path.read_bytes())
    verify(blob, fake_hub.repos["org/repo"]["model.sig"], public_key, signer)


def test_run_without_signing_publishes_only_the_artifact(
    fake_hub: FakeHubClient, tmp_path: Path, key_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    code = _cli(
        fake_hub,
        "run", "--no-sign",
        "--work-dir", str(tmp_path / "work"),
        "--key-path", str(key_path),
        "--repo-id", "org/repo",
    )  # fmt: skip
    assert code == 0
    assert fake_hub.list_files("org/repo") == ["model.enc"]
    assert "without a signature" in caplog.text


def test_package_does_not_reuse_files_from_previous_model(
    fake_hub: FakeHubClient, tmp_path: Path, make_settings: Any
) -> None:
    """A second download must not package leftovers from the previous model."""
    roberta = write_model_dir(
        tmp_path / "roberta",
        {"config.json": b'{"model_type": "roberta"}\n', "model.safetensors": b"roberta weights"},
    )
    tiny = write_model_dir(
        tmp_path / "tiny",
        {
            "config.json": b'{"model_type": "bert"}\n',
            "pytorch_model.bin": b"tiny weights",
            "vocab.txt": b"[PAD]\n",
        },
    )
    settings = make_settings(model_id="org/roberta")
    fake_hub.source_dir = roberta
    pipeline.run_package(settings, fake_hub)

    settings = make_settings(model_id="org/bert-tiny")
    fake_hub.source_dir = tiny
    manifest = pipeline.run_package(settings, fake_hub)

    assert {entry.path for entry in manifest.files} == {
        "config.json",
        "pytorch_model.bin",
        "vocab.txt",
    }
    assert (settings.model_dir / "config.json").read_bytes() == b'{"model_type": "bert"}\n'


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
    signing_key_path: Path,
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
        "--signing-key-path", str(signing_key_path),
        "--repo-id", "org/repo",
        "--mode", "one-shot",
    )  # fmt: skip
    assert code == 0
    blob = fake_hub.repos["org/repo"]["model.enc"]
    assert ArtifactHeader.decode(blob)[0].version == 1
    assert "model.sig" in fake_hub.repos["org/repo"]


def test_interactive_run_generates_missing_signing_keypair(
    fake_hub: FakeHubClient,
    tmp_path: Path,
    key_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Confirming the offer creates the key pair; the public half is left next to it."""
    monkeypatch.setattr("typer.prompt", lambda *_, default=None, **__: default)
    monkeypatch.setattr("typer.confirm", lambda *_, default=True, **__: True)
    signing_key = tmp_path / "keys" / "signing.key"
    code = _cli(
        fake_hub,
        "run", "--interactive",
        "--work-dir", str(tmp_path / "work"),
        "--key-path", str(key_path),
        "--signing-key-path", str(signing_key),
        "--repo-id", "org/repo",
    )  # fmt: skip
    assert code == 0
    assert (tmp_path / "keys" / "signing.pub").is_file()
    assert "model.sig" in fake_hub.repos["org/repo"]


def test_unknown_signer_is_rejected_by_parser(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["sign", "--signer", "rot13"]) == 2
    assert "is not one of" in capsys.readouterr().err


def test_gen_signing_keypair_writes_pem_pair_and_never_prints_keys(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    private = tmp_path / "signing.key"
    assert main(["gen-signing-keypair", "--out", str(private)]) == 0
    public = tmp_path / "signing.pub"
    assert private.stat().st_mode & 0o777 == 0o600
    assert b"PRIVATE KEY" in private.read_bytes()
    assert b"PUBLIC KEY" in public.read_bytes()
    captured = capsys.readouterr().out + capsys.readouterr().err
    assert "PRIVATE KEY" not in captured
    assert main(["gen-signing-keypair", "--out", str(private)]) == ConfigError.exit_code


def test_sign_without_artifact_fails(
    fake_hub: FakeHubClient, tmp_path: Path, signing_key_path: Path
) -> None:
    code = _cli(
        fake_hub, "sign", "--work-dir", str(tmp_path), "--signing-key-path", str(signing_key_path)
    )
    assert code == ConfigError.exit_code


def test_sign_without_signing_key_path_fails(
    fake_hub: FakeHubClient, key_path: Path, make_settings: Any
) -> None:
    settings = make_settings(key_path=key_path, signing_key_path=None)
    pipeline.run_package(settings, fake_hub)
    pipeline.run_encrypt(settings)
    with pytest.raises(ConfigError, match="signing key path is required"):
        pipeline.run_sign(settings)


def test_sign_with_symmetric_key_file_fails(
    fake_hub: FakeHubClient, key_path: Path, make_settings: Any
) -> None:
    """A raw key file is not a PEM private key: refuse before any signing."""
    settings = make_settings(key_path=key_path, signing_key_path=key_path)
    pipeline.run_package(settings, fake_hub)
    pipeline.run_encrypt(settings)
    with pytest.raises(ConfigError, match="invalid signing key file"):
        pipeline.run_sign(settings)


def test_sign_with_key_of_another_scheme_fails(
    fake_hub: FakeHubClient, key_path: Path, tmp_path: Path, make_settings: Any
) -> None:
    foreign = tmp_path / "ecdsa.key"
    foreign.write_bytes(get_signer("ecdsa-p256").generate_private_key())
    settings = make_settings(key_path=key_path, signing_key_path=foreign)
    pipeline.run_package(settings, fake_hub)
    pipeline.run_encrypt(settings)
    with pytest.raises(SigningError, match="signing failed"):
        pipeline.run_sign(settings)
    assert not settings.signature_path.exists()


def test_publish_refuses_missing_signature_unless_disabled(
    fake_hub: FakeHubClient, key_path: Path, make_settings: Any
) -> None:
    settings = make_settings(key_path=key_path)
    pipeline.run_package(settings, fake_hub)
    pipeline.run_encrypt(settings)
    with pytest.raises(ConfigError, match="signature not found"):
        pipeline.run_publish(settings, fake_hub)
    assert fake_hub.uploads == []
    pipeline.run_publish(make_settings(key_path=key_path, sign=False), fake_hub)
    assert fake_hub.list_files("org/repo") == ["model.enc"]


def test_publish_refuses_non_envelope_signature(
    fake_hub: FakeHubClient, key_path: Path, make_settings: Any
) -> None:
    settings = make_settings(key_path=key_path)
    pipeline.run_package(settings, fake_hub)
    pipeline.run_encrypt(settings)
    settings.signature_path.write_bytes(b"not a signature")
    with pytest.raises(HubError, match="not a signature envelope"):
        pipeline.run_publish(settings, fake_hub)
    assert fake_hub.uploads == []


def test_config_shows_signing_state(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["config", "--repo-id", "org/repo", "--no-sign"]) == 0
    assert "off" in capsys.readouterr().out
    assert main(["config", "--repo-id", "org/repo"]) == 0
    assert "ed25519" in capsys.readouterr().out


def test_signature_name_follows_artifact_name(
    fake_hub: FakeHubClient, tmp_path: Path, key_path: Path, signing_key_path: Path
) -> None:
    """Several artifacts can share one repository: each signature is `<stem>.sig`."""
    code = _cli(
        fake_hub,
        "run",
        "--work-dir", str(tmp_path / "work"),
        "--key-path", str(key_path),
        "--signing-key-path", str(signing_key_path),
        "--repo-id", "org/repo",
        "--artifact-name", "distilbert.v2.enc",
    )  # fmt: skip
    assert code == 0
    assert fake_hub.list_files("org/repo") == ["distilbert.v2.enc", "distilbert.v2.sig"]


def test_artifact_name_ending_in_sig_is_rejected(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["config", "--artifact-name", "model.sig"]) == ConfigError.exit_code
    assert "artifact_name" in capsys.readouterr().err
