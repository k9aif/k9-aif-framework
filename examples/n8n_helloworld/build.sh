#!/bin/bash
# Build and run K9-AIF n8n Hello World as a Podman container

set -e

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

IMAGE_NAME="k9aif-n8n-helloworld"
CONTAINER_NAME="k9aif-helloworld"
PORT=8001

echo "=== Building $IMAGE_NAME ==="
sudo podman build -f examples/n8n_helloworld/Containerfile -t $IMAGE_NAME .

echo ""
echo "=== Stopping existing container (if any) ==="
sudo podman rm -f $CONTAINER_NAME 2>/dev/null || true

echo ""
echo "=== Starting $CONTAINER_NAME on port $PORT ==="
sudo podman run -d \
  --name $CONTAINER_NAME \
  -p $PORT:$PORT \
  --env K9_ENV=development \
  $IMAGE_NAME

echo ""
echo "=== Done ==="
echo "K9-AIF Hello World running at http://0.0.0.0:$PORT"
echo ""
echo "Test with:"
echo "  curl -X POST http://localhost:$PORT/run -H 'Content-Type: application/json' -d '{\"caller\":\"n8n\"}'"
