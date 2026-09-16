"""`producer` command line: gen-key, gen-signing-keypair, package, encrypt, sign,
publish, run and config.

Every option is optional: environment variables (`PRODUCER_*`) supply defaults and
explicit flags override them. `run --interactive` asks for each value instead.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

import typer
from confidential_crypto import registry
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from producer.app import pipeline
from producer.core.errors import ConfigError, ProducerError
from producer.core.ports import HubClient
from producer.infra.hub import HfHubClient
from producer.infra.keys import write_new_key, write_new_signing_keypair
from producer.models.encryption import EncryptionMode
from producer.models.settings import ProducerSettings

ClientFactory = Callable[[ProducerSettings], HubClient]

app = typer.Typer(
    name="producer",
    help="Package, encrypt and publish Hugging Face models as confidential artifacts.",
    no_args_is_help=True,
    add_completion=False,
    rich_markup_mode="rich",
)
out = Console(soft_wrap=True)
err = Console(stderr=True, soft_wrap=True)


@dataclass(frozen=True, slots=True)
class State:
    """Per-invocation wiring shared through `ctx.obj`; tests inject a fake Hub here."""

    client_factory: ClientFactory


# ---------------------------------------------------------------------------
# Options. Each is declared once and reused by every command that accepts it.
# ---------------------------------------------------------------------------

_MODEL = "Model"
_ENCRYPTION = "Encryption"
_SIGNING = "Signing"
_HUB = "Hub"
_OUTPUT = "Output"


def _cipher_names() -> list[str]:
    return [c.name for c in registry.available_ciphers()]


def _signer_names() -> list[str]:
    return [s.name for s in registry.available_signers()]


def _validate_cipher(value: str | None) -> str | None:
    if value is not None and value not in _cipher_names():
        raise typer.BadParameter(f"{value!r} is not one of {', '.join(_cipher_names())}")
    return value


def _validate_signer(value: str | None) -> str | None:
    if value is not None and value not in _signer_names():
        raise typer.BadParameter(f"{value!r} is not one of {', '.join(_signer_names())}")
    return value


def _option(*flags: str, field: str, text: str, panel: str, **extra: Any) -> Any:
    """An optional setting override; help shows the default and its environment variable."""
    help_text = f"{text} [dim]\\[default: {_default_of(field)}; env PRODUCER_{field.upper()}][/dim]"
    return typer.Option(*flags, help=help_text, rich_help_panel=panel, **extra)


def _default_of(field: str) -> str:
    """`None` settings (key path, repository id) must be supplied by the command using them."""
    default = ProducerSettings.model_fields[field].default
    if default is None:
        return "required"
    return str(getattr(default, "value", default))


ModelId = Annotated[
    str | None,
    _option("--model-id", "-m", field="model_id", text="Hugging Face model id.", panel=_MODEL),
]
Revision = Annotated[
    str | None,
    _option(
        "--revision",
        field="model_revision",
        text="Branch, tag or commit of the model.",
        panel=_MODEL,
    ),
]
RepoId = Annotated[
    str | None,
    _option(
        "--repo-id",
        "-r",
        field="hub_repo_id",
        text="Hub repository receiving the artifact.",
        panel=_HUB,
    ),
]
Public = Annotated[
    bool | None,
    _option(
        "--public/--private",
        field="private_repo",
        text="Repository visibility on creation.",
        panel=_HUB,
    ),
]
KeyPath = Annotated[
    Path | None,
    _option("--key-path", "-k", field="key_path", text="Raw or hex key file.", panel=_ENCRYPTION),
]
Mode = Annotated[
    EncryptionMode | None,
    _option(
        "--mode",
        field="encryption_mode",
        text="chunked: format v2, O(chunk) memory. one-shot: format v1, small models.",
        panel=_ENCRYPTION,
    ),
]
ChunkSize = Annotated[
    int | None,
    _option(
        "--chunk-size",
        field="chunk_size",
        text="Bytes per chunk in chunked mode.",
        panel=_ENCRYPTION,
    ),
]
Cipher = Annotated[
    str | None,
    _option(
        "--cipher",
        field="cipher",
        text=f"AEAD cipher: {', '.join(_cipher_names())}.",
        panel=_ENCRYPTION,
        callback=_validate_cipher,
    ),
]
SigningKeyPath = Annotated[
    Path | None,
    _option(
        "--signing-key-path",
        "-s",
        field="signing_key_path",
        text="PEM private signing key.",
        panel=_SIGNING,
    ),
]
Signer = Annotated[
    str | None,
    _option(
        "--signer",
        field="signer",
        text=f"Signature scheme: {', '.join(_signer_names())}.",
        panel=_SIGNING,
        callback=_validate_signer,
    ),
]
Sign = Annotated[
    bool | None,
    _option(
        "--sign/--no-sign",
        field="sign",
        text="Sign the artifact and publish the signature (Layer 2).",
        panel=_SIGNING,
    ),
]
Metrics = Annotated[
    bool | None,
    _option(
        "--metrics/--no-metrics",
        field="metrics",
        text="Log per-step elapsed time and peak RSS.",
        panel=_OUTPUT,
    ),
]
ArtifactName = Annotated[
    str | None,
    _option(
        "--artifact-name",
        field="artifact_name",
        text="Encrypted file name; its signature is <stem>.sig.",
        panel=_OUTPUT,
    ),
]
WorkDir = Annotated[
    Path | None,
    _option(
        "--work-dir",
        "-w",
        field="work_dir",
        text="Download/package/upload directory.",
        panel=_OUTPUT,
    ),
]
Interactive = Annotated[
    bool,
    typer.Option("--interactive", "-i", help="Ask for every value, proposing the current default."),
]


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@app.callback()
def _root(
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Debug logging.")] = False,
) -> None:
    _configure_logging(verbose)


@app.command("gen-key")
def gen_key(
    out_path: Annotated[Path, typer.Option("--out", "-o", help="Key file to create (mode 0600).")],
    cipher: Cipher = None,
) -> None:
    """Write a fresh raw key to a file; refuses to overwrite."""
    settings = _settings(cipher=cipher)
    write_new_key(out_path, pipeline.resolve_cipher(settings.cipher))
    out.print(f"[green]wrote new {settings.cipher} key to {out_path}[/green]")


@app.command("gen-signing-keypair")
def gen_signing_keypair(
    out_path: Annotated[
        Path, typer.Option("--out", "-o", help="Private key PEM to create (mode 0600).")
    ],
    public_out: Annotated[
        Path | None,
        typer.Option("--public-out", help="Public key PEM to create [default: <out>.pub]."),
    ] = None,
    signer: Signer = None,
) -> None:
    """Write a fresh signing key pair; the public key goes to the consumer's ConfigMap."""
    settings = _settings(signer=signer)
    public_path = public_out or out_path.with_suffix(".pub")
    write_new_signing_keypair(out_path, public_path, pipeline.resolve_signer(settings.signer))
    out.print(
        f"[green]wrote new {settings.signer} key pair: {out_path} (private), "
        f"{public_path} (public)[/green]"
    )


