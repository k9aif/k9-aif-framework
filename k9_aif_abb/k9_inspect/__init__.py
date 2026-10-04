# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""k9_inspect — static conformance inspection of K9-AIF solutions (1.15).

Reads a solution folder (never executes it) and reports, per rule, where it
departs from the framework's architecture: ABB contracts, three-layer
decoupling, the single LLM call path, governance by construction, Kafka
ownership, configuration and secret hygiene, squad YAML structure.

    from k9_aif_abb.k9_inspect import K9Inspector
    report = K9Inspector().inspect("examples/MyApp")
    report.verdict, report.score, report.to_markdown()

CLI: ``k9aif inspect <folder> [--json] [--fail-on violation]``.
UI: k9x_inspector (k9x-ecosystem) — local folder or GitHub URL.
"""

from .base_inspection_rule import BaseInspectionRule
from .inspector import K9Inspector
from .models import Finding, InspectionReport, Severity
from .project import SolutionProject
from .registry import InspectionRuleRegistry

__all__ = ["BaseInspectionRule", "K9Inspector", "Finding", "InspectionReport", "Severity",
           "SolutionProject", "InspectionRuleRegistry"]
