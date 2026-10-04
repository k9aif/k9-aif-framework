# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""Rules over configuration, YAML definitions, deployment files and dependencies."""

from __future__ import annotations

import os
import re
from pathlib import Path
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
        off = [d for d in configs if _get(d.data, "security", "shield", "enabled") is False]
        d = off[0] if off else configs[0]
        return [self.finding("Shield is explicitly disabled (security.shield.enabled: false)" if off else
                             "security.shield.enabled is not true in any application config",
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
        off = [d for d in project.config_docs() if _get(d.data, "governance", "guardian", "enabled") is False]
        if off:
            return [self.finding("Granite Guardian is explicitly disabled (governance.guardian.enabled: false)",
                                 off[0].rel, _line_of(off[0], "guardian:"))]
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
            # a check built in code (e.g. an orchestrator's own egress chain) counts too
            missing = [c for c in ("PIIBoundaryCheck", "OutboundLinkCheck")
                       if c not in egress and not _code_mentions(project, f"{c}(")]
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


# A dependency entry: lowercase package name, optional extras and version, then a delimiter
# ("K9-AIF Workbench" in a description is not a dependency).
_SPEC_RE = re.compile(r"""(?:^|["'\s,\[])k9[-_]aif(\[[^\]]*\])?\s*(==|>=|~=|<=|<|>)?\s*([0-9][0-9.]*)?\s*(?=["',;\]\s#]|$)""")


def _dependency_files(project: SolutionProject):
    """Dependency files in the solution, then in parent folders up to the repository root
    (a solution inspected as a subfolder declares its dependencies at the top)."""
    names = ("requirements.txt", "requirements.in", "pyproject.toml", "setup.cfg")
    for name in names:
        for p in sorted(project.find_files(name), key=lambda p: len(p.parts)):
            yield p
    d = project.root
    while d.parent != d and not (d / ".git").exists():
        d = d.parent
        for name in names:
            if (d / name).is_file():
                yield d / name


def declared_framework(project: SolutionProject) -> Optional[Dict[str, Any]]:
    """The k9-aif requirement the solution declares: {op, version, file, line, text}, or None."""
    for p in _dependency_files(project):
        try:
            lines = p.read_text(errors="replace").splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines, 1):
            m = _SPEC_RE.search(line)
            if m and not line.lstrip().startswith("#"):
                rel = os.path.relpath(p, project.root)
                text = "k9-aif" + (m.group(1) or "") + (m.group(2) or "") + (m.group(3) or "")
                return {"op": m.group(2) or "", "version": m.group(3) or "", "file": rel, "line": i, "text": text}
    return None


def framework_status(project: SolutionProject, latest: str) -> Dict[str, Any]:
    """What the solution declares versus the latest k9-aif, for the report header."""
    d = declared_framework(project)
    out: Dict[str, Any] = {"latest": latest, "declared": d["text"] if d else None,
                           "file": d["file"] if d else None, "line": d["line"] if d else None}
    if not d:
        out["status"] = "undeclared"
    elif not d["version"]:
        out["status"] = "unpinned"
    elif latest and latest != "unknown" and older(d["version"], latest):
        out["status"] = "outdated" if d["op"] in ("==", "<", "<=", "~=") else "floor-behind"
    else:
        out["status"] = "current"
    out["version"] = d["version"] if d else None
    return out


@InspectionRuleRegistry.register
class FrameworkLatestRule(BaseInspectionRule):
    rule_id = "K9-DEP-002"
    title = "Runs the latest k9-aif"
    category = "Dependencies"
    severity = Severity.WARNING
    description = ("Framework releases close security gaps (new Shield checks, fixed patterns) and governance "
                   "behaviour. A solution pinned below the latest release does not get them; a >= floor below the "
                   "latest lets an old environment keep running an old framework.")
    fix = "Update the requirement to the latest k9-aif (e.g. k9-aif>=<latest>), rebuild and re-run the tests."

    def inspect(self, project: SolutionProject) -> List[Finding]:
        latest = self.config.get("latest_version") or _installed_version()
        st = framework_status(project, latest)
        if st["status"] == "outdated":
            return [self.finding(f"pins k9-aif {st['declared']} — latest is {latest}", st["file"], st["line"],
                                 st["declared"], fix=self.fix.replace("<latest>", latest))]
        if st["status"] == "floor-behind":
            return [self.finding(f"requires {st['declared']} — latest is {latest}; raise the floor",
                                 st["file"], st["line"], st["declared"], severity=Severity.RECOMMENDATION,
                                 fix=self.fix.replace("<latest>", latest))]
        return []


def _installed_version() -> str:
    try:
        from importlib.metadata import version
        return version("k9-aif")
    except Exception:
        return ""


@InspectionRuleRegistry.register
class GuardianFailOpenRule(BaseInspectionRule):
    rule_id = "K9-GOV-010"
    title = "Guardian fails closed"
    category = "Governance"
    severity = Severity.WARNING
    description = ("on_unavailable: fail_open lets every request through while Granite Guardian is down or slow, "
                   "silently; fail_closed (the default) blocks and reports it.")
    fix = "Set governance.guardian.on_unavailable: fail_closed (or remove the key)."

    def inspect(self, project: SolutionProject) -> List[Finding]:
        out = []
        for d in project.config_docs():
            if str(_get(d.data, "governance", "guardian", "on_unavailable") or "").lower() == "fail_open":
                out.append(self.finding("Guardian is fail_open", d.rel, _line_of(d, "on_unavailable")))
        return out


@InspectionRuleRegistry.register
class ZeroTrustRule(BaseInspectionRule):
    rule_id = "K9-GOV-011"
    title = "Zero Trust enabled with signed identity"
    category = "Zero Trust"
    severity = Severity.RECOMMENDATION
    description = ("Zero Trust at the orchestrator adds identity, role-based authorization, data-loss masking and "
                   "risk scoring. It is off unless enable_zero_trust is set; with payload identity (the 1.x default) "
                   "a caller can claim any role, so signed identity is needed for it to mean anything.")
    fix = "Set enable_zero_trust: true and security.identity.mode: signed (K9_IDENTITY_SECRET in .env)."

    def inspect(self, project: SolutionProject) -> List[Finding]:
        configs = project.config_docs()
        on = any(d.data.get("enable_zero_trust") is True for d in configs) or \
            any("enable_zero_trust=True" in m.source.replace(" ", "") for m in project.code_modules())
        if not on:
            return [self.finding("Zero Trust is not enabled (enable_zero_trust)")]
        signed = any(str(_get(d.data, "security", "identity", "mode") or "").lower() == "signed" for d in configs)
        if not signed:
            return [self.finding("Zero Trust is on but identity is self-declared in the payload",
                                 severity=Severity.WARNING)]
        return []


@InspectionRuleRegistry.register
class FrameworkVersionRule(BaseInspectionRule):
    rule_id = "K9-DEP-001"
    title = "Depends on k9-aif with governance by construction"
    category = "Dependencies"
    severity = Severity.WARNING
    description = ("Governance by construction (every agent and model call governed) needs k9-aif >= 1.15. "
                   "An older pin, or no declared dependency, leaves agents ungoverned unless each calls governance itself.")
    fix = "Declare k9-aif>=1.15 in requirements.txt or pyproject.toml."

    def inspect(self, project: SolutionProject) -> List[Finding]:
        d = declared_framework(project)
        if not d:
            return [self.finding("no k9-aif dependency declared", severity=Severity.RECOMMENDATION)]
        if d["op"] in ("==", "<=", "<", "~=") and d["version"] and older(d["version"], "1.15"):
            return [self.finding(f"pins k9-aif {d['op']}{d['version']} (before governance by construction)",
                                 d["file"], d["line"], d["text"])]
        return []


def older(v: str, ref: str) -> bool:
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
