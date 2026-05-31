#!/bin/bash
# K9-AIF n8n Hello World — build and run as a Podman container
# Run from within the n8n_helloworld/ folder:
#   cd examples/n8n_helloworld && bash build.sh

set -e

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$APP_DIR"

IMAGE_NAME="k9aif-n8n-helloworld"
CONTAINER_NAME="k9aif-helloworld"
PORT=8001

echo "=== Building $IMAGE_NAME ==="
podman build -t $IMAGE_NAME .

echo ""
echo "=== Stopping existing container (if any) ==="
podman rm -f $CONTAINER_NAME 2>/dev/null || true

echo ""
echo "=== Starting $CONTAINER_NAME on port $PORT ==="
podman run -d \
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
