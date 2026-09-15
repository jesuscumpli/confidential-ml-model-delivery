# AGENTS.md

Single source of agent instructions for this repository.

## Project overview

Confidential ML model delivery proof-of-concept. A **producer** encrypts a
Hugging Face model artifact (Layer 1) and optionally signs it
(Layer 2), then publishes it to the Hugging Face Hub. A **consumer**
running in Kubernetes retrieves the artifact, verifies the signature (Layer 2),
gets the decryption key from a Kubernetes Secret (Layer 1), decrypts, restores
and loads the model, and runs a minimal inference.

The authoritative spec lives in `docs/plan.md` and `docs/test_assignment.md`.
Start there before making changes.

## Repository layout

```text
services/producer/   # independent uv Python project (publishes artifacts)
services/consumer/   # independent uv Python project (retrieves artifacts)
tests/integration/   # end-to-end integration tests against both services
k8s/                 # Kubernetes manifests
scripts/             # helper scripts
docs/                # plan, architecture, security, layers docs
```

Producer and consumer are separate projects on purpose: independent dependency
graphs, Docker images, and trust boundaries. Do not introduce a shared Python
package unless duplication becomes substantial and clearly justified.

## Coding standards

- Everything must be written in English: identifiers, strings, comments,
  commit messages, and documentation.
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

## Working with uv

Each service is its own uv project. Run commands from the service directory:

```bash
cd services/producer
uv sync            # install deps + dev deps
uv run pytest      # run tests
uv run ruff check  # lint
uv run ruff format --check
uv run mypy src
```

## Milestones / status

See the implementation order in `docs/plan.md` (Section 8). Keep the system
runnable at each milestone; do not accumulate unverified infrastructure
changes. Do not jump to Layer 3 before Layers 1 and 2 are complete, tested,
and documented.

## Definition of done

The mandatory submission is complete when every unchecked item in
`docs/plan.md` Section 7 is satisfied. No secret material is committed.