#!/usr/bin/env bash
# K9-AIF EOC — Start app_backend (Container 1 / Process 1)
#
# FastAPI + web UI.  Publishes inbound events to Kafka eoc-events (K9_KAFKA_MODE=1).
# Results arrive back via SSE from eoc-results topic.
#
# Prerequisites:
#   - .venv activated OR this script activates it automatically
#   - Kafka running at 192.168.1.98:9092 (RHEL host)
#   - PostgreSQL running at 192.168.1.98:5432
#   - Neo4j running at 192.168.1.98:7687
#   - Ollama running at 192.168.1.98:11434
#
# Run:
#   ./start_eoc_app.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# ── Activate venv ─────────────────────────────────────────────────────────────
VENV="$REPO_ROOT/.venv"
if [[ -f "$VENV/bin/activate" ]]; then
  source "$VENV/bin/activate"
  echo "[app_backend] venv: $VENV"
else
  echo "[app_backend] WARNING: .venv not found at $REPO_ROOT — using system Python"
fi

# ── Load .env (without overriding existing shell exports) ────────────────────
ENV_FILE="$SCRIPT_DIR/.env"
if [[ -f "$ENV_FILE" ]]; then
  set -a
  source "$ENV_FILE"
  set +a
  echo "[app_backend] .env loaded from $ENV_FILE"
fi

# ── Runtime env ───────────────────────────────────────────────────────────────
export PYTHONPATH="$REPO_ROOT"
export K9_ENV="${K9_ENV:-development}"

# Kafka mode: publish events to eoc-events, consume eoc-results for SSE.
# Set to 0 to run in direct mode (EOCOrchestrator in-process, no Kafka needed).
export K9_KAFKA_MODE="${K9_KAFKA_MODE:-1}"

echo "------------------------------------------------------------"
echo " K9-AIF EOC — app_backend"
echo " PYTHONPATH : $REPO_ROOT"
echo " K9_KAFKA_MODE: $K9_KAFKA_MODE"
echo " URL        : http://localhost:8000/"
echo "------------------------------------------------------------"

cd "$REPO_ROOT"
exec uvicorn \
  "examples.K9X_Enterprise_Insurance_OperationsCenter.api.app:app" \
  --host 0.0.0.0 \
  --port 8000 \
  --reload \
  --log-level info
