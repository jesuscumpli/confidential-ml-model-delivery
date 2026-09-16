#!/usr/bin/env bash
# Delete the local kind cluster.
#
#   scripts/kind-down.sh
set -euo pipefail

: "${CLUSTER_NAME:=confidential-ml}"
kind delete cluster --name "${CLUSTER_NAME}"