#!/bin/bash
# PostToolUse: warn if NoopGovernance appears in example code
INPUT=$(cat)
FILE=$(python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('tool_input',{}).get('file_path',''))" <<< "$INPUT" 2>/dev/null)

[[ "$FILE" != */examples/* ]] && exit 0
[[ "$FILE" != *.py ]] && exit 0
[[ ! -f "$FILE" ]] && exit 0

MATCHES=$(grep -n "NoopGovernance" "$FILE" 2>/dev/null)
if [ -n "$MATCHES" ]; then
  echo "⚠ NoopGovernance found in example code — governance must be explicit in production:" >&2
  echo "$MATCHES" >&2
fi
exit 0
