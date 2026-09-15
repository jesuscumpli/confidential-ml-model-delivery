# Confidential ML Model Delivery

Confidential distribution of a Hugging Face ML model, as a proof-of-concept.

A **producer** encrypts a model artifact (AEAD cipher, Layer 1) and optionally
signs it (asymmetric signature, Layer 2), then publishes it to the Hugging Face
Hub. The concrete algorithms are chosen in a measured evaluation phase
(`benchmarks/`, `docs/crypto-evaluation.md`); the expected defaults are
AES-256-GCM and Ed25519. A
**consumer** running in Kubernetes retrieves the artifact, verifies the
signature, obtains the decryption key from a Kubernetes Secret, decrypts,
restores and loads the model, and runs minimal inference.

The authoritative specification lives in `docs/plan.md` and
`docs/test_assignment.md`.

## Repository layout

```text
packages/confidential-crypto/  # shared crypto core: format, registry, ciphers, signers
services/producer/             # independent uv Python project (publishes artifacts)
services/consumer/             # independent uv Python project (retrieves artifacts)
benchmarks/                    # crypto evaluation: runners + Jupyter notebook
tests/integration/             # end-to-end integration tests against both services
k8s/                           # Kubernetes manifests
scripts/                       # helper scripts (check.sh runs all quality gates)
docs/                          # plan, tasks, architecture, security, layers docs
```

## Status

Work in progress. Milestones are tracked in `docs/plan.md` (Section 8) and
`docs/tasks.md`. M0 (four uv projects, shared crypto package skeleton,
benchmarks skeleton, quality gates, Dockerfiles) is done. Nothing functional is
published yet.

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) 0.12.x or newer
- Docker (for image builds)
- Optionally a Kubernetes cluster for the consumer deployment (Layer 4+)

## Local development

Every project (`packages/confidential-crypto`, `services/producer`,
`services/consumer`, `benchmarks`) is an independent uv project; run commands
from its directory:

```bash
cd services/producer
uv sync                 # install deps + dev deps
uv run pytest           # run tests
uv run ruff check       # lint
uv run ruff format      # format
uv run mypy src         # type check
```

`scripts/check.sh` runs lint, format check, type check and tests in all
projects at once.

## Image build

Images are built from the repository root so the shared crypto package is in
the build context:

```bash
docker build -f services/producer/Dockerfile -t producer:dev .
docker build -f services/consumer/Dockerfile -t consumer:dev .
```

## Documentation

- `docs/plan.md` — project plan and milestones.
- `docs/test_assignment.md` — original assignment text.

Architecture, security and layer documentation are added as the milestones
complete (see `docs/plan.md` Section 7).