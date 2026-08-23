#!/usr/bin/env bash
# K9-AIF EOC — Start eoc_orchestrator (Container 3 / Process 3)
#
# Consumes events from all seven domain Kafka topics, dispatches each to
# EOCOrchestrator (which runs all squad orchestrators in-process), and
# publishes the result to `eoc-results`.
#
# Prerequisites:
#   - Kafka running (see K9_KAFKA_BROKERS / config.yaml for the broker address)
#   - PostgreSQL, Neo4j, Ollama running on RHEL host
#   - eoc_router running (so domain topics receive events)
#
# Run:
#   ./start_eoc_orchestrator.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# ── Activate venv ─────────────────────────────────────────────────────────────
VENV="$REPO_ROOT/.venv"
if [[ -f "$VENV/bin/activate" ]]; then
  source "$VENV/bin/activate"
  echo "[eoc_orchestrator] venv: $VENV"
else
  echo "[eoc_orchestrator] WARNING: .venv not found at $REPO_ROOT — using system Python"
fi

# ── Runtime env ───────────────────────────────────────────────────────────────
export PYTHONPATH="$REPO_ROOT"
export K9_ENV="${K9_ENV:-development}"

echo "------------------------------------------------------------"
echo " K9-AIF EOC — eoc_orchestrator"
echo " PYTHONPATH : $REPO_ROOT"
echo " Kafka      : ${K9_KAFKA_BROKERS:-see config.yaml}"
echo " Consuming  : eoc-claims, eoc-documents, eoc-fraud, eoc-policy,"
echo "              eoc-catastrophe, eoc-customer, eoc-audit"
echo " Publishing : eoc-results"
echo " Squads     : all 7 loaded in-process"
echo "------------------------------------------------------------"

cd "$REPO_ROOT"
exec python -m \
  examples.K9X_Enterprise_Insurance_OperationsCenter.orchestrators.eoc_orchestrator_process