@app.command()
def package(
    ctx: typer.Context,
    model_id: ModelId = None,
    revision: Revision = None,
    work_dir: WorkDir = None,
) -> None:
    """Download the model and build the deterministic plaintext tar."""
    settings = _settings(model_id=model_id, model_revision=revision, work_dir=work_dir)
    pipeline.run_package(settings, _client(ctx, settings))
    out.print(f"[green]package written to {settings.package_path}[/green]")


@app.command()
def encrypt(
    key_path: KeyPath = None,
    mode: Mode = None,
    chunk_size: ChunkSize = None,
    cipher: Cipher = None,
    artifact_name: ArtifactName = None,
    work_dir: WorkDir = None,
    metrics: Metrics = None,
) -> None:
    """Encrypt the package into the upload directory."""
    settings = _settings(
        key_path=key_path,
        encryption_mode=mode,
        chunk_size=chunk_size,
        cipher=cipher,
        artifact_name=artifact_name,
        work_dir=work_dir,
        metrics=metrics,
    )
    artifact_path = pipeline.run_encrypt(settings)
    out.print(f"[green]encrypted artifact written to {artifact_path}[/green]")


@app.command()
def sign(
    signing_key_path: SigningKeyPath = None,
    signer: Signer = None,
    artifact_name: ArtifactName = None,
    work_dir: WorkDir = None,
) -> None:
    """Sign the encrypted artifact (Layer 2) into the upload directory."""
    settings = _settings(
        signing_key_path=signing_key_path,
        signer=signer,
        artifact_name=artifact_name,
        work_dir=work_dir,
    )
    signature_path = pipeline.run_sign(settings)
    out.print(f"[green]signature written to {signature_path}[/green]")


