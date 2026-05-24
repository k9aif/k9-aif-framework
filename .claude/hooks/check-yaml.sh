#!/bin/bash
# PostToolUse: validate YAML syntax after Write/Edit
INPUT=$(cat)
FILE=$(python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('tool_input',{}).get('file_path',''))" <<< "$INPUT" 2>/dev/null)

[[ "$FILE" != *.yaml && "$FILE" != *.yml ]] && exit 0
[[ ! -f "$FILE" ]] && exit 0

python3 -c "import yaml,sys; yaml.safe_load(open('$FILE'))" 2>&1
if [ $? -eq 0 ]; then
  echo "✓ YAML ok: $FILE"
else
  echo "✗ YAML parse error in $FILE" >&2
  exit 2
fi
