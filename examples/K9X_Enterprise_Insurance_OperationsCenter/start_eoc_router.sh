#!/usr/bin/env bash
# K9-AIF EOC — Start eoc_router (Container 2 / Process 2)
#
# Consumes events from Kafka topic `eoc-events` and routes each one
# to the correct domain topic (eoc-claims, eoc-fraud, …) via EOCRouter.
#
# Prerequisites:
#   - Kafka running at 192.168.1.98:9092 (RHEL host, configured in config.yaml)
#   - app_backend running (so events arrive on eoc-events)
#
# Run:
#   ./start_eoc_router.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# ── Activate venv ─────────────────────────────────────────────────────────────
VENV="$REPO_ROOT/.venv"
if [[ -f "$VENV/bin/activate" ]]; then
  source "$VENV/bin/activate"
  echo "[eoc_router] venv: $VENV"
else
  echo "[eoc_router] WARNING: .venv not found at $REPO_ROOT — using system Python"
fi

# ── Load .env ─────────────────────────────────────────────────────────────────
ENV_FILE="$SCRIPT_DIR/.env"
if [[ -f "$ENV_FILE" ]]; then
  set -a
  source "$ENV_FILE"
  set +a
  echo "[eoc_router] .env loaded from $ENV_FILE"
fi

# ── Runtime env ───────────────────────────────────────────────────────────────
export PYTHONPATH="$REPO_ROOT"
export K9_ENV="${K9_ENV:-development}"

# Override broker if you need to point at a different host
# export K9_KAFKA_BROKERS="192.168.1.98:9092"

echo "------------------------------------------------------------"
echo " K9-AIF EOC — eoc_router"
echo " PYTHONPATH : $REPO_ROOT"
echo " Kafka      : $(python -c "
import yaml, os
cfg = yaml.safe_load(open('$REPO_ROOT/examples/K9X_Enterprise_Insurance_OperationsCenter/config/config.yaml'))
brokers = cfg.get('messaging', {}).get('brokers', ['?'])
print(','.join(brokers))
" 2>/dev/null || echo "192.168.1.98:9092")"
echo " Consuming  : eoc-events"
echo " Routing to : eoc-claims, eoc-documents, eoc-fraud, eoc-policy,"
echo "              eoc-catastrophe, eoc-customer, eoc-audit"
echo "------------------------------------------------------------"

cd "$REPO_ROOT"
exec python -m \
  examples.K9X_Enterprise_Insurance_OperationsCenter.router.eoc_router_process
