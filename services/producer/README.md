# producer

Packages a Hugging Face model deterministically, encrypts it (Layer 1) and publishes
only the encrypted artifact to the Hugging Face Hub. Layer 2 signing is added in a
later milestone.

## Usage

```bash
uv sync
uv run producer gen-key --out ../../var/secrets/model.key   # raw 32-byte key, mode 0600
uv run producer package                                 # download + deterministic model.tar
uv run producer encrypt --key-path ../../var/secrets/model.key
HF_TOKEN=... uv run producer publish --repo-id <user>/<repo>
HF_TOKEN=... uv run producer run --key-path ... --repo-id ...   # all three steps
```

Every flag is optional and overrides the matching `PRODUCER_*` variable; `--help` on
any command lists the flags grouped by concern, with their default and variable:

```bash
uv run producer run --help
uv run producer run --interactive                  # prompts for each value (Enter keeps the default)
uv run producer run --model-id distilbert-base-uncased --mode one-shot --cipher chacha20-poly1305 ...
uv run producer config                             # effective configuration, token masked
```

Working directory layout (`PRODUCER_WORK_DIR`, default `./var/artifacts`):

```text
var/artifacts/model/            allow-listed model files from the Hub
var/artifacts/model.tar         plaintext package: manifest.json + files, reproducible
var/artifacts/upload/model.enc  the only file that is ever uploaded
```

`publish` refuses any file that does not carry the encrypted-artifact header, so the
plaintext package or the key cannot be pushed by mistake.

## Configuration

Environment variables (CLI flags override them; the key bytes are never a setting):

| Variable | Default | Purpose |
| --- | --- | --- |
| `PRODUCER_MODEL_ID` | `prajjwal1/bert-tiny` | model to package |
| `PRODUCER_MODEL_REVISION` | `main` | branch, tag or commit; the resolved commit goes into `manifest.json` |
| `PRODUCER_HUB_REPO_ID` | — | destination repository |
| `HF_TOKEN` | — | Hub token (`SecretStr`, never logged) |
| `PRODUCER_PRIVATE_REPO` | `true` | create the destination as private |
| `PRODUCER_ARTIFACT_NAME` | `model.enc` | name of the encrypted file |
| `PRODUCER_KEY_PATH` | — | path of the raw/hex key file |
| `PRODUCER_WORK_DIR` | `var/artifacts` | download/package/upload directory |
| `PRODUCER_CIPHER` | `aes-256-gcm` | any production cipher from the registry |
| `PRODUCER_ENCRYPTION_MODE` | `chunked` | `chunked` (format v2) or `one-shot` (v1) |
| `PRODUCER_CHUNK_SIZE` | `1048576` | bytes per chunk in chunked mode |

## Package format

`model.tar` contains `manifest.json` first (`model_id`, resolved `revision`, per-file
`size` and `sha256`), then the allow-listed files (`config.json`, tokenizer files,
`*.safetensors`; `pytorch_model.bin` only when no safetensors weights exist). Entries
are sorted, `mtime` 0, uid/gid 0, mode 0644, relative paths only, so the same input
always yields the same bytes.

## Docker

```bash
docker build -f services/producer/Dockerfile -t producer:dev .   # from the repository root
docker run --rm -e HF_TOKEN -v "$PWD/var/secrets:/secrets:ro" producer:dev \
  run --key-path /secrets/model.key --repo-id <user>/<repo>
```

## Develop

```bash
uv run pytest            # real-Hub test is skipped unless HF_TOKEN and PRODUCER_TEST_REPO_ID are set
uv run ruff check
uv run mypy src tests
```
