#!/bin/bash
# PostToolUse: an orchestrator knows only squads (k9_inspect K9-DEC-002).
# Added 2026-10-14 after DAS and the EOC were found naming agents in their
# orchestrators (AGENTS = (...) tuples, AgentRegistry/AgentLoader built inside
# _load_squad()). Registering by name (1.15) had removed the imports, so
# K9-DEC-001 and the old "imports Squads only" wording both passed it.
# Exit 2 = the edit is reported back as a violation to fix.
INPUT=$(cat)
FILE=$(python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('tool_input',{}).get('file_path',''))" <<< "$INPUT" 2>/dev/null)

[[ "$FILE" != *.py ]] && exit 0
[[ ! -f "$FILE" ]] && exit 0
[[ "$FILE" == */tests/* || "$(basename "$FILE")" == test_* ]] && exit 0

FINDINGS=$(python3 - "$FILE" <<'PY'
import ast, re, sys
path = sys.argv[1]
try:
    tree = ast.parse(open(path).read())
except Exception:
    sys.exit(0)
classes = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
def base(b):
    return b.id if isinstance(b, ast.Name) else b.attr if isinstance(b, ast.Attribute) else ""
orch = [c for c in classes if any(base(b).endswith("Orchestrator") for b in c.bases)]
others = [c for c in classes if c not in orch]
if not orch or others and any(any(base(b).endswith(("Agent", "Squad", "Router")) for b in c.bases) for c in others):
    sys.exit(0)        # not an orchestrator module (or an entry point mixing layers on purpose)
out = []
machinery = {"AgentRegistry", "AgentLoader", "register_into"}
for n in ast.walk(tree):
    name = (n.id if isinstance(n, ast.Name) else n.attr if isinstance(n, ast.Attribute) else
            n.module.split(".")[-1] if isinstance(n, ast.ImportFrom) and n.module else "")
    if isinstance(n, ast.ImportFrom):
        for a in n.names:
            if a.name in machinery:
                out.append(f"{getattr(n, 'lineno', 0)}: builds agents ({a.name})")
    elif name in machinery:
        out.append(f"{getattr(n, 'lineno', 0)}: builds agents ({name})")
    if isinstance(n, ast.Constant) and isinstance(n.value, str) and re.fullmatch(r"[A-Z]\w*Agent", n.value):
        out.append(f"{n.lineno}: names agent {n.value!r}")
print("\n".join(sorted(set(out), key=lambda s: int(s.split(':')[0]))))
PY
)
if [ -n "$FINDINGS" ]; then
  echo "✖ K9-DEC-002: an orchestrator knows only squads. Load squads with self.squads.load_one(squad_yaml, squad_id); the squad layer (SquadLoader.from_agents at the entry point) builds the agents each squad YAML names. In $FILE:" >&2
  echo "$FINDINGS" >&2
  exit 2
fi
exit 0
