# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""Findings and the inspection report.

Severity order (most severe first):

    CRITICAL        a governance or security control is bypassed, or a secret is exposed
    VIOLATION       breaks an ABB contract or a framework rule; fix before production
    WARNING         degrades reliability, governance or maintainability; fix soon
    RECOMMENDATION  a better framework pattern exists
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class Severity(str, Enum):
    CRITICAL = "critical"
    VIOLATION = "violation"
    WARNING = "warning"
    RECOMMENDATION = "recommendation"

    @property
    def rank(self) -> int:
        return ["critical", "violation", "warning", "recommendation"].index(self.value)


@dataclass
class Finding:
    """One rule violation at one place in the solution."""

    rule_id: str
    severity: Severity
    category: str
    message: str
    file: str = ""                  # path relative to the inspected root
    line: int = 0
    snippet: str = ""
    fix: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["severity"] = self.severity.value
        return d


@dataclass
class RuleOutcome:
    rule_id: str
    title: str
    category: str
    severity: Severity
    passed: bool
    findings: int


@dataclass
class InspectionReport:
    """Result of inspecting one solution."""

    root: str
    source: str                     # local path or repository URL as given
    framework_version: str
    files_python: int
    files_yaml: int
    findings: List[Finding] = field(default_factory=list)
    rules: List[RuleOutcome] = field(default_factory=list)
    inspected_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    commit: Optional[str] = None
    framework: Dict[str, Any] = field(default_factory=dict)   # what the solution declares vs the latest k9-aif

    # ── summary ───────────────────────────────────────────────────────────────
    def counts(self) -> Dict[str, int]:
        out = {s.value: 0 for s in Severity}
        for f in self.findings:
            out[f.severity.value] += 1
        return out

    @property
    def score(self) -> int:
        """Share of rules with no finding, in percent."""
        return round(100 * sum(r.passed for r in self.rules) / len(self.rules)) if self.rules else 100

    @property
    def verdict(self) -> str:
        c = self.counts()
        if c["critical"] or c["violation"]:
            return "NON-COMPLIANT"
        return "COMPLIANT WITH WARNINGS" if c["warning"] else "COMPLIANT"

    def sorted_findings(self) -> List[Finding]:
        return sorted(self.findings, key=lambda f: (f.severity.rank, f.category, f.file, f.line))

    # ── output ────────────────────────────────────────────────────────────────
    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source, "commit": self.commit, "framework_version": self.framework_version,
            "framework": self.framework,
            "inspected_at": self.inspected_at, "verdict": self.verdict, "score": self.score,
            "counts": self.counts(), "files": {"python": self.files_python, "yaml": self.files_yaml},
            "rules": [{**asdict(r), "severity": r.severity.value} for r in self.rules],
            "findings": [f.to_dict() for f in self.sorted_findings()],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    def to_markdown(self) -> str:
        c = self.counts()
        lines = [
            "# K9-AIF Compliance Report", "",
            f"- **Source:** {self.source}" + (f" @ `{self.commit}`" if self.commit else ""),
            f"- **Inspected:** {self.inspected_at} with k9-aif {self.framework_version}",
            f"- **Files:** {self.files_python} Python, {self.files_yaml} YAML",
            f"- **Framework:** {_framework_line(self.framework)}",
            f"- **Verdict:** {self.verdict} — {self.score}% of {len(self.rules)} rules pass",
            f"- **Findings:** {c['critical']} critical, {c['violation']} violations, "
            f"{c['warning']} warnings, {c['recommendation']} recommendations", "",
        ]
        for sev in Severity:
            group = [f for f in self.sorted_findings() if f.severity == sev]
            if not group:
                continue
            lines += [f"## {sev.value.upper()} ({len(group)})", ""]
            for f in group:
                where = f"`{f.file}:{f.line}`" if f.line else (f"`{f.file}`" if f.file else "")
                lines.append(f"- **{f.rule_id}** [{f.category}] {where} — {f.message}")
                if f.fix:
                    lines.append(f"  - Fix: {f.fix}")
            lines.append("")
        lines += ["## Rules", "", "| Rule | Category | Severity | Result |", "|---|---|---|---|"]
        for r in self.rules:
            lines.append(f"| {r.rule_id} {r.title} | {r.category} | {r.severity.value} | "
                         f"{'pass' if r.passed else f'{r.findings} finding(s)'} |")
        return "\n".join(lines) + "\n"


_STATUS_TEXT = {"current": "up to date", "outdated": "OUTDATED — update to the latest",
                "floor-behind": "minimum is behind the latest — raise it", "unpinned": "no version given",
                "undeclared": "no k9-aif dependency declared"}


def _framework_line(fw: Dict[str, Any]) -> str:
    if not fw:
        return "not checked"
    declared = f"`{fw['declared']}` ({fw['file']}:{fw['line']})" if fw.get("declared") else "none"
    latest = f", latest k9-aif {fw['latest']}" if fw.get("latest") else ""
    return f"declares {declared}{latest} — {_STATUS_TEXT.get(fw.get('status'), fw.get('status'))}"
