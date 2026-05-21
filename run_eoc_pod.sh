#!/bin/bash
# SPDX-License-Identifier: Apache-2.0
# K9-AIF Enterprise Insurance Operations Center
# Podman pod launcher (Rootful) — RHEL
#
# Creates the 'eoc-dev' pod with 3 containers from a single image:
#   eoc-app-backend    — FastAPI + Web UI  (port 8000)
#   eoc-orchestrator   — Kafka consumer → squads → agents → eoc-results
#   eoc-router         — Kafka router: eoc-events → domain topics
#
# Prerequisites (running on RHEL host):
#   - Kafka at 192.168.1.98:9092
#   - PostgreSQL at 192.168.1.98:5432
#   - Neo4j at 192.168.1.98:7687
#   - Ollama at 192.168.1.98:11434
#
# Usage:
#   cd ~/k9-aif-framework
#   bash run_eoc_pod.sh

set -e

# -----------------------------------------------------------
# Configuration
# -----------------------------------------------------------
REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
EOC_DIR="$REPO_ROOT/examples/K9X_Enterprise_Insurance_OperationsCenter"

IMAGE_NAME="k9-aif-eoc:latest"
POD_NAME="eoc-dev"

HOST_IP="192.168.1.98"
HOST_PORT=8010

VOLUME_BASE="/home/container_storage/volumes/eoc-dev"

# -----------------------------------------------------------
echo "--------------------------------------------------"
echo "  Building K9-AIF EOC image: $IMAGE_NAME"
echo "--------------------------------------------------"
cd "$REPO_ROOT"
sudo podman build -t $IMAGE_NAME .

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
sudo mkdir -p ${VOLUME_BASE}/{config,data,logs}
sudo chmod -R 777 ${VOLUME_BASE}

# -----------------------------------------------------------
echo
echo "  Starting containers inside pod: $POD_NAME"
echo "--------------------------------------------------"

# Container 1 — API backend + Web UI
echo "  Launching eoc-app-backend..."
sudo podman run -d \
  --name eoc-app-backend \
  --pod $POD_NAME \
  -e K9_ENV=production \
  -e K9_KAFKA_MODE=1 \
  -v ${VOLUME_BASE}/config:/app/examples/K9X_Enterprise_Insurance_OperationsCenter/config \
  -v ${VOLUME_BASE}/data:/app/examples/K9X_Enterprise_Insurance_OperationsCenter/data \
  -v ${VOLUME_BASE}/logs:/app/logs \
  --restart=on-failure:3 \
  $IMAGE_NAME \
  bash examples/K9X_Enterprise_Insurance_OperationsCenter/start_eoc_app.sh

# Container 2 — Orchestrator process (squads + agents)
echo "  Launching eoc-orchestrator..."
sudo podman run -d \
  --name eoc-orchestrator \
  --pod $POD_NAME \
  -e K9_ENV=production \
  -v ${VOLUME_BASE}/config:/app/examples/K9X_Enterprise_Insurance_OperationsCenter/config \
  -v ${VOLUME_BASE}/data:/app/examples/K9X_Enterprise_Insurance_OperationsCenter/data \
  -v ${VOLUME_BASE}/logs:/app/logs \
  --restart=on-failure:3 \
  $IMAGE_NAME \
  bash examples/K9X_Enterprise_Insurance_OperationsCenter/start_eoc_orchestrator.sh

# Container 3 — EOC Router (eoc-events → domain topics)
echo "  Launching eoc-router..."
sudo podman run -d \
  --name eoc-router \
  --pod $POD_NAME \
  -e K9_ENV=production \
  -v ${VOLUME_BASE}/config:/app/examples/K9X_Enterprise_Insurance_OperationsCenter/config \
  -v ${VOLUME_BASE}/data:/app/examples/K9X_Enterprise_Insurance_OperationsCenter/data \
  -v ${VOLUME_BASE}/logs:/app/logs \
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
