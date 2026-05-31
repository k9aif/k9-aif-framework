#!/bin/bash
# K9-AIF n8n Hello World — run both n8n and n8n-helloworld in a shared pod
# Containers in the same pod share the network — use http://localhost:8001/run in n8n

set -e

POD_NAME="n8n_pod"
PORT_N8N=5678
PORT_K9AIF=8001

echo "=== Stopping existing containers (if any) ==="
podman rm -f n8n-helloworld 2>/dev/null || true
podman rm -f n8n 2>/dev/null || true
podman pod rm -f $POD_NAME 2>/dev/null || true

echo ""
echo "=== Creating pod: $POD_NAME ==="
podman pod create --name $POD_NAME \
  -p $PORT_N8N:$PORT_N8N \
  -p $PORT_K9AIF:$PORT_K9AIF

echo ""
echo "=== Starting n8n ==="
podman run -d \
  --pod $POD_NAME \
  --name n8n \
  docker.io/n8nio/n8n:latest

echo ""
echo "=== Starting n8n-helloworld ==="
podman run -d \
  --pod $POD_NAME \
  --name n8n-helloworld \
  --env K9_ENV=development \
  localhost/n8n-helloworld:latest

HOST_IP=$(hostname -I | awk '{print $1}')
echo ""
echo "=== Done ==="
echo "n8n UI:             http://$HOST_IP:$PORT_N8N"
echo "K9-AIF Hello World: http://$HOST_IP:$PORT_K9AIF/run"
echo ""
echo "In n8n HTTP Request node, set URL to:"
echo "  http://localhost:$PORT_K9AIF/run"
