# consumer

Downloads the encrypted model artifact and its signature from the Hugging Face Hub,
verifies the signature with the producer's public key (Layer 2, a ConfigMap mounted as
a file), decrypts it with the Layer 1 key (a Kubernetes Secret mounted as a file),
restores the model package safely, loads it with Transformers and runs one fill-mask
inference. Runs as a Kubernetes `Job`.

## Usage

```bash
uv sync
CONSUMER_KEY_PATH=../../var/secrets/model.key CONSUMER_PUBLIC_KEY_PATH=../../var/secrets/signing.pub \
  uv run consumer --repo-id <user>/<repo>
uv run consumer --help   # every flag, grouped, with its default and CONSUMER_* variable
```

Flags override the environment: `--artifact-name`, `--revision`,
`--public-key-path`, `--signer`, `--no-verify` (development only), `--key-source file|env`,
`--key-path`, `--key-env-var`, `--prompt`, `--top-k`, `--work-dir`, `-v`.

Exit codes identify the failing stage: `2` configuration/key source, `3` download,
`4` signature (Layer 2), `5` decryption, `6` package extraction, `7` model load,
`8` inference.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `CONSUMER_HUB_REPO_ID` | — (required) | repository holding the artifact |
| `CONSUMER_ARTIFACT_NAME` | `model.enc` | encrypted file name; the signature is `<stem>.sig` (`model.sig`) |
| `CONSUMER_ARTIFACT_REVISION` | `main` | Hub revision to fetch (artifact and signature) |
| `CONSUMER_VERIFY_SIGNATURE` | `true` | `false` skips Layer 2 with a warning (development only) |
| `CONSUMER_PUBLIC_KEY_PATH` | `/etc/model-public-key/signing.pub` | PEM public key from the mounted ConfigMap |
| `CONSUMER_SIGNER` | `ed25519` | expected scheme; envelopes with another scheme are rejected |
| `HF_TOKEN` | — | only needed for private repositories (`SecretStr`) |
| `CONSUMER_KEY_SOURCE` | `file` | `file` (mounted Secret) or `env` (development only) |
| `CONSUMER_KEY_PATH` | `/etc/model-key/key` | key file path for `file` |
| `CONSUMER_KEY_ENV_VAR` | `MODEL_KEY` | variable name for `env` |
| `CONSUMER_WORK_DIR` | private temp dir | where artifact, package and model are restored |
| `CONSUMER_PROMPT` | `The capital of France is [MASK].` | fill-mask prompt |
| `CONSUMER_TOP_K` | `5` | predictions to print |

Key bytes never enter settings, logs or error messages: they are read by a
`KeyProvider` (`FileKeyProvider`, `EnvKeyProvider`; `CdhKeyProvider` is the Layer 3
design stub) at the moment of decryption.

## Safety properties

- Verification runs before decryption by construction: `decrypt_file` only accepts the
  `VerifiedArtifact` returned by `verify_file`, and the decryption key is not even read
  until the signature checked out. A tampered artifact, a tampered signature, a wrong
  public key or a scheme mismatch all exit with code `4` and never touch Layer 1.
- Decryption dispatches on the authenticated version byte (chunked v2 or one-shot v1);
  the plaintext package is renamed into place only after every chunk authenticated.
- Extraction accepts regular files with relative paths only (no links, no `..`, no
  absolute names), requires `manifest.json` first, and verifies every file's SHA-256.
- Models without `model_type` in `config.json` (e.g. `prajjwal1/bert-tiny`) load through
  explicit `BertTokenizer`/`BertForMaskedLM`; others through the `Auto*` classes.

## Docker

```bash
docker build -f services/consumer/Dockerfile -t consumer:dev .   # from the repository root
docker run --rm \
  -v "$PWD/var/secrets/model.key:/etc/model-key/key:ro" \
  -v "$PWD/var/secrets/signing.pub:/etc/model-public-key/signing.pub:ro" \
  consumer:dev --repo-id <user>/<repo>
```

## Develop

```bash
uv run pytest            # `-m slow` downloads bert-tiny and runs a real inference
uv run ruff check
uv run mypy src tests
```
