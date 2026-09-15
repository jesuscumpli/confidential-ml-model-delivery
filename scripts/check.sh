#!/usr/bin/env bash
# Run lint, format check, type check and tests in every uv project.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECTS=(
  packages/confidential-crypto
  services/producer
  services/consumer
  benchmarks
)

for project in "${PROJECTS[@]}"; do
  echo "==> ${project}"
  (
    cd "${ROOT}/${project}"
    uv sync --quiet
    uv run ruff check .
    uv run ruff format --check .
    uv run mypy src
    uv run pytest -q
  )
done
echo "All checks passed."
