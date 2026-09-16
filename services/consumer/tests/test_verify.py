"""Layer 2: verification outcomes, and the guarantee that failure stops before decryption."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest
from confidential_crypto import get_signer, sign

from consumer.app import pipeline
from consumer.cli.main import main
from consumer.core.errors import ConfigError, DownloadError, ModelLoadError, SignatureError
from consumer.core.verify import verify_file
from tests.conftest import SIGNER, FakeArtifactSource, StaticKeyProvider, flip_byte


@pytest.fixture
def paths(tmp_path: Path, artifact: bytes, signature: bytes) -> tuple[Path, Path]:
    artifact_path, signature_path = tmp_path / "model.enc", tmp_path / "model.sig"
    artifact_path.write_bytes(artifact)
    signature_path.write_bytes(signature)
    return artifact_path, signature_path


def test_valid_signature_verifies(paths: tuple[Path, Path], public_key: bytes) -> None:
    verified = verify_file(*paths, public_key, SIGNER)
    assert verified.verified and verified.path == paths[0]


@pytest.mark.parametrize("position", ["header", "body", "tail"])
def test_modified_artifact_fails(
    paths: tuple[Path, Path], artifact: bytes, public_key: bytes, position: str
) -> None:
    index = {"header": 5, "body": len(artifact) // 2, "tail": len(artifact) - 1}[position]
    paths[0].write_bytes(flip_byte(artifact, index))
    with pytest.raises(SignatureError, match="signature is invalid"):
        verify_file(*paths, public_key, SIGNER)


def test_modified_signature_fails(
    paths: tuple[Path, Path], signature: bytes, public_key: bytes
) -> None:
    paths[1].write_bytes(flip_byte(signature, len(signature) - 1))
    with pytest.raises(SignatureError, match="signature is invalid"):
        verify_file(*paths, public_key, SIGNER)


def test_wrong_public_key_fails(paths: tuple[Path, Path]) -> None:
    other = SIGNER.public_key_from_private(SIGNER.generate_private_key())
    with pytest.raises(SignatureError, match="expected public key"):
        verify_file(*paths, other, SIGNER)


def test_scheme_mismatch_fails(paths: tuple[Path, Path], artifact: bytes) -> None:
    """An envelope declaring another scheme is refused even with a matching key pair."""
    ecdsa = get_signer("ecdsa-p256")
    private = ecdsa.generate_private_key()
    paths[1].write_bytes(sign(artifact, private, ecdsa))
    with pytest.raises(SignatureError, match="scheme does not match"):
        verify_file(*paths, ecdsa.public_key_from_private(private), SIGNER)


def test_malformed_envelope_fails(paths: tuple[Path, Path], public_key: bytes) -> None:
    paths[1].write_bytes(b"garbage")
    with pytest.raises(SignatureError, match="envelope"):
        verify_file(*paths, public_key, SIGNER)


def test_missing_signature_file_fails(paths: tuple[Path, Path], public_key: bytes) -> None:
    paths[1].unlink()
    with pytest.raises(SignatureError, match="cannot read"):
        verify_file(*paths, public_key, SIGNER)


# --- pipeline: verification happens before any decryption ------------------------------


def test_tampered_artifact_is_never_decrypted(
    artifact: bytes,
    signature: bytes,
    provider: StaticKeyProvider,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One flipped byte: exit 4, the key is never requested and decrypt is never called."""
    tampered = flip_byte(artifact, len(artifact) // 2)
    source = FakeArtifactSource({"model.enc": tampered, "model.sig": signature}, tmp_path / "c")

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("decrypt_file must not run after a verification failure")

    monkeypatch.setattr(pipeline, "decrypt_file", forbidden)
    monkeypatch.setenv("CONSUMER_WORK_DIR", str(tmp_path / "work"))
    code = main(["--repo-id", "org/repo"], source=source, provider=provider)
    assert code == SignatureError.exit_code
    assert provider.requests == 0
    assert not (tmp_path / "work" / "model.tar").exists()


def test_valid_signature_proceeds_to_decrypt(
    source: FakeArtifactSource, provider: StaticKeyProvider, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="consumer.app.pipeline"):
        code = main(["--repo-id", "org/repo"], source=source, provider=provider)
    assert code == ModelLoadError.exit_code  # the fake package is not a loadable model
    assert provider.requests == 1
    assert caplog.text.index("signature model.sig verified") < caplog.text.index("decrypted")
    assert [call[1] for call in source.calls] == ["model.enc", "model.sig"]


def test_missing_signature_on_hub_is_a_download_error(
    artifact: bytes, provider: StaticKeyProvider, tmp_path: Path
) -> None:
    class NoSignatureSource(FakeArtifactSource):
        def fetch(self, repo_id: str, filename: str, revision: str, *, force: bool = False) -> Path:
            if filename == "model.sig":
                raise DownloadError("HTTP 404")
            return super().fetch(repo_id, filename, revision, force=force)

    source = NoSignatureSource({"model.enc": artifact}, tmp_path / "cache")
    code = main(["--repo-id", "org/repo"], source=source, provider=provider)
    assert code == DownloadError.exit_code
    assert provider.requests == 0


def test_wrong_public_key_file_exit_code(
    source: FakeArtifactSource, provider: StaticKeyProvider, public_key_file: Path
) -> None:
    public_key_file.write_bytes(SIGNER.public_key_from_private(SIGNER.generate_private_key()))
    code = main(["--repo-id", "org/repo"], source=source, provider=provider)
    assert code == SignatureError.exit_code
    assert provider.requests == 0


def test_missing_public_key_file_is_config_error(
    source: FakeArtifactSource, provider: StaticKeyProvider, tmp_path: Path
) -> None:
    code = main(
        ["--repo-id", "org/repo", "--public-key-path", str(tmp_path / "absent")],
        source=source,
        provider=provider,
    )
    assert code == ConfigError.exit_code
    assert provider.requests == 0


def test_non_pem_public_key_file_is_config_error(
    source: FakeArtifactSource, provider: StaticKeyProvider, public_key_file: Path
) -> None:
    public_key_file.write_bytes(os.urandom(32))
    code = main(["--repo-id", "org/repo"], source=source, provider=provider)
    assert code == ConfigError.exit_code


def test_unknown_signer_is_config_error(
    source: FakeArtifactSource, provider: StaticKeyProvider
) -> None:
    code = main(["--repo-id", "org/repo", "--signer", "rot13"], source=source, provider=provider)
    assert code == ConfigError.exit_code
    assert provider.requests == 0


def test_no_verify_skips_signature_with_a_warning(
    artifact: bytes, provider: StaticKeyProvider, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    source = FakeArtifactSource({"model.enc": artifact}, tmp_path / "cache")
    with caplog.at_level(logging.WARNING, logger="consumer.app.pipeline"):
        code = main(["--repo-id", "org/repo", "--no-verify"], source=source, provider=provider)
    assert code == ModelLoadError.exit_code
    assert "verification disabled" in caplog.text
    assert [call[1] for call in source.calls] == ["model.enc"]
