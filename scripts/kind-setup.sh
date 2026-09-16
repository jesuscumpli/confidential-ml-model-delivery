#!/usr/bin/env bash
# One-shot local Kubernetes setup: create the kind cluster (no-op if it exists),
# build the producer/consumer images, and load the consumer image into the cluster.
# Idempotent: safe to re-run after any change to Dockerfiles or manifests.
#
#   scripts/kind-setup.sh
#
# Environment: CLUSTER_NAME (confidential-ml), NAMESPACE (confidential-ml),
# PRODUCER_IMAGE (producer:dev), CONSUMER_IMAGE (consumer:dev).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
: "${CLUSTER_NAME:=confidential-ml}"
: "${NAMESPACE:=confidential-ml}"
: "${PRODUCER_IMAGE:=producer:dev}"
: "${CONSUMER_IMAGE:=consumer:dev}"

if kind get clusters 2>/dev/null | grep -qx "${CLUSTER_NAME}"; then
  echo "==> kind cluster ${CLUSTER_NAME} already exists"
else
  echo "==> creating kind cluster ${CLUSTER_NAME}"
  kind create cluster --name "${CLUSTER_NAME}" --wait 120s
fi

echo "==> applying namespace ${NAMESPACE}"
kubectl --context "kind-${CLUSTER_NAME}" apply -f "${ROOT}/k8s/namespace.yaml"

echo "==> building images from the repository root (shared crypto package in context)"
docker build -f "${ROOT}/services/producer/Dockerfile" -t "${PRODUCER_IMAGE}" "${ROOT}"
docker build -f "${ROOT}/services/consumer/Dockerfile" -t "${CONSUMER_IMAGE}" "${ROOT}"

echo "==> loading ${CONSUMER_IMAGE} into the cluster"
kind load docker-image "${CONSUMER_IMAGE}" --name "${CLUSTER_NAME}"

echo "==> setup complete: run scripts/demo.sh next"