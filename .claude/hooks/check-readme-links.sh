#!/bin/bash
# PostToolUse: README.md must keep only absolute links/images -- it is the
# PyPI long_description, and PyPI 404s every relative path. Blocks (exit 2)
# with the offending lines so they get fixed before commit.
INPUT=$(cat)
FILE=$(python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('tool_input',{}).get('file_path',''))" <<< "$INPUT" 2>/dev/null)

REPO="/Users/ravinatarajan/ai/k9-aif-framework"
[[ "$FILE" != "$REPO/README.md" ]] && exit 0
[[ ! -f "$FILE" ]] && exit 0

python3 "$REPO/scripts/check_readme_links.py" "$FILE" 1>/dev/null
if [ $? -ne 0 ]; then
  exit 2
fi
echo "✓ README links absolute: $FILE"
