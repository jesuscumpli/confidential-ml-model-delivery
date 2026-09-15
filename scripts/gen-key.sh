#!/usr/bin/env bash
# Generate a fresh Layer 1 symmetric key file (raw bytes, mode 0600). Never prints the key.
#   scripts/gen-key.sh [KEY_PATH]   (default: ./secrets/model.key)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
KEY_PATH="${1:-${ROOT}/secrets/model.key}"

uv run --project "${ROOT}/services/producer" producer gen-key --out "${KEY_PATH}"
