#!/usr/bin/env bash
# Deploy and verify the consumer Job end to end.
#
#   HUB_REPO_ID=<user>/<repo> scripts/demo.sh                       # happy path
#   HUB_REPO_ID=<user>/<repo> scripts/demo.sh negative corrupt      # wrong key, exit 5
#   HUB_REPO_ID=<user>/<repo> scripts/demo.sh negative missing      # secret absent, stuck
#   HUB_REPO_ID=<user>/<repo> scripts/demo.sh negative tamper       # flipped byte, exit 4
#
# Requires: scripts/kind-setup.sh already run, the artifact and its signature already
# published by the producer, the decryption key at KEY_PATH (scripts/gen-key.sh) and
# the public signing key at PUBLIC_KEY_PATH (scripts/gen-signing-keypair.sh). Fresh
# Secret and ConfigMaps are created from these values on every run. PROMPT and TOP_K,
# when set, are added to the ConfigMap and override the consumer's inference defaults.
# The tamper variant
# also needs HF_TOKEN with write access: it publishes a one-byte-flipped copy of the
# artifact to the `tampered` branch of HUB_REPO_ID and points the consumer at it.
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
: "${PUBLIC_KEY_PATH:=${ROOT}/var/secrets/signing.pub}"
: "${ARTIFACT_NAME:=model.enc}"
: "${PROMPT:=}"           # empty: the consumer's default fill-mask prompt
: "${TOP_K:=}"            # empty: the consumer's default (5)
: "${TAMPERED_BRANCH:=tampered}"

KUBECTL=(kubectl --context "kind-${CLUSTER_NAME}" --namespace "${NAMESPACE}")

apply_config() {
  local revision="${1:-main}"
  "${KUBECTL[@]}" create configmap consumer-config \
    --from-literal=hub_repo_id="${HUB_REPO_ID}" \
    --from-literal=artifact_name="${ARTIFACT_NAME}" \
    --from-literal=artifact_revision="${revision}" \
    ${PROMPT:+--from-literal=prompt="${PROMPT}"} \
    ${TOP_K:+--from-literal=top_k="${TOP_K}"} \
    --dry-run=client -o yaml | "${KUBECTL[@]}" apply -f -
  apply_public_key
  "${KUBECTL[@]}" delete job consumer --ignore-not-found --wait=true
}

apply_public_key() {
  echo "==> rendering and applying the public signing key ConfigMap from ${PUBLIC_KEY_PATH}"
  PUBLIC_KEY_PATH="${PUBLIC_KEY_PATH}" NAMESPACE="${NAMESPACE}" \
    "${ROOT}/scripts/gen-configmap-public-key.sh"
  "${KUBECTL[@]}" apply -f "${ROOT}/k8s/configmap-public-key.yaml"
}

apply_job() {
  "${KUBECTL[@]}" apply -f "${ROOT}/k8s/consumer-job.yaml"
}

job_state() {
  local status
  status="$("${KUBECTL[@]}" get job consumer \
    -o jsonpath='{.status.conditions[?(@.status=="True")].type}' 2>/dev/null || true)"
  case "${status}" in
    *Complete*|*SuccessCriteriaMet*) echo complete ;;
    *Failed*) echo failed ;;
    *) echo running ;;
  esac
}

wait_for_job() {
  # Poll instead of `kubectl wait --for=condition=...`: that call only returns when the
  # requested condition appears, so waiting for `complete` on a Job that failed at once
  # would block for the whole timeout. Here any terminal state ends the wait.
  local expected="$1" timeout="$2" deadline state
  deadline=$(( SECONDS + ${timeout%s} ))
  while :; do
    state="$(job_state)"
    if [[ "${state}" != running ]]; then
      break
    fi
    if (( SECONDS >= deadline )); then
      echo "---- pod status ----"
      "${KUBECTL[@]}" get pods -l app=consumer -o wide || true
      echo "job status: timed out waiting for ${expected}"
      return 1
    fi
    sleep 2
  done
  echo "---- consumer logs ----"
  "${KUBECTL[@]}" logs job/consumer || true
  echo "-----------------------"
  echo "job status: ${state}"
  [[ "${state}" == "${expected}" ]]
}

apply_secret() {
  if [[ ! -f "${KEY_PATH}" ]]; then
    echo "key file not found: ${KEY_PATH} (run scripts/gen-key.sh first)" >&2
    exit 1
  fi
  echo "==> creating Secret ${SECRET_NAME} from ${KEY_PATH}"
  "${KUBECTL[@]}" create secret generic "${SECRET_NAME}" --from-file=key="${KEY_PATH}" \
    --dry-run=client -o yaml | "${KUBECTL[@]}" apply -f -
}

run_happy_path() {
  apply_secret
  apply_config
  apply_job
  echo "==> waiting for the consumer Job to complete"
  wait_for_job complete 300s
}

run_negative() {
  local variant="${1:-corrupt}" revision=main
  case "${variant}" in
    missing|corrupt) ;;
    tamper) revision="${TAMPERED_BRANCH}" ;;
    *) echo "usage: scripts/demo.sh negative [missing|corrupt|tamper]" >&2; exit 2 ;;
  esac
  apply_config "${revision}"
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
    tamper)
      apply_secret
      echo "==> publishing a one-byte-flipped ${ARTIFACT_NAME} to ${HUB_REPO_ID}@${TAMPERED_BRANCH}"
      uv run --project "${ROOT}" python "${ROOT}/scripts/publish-tampered.py" "${HUB_REPO_ID}" \
        --artifact-name "${ARTIFACT_NAME}" --branch "${TAMPERED_BRANCH}"
      echo "==> consumer pinned to revision ${TAMPERED_BRANCH}: verification must fail (exit 4)"
      echo "    with the real Secret in place, so a decryption attempt would otherwise succeed"
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
    echo "job did not fail within the timeout: pod is stuck (expected for variant=missing) or it completed"
  fi
  "${KUBECTL[@]}" delete job consumer --ignore-not-found --wait=true
}

case "${1:-run}" in
  run) run_happy_path ;;
  negative) run_negative "${2:-corrupt}" ;;
  *) echo "usage: scripts/demo.sh [run|negative [missing|corrupt|tamper]]" >&2; exit 2 ;;
esac