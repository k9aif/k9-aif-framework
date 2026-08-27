#!/usr/bin/env bash
# weather_assist launcher — Web UI (Weather + Architecture/About tabs)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRAMEWORK_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
VENV_DIR="$FRAMEWORK_ROOT/.venv"

if [ ! -d "$VENV_DIR" ]; then
  echo "[weather_assist] ERROR: framework venv not found at $VENV_DIR"
  echo "  Run: cd $FRAMEWORK_ROOT && python3.11 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi

source "$VENV_DIR/bin/activate"

echo "[weather_assist] Using framework venv: $VENV_DIR"
echo "[weather_assist] Installing weather_assist dependencies..."
pip install -q -r "$SCRIPT_DIR/requirements.txt"

if [ ! -f "$FRAMEWORK_ROOT/.env" ] && [ ! -f "$SCRIPT_DIR/.env" ]; then
  echo "[weather_assist] No .env found — copy env-example to .env and adjust as needed."
  echo "  (Defaults to http://localhost:11434 / granite3.3:2b if left unset.)"
fi

echo "[weather_assist] Starting Web UI on http://127.0.0.1:8000"
cd "$FRAMEWORK_ROOT"
python -m examples.weather_assist.k9.webui
