#!/bin/bash
# PostToolUse: run framework tests after any edit under k9_aif_abb/
INPUT=$(cat)
FILE=$(python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('tool_input',{}).get('file_path',''))" <<< "$INPUT" 2>/dev/null)

[[ "$FILE" != */k9_aif_abb/* ]] && exit 0

REPO="/Users/ravinatarajan/ai/k9-aif-framework"
cd "$REPO" || exit 0

source .venv/bin/activate 2>/dev/null || true

echo "→ running ABB tests..."
pytest k9_aif_abb/tests/test_framework.py k9_aif_abb/tests/test_intelligent_model_router.py \
  -q --tb=short 2>&1 | tail -20
