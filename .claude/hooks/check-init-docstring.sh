#!/bin/bash
# PostToolUse: warn if __init__.py is missing a module docstring (needed for pydoc)
INPUT=$(cat)
FILE=$(python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('tool_input',{}).get('file_path',''))" <<< "$INPUT" 2>/dev/null)

[[ "$FILE" != *__init__.py ]] && exit 0
[[ ! -f "$FILE" ]] && exit 0

# Check if file has a module-level docstring (first non-empty, non-comment line starts with """)
HAS_DOC=$(python3 -c "
import ast, sys
try:
    tree = ast.parse(open('$FILE').read())
    has = (tree.body and isinstance(tree.body[0], ast.Expr) and isinstance(tree.body[0].value, ast.Constant))
    print('yes' if has else 'no')
except:
    print('no')
" 2>/dev/null)

if [ "$HAS_DOC" = "no" ]; then
  echo "⚠ $FILE has no module docstring — pydoc will generate an empty page for this module." >&2
  echo "  Add a triple-quoted docstring at the top describing the package." >&2
fi
exit 0