@app.command()
def publish(
    ctx: typer.Context,
    repo_id: RepoId = None,
    public: Public = None,
    sign: Sign = None,
    artifact_name: ArtifactName = None,
    work_dir: WorkDir = None,
) -> None:
    """Upload the encrypted artifact and its signature to the Hub (nothing else, ever)."""
    settings = _settings(
        hub_repo_id=repo_id,
        private_repo=_private(public),
        sign=sign,
        artifact_name=artifact_name,
        work_dir=work_dir,
    )
    commit = pipeline.run_publish(settings, _client(ctx, settings))
    _print_published(settings, commit)


@app.command()
def run(
    ctx: typer.Context,
    model_id: ModelId = None,
    revision: Revision = None,
    repo_id: RepoId = None,
    public: Public = None,
    key_path: KeyPath = None,
    mode: Mode = None,
    chunk_size: ChunkSize = None,
    cipher: Cipher = None,
    signing_key_path: SigningKeyPath = None,
    signer: Signer = None,
    sign: Sign = None,
    artifact_name: ArtifactName = None,
    work_dir: WorkDir = None,
    metrics: Metrics = None,
    interactive: Interactive = False,
) -> None:
    """Package, encrypt, sign and publish in one go."""
    settings = _settings(
        model_id=model_id,
        model_revision=revision,
        hub_repo_id=repo_id,
        private_repo=_private(public),
        key_path=key_path,
        encryption_mode=mode,
        chunk_size=chunk_size,
        cipher=cipher,
        signing_key_path=signing_key_path,
        signer=signer,
        sign=sign,
        artifact_name=artifact_name,
        work_dir=work_dir,
        metrics=metrics,
    )
    if interactive:
        settings = _ask_settings(settings)
    _print_config(settings)
    commit = pipeline.run_all(settings, _client(ctx, settings))
    _print_published(settings, commit)


@app.command()
def config(
    model_id: ModelId = None,
    revision: Revision = None,
    repo_id: RepoId = None,
    public: Public = None,
    key_path: KeyPath = None,
    mode: Mode = None,
    chunk_size: ChunkSize = None,
    cipher: Cipher = None,
    signing_key_path: SigningKeyPath = None,
    signer: Signer = None,
    sign: Sign = None,
    artifact_name: ArtifactName = None,
    work_dir: WorkDir = None,
    metrics: Metrics = None,
) -> None:
    """Show the effective configuration (environment plus flags). Secrets are masked."""
    settings = _settings(
        model_id=model_id,
        model_revision=revision,
        hub_repo_id=repo_id,
        private_repo=_private(public),
        key_path=key_path,
        encryption_mode=mode,
        chunk_size=chunk_size,
        cipher=cipher,
        signing_key_path=signing_key_path,
        signer=signer,
        sign=sign,
        artifact_name=artifact_name,
        work_dir=work_dir,
        metrics=metrics,
    )
    _print_config(settings)


# ---------------------------------------------------------------------------
# Interactive mode
# ---------------------------------------------------------------------------


def _ask_settings(current: ProducerSettings) -> ProducerSettings:
    """Prompt for each value; pressing Enter keeps the default shown."""
    answers: dict[str, Any] = {
        "model_id": typer.prompt("Model id", default=current.model_id),
        "model_revision": typer.prompt("Model revision", default=current.model_revision),
        "hub_repo_id": typer.prompt("Hub repository id", default=current.hub_repo_id),
        "private_repo": typer.confirm("Private repository?", default=current.private_repo),
        "cipher": _ask_choice("Cipher", _cipher_names(), current.cipher),
        "encryption_mode": _ask_choice(
            "Encryption mode", [m.value for m in EncryptionMode], current.encryption_mode.value
        ),
        "artifact_name": typer.prompt("Artifact name", default=current.artifact_name),
        "work_dir": typer.prompt("Work directory", default=current.work_dir, type=Path),
        "key_path": _ask_key_path(current),
        "sign": typer.confirm("Sign the artifact (Layer 2)?", default=current.sign),
        "metrics": typer.confirm("Log per-step metrics?", default=current.metrics),
    }
    if answers["encryption_mode"] == EncryptionMode.CHUNKED.value:
        answers["chunk_size"] = typer.prompt("Chunk size (bytes)", default=current.chunk_size)
    if answers["sign"]:
        answers["signer"] = _ask_choice("Signer", _signer_names(), current.signer)
        answers["signing_key_path"] = _ask_signing_key_path(current, answers["signer"])
    return _settings(**answers)


