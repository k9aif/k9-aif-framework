# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""K9Inspector — runs every registered rule over a solution folder."""

from __future__ import annotations

import logging
import subprocess
from typing import Any, Dict, Iterable, Optional

from .models import InspectionReport, RuleOutcome
from .project import SolutionProject
from .registry import InspectionRuleRegistry

log = logging.getLogger(__name__)


def _framework_version() -> str:
    try:
        from importlib.metadata import version
        return version("k9-aif")
    except Exception:
        return "unknown"


def _git_commit(root) -> Optional[str]:
    try:
        out = subprocess.run(["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=10)
        return out.stdout.strip() or None if out.returncode == 0 else None
    except Exception:
        return None


class K9Inspector:
    """Static conformance inspection of a K9-AIF solution.

        report = K9Inspector().inspect("examples/MyApp")
        print(report.to_markdown())
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None, only: Optional[Iterable[str]] = None) -> None:
        self.config = config or {}
        self.only = set(only) if only else None

    def inspect(self, root, source: Optional[str] = None) -> InspectionReport:
        project = SolutionProject(root)
        report = InspectionReport(
            root=str(project.root), source=source or str(project.root), framework_version=_framework_version(),
            files_python=len(project.modules), files_yaml=len(project.yaml_docs), commit=_git_commit(project.root))
        for rule_cls in InspectionRuleRegistry.all():
            if self.only and rule_cls.rule_id not in self.only:
                continue
            rule = rule_cls(self.config.get(rule_cls.rule_id))
            try:
                found = rule.inspect(project)
            except Exception as exc:          # a broken rule must not hide the others
                log.exception("rule %s failed", rule.rule_id)
                found = [rule.finding(f"rule could not run: {type(exc).__name__}: {exc}")]
            report.findings.extend(found)
            report.rules.append(RuleOutcome(rule.rule_id, rule.title, rule.category, rule.severity,
                                            not found, len(found)))
        return report
