#!/bin/bash
# PostToolUse: warn if agent code calls a model router directly instead of
# going through llm_invoke()/llm_invoke_stream(). Added 2026-09-21 after
# ChatAgent.execute() was found calling self.router.invoke() directly,
# silently skipping llm_invoke's retry-on-empty-response logic and LLMCall
# trace event -- the same bug found in acme_support_center's base agent and
# five files in acme_health_insurance (agents AND an orchestrator).
# llm_invoke.py itself legitimately calls router.invoke() internally --
# that's the one sanctioned place this pattern belongs, so it's excluded
# below.
#
# First version of this hook only matched .router.invoke(/
# ModelRouterFactory.get_router( -- missed acme_health_insurance's
# K9ModelRouter(catalog) direct-construction + .ainvoke() pattern entirely
# until a manual full-repo grep caught it. Broadened below so the hook
# itself doesn't repeat that gap.
INPUT=$(cat)
FILE=$(python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('tool_input',{}).get('file_path',''))" <<< "$INPUT" 2>/dev/null)

[[ "$FILE" != */examples/* && "$FILE" != */k9_projects/* ]] && exit 0
[[ "$FILE" != *.py ]] && exit 0
[[ "$FILE" == */llm_invoke.py ]] && exit 0
[[ ! -f "$FILE" ]] && exit 0

MATCHES=$(grep -n "\.router\.invoke(\|\.router\.ainvoke(\|ModelRouterFactory\.get_router(\|K9ModelRouter(" "$FILE" 2>/dev/null)
if [ -n "$MATCHES" ]; then
  echo "⚠ Direct router call found -- agents must use llm_invoke()/llm_invoke_stream(), never ModelRouterFactory/K9ModelRouter/router.invoke()/.ainvoke() directly (loses retry-on-empty-response + LLMCall trace event):" >&2
  echo "$MATCHES" >&2
fi
exit 0
