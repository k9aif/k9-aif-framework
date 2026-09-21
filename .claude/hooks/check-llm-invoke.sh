#!/bin/bash
# PostToolUse: warn if agent code calls a model router directly instead of
# going through llm_invoke()/llm_invoke_stream(). Added 2026-09-21 after
# ChatAgent.execute() was found calling self.router.invoke() directly,
# silently skipping llm_invoke's retry-on-empty-response logic and LLMCall
# trace event -- the same bug found in acme_support_center's base agent and
# three files in acme_health_insurance. llm_invoke.py itself legitimately
# calls router.invoke() internally -- that's the one sanctioned place this
# pattern belongs, so it's excluded below.
INPUT=$(cat)
FILE=$(python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('tool_input',{}).get('file_path',''))" <<< "$INPUT" 2>/dev/null)

[[ "$FILE" != */examples/* && "$FILE" != */k9_projects/* ]] && exit 0
[[ "$FILE" != *.py ]] && exit 0
[[ "$FILE" == */llm_invoke.py ]] && exit 0
[[ ! -f "$FILE" ]] && exit 0

MATCHES=$(grep -n "\.router\.invoke(\|ModelRouterFactory\.get_router(" "$FILE" 2>/dev/null)
if [ -n "$MATCHES" ]; then
  echo "⚠ Direct router call found -- agents must use llm_invoke()/llm_invoke_stream(), never ModelRouterFactory/router.invoke() directly (loses retry-on-empty-response + LLMCall trace event):" >&2
  echo "$MATCHES" >&2
fi
exit 0
