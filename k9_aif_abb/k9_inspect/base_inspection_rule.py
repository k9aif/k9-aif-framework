# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""BaseInspectionRule — ABB contract for one static conformance rule.

A rule reads a SolutionProject (parsed, never executed) and returns Findings.
New rules extend this contract and register with InspectionRuleRegistry; the
inspector and the k9x_inspector UI pick them up without other changes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from .models import Finding, Severity
from .project import PyModule, SolutionProject


class BaseInspectionRule(ABC):
    """One conformance rule. Subclasses set the class attributes and implement inspect()."""

    rule_id: str = ""
    title: str = ""
    category: str = ""
    severity: Severity = Severity.WARNING
    description: str = ""          # what the rule checks and why it matters
    fix: str = ""                  # default remediation

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config: Dict[str, Any] = config or {}

    @abstractmethod
    def inspect(self, project: SolutionProject) -> List[Finding]:
        """Return the findings for this rule (empty list = rule passes)."""
        raise NotImplementedError

    # ── helpers for subclasses ────────────────────────────────────────────────
    def finding(self, message: str, file: str = "", line: int = 0, snippet: str = "",
                severity: Optional[Severity] = None, fix: Optional[str] = None) -> Finding:
        return Finding(self.rule_id, severity or self.severity, self.category, message,
                       file, line, snippet[:200], fix if fix is not None else self.fix)

    def at(self, module: PyModule, node: Any, message: str, **kw: Any) -> Finding:
        line = getattr(node, "lineno", 0)
        return self.finding(message, module.rel, line, module.line(line), **kw)

    def describe(self) -> Dict[str, str]:
        return {"rule_id": self.rule_id, "title": self.title, "category": self.category,
                "severity": self.severity.value, "description": self.description, "fix": self.fix}
