#!/bin/bash
# SPDX-License-Identifier: Apache-2.0
# K9-AIF Enterprise Insurance Operations Center
# Podman pod launcher (Rootful) — RHEL

set -e

# -----------------------------------------------------------
# Configuration
# -----------------------------------------------------------
REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
EOC_DIR="$REPO_ROOT/examples/K9X_Enterprise_Insurance_OperationsCenter"

IMAGE_NAME="k9-aif-eoc:latest"
POD_NAME="eoc-dev"
ENV_FILE="$EOC_DIR/.env"

HOST_IP="192.168.1.98"
HOST_PORT=8010

VOLUME_BASE="/home/container_storage/volumes/eoc-dev"

# -----------------------------------------------------------
echo "--------------------------------------------------"
echo "  Building K9-AIF EOC image: $IMAGE_NAME"
echo "--------------------------------------------------"
cd "$REPO_ROOT"
sudo podman build -t $IMAGE_NAME \
  -f examples/K9X_Enterprise_Insurance_OperationsCenter/Containerfile .

# -----------------------------------------------------------
echo
echo "  Recreating pod: $POD_NAME"
echo "--------------------------------------------------"
if sudo podman pod exists $POD_NAME; then
  echo "  Removing existing pod..."
  sudo podman pod rm -f $POD_NAME
fi

sudo podman pod create \
  --name $POD_NAME \
  --network bridge \
  -p ${HOST_PORT}:8000

# -----------------------------------------------------------
echo
echo "  Ensuring shared volume directories..."
sudo mkdir -p ${VOLUME_BASE}/{config,data,logs,runtime}
sudo chown -R ravinata:ravinata ${VOLUME_BASE}
sudo chmod -R 777 ${VOLUME_BASE}

echo "  Applying SELinux container labels..."
sudo chcon -Rt container_file_t ${VOLUME_BASE} || true

echo "  Ensuring config volume contains runtime config..."
if [ ! -f "${VOLUME_BASE}/config/config.yaml" ]; then
  cp -av ${EOC_DIR}/config/. ${VOLUME_BASE}/config/
fi

# -----------------------------------------------------------
echo
echo "  Starting containers inside pod: $POD_NAME"
echo "--------------------------------------------------"

# Container 1 — API backend + Web UI
echo "  Launching eoc-app-backend..."
sudo podman run -d \
  --name eoc-app-backend \
  --pod $POD_NAME \
  --env-file $ENV_FILE \
  -e K9_ENV=production \
  -e K9_KAFKA_MODE=1 \
  -v ${VOLUME_BASE}/config:/app/examples/K9X_Enterprise_Insurance_OperationsCenter/config:Z \
  -v ${VOLUME_BASE}/data:/app/examples/K9X_Enterprise_Insurance_OperationsCenter/data:Z \
  -v ${VOLUME_BASE}/logs:/app/logs:Z \
  -v ${VOLUME_BASE}/runtime:/app/runtime:Z \
  --restart=on-failure:3 \
  $IMAGE_NAME \
  bash examples/K9X_Enterprise_Insurance_OperationsCenter/start_eoc_app.sh

# Container 2 — Orchestrator process
echo "  Launching eoc-orchestrator..."
sudo podman run -d \
  --name eoc-orchestrator \
  --pod $POD_NAME \
  --env-file $ENV_FILE \
  -e K9_ENV=production \
  -e K9_KAFKA_MODE=1 \
  -v ${VOLUME_BASE}/config:/app/examples/K9X_Enterprise_Insurance_OperationsCenter/config:Z \
  -v ${VOLUME_BASE}/data:/app/examples/K9X_Enterprise_Insurance_OperationsCenter/data:Z \
  -v ${VOLUME_BASE}/logs:/app/logs:Z \
  -v ${VOLUME_BASE}/runtime:/app/runtime:Z \
  --restart=on-failure:3 \
  $IMAGE_NAME \
  bash examples/K9X_Enterprise_Insurance_OperationsCenter/start_eoc_orchestrator.sh

# Container 3 — EOC Router
echo "  Launching eoc-router..."
sudo podman run -d \
  --name eoc-router \
  --pod $POD_NAME \
  --env-file $ENV_FILE \
  -e K9_ENV=production \
  -e K9_KAFKA_MODE=1 \
  -v ${VOLUME_BASE}/config:/app/examples/K9X_Enterprise_Insurance_OperationsCenter/config:Z \
  -v ${VOLUME_BASE}/data:/app/examples/K9X_Enterprise_Insurance_OperationsCenter/data:Z \
  -v ${VOLUME_BASE}/logs:/app/logs:Z \
  -v ${VOLUME_BASE}/runtime:/app/runtime:Z \
  --restart=on-failure:3 \
  $IMAGE_NAME \
  bash examples/K9X_Enterprise_Insurance_OperationsCenter/start_eoc_router.sh

# -----------------------------------------------------------
echo
echo "--------------------------------------------------"
echo "  All containers up inside pod: $POD_NAME"
echo "--------------------------------------------------"
sudo podman pod ps
sudo podman ps --pod

echo
echo "  Web UI  : http://${HOST_IP}:${HOST_PORT}/webui/"
echo "  API     : http://${HOST_IP}:${HOST_PORT}/docs"
echo "  Health  : http://${HOST_IP}:${HOST_PORT}/health"
echo "  Volumes : ${VOLUME_BASE}"
echo "--------------------------------------------------"