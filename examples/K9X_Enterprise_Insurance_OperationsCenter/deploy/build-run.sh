#!/usr/bin/env bash
# K9-AIF EOC — Podman build and deploy helper
# Run from the k9-aif-framework repo root on RHEL.
#
# Commands:
#   build        — build the k9-aif-eoc container image
#   secret       — store secrets (Neo4j + Postgres passwords) from .env
#   seed-neo4j   — run eoc_seed.cypher against Neo4j (once)
#   up           — deploy k9-eoc-pod (3 containers)
#   down         — stop and remove the pod
#   status       — show pod and container status
#   logs         — tail app-backend logs
#   logs-router  — tail eoc-router logs
#   logs-orch    — tail eoc-orchestrator logs
#   dev          — quick single-container dev run (direct mode, no Kafka)
#   all          — build + secret + up in one step

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
EOC_DIR="$REPO_ROOT/examples/K9X_Enterprise_Insurance_OperationsCenter"
IMAGE="k9-aif-eoc:latest"
POD_NAME="k9-eoc-pod"

cmd="${1:-help}"

case "$cmd" in

  build)
    echo "Building $IMAGE from $REPO_ROOT ..."
    podman build -t "$IMAGE" \
      -f "$EOC_DIR/Containerfile" \
      "$REPO_ROOT"
    echo "Build complete: $IMAGE"
    ;;

  secret)
    ENV_FILE="$EOC_DIR/.env"
    [[ -f "$ENV_FILE" ]] || { echo "Error: $ENV_FILE not found"; exit 1; }

    # Neo4j password
    NEO4J_PW=$(grep -E '^NEO4J_PASSWORD=' "$ENV_FILE" | cut -d= -f2- | tr -d '[:space:]')
    if podman secret exists neo4j-password 2>/dev/null; then
      podman secret rm neo4j-password
    fi
    printf '%s' "$NEO4J_PW" | podman secret create neo4j-password -
    echo "Secret 'neo4j-password' stored."

    # Postgres password
    PG_PW=$(grep -E '^K9_PG_PASSWORD=' "$ENV_FILE" | cut -d= -f2- | tr -d '[:space:]')
    if [[ -n "$PG_PW" ]]; then
      if podman secret exists pg-password 2>/dev/null; then
        podman secret rm pg-password
      fi
      printf '%s' "$PG_PW" | podman secret create pg-password -
      echo "Secret 'pg-password' stored."
    else
      echo "Warning: K9_PG_PASSWORD not found in .env — pg-password secret not created"
    fi
    ;;

  seed-neo4j)
    NEO4J_URI="${NEO4J_URI:-bolt://192.168.1.98:7687}"
    NEO4J_USER="${NEO4J_USER:-neo4j}"
    echo "Seeding Neo4j at $NEO4J_URI ..."
    cypher-shell -a "$NEO4J_URI" -u "$NEO4J_USER" -p "$NEO4J_PASSWORD" \
      --file "$EOC_DIR/data/eoc_seed.cypher"
    echo "Neo4j seed complete."
    ;;

  up)
    echo "Deploying pod: $POD_NAME (3 containers) ..."
    podman play kube "$SCRIPT_DIR/eoc-pod.yaml" --replace
    echo ""
    echo "Pod running. Containers:"
    podman ps --filter "pod=$POD_NAME" --format "table {{.Names}}\t{{.Status}}\t{{.Command}}"
    echo ""
    HOST_IP=$(hostname -I | awk '{print $1}')
    echo "  Web UI:      http://${HOST_IP}:8000/"
    echo "  API spec:    http://${HOST_IP}:8000/docs"
    echo "  Health:      http://${HOST_IP}:8000/health"
    echo ""
    echo "Logs:"
    echo "  podman logs -f ${POD_NAME}-app-backend"
    echo "  podman logs -f ${POD_NAME}-eoc-router"
    echo "  podman logs -f ${POD_NAME}-eoc-orchestrator"
    ;;

  down)
    echo "Stopping pod: $POD_NAME ..."
    podman play kube "$SCRIPT_DIR/eoc-pod.yaml" --down || true
    echo "Pod stopped."
    ;;

  status)
    echo "=== Pod ==="
    podman pod ps --filter "name=$POD_NAME"
    echo ""
    echo "=== Containers ==="
    podman ps -a --filter "pod=$POD_NAME" \
      --format "table {{.Names}}\t{{.Status}}\t{{.RestartCount}}\t{{.Command}}"
    ;;

  logs)
    podman logs -f "${POD_NAME}-app-backend"
    ;;

  logs-router)
    podman logs -f "${POD_NAME}-eoc-router"
    ;;

  logs-orch)
    podman logs -f "${POD_NAME}-eoc-orchestrator"
    ;;

  dev)
    # Quick dev run — single container, direct mode (no Kafka), live reload.
    # All external services are accessed via --add-host.
    echo "Starting dev server (direct mode, no Kafka) ..."
    podman run --rm \
      -p 8000:8000 \
      --env-file "$EOC_DIR/.env" \
      --add-host rhel-host:192.168.1.98 \
      -v "$REPO_ROOT:/app:ro,z" \
      -e PYTHONPATH=/app \
      -e K9_ENV=development \
      --name eoc-dev \
      python:3.11-slim \
      uvicorn \
        "examples.K9X_Enterprise_Insurance_OperationsCenter.api.app:app" \
        --host 0.0.0.0 --port 8000 --reload
    ;;

  all)
    "$0" build
    "$0" secret
    "$0" up
    ;;

  help|*)
    echo "Usage: $0 <command>"
    echo ""
    echo "Commands:"
    echo "  build        — build the Podman image (k9-aif-eoc:latest)"
    echo "  secret       — store NEO4J_PASSWORD + K9_PG_PASSWORD from .env as Podman secrets"
    echo "  seed-neo4j   — run eoc_seed.cypher against Neo4j (run once after Neo4j is up)"
    echo "  up           — deploy k9-eoc-pod (3 containers: app_backend, eoc_router, eoc_orchestrator)"
    echo "  down         — stop and remove the pod"
    echo "  status       — show pod and container status"
    echo "  logs         — tail app-backend logs"
    echo "  logs-router  — tail eoc-router logs"
    echo "  logs-orch    — tail eoc-orchestrator logs"
    echo "  dev          — quick dev run (single container, direct mode, no Kafka)"
    echo "  all          — build + secret + up in one step"
    ;;

esac
