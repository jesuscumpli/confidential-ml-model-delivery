"""`producer` command line: gen-key, package, encrypt, publish and run (all steps)."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from confidential_crypto import registry

from producer import pipeline
from producer.encrypt import EncryptionMode
from producer.errors import ProducerError
from producer.hub import HfHubClient, HubClient
from producer.keys import write_new_key
from producer.settings import ProducerSettings

ClientFactory = Callable[[ProducerSettings], HubClient]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="producer", description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    sub = parser.add_subparsers(dest="command", required=True)

    gen_key = sub.add_parser("gen-key", help="write a fresh raw key to a file (mode 0600)")
    gen_key.add_argument("--out", type=Path, required=True, help="key file to create")
    _add_cipher(gen_key)

    package = sub.add_parser("package", help="download the model and build the plaintext tar")
    _add_model(package)
    _add_work_dir(package)

    encrypt = sub.add_parser("encrypt", help="encrypt the package into the upload dir")
    encrypt.add_argument("--key-path", type=Path, help="raw or hex key file")
    encrypt.add_argument("--artifact-name", help="encrypted file name (default model.enc)")
    encrypt.add_argument("--mode", type=EncryptionMode, choices=list(EncryptionMode))
    encrypt.add_argument("--chunk-size", type=int, help="bytes per chunk in chunked mode")
    _add_cipher(encrypt)
    _add_work_dir(encrypt)

    publish = sub.add_parser("publish", help="upload the encrypted artifact to the Hub")
    _add_repo(publish)
    publish.add_argument("--artifact-name", help="encrypted file name (default model.enc)")
    _add_work_dir(publish)

    run = sub.add_parser("run", help="package, encrypt and publish in one go")
    _add_model(run)
    _add_repo(run)
    run.add_argument("--key-path", type=Path, help="raw or hex key file")
    run.add_argument("--artifact-name", help="encrypted file name (default model.enc)")
    run.add_argument("--mode", type=EncryptionMode, choices=list(EncryptionMode))
    run.add_argument("--chunk-size", type=int, help="bytes per chunk in chunked mode")
    _add_cipher(run)
    _add_work_dir(run)
    return parser


def main(argv: Sequence[str] | None = None, *, client_factory: ClientFactory | None = None) -> int:
    args = build_parser().parse_args(argv)
    _configure_logging(args.verbose)
    factory = client_factory or _default_client
    try:
        settings = ProducerSettings(**_overrides(args))
        _COMMANDS[args.command](args, settings, factory)
    except ProducerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.exit_code
    return 0


def _gen_key(args: argparse.Namespace, settings: ProducerSettings, _: ClientFactory) -> None:
    write_new_key(args.out, pipeline.resolve_cipher(settings.cipher))
    print(f"wrote new {settings.cipher} key to {args.out}")


def _package(_: argparse.Namespace, settings: ProducerSettings, factory: ClientFactory) -> None:
    pipeline.run_package(settings, factory(settings))
    print(f"package written to {settings.package_path}")


def _encrypt(_: argparse.Namespace, settings: ProducerSettings, __: ClientFactory) -> None:
    print(f"encrypted artifact written to {pipeline.run_encrypt(settings)}")


def _publish(_: argparse.Namespace, settings: ProducerSettings, factory: ClientFactory) -> None:
    commit = pipeline.run_publish(settings, factory(settings))
    print(f"published {settings.artifact_name} to {settings.hub_repo_id} at {commit}")


def _run(_: argparse.Namespace, settings: ProducerSettings, factory: ClientFactory) -> None:
    commit = pipeline.run_all(settings, factory(settings))
    print(f"published {settings.artifact_name} to {settings.hub_repo_id} at {commit}")


_COMMANDS: dict[str, Callable[[argparse.Namespace, ProducerSettings, ClientFactory], None]] = {
    "gen-key": _gen_key,
    "package": _package,
    "encrypt": _encrypt,
    "publish": _publish,
    "run": _run,
}

# CLI flag -> settings field; only flags the user actually passed override the environment
_OVERRIDES = {
    "model_id": "model_id",
    "revision": "model_revision",
    "repo_id": "hub_repo_id",
    "public": "private_repo",
    "key_path": "key_path",
    "artifact_name": "artifact_name",
    "mode": "encryption_mode",
    "chunk_size": "chunk_size",
    "cipher": "cipher",
    "work_dir": "work_dir",
}


def _overrides(args: argparse.Namespace) -> dict[str, Any]:
    values = {field: getattr(args, flag, None) for flag, field in _OVERRIDES.items()}
    if values.get("private_repo") is not None:
        values["private_repo"] = not values["private_repo"]
    return {field: value for field, value in values.items() if value is not None}


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO, format="%(levelname)s %(message)s"
    )
    # per-request HTTP logs from the Hub client carry no value at INFO
    for name in ("httpx", "huggingface_hub"):
        logging.getLogger(name).setLevel(logging.DEBUG if verbose else logging.WARNING)


def _default_client(settings: ProducerSettings) -> HubClient:
    return HfHubClient(settings.token_value())


def _add_cipher(parser: argparse.ArgumentParser) -> None:
    names = [c.name for c in registry.available_ciphers()]
    parser.add_argument("--cipher", choices=names, help=f"default {registry.DEFAULT_CIPHER}")


def _add_model(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--model-id", help="Hugging Face model id")
    parser.add_argument("--revision", help="branch, tag or commit of the model")


def _add_repo(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo-id", help="Hub repository receiving the artifact")
    parser.add_argument("--public", action="store_true", default=None, help="create as public")


def _add_work_dir(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--work-dir", type=Path, help="download/package/upload directory")
