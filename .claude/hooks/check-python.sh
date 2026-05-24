#!/bin/bash
# PostToolUse: syntax-check any Python file after Write/Edit
INPUT=$(cat)
FILE=$(python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('tool_input',{}).get('file_path',''))" <<< "$INPUT" 2>/dev/null)

[[ "$FILE" != *.py ]] && exit 0
[[ ! -f "$FILE" ]] && exit 0

python3 -m py_compile "$FILE" 2>&1
if [ $? -eq 0 ]; then
  echo "✓ syntax ok: $FILE"
else
  echo "✗ syntax error in $FILE" >&2
  exit 2
fi
