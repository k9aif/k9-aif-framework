# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""Rules over configuration, YAML definitions, deployment files and dependencies."""

from __future__ import annotations

import re
import subprocess
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ..base_inspection_rule import BaseInspectionRule
from ..models import Finding, Severity
from ..project import SolutionProject, YamlDoc
from ..registry import InspectionRuleRegistry

_SECRET_KEY = re.compile(r"(?i)(password|passwd|secret|api[_-]?key|token|access[_-]?key|private[_-]?key)$")
_PLACEHOLDER = re.compile(r"^\s*(\$\{.*\}|\$[A-Z_]+|env:|<.*>|\*+|x+|your[_-].*|changeme.*|example.*|none|null|)\s*$", re.I)


def _get(d: Any, *path: str) -> Any:
    for p in path:
        if not isinstance(d, dict):
            return None
        d = d.get(p)
    return d


def _walk(d: Any, prefix: str = "") -> Iterable[Tuple[str, Any]]:
    if isinstance(d, dict):
        for k, v in d.items():
            yield from _walk(v, f"{prefix}.{k}" if prefix else str(k))
    elif isinstance(d, list):
        for i, v in enumerate(d):
            yield from _walk(v, f"{prefix}[{i}]")
    else:
        yield prefix, d


def _line_of(doc: YamlDoc, needle: str) -> int:
    for i, line in enumerate(doc.text.splitlines(), 1):
        if needle in line:
            return i
    return 0


def _code_mentions(project: SolutionProject, *names: str) -> bool:
    return any(n in m.source for m in project.code_modules() for n in names)


@InspectionRuleRegistry.register
class ShieldEnabledRule(BaseInspectionRule):
    rule_id = "K9-GOV-001"
    title = "Shield governance is enabled"
    category = "Governance"
    severity = Severity.VIOLATION
    description = ("Since k9-aif 1.15 every agent is governed by construction from security.shield in the "
                   "application config. Without it, agents get NoopGovernance, which the framework refuses in "
                   "production (PermissionError before the agent runs), and nothing is checked anywhere else.")
    fix = ("Add security.shield: {enabled: true, ingress: {checks: [InputSizeCheck, PromptInjectionCheck, "
           "PIIBoundaryCheck]}, egress: {checks: [PIIBoundaryCheck, OutboundLinkCheck]}} to config.yaml.")

    def inspect(self, project: SolutionProject) -> List[Finding]:
        configs = project.config_docs()
        if not configs:
            return [self.finding("no application config.yaml found (inference/security/governance sections)",
                                 severity=Severity.WARNING,
                                 fix="Add config/config.yaml; see the framework's config.yaml for the sections.")]
        if any(_get(d.data, "security", "shield", "enabled") is True for d in configs):
            return []
        explicit = _code_mentions(project, "ShieldGovernance(", "GuardianGovernance(", "ChainedGovernance(")
        d = configs[0]
        return [self.finding("security.shield.enabled is not true in any application config",
                             d.rel, _line_of(d, "security:"),
                             severity=Severity.WARNING if explicit else Severity.VIOLATION,
                             fix=self.fix + (" Governance is passed explicitly in code; the config setting makes "
                                             "every agent governed without that." if explicit else ""))]


@InspectionRuleRegistry.register
class ShieldChecksConfiguredRule(BaseInspectionRule):
    rule_id = "K9-GOV-002"
    title = "Shield has ingress and egress checks"
    category = "Governance"
    severity = Severity.VIOLATION
    description = ("ShieldGovernance runs only the checks listed. Enabled with empty lists, it logs enabled=True "
                   "and blocks nothing.")
    fix = "List checks under security.shield.ingress.checks and security.shield.egress.checks."

    def inspect(self, project: SolutionProject) -> List[Finding]:
        out = []
        for d in project.config_docs():
            shield = _get(d.data, "security", "shield") or {}
            if shield.get("enabled") is not True:
                continue
            for side in ("ingress", "egress"):
                if not (_get(shield, side, "checks") or []):
                    out.append(self.finding(f"security.shield.{side}.checks is empty", d.rel, _line_of(d, "shield:")))
        return out


