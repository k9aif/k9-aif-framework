#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# K9-AIF — K9X Enterprise Insurance Operations Center launcher
#
# Usage (from k9-aif-framework root):
#   ./k9xos.sh --all            — open 3 Terminal windows (default)
#   ./k9xos.sh --app            — start app_backend only
#   ./k9xos.sh --router         — start eoc_router only
#   ./k9xos.sh --orchestrator   — start eoc_orchestrator only
#   ./k9xos.sh --help           — show this help

clear

set -euo pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
EOC_DIR="$SCRIPT_DIR/examples/K9X_Enterprise_Insurance_OperationsCenter"
cd "$SCRIPT_DIR"

# ─── Colours ────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

# ─── Banner ─────────────────────────────────────────────────────────────────
echo ""
echo -e "${CYAN}${BOLD}╔══════════════════════════════════════════════════════════════╗${RESET}"
echo -e "${CYAN}${BOLD}║   K9X Enterprise Insurance Operations Center                 ║${RESET}"
echo -e "${CYAN}${BOLD}║   K9-AIF Framework — SBB Example                            ║${RESET}"
echo -e "${CYAN}${BOLD}╚══════════════════════════════════════════════════════════════╝${RESET}"
echo ""

# ─── Parse flag ─────────────────────────────────────────────────────────────
FLAG="${1:---help}"

case "$FLAG" in

  --all)
    echo -e "${BOLD}Launching 3-process EOC (separate Terminal windows)...${RESET}"
    echo ""
    echo -e "  ${GREEN}Window 1${RESET} → eoc_orchestrator  (loads all squads — starts first)"
    echo -e "  ${GREEN}Window 2${RESET} → eoc_router         (routes Kafka events)"
    echo -e "  ${GREEN}Window 3${RESET} → app_backend        (FastAPI + UI — opens browser)"
    echo ""

    K9XOS="$SCRIPT_DIR/k9xos.sh"

    if command -v osascript &>/dev/null; then
      osascript <<APPLE
tell application "Terminal"
  activate
  do script "echo '' && $K9XOS --orchestrator"
  delay 1
  do script "echo '' && $K9XOS --router"
  delay 1
  do script "echo '' && $K9XOS --app"
end tell
APPLE
      echo -e "${GREEN}All three windows launched.${RESET}"
      echo -e "Start order: orchestrator → router → app  (allow ~15s for orchestrator to load squads)"
    else
      echo -e "${YELLOW}No 'osascript' found (not macOS). Run each in its own terminal:${RESET}"
      echo -e "  Terminal 1:  ${CYAN}./k9xos.sh --orchestrator${RESET}"
      echo -e "  Terminal 2:  ${CYAN}./k9xos.sh --router${RESET}"
      echo -e "  Terminal 3:  ${CYAN}./k9xos.sh --app${RESET}"
    fi
    exit 0
    ;;

  --app)
    echo -e "${GREEN}Mode:${RESET}   app_backend  (Process 1)"
    echo -e "${CYAN}        FastAPI + Web UI${RESET}"
    echo -e "${CYAN}        Kafka mode: K9_KAFKA_MODE=${K9_KAFKA_MODE:-1}${RESET}"
    echo ""
    echo -e "${BOLD}Endpoints:${RESET}"
    echo -e "  ${CYAN}Landing      ${RESET}→  http://localhost:8000/"
    echo -e "  ${CYAN}Dashboard    ${RESET}→  http://localhost:8000/webui/index.html"
    echo -e "  ${CYAN}Swagger UI   ${RESET}→  http://localhost:8000/docs"
    echo -e "  ${CYAN}ReDoc        ${RESET}→  http://localhost:8000/redoc"
    echo -e "  ${CYAN}Health       ${RESET}→  http://localhost:8000/health"
    echo ""
    echo -e "${YELLOW}Starting app_backend... (Ctrl+C to stop)${RESET}"
    echo ""
    (
      sleep 2
      if command -v open &>/dev/null; then
        open "http://localhost:8000"
      elif command -v xdg-open &>/dev/null; then
        xdg-open "http://localhost:8000"
      fi
    ) &
    exec "$EOC_DIR/start_eoc_app.sh"
    ;;

  --router)
    echo -e "${GREEN}Mode:${RESET}   eoc_router  (Process 2)"
    echo -e "${CYAN}        Consumes: eoc-events${RESET}"
    echo -e "${CYAN}        Routes to: eoc-claims, eoc-fraud, eoc-documents, …${RESET}"
    echo ""
    echo -e "${YELLOW}Starting eoc_router... (Ctrl+C to stop)${RESET}"
    echo ""
    exec "$EOC_DIR/start_eoc_router.sh"
    ;;

  --orchestrator)
    echo -e "${GREEN}Mode:${RESET}   eoc_orchestrator  (Process 3)"
    echo -e "${CYAN}        Consumes: all 7 domain topics${RESET}"
    echo -e "${CYAN}        Publishes: eoc-results${RESET}"
    echo -e "${CYAN}        Runs all squads and agents in-process${RESET}"
    echo ""
    echo -e "${YELLOW}Starting eoc_orchestrator... (Ctrl+C to stop)${RESET}"
    echo ""
    exec "$EOC_DIR/start_eoc_orchestrator.sh"
    ;;

  --help|-h)
    echo -e "${BOLD}Usage:${RESET}  ./k9xos.sh [--flag]"
    echo ""
    echo -e "${BOLD}Flags:${RESET}"
    echo -e "  ${GREEN}--all${RESET}           Open 3 Terminal windows (orchestrator + router + app)  [default]"
    echo -e "  ${GREEN}--app${RESET}           Start app_backend only   (FastAPI + UI, Process 1)"
    echo -e "  ${GREEN}--router${RESET}        Start eoc_router only    (Kafka router,  Process 2)"
    echo -e "  ${GREEN}--orchestrator${RESET}  Start eoc_orchestrator only (squad runner, Process 3)"
    echo -e "  ${GREEN}--help${RESET}          Show this help"
    echo ""
    echo -e "${BOLD}Single-process dev (no Kafka):${RESET}"
    echo -e "  ${CYAN}K9_KAFKA_MODE=0 ./k9xos.sh --app${RESET}"
    echo ""
    ;;

  *)
    echo -e "${RED}Unknown flag: $FLAG${RESET}"
    echo -e "Run ${CYAN}./k9xos.sh --help${RESET} for usage."
    exit 1
    ;;

esac
