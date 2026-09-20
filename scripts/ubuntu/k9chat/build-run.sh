#!/usr/bin/env bash
# k9chat — build and run helper (single container, no pod needed)
# Run from anywhere on the Podman host (no sudo needed to invoke -- the
# script escalates internally). Mirrors k9x_mcp_server's ubuntu/build-
# run.sh structure (build/start/stop/logs/all).
#
# Build context is the k9-aif-framework repo root (three levels up from
# this script: scripts/ubuntu/k9chat/ -> repo root), since the image needs
# both k9_aif_abb/ and examples/k9chat/ together -- see the Containerfile.
#
# Runs rootful (sudo podman), matching the k9x_mcp_server/studiox_ibm
# precedent. USER 1001 in the Containerfile still applies inside the
# container regardless of how it was launched.
#
# Requires examples/k9chat/.env to already exist on the host (copy
# examples/k9chat/.env.example there and fill in your own Ollama host,
# GPU telemetry URL, etc. -- start refuses to run without it).
#
# Commands:
#   build   — build the k9chat container image
#   start   — start the container (port 7777 by default, override with HOST_PORT)
#   stop    — stop the container
#   logs    — tail logs
#   seed    — run seed_knowledge_base.py once against the mounted data volume
#   all     — build + start

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
K9CHAT_DIR="$REPO_ROOT/examples/k9chat"

IMAGE="k9chat:latest"
CONTAINER="k9chat"
HOST_PORT="${HOST_PORT:-7777}"

cmd="${1:-help}"

case "$cmd" in

  build)
    echo "Building $IMAGE (context: $REPO_ROOT) ..."
    cd "$REPO_ROOT"
    sudo podman build -t "$IMAGE" -f scripts/ubuntu/k9chat/Containerfile .
    echo "Build complete: $IMAGE"
    ;;

  start)
    if [[ ! -f "$K9CHAT_DIR/.env" ]]; then
      echo "Missing $K9CHAT_DIR/.env -- copy examples/k9chat/.env.example" \
           "there and fill it in first (Ollama host, GPU telemetry URL, etc.)."
      exit 1
    fi
    echo "Starting $CONTAINER on port $HOST_PORT ..."
    sudo podman rm -f "$CONTAINER" 2>/dev/null || true
    mkdir -p "$K9CHAT_DIR/data"
    sudo podman run -d \
      --name "$CONTAINER" \
      --restart=always \
      -p "${HOST_PORT}:7777" \
      --env-file "$K9CHAT_DIR/.env" \
      -e K9CHAT_CHROMA_PATH=/app/data/.chroma \
      -e K9CHAT_PROJECTS_DB=/app/data/k9chat_projects.db \
      -v "$K9CHAT_DIR/data:/app/data:Z" \
      "$IMAGE"
    echo ""
    HOST_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
    HOST_IP="${HOST_IP:-localhost}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  k9chat"
    echo "  UI: http://${HOST_IP}:${HOST_PORT}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    ;;

  stop)
    echo "Stopping $CONTAINER ..."
    sudo podman stop "$CONTAINER" 2>/dev/null || true
    echo "Stopped."
    ;;

  logs)
    sudo podman logs -f "$CONTAINER"
    ;;

  seed)
    if [[ ! -f "$K9CHAT_DIR/.env" ]]; then
      echo "Missing $K9CHAT_DIR/.env -- see 'start' for setup."
      exit 1
    fi
    echo "Seeding the knowledge base into the mounted data volume ..."
    mkdir -p "$K9CHAT_DIR/data"
    sudo podman run --rm \
      --env-file "$K9CHAT_DIR/.env" \
      -e K9CHAT_CHROMA_PATH=/app/data/.chroma \
      -v "$K9CHAT_DIR/data:/app/data:Z" \
      "$IMAGE" python -m examples.k9chat.seed_knowledge_base
    ;;

  all)
    "$0" build
    "$0" start
    ;;

  help|*)
    echo "Usage: $0 <command>"
    echo ""
    echo "Commands:"
    echo "  build   — build the Podman image ($IMAGE)"
    echo "  start   — start the container (port ${HOST_PORT}, override with HOST_PORT=...)"
    echo "  stop    — stop the container"
    echo "  logs    — tail logs"
    echo "  seed    — run seed_knowledge_base.py once against the mounted data volume"
    echo "  all     — build + start"
    ;;

esac