@InspectionRuleRegistry.register
class GuardianConfiguredRule(BaseInspectionRule):
    rule_id = "K9-GOV-004"
    title = "Granite Guardian (semantic screening) is configured"
    category = "Governance"
    severity = Severity.WARNING
    description = ("Pattern checks miss paraphrased attacks; Granite Guardian is the framework's semantic layer "
                   "and is required for a complete governance configuration.")
    fix = "Set governance.guardian.enabled: true (model granite4.1-guardian:8b) or use GuardianGovernance."

    def inspect(self, project: SolutionProject) -> List[Finding]:
        for d in project.config_docs():
            g = d.data.get("governance") or {}
            if isinstance(g, dict) and (_get(g, "guardian", "enabled") or str(g.get("provider", "")).lower() == "guardian"
                                        or "guardian" in str(g.get("model_alias", "")).lower()):
                return []
        if _code_mentions(project, "GuardianGovernance", "ProfanityGovernance"):
            return []
        return [self.finding("no Granite Guardian configuration found")]


@InspectionRuleRegistry.register
class EgressCoverageRule(BaseInspectionRule):
    rule_id = "K9-GOV-006"
    title = "Egress screens personal data and links"
    category = "Governance"
    severity = Severity.RECOMMENDATION
    description = ("Agent output reaches people: PIIBoundaryCheck flags personal data and OutboundLinkCheck "
                   "blocks phishing links (look-alikes, brand-in-subdomain, payment lures).")
    fix = "Add PIIBoundaryCheck and OutboundLinkCheck (with allowed_domains) to security.shield.egress.checks."

    def inspect(self, project: SolutionProject) -> List[Finding]:
        out = []
        for d in project.config_docs():
            shield = _get(d.data, "security", "shield") or {}
            if shield.get("enabled") is not True:
                continue
            egress = set(_get(shield, "egress", "checks") or [])
            missing = [c for c in ("PIIBoundaryCheck", "OutboundLinkCheck") if c not in egress]
            if missing:
                out.append(self.finding(f"egress does not run {', '.join(missing)}", d.rel, _line_of(d, "egress:")))
        return out


@InspectionRuleRegistry.register
class ProductionEnvRule(BaseInspectionRule):
    rule_id = "K9-GOV-005"
    title = "Deployments run with K9_ENV=production"
    category = "Governance"
    severity = Severity.WARNING
    description = ("K9_ENV=development or test turns off the production refusal of ungoverned agents and model "
                   "calls. Deployment files should not set it.")
    fix = "Remove K9_ENV from deployment files (unset means production) or set K9_ENV=production."

    _DEPLOY = ("Containerfile", "Dockerfile", "docker-compose.yml", "docker-compose.yaml", "compose.yaml")

    def inspect(self, project: SolutionProject) -> List[Finding]:
        out = []
        pat = re.compile(r"K9_ENV\s*[=:]\s*['\"]?(dev|development|test)\b", re.I)
        files = [p for p in project.other_files if p.name in self._DEPLOY or p.suffix == ".sh"
                 or p.name.endswith((".env.example", "env-example", ".env.sample"))]
        files += [d.path for d in project.yaml_docs if "pod" in d.path.name or "deploy" in d.path.name
                  or d.path.name in self._DEPLOY]
        for p in files:
            for i, line in enumerate(p.read_text(errors="replace").splitlines(), 1):
                if pat.search(line) and not line.lstrip().startswith("#"):
                    out.append(self.finding("deployment sets K9_ENV to a non-production value",
                                            project.rel(p), i, line.strip()))
        return out


@InspectionRuleRegistry.register
class SecretsInConfigRule(BaseInspectionRule):
    rule_id = "K9-CFG-002"
    title = "No secrets in YAML"
    category = "Secrets"
    severity = Severity.CRITICAL
    description = "Passwords, tokens and keys in YAML end up in the repository and in every image built from it."
    fix = "Read secrets from the environment (.env, gitignored) or a secret manager (SecretManagerFactory)."

    def inspect(self, project: SolutionProject) -> List[Finding]:
        out = []
        for d in project.yaml_docs:
            for path, value in _walk(d.data):
                key = re.split(r"[.\[]", path)[-1] if path else ""
                if isinstance(value, (str, int)) and not isinstance(value, bool) and _SECRET_KEY.search(key) \
                        and not _PLACEHOLDER.match(str(value)) and len(str(value)) >= 4:
                    out.append(self.finding(f"{path} holds a literal value", d.rel, _line_of(d, f"{key}:")))
        return out


