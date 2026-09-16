#!/usr/bin/env bash
# Render k8s/configmap-public-key.yaml from the producer's public signing key.
# The public key is not secret, but the manifest is generated (and git-ignored) so the
# demo always uses the key pair of the current checkout.
#   PUBLIC_KEY_PATH=var/secrets/signing.pub scripts/gen-configmap-public-key.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
: "${NAMESPACE:=confidential-ml}"
: "${PUBLIC_KEY_PATH:=${ROOT}/var/secrets/signing.pub}"
: "${OUT:=${ROOT}/k8s/configmap-public-key.yaml}"

if [[ ! -f "${PUBLIC_KEY_PATH}" ]]; then
  echo "public key not found: ${PUBLIC_KEY_PATH} (run scripts/gen-signing-keypair.sh first)" >&2
  exit 1
fi
if ! grep -q "BEGIN PUBLIC KEY" "${PUBLIC_KEY_PATH}"; then
  echo "refusing: ${PUBLIC_KEY_PATH} is not a PEM public key" >&2
  exit 1
fi

kubectl create configmap model-public-key --namespace "${NAMESPACE}" \
  --from-file=signing.pub="${PUBLIC_KEY_PATH}" --dry-run=client -o yaml > "${OUT}"
echo "wrote ${OUT}"
