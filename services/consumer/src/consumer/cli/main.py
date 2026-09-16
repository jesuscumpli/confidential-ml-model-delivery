"""`consumer` command line: one run whose exit code identifies the failing stage.

Every option is optional: environment variables (`CONSUMER_*`) supply defaults and
explicit flags override them. Key bytes are never an option, only where to find them.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from consumer.app import pipeline
from consumer.core.errors import ConfigError, ConsumerError
from consumer.core.ports import ArtifactSource, KeyProvider
from consumer.infra.hub import HfArtifactSource
from consumer.models.inference import Prediction
from consumer.models.settings import ConsumerSettings, KeySource

app = typer.Typer(
    name="consumer",
    help="Retrieve, decrypt, restore and run a confidential model artifact.",
    add_completion=False,
    rich_markup_mode="rich",
)
out = Console(soft_wrap=True)
err = Console(stderr=True, soft_wrap=True)
log = logging.getLogger("consumer")

_ARTIFACT = "Artifact"
_SIGNATURE = "Signature (Layer 2)"
_KEY = "Decryption key"
_INFERENCE = "Inference"
_OUTPUT = "Output"


def _option(*flags: str, field: str, text: str, panel: str, default: str | None = None) -> Any:
    """An optional setting override; help shows the default and its environment variable."""
    shown = default or _default_of(field)
    help_text = f"{text} [dim]\\[default: {shown}; env CONSUMER_{field.upper()}][/dim]"
    return typer.Option(*flags, help=help_text, rich_help_panel=panel)


def _default_of(field: str) -> str:
    info = ConsumerSettings.model_fields[field]
    if info.is_required():
        return "required"
    return str(getattr(info.default, "value", info.default))


RepoId = Annotated[
    str | None,
    _option(
        "--repo-id",
        "-r",
        field="hub_repo_id",
        text="Hub repository holding the encrypted artifact.",
        panel=_ARTIFACT,
    ),
]
ArtifactName = Annotated[
    str | None,
    _option(
        "--artifact-name",
        field="artifact_name",
        text="Encrypted file name; its signature is <stem>.sig.",
        panel=_ARTIFACT,
    ),
]
Revision = Annotated[
    str | None,
    _option(
        "--revision",
        field="artifact_revision",
        text="Branch, tag or commit of the artifact repository.",
        panel=_ARTIFACT,
    ),
]
Force = Annotated[
    bool | None,
    _option(
        "--force/--no-force",
        field="force",
        text="Re-download the artifact even when it is already cached.",
        panel=_ARTIFACT,
    ),
]
Verify = Annotated[
    bool | None,
    _option(
        "--verify/--no-verify",
        field="verify_signature",
        text="Verify the signature before decrypting; --no-verify is for development only.",
        panel=_SIGNATURE,
    ),
]
PublicKeyPath = Annotated[
    Path | None,
    _option(
        "--public-key-path",
        field="public_key_path",
        text="PEM public key (mounted ConfigMap).",
        panel=_SIGNATURE,
    ),
]
Signer = Annotated[
    str | None,
    _option(
        "--signer",
        field="signer",
        text="Expected signature scheme; an envelope with another scheme is rejected.",
        panel=_SIGNATURE,
    ),
]
KeySourceOpt = Annotated[
    KeySource | None,
    _option(
        "--key-source",
        field="key_source",
        text="file: mounted Secret (production). env: variable (development only).",
        panel=_KEY,
    ),
]
KeyPath = Annotated[
    Path | None,
    _option("--key-path", "-k", field="key_path", text="Key file (raw or hex).", panel=_KEY),
]
KeyEnvVar = Annotated[
    str | None,
    _option(
        "--key-env-var",
        field="key_env_var",
        text="Variable holding the key when --key-source=env.",
        panel=_KEY,
    ),
]
Prompt = Annotated[
    str | None,
    _option(
        "--prompt",
        "-p",
        field="prompt",
        text="Fill-mask prompt containing exactly one [MASK].",
        panel=_INFERENCE,
    ),
]
TopK = Annotated[
    int | None,
    _option("--top-k", field="top_k", text="Number of predictions to show.", panel=_INFERENCE),
]
WorkDir = Annotated[
    Path | None,
    _option(
        "--work-dir",
        "-w",
        field="work_dir",
        text="Private directory for the plaintext.",
        panel=_INFERENCE,
        default="temporary, removed on exit",
    ),
]
Metrics = Annotated[
    bool | None,
    _option(
        "--metrics/--no-metrics",
        field="metrics",
        text="Log decrypt elapsed time, throughput and peak RSS.",
        panel=_OUTPUT,
    ),
]


@app.command()
def run(
    ctx: typer.Context,
    repo_id: RepoId = None,
    artifact_name: ArtifactName = None,
    revision: Revision = None,
    force: Force = None,
    verify: Verify = None,
    public_key_path: PublicKeyPath = None,
    signer: Signer = None,
    key_source: KeySourceOpt = None,
    key_path: KeyPath = None,
    key_env_var: KeyEnvVar = None,
    prompt: Prompt = None,
    top_k: TopK = None,
    work_dir: WorkDir = None,
    metrics: Metrics = None,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Debug logging.")] = False,
) -> None:
    """Download → verify → decrypt → restore → load → predict, then print the predictions."""
    _configure_logging(verbose)
    settings = _settings(
        hub_repo_id=repo_id,
        artifact_name=artifact_name,
        artifact_revision=revision,
        force=force,
        verify_signature=verify,
        public_key_path=public_key_path,
        signer=signer,
        key_source=key_source,
        key_path=key_path,
        key_env_var=key_env_var,
        prompt=prompt,
        top_k=top_k,
        work_dir=work_dir,
        metrics=metrics,
    )
    wiring: Wiring = ctx.obj
    predictions = pipeline.run(
        settings,
        wiring.source or HfArtifactSource(settings.token_value()),
        wiring.provider or pipeline.key_provider_for(settings),
    )
    _print_predictions(settings.prompt, predictions)


@dataclass(frozen=True, slots=True)
class Wiring:
    """Adapters injected by tests through `ctx.obj`; `None` selects the real ones."""

    source: ArtifactSource | None
    provider: KeyProvider | None


def _settings(**overrides: Any) -> ConsumerSettings:
    """Environment first, then only the flags the user actually passed."""
    given = {name: value for name, value in overrides.items() if value is not None}
    try:
        return ConsumerSettings(**given)
    except ValidationError as exc:
        raise ConfigError(f"invalid configuration: {_fields(exc)}") from exc


def _fields(exc: ValidationError) -> str:
    return ", ".join(".".join(map(str, error["loc"])) or "<root>" for error in exc.errors())


def _print_predictions(prompt: str, predictions: list[Prediction]) -> None:
    table = Table(title=f"prompt: {prompt}")
    table.add_column("#", justify="right")
    table.add_column("token", style="bold")
    table.add_column("probability", justify="right")
    for rank, prediction in enumerate(predictions, start=1):
        table.add_row(str(rank), prediction.token, f"{prediction.probability:.3f}")
    out.print(table)


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO, format="%(levelname)s %(message)s"
    )
    for name in ("httpx", "huggingface_hub", "transformers"):
        logging.getLogger(name).setLevel(logging.DEBUG if verbose else logging.WARNING)


def main(
    argv: list[str] | None = None,
    *,
    source: ArtifactSource | None = None,
    provider: KeyProvider | None = None,
) -> int:
    """Run the CLI and return the process exit code (never raises `SystemExit`)."""
    try:
        app(args=argv, standalone_mode=False, obj=Wiring(source, provider))
    except typer.TyperException as exc:
        err.print(f"[red]error:[/red] {exc.format_message()}")
        return exc.exit_code
    except ConsumerError as exc:
        log.error("%s", exc)
        return exc.exit_code
    except Exception:
        log.exception("unexpected failure")
        return 1
    return 0