@InspectionRuleRegistry.register
class EnvFileTrackedRule(BaseInspectionRule):
    rule_id = "K9-CFG-003"
    title = ".env is not committed"
    category = "Secrets"
    severity = Severity.CRITICAL
    description = "A .env file holds the deployment's secrets; it must be gitignored, with an example file committed instead."
    fix = "git rm --cached .env; add .env to .gitignore; commit an env-example without values."

    def inspect(self, project: SolutionProject) -> List[Finding]:
        envs = [p for p in project.other_files if p.name == ".env" or (p.name.startswith(".env.")
                and not p.name.endswith(("example", "sample", "template")))]
        if not envs:
            return []
        tracked = _git_tracked(project.root)
        out = []
        for p in envs:
            rel = project.rel(p)
            if tracked is None:
                ignored = _gitignore_mentions(project, p.name)
                if not ignored:
                    out.append(self.finding(f"{rel} present and not listed in .gitignore", rel))
            elif rel in tracked:
                out.append(self.finding(f"{rel} is committed to the repository", rel))
        return out


@InspectionRuleRegistry.register
class SquadYamlRule(BaseInspectionRule):
    rule_id = "K9-YAML-001"
    title = "Squad YAML structure"
    category = "Squad/Agent YAML"
    severity = Severity.VIOLATION
    description = ("Squads are defined under a top-level squads: key; each flow step is a mapping with agent:; "
                   "every agent in the flow is declared; squads do not name their orchestrator.")
    fix = "squads: {my_squad: {agents: [A, B], flow: [{agent: A}, {agent: B}]}} — no orchestrator: field."

    def inspect(self, project: SolutionProject) -> List[Finding]:
        out = []
        for d in project.yaml_docs:
            data = d.data
            if not isinstance(data, dict):
                continue
            if "flow" in data and "squads" not in data:
                out.append(self.finding("squad definition without a top-level squads: key — the framework's "
                                        "SquadLoader cannot load it (a custom loader can)", d.rel, _line_of(d, "flow:"),
                                        severity=Severity.WARNING))
                continue
            squads = data.get("squads")
            if not isinstance(squads, dict):
                continue
            for sid, sq in squads.items():
                if not isinstance(sq, dict):
                    continue
                if "orchestrator" in sq:
                    out.append(self.finding(f"squad {sid} names an orchestrator (decoupling)", d.rel, _line_of(d, "orchestrator:")))
                declared = {a if isinstance(a, str) else (a or {}).get("name") or (a or {}).get("agent")
                            for a in (sq.get("agents") or [])}
                for step in sq.get("flow") or []:
                    if isinstance(step, str):
                        out.append(self.finding(f"squad {sid}: flow step '{step}' is a string, not {{agent: ...}}",
                                                d.rel, _line_of(d, step)))
                    elif isinstance(step, dict) and declared and step.get("agent") and step["agent"] not in declared:
                        out.append(self.finding(f"squad {sid}: flow agent {step['agent']} not declared in agents:",
                                                d.rel, _line_of(d, str(step["agent"]))))
        return out


@InspectionRuleRegistry.register
class AgentYamlRule(BaseInspectionRule):
    rule_id = "K9-YAML-002"
    title = "Agent YAML does not name its squad or routing"
    category = "Squad/Agent YAML"
    severity = Severity.VIOLATION
    description = "An agent does not know which squad uses it or how events are routed (three-layer decoupling)."
    fix = "Remove squad: and routing: from the agent definition; the squad lists its agents."

    def inspect(self, project: SolutionProject) -> List[Finding]:
        out = []
        for d in project.yaml_docs:
            agents = d.data.get("agents") if isinstance(d.data, dict) else None
            if not isinstance(agents, dict) or "squads" in d.data:
                continue
            for aid, a in agents.items():
                if isinstance(a, dict):
                    for bad in ("squad", "routing"):
                        if bad in a:
                            out.append(self.finding(f"agent {aid} has {bad}:", d.rel, _line_of(d, f"{bad}:")))
        return out


