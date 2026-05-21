#!/bin/bash
# SPDX-License-Identifier: Apache-2.0
# K9-AIF EOC — Build container image
#
# Usage:
#   bash build.sh

set -e

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
IMAGE_NAME="k9-aif-eoc:latest"

echo "--------------------------------------------------"
echo "  Building: $IMAGE_NAME"
echo "--------------------------------------------------"
cd "$REPO_ROOT"
sudo podman build -t $IMAGE_NAME .
echo "--------------------------------------------------"
echo "  Done: $IMAGE_NAME"
echo "--------------------------------------------------"
