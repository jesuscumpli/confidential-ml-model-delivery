#!/usr/bin/env bash
# Create (or update) the Kubernetes Secret holding the Layer 1 decryption key from a key file.
#   scripts/create-k8s-secret.sh [KEY_PATH]
# Environment: NAMESPACE (default confidential-ml), SECRET_NAME (default model-key).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
KEY_PATH="${1:-${ROOT}/secrets/model.key}"
NAMESPACE="${NAMESPACE:-confidential-ml}"
SECRET_NAME="${SECRET_NAME:-model-key}"

if [[ ! -f "${KEY_PATH}" ]]; then
  echo "key file not found: ${KEY_PATH} (run scripts/gen-key.sh first)" >&2
  exit 1
fi

kubectl create secret generic "${SECRET_NAME}" \
  --namespace "${NAMESPACE}" \
  --from-file=key="${KEY_PATH}" \
  --dry-run=client -o yaml | kubectl apply -f -
echo "secret ${SECRET_NAME} applied in namespace ${NAMESPACE} (key file: ${KEY_PATH})"
