#!/usr/bin/env bash
# Deploy and verify the consumer Job end to end.
#
#   HUB_REPO_ID=<user>/<repo> scripts/demo.sh                       # happy path
#   HUB_REPO_ID=<user>/<repo> scripts/demo.sh negative corrupt      # wrong key, exit 5
#   HUB_REPO_ID=<user>/<repo> scripts/demo.sh negative missing      # secret absent, stuck
#
# Requires: scripts/kind-setup.sh already run, the artifact already published by the
# producer, and the decryption key at KEY_PATH (see scripts/gen-key.sh). A fresh
# Secret and ConfigMap are created from these values on every run.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -z "${HUB_REPO_ID:-}" ]]; then
  echo "usage: HUB_REPO_ID=<user>/<repo> scripts/demo.sh [negative [missing|corrupt]]" >&2
  echo "       HUB_REPO_ID points at the Hub repository holding the encrypted artifact" >&2
  exit 2
fi
: "${CLUSTER_NAME:=confidential-ml}"
: "${NAMESPACE:=confidential-ml}"
: "${SECRET_NAME:=model-key}"
: "${KEY_PATH:=${ROOT}/var/secrets/model.key}"
: "${ARTIFACT_NAME:=model.enc}"

KUBECTL=(kubectl --context "kind-${CLUSTER_NAME}" --namespace "${NAMESPACE}")

apply_config() {
  "${KUBECTL[@]}" create configmap consumer-config \
    --from-literal=hub_repo_id="${HUB_REPO_ID}" \
    --from-literal=artifact_name="${ARTIFACT_NAME}" \
    --dry-run=client -o yaml | "${KUBECTL[@]}" apply -f -
  "${KUBECTL[@]}" delete job consumer --ignore-not-found --wait=true
}

apply_job() {
  "${KUBECTL[@]}" apply -f "${ROOT}/k8s/consumer-job.yaml"
}

wait_for_job() {
  local condition="$1" timeout="$2"
  if "${KUBECTL[@]}" wait --for=condition="${condition}" job/consumer --timeout="${timeout}" 2>/dev/null; then
    echo "---- consumer logs ----"
    "${KUBECTL[@]}" logs job/consumer || true
    echo "-----------------------"
    echo "job status: ${condition}"
  else
    echo "---- pod status ----"
    "${KUBECTL[@]}" get pods -l app=consumer -o wide || true
    echo "job status: timed out waiting for ${condition}"
    return 1
  fi
}

run_happy_path() {
  if [[ ! -f "${KEY_PATH}" ]]; then
    echo "key file not found: ${KEY_PATH} (run scripts/gen-key.sh first)" >&2
    exit 1
  fi
  echo "==> creating Secret ${SECRET_NAME} from ${KEY_PATH}"
  "${KUBECTL[@]}" create secret generic "${SECRET_NAME}" --from-file=key="${KEY_PATH}" \
    --dry-run=client -o yaml | "${KUBECTL[@]}" apply -f -
  apply_config
  apply_job
  echo "==> waiting for the consumer Job to complete"
  wait_for_job complete 300s
}

run_negative() {
  local variant="${1:-corrupt}"
  if [[ "${variant}" != missing && "${variant}" != corrupt ]]; then
    echo "usage: scripts/demo.sh negative [missing|corrupt]" >&2
    exit 2
  fi
  apply_config
  case "${variant}" in
    missing)
      "${KUBECTL[@]}" delete secret "${SECRET_NAME}" --ignore-not-found
      echo "==> Secret ${SECRET_NAME} deleted: the pod cannot mount the key and never starts"
      ;;
    corrupt)
      local wrong_key
      wrong_key="$(mktemp)"
      trap 'rm -f "${wrong_key}"' EXIT
      head -c 32 /dev/urandom > "${wrong_key}"
      "${KUBECTL[@]}" create secret generic "${SECRET_NAME}" --from-file=key="${wrong_key}" \
        --dry-run=client -o yaml | "${KUBECTL[@]}" apply -f -
      echo "==> Secret replaced with a random key: decryption must fail (exit 5)"
      ;;
  esac
  apply_job
  echo "==> waiting for the consumer Job to fail"
  if wait_for_job failed 90s; then
    exit_code="$("${KUBECTL[@]}" get pods -l app=consumer \
      -o jsonpath='{.items[0].status.containerStatuses[0].state.terminated.exitCode}')"
    echo "job failed as expected (consumer exit code ${exit_code})"
    echo "note: re-run scripts/demo.sh to restore the real Secret"
  else
    echo "job did not finish: pod is stuck (expected for variant=missing)"
  fi
  "${KUBECTL[@]}" delete job consumer --ignore-not-found --wait=true
}

case "${1:-run}" in
  run) run_happy_path ;;
  negative) run_negative "${2:-corrupt}" ;;
  *) echo "usage: scripts/demo.sh [run|negative [missing|corrupt]]" >&2; exit 2 ;;
esac