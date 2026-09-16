# Confidential ML Model Delivery

Proof-of-concept for confidential distribution of a Hugging Face ML model.

A **producer** encrypts a model artifact (AES-256-GCM, Layer 1) and optionally
signs it (Ed25519, Layer 2), then publishes it to the Hugging Face Hub. A
**consumer** retrieves the artifact, verifies the signature, obtains the decryption
key from a Kubernetes Secret, decrypts, restores and loads the model, and runs one
minimal inference. The algorithm choices are justified with measurements in
`docs/crypto-evaluation.md`; the original assignment is `docs/test_assignment.md`.

```text
producer ──encrypt──▶ Hugging Face Hub ◀──download / decrypt── consumer (Kubernetes Job)
     │                                    ▲
     └────────────── key ────────────────┘   (Kubernetes Secret, Layer 1)
```

## Repository layout

```text
pyproject.toml                 # uv workspace root: one shared environment for all members
uv.lock                        # single lockfile for the whole workspace
packages/confidential-crypto/  # shared crypto core: artifact format, registry, ciphers, signers
services/producer/             # uv workspace member: encrypts and publishes artifacts
services/consumer/             # uv workspace member: retrieves, decrypts, loads, infers
benchmarks/                    # uv workspace member: crypto evaluation runners + notebook
k8s/                           # Kubernetes manifests (namespace, consumer Job)
scripts/                       # entry points: gen-key, kind-setup, demo, kind-down, check
docs/                          # plan, tasks, crypto evaluation/decision, assignment
tests/integration/             # end-to-end integration tests (planned)
```

## Prerequisites

- Python 3.12 and [uv](https://docs.astral.sh/uv/) (>= 0.12)
- [Docker](https://www.docker.com/)
- [kind](https://kind.sigs.k8s.io/) + `kubectl` (only for the Kubernetes part)
- A Hugging Face account and token (`HF_TOKEN`) for the publish/download steps

## Quick start

```bash
# 1. Install the whole workspace and run the quality gates — optional but recommended
uv sync --all-extras --all-groups --all-packages
scripts/check.sh

# 2. Local: encrypt a model and publish it to the Hub
scripts/gen-key.sh
HF_TOKEN=<token> uv run producer run \
  --key-path var/secrets/model.key --repo-id <user>/<repo>

# 3. Local: verify the whole flow without Kubernetes
CONSUMER_KEY_PATH=var/secrets/model.key uv run consumer --repo-id <user>/<repo>

# 4. Kubernetes (kind): same flow as a Job with the key in a Secret
scripts/kind-setup.sh
HUB_REPO_ID=<user>/<repo> scripts/demo.sh
```

## Run locally with uv

The root `pyproject.toml` defines a [uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/)
whose members are the crypto package, the producer, the consumer and the benchmarks.
One sync at the root installs every member and the shared dev tools into a single
environment, so all commands run from the repository root:

```bash
uv sync --all-extras --all-groups --all-packages   # install everything once
```

Producer (package → encrypt → publish):

```bash
uv run producer gen-key --out var/secrets/model.key     # or scripts/gen-key.sh
HF_TOKEN=<token> uv run producer run \
  --key-path var/secrets/model.key --repo-id <user>/<repo>
```

Individual steps are available too (`producer package`, `producer encrypt`,
`producer publish`), plus `producer config` to print the effective configuration and
`producer run --interactive` to be prompted for every value (model, repository, cipher,
chunked/one-shot mode, key file). Any command's `--help` lists its flags with defaults
and the `PRODUCER_*` variable each one overrides. The only file ever uploaded is
`var/artifacts/upload/model.enc`; the plaintext package and key are never published.

Consumer (download → decrypt → restore → load → fill-mask inference):

```bash
CONSUMER_KEY_PATH=var/secrets/model.key \
  uv run consumer --repo-id <user>/<repo>
```

Exit codes identify the failing stage: `2` config/key source, `3` download,
`4` signature (Layer 2), `5` decryption, `6` extraction, `7` model load, `8` inference.

The same commands also work from inside a member directory (e.g. `cd services/producer
&& uv run producer ...`), which is convenient when working on one project.

## Run with Docker

Images are built from the repository root so the shared crypto package is in the
build context:

```bash
docker build -f services/producer/Dockerfile -t producer:dev .
docker build -f services/consumer/Dockerfile -t consumer:dev .
```

Producer (all steps, token and key supplied at run time, never baked into the image):

```bash
docker run --rm -e HF_TOKEN -v "$PWD/var/secrets:/secrets:ro" producer:dev \
  run --key-path /secrets/model.key --repo-id <user>/<repo>
```

Consumer:

```bash
docker run --rm -v "$PWD/var/secrets/model.key:/etc/model-key/key:ro" consumer:dev \
  --repo-id <user>/<repo>
```

## Run on Kubernetes (kind)

The consumer runs as a Kubernetes `Job`: one inference, then exit. A failed stage
surfaces as a non-zero exit code. The decryption key lives in a Secret mounted as a
read-only file; the Hub repository id is non-secret configuration.

### 1. Setup — cluster, images, and namespace, in one idempotent script

```bash
scripts/kind-setup.sh
```

This creates the `confidential-ml` kind cluster (if absent), builds both images,
applies `k8s/namespace.yaml`, and loads the consumer image into the cluster.

### 2. Demo — happy path

```bash
HUB_REPO_ID=<user>/<repo> scripts/demo.sh
```

`demo.sh` creates the Secret from `var/secrets/model.key` and a
`consumer-config` ConfigMap (`hub_repo_id`, `artifact_name`), applies
`k8s/consumer-job.yaml`, waits for the Job, and prints the inference result.

### 3. Demo — failure paths

```bash
HUB_REPO_ID=<user>/<repo> scripts/demo.sh negative corrupt   # wrong key ⇒ exit 5
HUB_REPO_ID=<user>/<repo> scripts/demo.sh negative missing   # no Secret ⇒ pod stuck on mount
```

### 4. Teardown

```bash
scripts/kind-down.sh
```

### Manifests overview

`k8s/namespace.yaml` creates the namespace with the `restricted` Pod Security
profile. `k8s/consumer-job.yaml` is the workload. The Secret and ConfigMap are
generated at run time by `scripts/demo.sh` — nothing secret is committed. Their
runtime shape:

```yaml
# Secret (from the key file, 32 raw bytes):
apiVersion: v1
kind: Secret
metadata: { name: model-key, namespace: confidential-ml }
data:
  key: <base64 of the key bytes>

# ConfigMap:
apiVersion: v1
kind: ConfigMap
metadata: { name: consumer-config, namespace: confidential-ml }
data:
  hub_repo_id: <user>/<repo>
  artifact_name: model.enc
```

## Quality gates

`scripts/check.sh` runs `ruff check`, `ruff format --check`, `mypy` and `pytest`
in all four uv projects (crypto package, producer, consumer, benchmarks). It must
pass before a milestone is considered done.

## Documentation

- `docs/plan.md` — project plan, milestones, implementation order.
- `docs/tasks.md` — per-milestone checklist with the decisions taken.
- `docs/crypto-evaluation.md` — how AES-256-GCM and Ed25519 (and chunked mode)
  were selected, with measurements.
- `docs/crypto-decision.md` — plain-language (Spanish) summary of the decisions.
- `docs/test_assignment.md` — the original assignment text.