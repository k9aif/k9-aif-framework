# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""SolutionProject — a static view of a K9-AIF solution (SBB) folder.

Python files are parsed to ASTs and YAML files loaded with safe_load. Nothing
from the inspected code is imported or executed, so an untrusted repository can
be inspected safely.

Each class is given a role (agent / squad / orchestrator / router) from its base
classes, resolved through the solution's own class hierarchy, so
`class ClaimsAgent(MyBaseAgent)` is an agent when `MyBaseAgent(BaseAgent)` is.
"""

from __future__ import annotations

import ast
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

import yaml

SKIP_DIRS = {".git", ".venv", "venv", "env", "node_modules", "__pycache__", "site-packages",
             "dist", "build", ".mypy_cache", ".pytest_cache", ".tox", "docs", "pydocs"}
MAX_FILE_BYTES = 2_000_000

# Framework base classes by role (k9_aif_abb). Subclasses inside the solution inherit the role.
ROLE_BASES: Dict[str, Set[str]] = {
    "agent": {"BaseAgent", "BaseValidationLoopAgent", "K9ValidationLoopAgent", "K9PlanningLoopAgent",
              "BaseCriticActorAgent", "K9CriticActorAgent", "BaseMCPAgent", "BaseIntentAgent", "K9IntentAgent",
              "BaseRulesAgent", "BaseFormatterAgent", "BaseIoTAgent", "BaseLoggingAgent", "BaseMessageAgent",
              "BaseSecurityAgent", "K9EmbeddingAgent", "K9RetrievalAgent"},
    "squad": {"BaseSquad", "IntentSquad"},
    "orchestrator": {"BaseOrchestrator", "BaseHILOrchestrator", "IntentOrchestrator", "BaseIntegrationAdapter",
                     "CrewAIOrchestratorAdapter", "LangGraphOrchestratorAdapter",
                     "ClaudeAgentSDKOrchestratorAdapter"},
    "router": {"BaseRouter", "K9EventRouter"},
}
LOOP_AGENT_BASES = {"BaseValidationLoopAgent", "K9ValidationLoopAgent", "K9PlanningLoopAgent",
                    "BaseCriticActorAgent", "K9CriticActorAgent"}


@dataclass
class ClassInfo:
    name: str
    module: "PyModule"
    node: ast.ClassDef
    bases: List[str]
    role: Optional[str] = None
    framework_bases: Set[str] = field(default_factory=set)   # resolved k9_aif_abb ancestors

    @property
    def methods(self) -> Dict[str, ast.AST]:
        return {n.name: n for n in self.node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


@dataclass
class PyModule:
    path: Path
    rel: str
    source: str
    tree: Optional[ast.Module]
    error: Optional[str] = None
    classes: List[ClassInfo] = field(default_factory=list)
    imports: List[ast.AST] = field(default_factory=list)

    @property
    def is_test(self) -> bool:
        parts = Path(self.rel).parts
        return any(p in ("tests", "test") for p in parts) or Path(self.rel).name.startswith("test_") \
            or Path(self.rel).name.endswith("_test.py") or Path(self.rel).name == "conftest.py"

    @property
    def roles(self) -> Set[str]:
        return {c.role for c in self.classes if c.role}

    def line(self, n: int) -> str:
        lines = self.source.splitlines()
        return lines[n - 1].strip() if 0 < n <= len(lines) else ""


def _is_agent_definition(data: dict) -> bool:
    return "class" in data and bool({"role", "goal", "instructions"} & set(data))


@dataclass
class YamlDoc:
    path: Path
    rel: str
    data: Any
    error: Optional[str] = None
    text: str = ""


def _base_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript):
        return _base_name(node.value)
    return ""


class SolutionProject:
    """Parsed view of every Python and YAML file under a root folder."""

    def __init__(self, root: str | os.PathLike) -> None:
        self.root = Path(root).resolve()
        if not self.root.is_dir():
            raise NotADirectoryError(f"not a folder: {root}")
        self.modules: List[PyModule] = []
        self.yaml_docs: List[YamlDoc] = []
        self.other_files: List[Path] = []
        self._load()
        self._resolve_roles()

    # ── loading ───────────────────────────────────────────────────────────────
    def files(self) -> Iterable[Path]:
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")
                           or d in (".github",)]
            for fn in filenames:
                p = Path(dirpath) / fn
                try:
                    if p.is_file() and p.stat().st_size <= MAX_FILE_BYTES:
                        yield p
                except OSError:
                    continue

    def rel(self, p: Path) -> str:
        return str(p.relative_to(self.root))

    def _load(self) -> None:
        for p in self.files():
            if p.suffix == ".py":
                src = p.read_text(errors="replace")
                try:
                    tree, err = ast.parse(src, filename=str(p)), None
                except SyntaxError as exc:
                    tree, err = None, f"line {exc.lineno}: {exc.msg}"
                mod = PyModule(p, self.rel(p), src, tree, err)
                if tree is not None:
                    for node in ast.walk(tree):
                        if isinstance(node, ast.ClassDef):
                            mod.classes.append(ClassInfo(node.name, mod, node, [_base_name(b) for b in node.bases]))
                        elif isinstance(node, (ast.Import, ast.ImportFrom)):
                            mod.imports.append(node)
                self.modules.append(mod)
            elif p.suffix in (".yaml", ".yml"):
                text = p.read_text(errors="replace")
                try:
                    docs = [d for d in yaml.safe_load_all(text) if d is not None]
                    data, err = (docs[0] if len(docs) == 1 else docs), None
                except yaml.YAMLError as exc:
                    data, err = None, str(exc).splitlines()[0]
                self.yaml_docs.append(YamlDoc(p, self.rel(p), data, err, text))
            else:
                self.other_files.append(p)

    def _resolve_roles(self) -> None:
        local = {c.name: c for m in self.modules for c in m.classes}

        def ancestors(cls: ClassInfo, seen: Set[str]) -> Set[str]:
            out: Set[str] = set()
            for b in cls.bases:
                if b in seen:
                    continue
                if b in local and local[b] is not cls:
                    out |= ancestors(local[b], seen | {b})
                else:
                    out.add(b)
            return out

        for m in self.modules:
            for c in m.classes:
                anc = ancestors(c, {c.name})
                for role, bases in ROLE_BASES.items():
                    hit = anc & bases
                    if hit:
                        c.role, c.framework_bases = role, hit
                        break

    # ── queries ───────────────────────────────────────────────────────────────
    def classes(self, role: Optional[str] = None, include_tests: bool = False) -> List[ClassInfo]:
        return [c for m in self.modules if include_tests or not m.is_test
                for c in m.classes if role is None or c.role == role]

    def code_modules(self) -> List[PyModule]:
        """Non-test modules that parsed."""
        return [m for m in self.modules if not m.is_test and m.tree is not None]

    def config_docs(self) -> List[YamlDoc]:
        """YAML files that look like a K9-AIF application config (have inference/security/governance).
        An agent definition (class + role/goal/instructions) is not one, even with its own governance:
        pre_process/post_process block."""
        return [d for d in self.yaml_docs if isinstance(d.data, dict)
                and ({"inference", "security", "governance", "messaging", "llm_factory"} & set(d.data))
                and not _is_agent_definition(d.data)]

    def find_files(self, *names: str) -> List[Path]:
        wanted = {n.lower() for n in names}
        return [p for p in self.other_files if p.name.lower() in wanted]
