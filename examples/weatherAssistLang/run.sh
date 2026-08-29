#!/usr/bin/env bash
# weatherAssistLang launcher — Web UI (Weather + Architecture/About tabs)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRAMEWORK_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
VENV_DIR="$FRAMEWORK_ROOT/.venv"

if [ ! -d "$VENV_DIR" ]; then
  echo "[weatherAssistLang] ERROR: framework venv not found at $VENV_DIR"
  echo "  Run: cd $FRAMEWORK_ROOT && python3.11 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi

source "$VENV_DIR/bin/activate"

echo "[weatherAssistLang] Using framework venv: $VENV_DIR"
echo "[weatherAssistLang] Installing weatherAssistLang dependencies..."
pip install -q -r "$SCRIPT_DIR/requirements.txt"

if [ ! -f "$FRAMEWORK_ROOT/.env" ] && [ ! -f "$SCRIPT_DIR/.env" ]; then
  echo "[weatherAssistLang] No .env found — copy env-example to .env and adjust as needed."
  echo "  (Defaults to http://localhost:11434 / llama3.2:1b if left unset.)"
fi

echo "[weatherAssistLang] Starting Web UI on http://127.0.0.1:8001"
cd "$FRAMEWORK_ROOT"
python -m examples.weatherAssistLang.k9.webui
