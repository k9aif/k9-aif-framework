#!/bin/bash
# K9-AIF n8n Hello World — start the FastAPI server

set -e

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

source .venv/bin/activate

echo "Starting K9-AIF n8n Hello World on http://0.0.0.0:8001"
echo "  POST /run  — invoke the HelloWorldAgent pipeline"
echo "  GET  /health — health check"
echo ""

uvicorn examples.n8n_helloworld.api.app:app --host 0.0.0.0 --port 8001 --reload
