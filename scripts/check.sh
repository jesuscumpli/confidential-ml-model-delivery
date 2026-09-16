#!/usr/bin/env bash
# Run lint, format check, type check and tests in every workspace member.
# One workspace sync at the root installs all members and dev tools; the shared
# environment is then reused for each member's checks.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECTS=(
  packages/confidential-crypto
  services/producer
  services/consumer
  benchmarks
)

echo "==> syncing the workspace (root)"
uv sync --quiet --all-extras --all-groups --all-packages

for project in "${PROJECTS[@]}"; do
  echo "==> ${project}"
  (
    cd "${ROOT}/${project}"
    uv run --no-sync ruff check .
    uv run --no-sync ruff format --check .
    uv run --no-sync mypy src tests
    uv run --no-sync pytest -q
  )
done

echo "==> tests/integration (both services, fake Hub)"
(
  cd "${ROOT}"
  uv run --no-sync ruff check tests
  uv run --no-sync ruff format --check tests
  uv run --no-sync mypy tests
  uv run --no-sync pytest -q
)
echo "All checks passed."