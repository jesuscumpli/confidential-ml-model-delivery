# AGENTS.md

Single source of agent instructions for this repository.

## Project overview

Confidential ML model delivery proof-of-concept. A **producer** encrypts a
Hugging Face model artifact (Layer 1) and optionally signs it
(Layer 2), then publishes it to the Hugging Face Hub. A **consumer**
running in Kubernetes retrieves the artifact, verifies the signature (Layer 2),
gets the decryption key from a Kubernetes Secret (Layer 1), decrypts, restores
and loads the model, and runs a minimal inference.

The authoritative spec lives in `docs/plan.md` and `docs/test_assignment.md`;
the per-milestone checklist is `docs/tasks.md`. Start there before making changes.

## Repository layout

```text
packages/confidential-crypto/  # shared crypto core: format, registry, ciphers, signers
services/producer/             # independent uv Python project (publishes artifacts)
services/consumer/             # independent uv Python project (retrieves artifacts)
benchmarks/                    # crypto evaluation: runners + Jupyter notebook
tests/integration/             # end-to-end integration tests against both services
k8s/                           # Kubernetes manifests
scripts/                       # helper scripts (check.sh runs all quality gates)
docs/                          # plan, tasks, decision records, architecture, security, layers docs
```

Producer and consumer are separate projects on purpose: independent dependency
graphs, Docker images, and trust boundaries. Do not introduce a shared Python
package unless duplication becomes substantial and clearly justified.

The one justified shared package is `packages/confidential-crypto`: the artifact
format and algorithm registry must be identical on both sides. It contains no
Hub, Kubernetes or model-loading code. Algorithms used only by the evaluation
phase live behind its `bench` extra and never ship in service images.

## Crypto evaluation decisions

The algorithms were measured in `benchmarks/` and the results justify the registry
defaults; the formal record is `docs/crypto-evaluation.md` and a plain-language
Spanish summary is `docs/crypto-decision.md`.

- Cipher: `aes-256-gcm` (top-ranked; fastest and most standard, nonce risk controllable).
- Signer: `ed25519` (top-ranked; deterministic, constant-time, minimal signatures).
- Encryption mode: **chunked (format v2) is the production default** because LLM
  artifacts are multi-GB and one-shot would need ~2x the artifact in RAM. Chunked keeps
  memory at O(chunk), matches one-shot's security guarantees, and measured no throughput
  penalty file-to-file. `streaming-gcm` was rejected (releases plaintext before auth).
- The consumer dispatches on the authenticated version byte, so one-shot (v1) remains
  available per artifact for small models; the producer config selects the mode.

## Coding standards

- Everything must be written in English: identifiers, strings, comments,
  commit messages, and documentation.
  Exception: user-facing documentation explicitly requested in Spanish by the
  maintainers (e.g. `docs/crypto-decision.md`) stays in Spanish.
- Follow good programming practices: type hints, small focused functions,
  explicit error handling, no dead code.
- Do not add excessive comments. Only short essential comments that explain
  *why*, never restate *what* the code does.
- Add docstrings only where they add value: public modules, public functions,
  classes and non-trivial logic.
- Keep Python projects formatted, linted and typed:
  - `ruff` for linting and formatting;
  - `mypy` in strict mode for type checking;
  - `pytest` for tests.
- Security tests are first-class tests, not optional examples: cover both
  positive and negative security paths.
- Never commit secrets, keys, tokens, or decrypted model artifacts.
- No key material in logs, error messages, or test fixtures.
- Configuration: use `pydantic-settings` for typed settings from environment
  variables in the services (`services/*`); mark sensitive fields as `SecretStr`;
  never `model_dump`/print a settings object wholesale. Keep decryption key
  material out of settings and out of env vars: it comes from a file-mounted
  Kubernetes Secret through the consumer's `KeyProvider` (or a user-given path in
  the producer), never from `pydantic-settings`.
- Python packages: use `pydantic-settings` only in the services, never in
  `packages/confidential-crypto` (the shared package stays dependency-light).

## Working with uv

Each project (`packages/confidential-crypto`, `services/*`, `benchmarks`) is its
own uv project. Run commands from the project directory:

```bash
cd services/producer
uv sync            # install deps + dev deps
uv run pytest      # run tests
uv run ruff check  # lint
uv run ruff format --check
uv run mypy src
```

`scripts/check.sh` runs all of the above in every project; it must pass before
a milestone is considered done.

Docker images are built from the repository root so the shared package is in
the build context:

```bash
docker build -f services/producer/Dockerfile -t producer:dev .
docker build -f services/consumer/Dockerfile -t consumer:dev .
```

## Milestones / status

See the implementation order in `docs/plan.md` (Section 8). Keep the system
runnable at each milestone; do not accumulate unverified infrastructure
changes. Do not jump to Layer 3 before Layers 1 and 2 are complete, tested,
and documented.

## Definition of done

The mandatory submission is complete when every unchecked item in
`docs/plan.md` Section 7 is satisfied. No secret material is committed.