def _ask_choice(label: str, choices: list[str], default: str) -> str:
    """Prompt until the answer is one of `choices`."""
    while True:
        answer = str(typer.prompt(f"{label} [{'/'.join(choices)}]", default=default))
        if answer in choices:
            return answer
        err.print(f"[red]{answer!r} is not one of {', '.join(choices)}[/red]")


def _ask_key_path(current: ProducerSettings) -> Path:
    """Ask where the key lives and offer to create it when the file is missing."""
    default = current.key_path or Path("var/secrets/model.key")
    path = Path(typer.prompt("Key file", default=default, type=Path))
    if not path.exists() and typer.confirm(f"{path} does not exist. Generate a new key there?"):
        write_new_key(path, pipeline.resolve_cipher(current.cipher))
        out.print(f"[green]wrote new {current.cipher} key to {path}[/green]")
    return path


def _ask_signing_key_path(current: ProducerSettings, signer: str) -> Path:
    """Ask where the private signing key lives and offer to create the pair when missing."""
    default = current.signing_key_path or Path("var/secrets/signing.key")
    path = Path(typer.prompt("Signing key file", default=default, type=Path))
    if not path.exists() and typer.confirm(
        f"{path} does not exist. Generate a new key pair there?"
    ):
        public_path = path.with_suffix(".pub")
        write_new_signing_keypair(path, public_path, pipeline.resolve_signer(signer))
        out.print(f"[green]wrote new {signer} key pair: {path}, {public_path}[/green]")
    return path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _settings(**overrides: Any) -> ProducerSettings:
    """Environment first, then only the flags the user actually passed."""
    given = {name: value for name, value in overrides.items() if value is not None}
    try:
        return ProducerSettings(**given)
    except ValidationError as exc:
        raise ConfigError(f"invalid configuration: {_fields(exc)}") from exc


def _fields(exc: ValidationError) -> str:
    return ", ".join(".".join(map(str, error["loc"])) or "<root>" for error in exc.errors())


def _private(public: bool | None) -> bool | None:
    return None if public is None else not public


def _client(ctx: typer.Context, settings: ProducerSettings) -> HubClient:
    state: State = ctx.obj
    return state.client_factory(settings)


def _default_client(settings: ProducerSettings) -> HubClient:
    return HfHubClient(settings.token_value())


def _print_config(settings: ProducerSettings) -> None:
    table = Table(title="Effective configuration", show_header=False, box=None)
    table.add_column(style="bold")
    table.add_column()
    visibility = "private" if settings.private_repo else "public"
    rows = {
        "model": f"{settings.model_id}@{settings.model_revision}",
        "hub repo": f"{settings.hub_repo_id or '-'} ({visibility})",
        "hf token": "set" if settings.hf_token else "not set",
        "cipher": settings.cipher,
        "mode": settings.encryption_mode.value,
        "chunk size": f"{settings.chunk_size:,} bytes",
        "metrics": "on" if settings.metrics else "off",
        "key file": str(settings.key_path or "-"),
        "signing": f"{settings.signer}" if settings.sign else "off",
        "signing key": str(settings.signing_key_path or "-") if settings.sign else "-",
        "artifact": str(settings.artifact_path),
        "signature": str(settings.signature_path) if settings.sign else "-",
        "work dir": str(settings.work_dir),
    }
    for name, value in rows.items():
        table.add_row(name, value)
    out.print(table)


def _print_published(settings: ProducerSettings, commit: str) -> None:
    names = settings.artifact_name
    if settings.sign:
        names += f" + {settings.signature_name}"
    out.print(f"[green]published {names} to {settings.hub_repo_id} at commit {commit}[/green]")


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO, format="%(levelname)s %(message)s"
    )
    # per-request HTTP logs from the Hub client carry no value at INFO
    for name in ("httpx", "huggingface_hub"):
        logging.getLogger(name).setLevel(logging.DEBUG if verbose else logging.WARNING)


def main(argv: list[str] | None = None, *, client_factory: ClientFactory | None = None) -> int:
    """Run the CLI and return the process exit code (never raises `SystemExit`)."""
    state = State(client_factory=client_factory or _default_client)
    try:
        app(args=argv, standalone_mode=False, obj=state)
    except typer.TyperException as exc:
        # usage errors (unknown command, bad value): echo the message with exit code 2
        err.print(f"[red]error:[/red] {exc.format_message()}")
        return exc.exit_code
    except ProducerError as exc:
        err.print(f"[red]error:[/red] {exc}")
        return exc.exit_code
    return 0