@InspectionRuleRegistry.register
class ModelAliasRule(BaseInspectionRule):
    rule_id = "K9-CFG-004"
    title = "Agent model aliases exist in the model catalog"
    category = "Configuration"
    severity = Severity.WARNING
    description = "An agent that names a model alias missing from inference.llm_factory.models falls back to the default model."
    fix = "Add the alias under inference.llm_factory.models (or correct the agent's model:)."

    def inspect(self, project: SolutionProject) -> List[Finding]:
        aliases = set()
        for d in project.config_docs():
            aliases |= set((_get(d.data, "inference", "llm_factory", "models") or {}).keys())
            aliases |= set((_get(d.data, "inference", "model_catalog") or {}).keys()) \
                if isinstance(_get(d.data, "inference", "model_catalog"), dict) else set()
        if not aliases:
            return []
        out = []
        for d in project.yaml_docs:
            agents = d.data.get("agents") if isinstance(d.data, dict) else None
            if isinstance(agents, dict):
                for aid, a in agents.items():
                    m = a.get("model") if isinstance(a, dict) else None
                    if isinstance(m, str) and m not in aliases and ":" not in m:
                        out.append(self.finding(f"agent {aid} uses model alias '{m}' not in the catalog",
                                                d.rel, _line_of(d, f"model: {m}")))
        return out


@InspectionRuleRegistry.register
class FrameworkVersionRule(BaseInspectionRule):
    rule_id = "K9-DEP-001"
    title = "Depends on k9-aif with governance by construction"
    category = "Dependencies"
    severity = Severity.WARNING
    description = ("Governance by construction (every agent and model call governed) needs k9-aif >= 1.15. "
                   "An older pin, or no declared dependency, leaves agents ungoverned unless each calls governance itself.")
    fix = "Declare k9-aif>=1.15 in requirements.txt or pyproject.toml."

    _SPEC = re.compile(r"k9[-_]aif\s*(\[[^\]]*\])?\s*(==|>=|~=|<=|<|>)?\s*([0-9][0-9.]*)?", re.I)

    def inspect(self, project: SolutionProject) -> List[Finding]:
        files = project.find_files("requirements.txt", "pyproject.toml", "setup.cfg", "requirements.in")
        hits = []
        for p in files:
            for i, line in enumerate(p.read_text(errors="replace").splitlines(), 1):
                m = self._SPEC.search(line)
                if m and not line.lstrip().startswith("#"):
                    hits.append((p, i, line.strip(), m.group(2), m.group(3)))
        if not hits:
            return [self.finding("no k9-aif dependency declared", severity=Severity.RECOMMENDATION)]
        out = []
        for p, i, line, op, ver in hits:
            if op in ("==", "<=", "<", "~=") and ver and _older(ver, "1.15"):
                out.append(self.finding(f"pins k9-aif {op}{ver} (before governance by construction)",
                                        project.rel(p), i, line))
        return out


def _older(v: str, ref: str) -> bool:
    def t(x): return tuple(int(p) for p in re.findall(r"\d+", x)[:3])
    return t(v) < t(ref)


def _git_tracked(root) -> Optional[set]:
    try:
        out = subprocess.run(["git", "-C", str(root), "ls-files"], capture_output=True, text=True, timeout=20)
        return set(out.stdout.splitlines()) if out.returncode == 0 else None
    except Exception:
        return None


def _gitignore_mentions(project: SolutionProject, name: str) -> bool:
    for p in project.other_files:
        if p.name == ".gitignore":
            lines = [l.strip() for l in p.read_text(errors="replace").splitlines()]
            if any(l in (name, "/" + name, ".env*", ".env.*", "*.env") for l in lines):
                return True
    return False
