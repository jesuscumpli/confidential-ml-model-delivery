#!/usr/bin/env bash
# Generate a fresh Layer 2 signing key pair (PEM). The private key stays with the
# producer (mode 0600); the public key is what the consumer's ConfigMap carries.
#   scripts/gen-signing-keypair.sh [PRIVATE_KEY_PATH]   (default: ./var/secrets/signing.key;
#                                                        public key: <same>.pub)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PRIVATE_PATH="${1:-${ROOT}/var/secrets/signing.key}"

uv run --project "${ROOT}" producer gen-signing-keypair --out "${PRIVATE_PATH}"
