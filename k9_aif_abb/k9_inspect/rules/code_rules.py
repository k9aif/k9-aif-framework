# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""Rules over the solution's Python code (AST only)."""

from __future__ import annotations

import ast
import re
from typing import List, Set

from ..base_inspection_rule import BaseInspectionRule
from ..models import Finding, Severity
from ..project import LOOP_AGENT_BASES, PyModule, SolutionProject
from ..registry import InspectionRuleRegistry

# Direct model access that bypasses llm_invoke (and therefore governance and the LLMCall trace).
_DIRECT_LLM_IMPORTS = {"openai", "anthropic", "ollama", "litellm", "google.generativeai", "google.genai",
                       "langchain_openai", "langchain_anthropic", "langchain_ollama", "langchain_community.llms",
                       "mistralai", "cohere", "groq", "ibm_watsonx_ai"}
_DIRECT_LLM_NAMES = {"OllamaLLM", "LLMFactory", "ModelRouterFactory", "K9ModelRouter"}
_LLM_HTTP = re.compile(r"/api/(generate|chat)\b|/v1/(chat/)?completions\b|/v1/messages\b")
_KAFKA_IMPORTS = {"kafka", "confluent_kafka", "aiokafka"}
_KAFKA_CALLS = {"publish_to", "send_and_wait", "produce"}
_PRIVATE_IP = re.compile(r"\b(?:10\.\d{1,3}|192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b")


def _imported_modules(mod: PyModule) -> List[tuple]:
    out = []
    for node in mod.imports:
        if isinstance(node, ast.Import):
            out += [(a.name, a.asname or a.name.split(".")[0], node) for a in node.names]
        elif node.module:
            out += [(node.module, a.asname or a.name, node) for a in node.names]
            out += [(f"{node.module}.{a.name}", a.asname or a.name, node) for a in node.names]
    return out


def _calls(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
            yield name, node


def _inside_llm_invoke_module(mod: PyModule) -> bool:
    return mod.rel.endswith("llm_invoke.py")


@InspectionRuleRegistry.register
class DirectModelAccessRule(BaseInspectionRule):
    rule_id = "K9-LLM-001"
    title = "Model calls go through llm_invoke()"
    category = "LLM path"
    severity = Severity.CRITICAL
    description = ("Every model call must go through llm_invoke(): it is where governance by construction "
                   "checks calls made outside an agent, where empty replies are retried and where the LLMCall "
                   "trace is emitted. Importing a provider SDK, OllamaLLM, LLMFactory or ModelRouterFactory, "
                   "or posting to a model HTTP endpoint, bypasses all three.")
    fix = ("Replace with: from k9_aif_abb.k9_utils.llm_invoke import llm_invoke; "
           "llm_invoke(self.config, InferenceRequest(prompt=..., task_type=...)).")

    def inspect(self, project: SolutionProject) -> List[Finding]:
        out = []
        for m in project.code_modules():
            if _inside_llm_invoke_module(m):
                continue
            # Execution layers (agent/squad/orchestrator) must not reach models directly: CRITICAL.
            # Elsewhere (entry points, health checks, a custom BaseModelRouter SBB) wiring a router or
            # probing the model server is legitimate; a provider SDK or model HTTP call there is a WARNING.
            layer = bool(m.roles & {"agent", "squad", "orchestrator"})
            sev = Severity.CRITICAL if layer else Severity.WARNING
            seen_nodes = set()
            for full, alias, node in _imported_modules(m):
                if id(node) in seen_nodes:
                    continue
                top = full.split(".")[0]
                sdk = full in _DIRECT_LLM_IMPORTS or top in _DIRECT_LLM_IMPORTS
                if sdk or (layer and alias in _DIRECT_LLM_NAMES):
                    seen_nodes.add(id(node))
                    out.append(self.at(m, node, f"imports {full if sdk else alias} — model access outside llm_invoke()",
                                       severity=sev))
            for node in ast.walk(m.tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and _LLM_HTTP.search(node.value):
                    out.append(self.at(m, node, "calls a model HTTP endpoint directly"
                                       + ("" if layer else " (acceptable for health checks / warm-up, not for inference)"),
                                       severity=sev))
            for name, node in _calls(m.tree):
                if name == "invoke" and isinstance(node.func, ast.Attribute) and \
                        re.search(r"router", ast.unparse(node.func.value), re.I) and \
                        not any(c.role is None and "Router" in c.name for c in m.classes):
                    out.append(self.at(m, node, "calls a model router's invoke() directly", severity=sev))
        return _dedupe(out)


@InspectionRuleRegistry.register
class LlmInvokeErrorHandlingRule(BaseInspectionRule):
    rule_id = "K9-LLM-002"
    title = "llm_invoke() failures are handled"
    category = "LLM path"
    severity = Severity.WARNING
    description = "llm_invoke() raises RuntimeError on failure (it never returns empty output); an unhandled call fails the whole flow."
    fix = "Wrap the call: try: ... except RuntimeError as exc: return a failed result with the reason."

    def inspect(self, project: SolutionProject) -> List[Finding]:
        out = []
        for m in project.code_modules():
            guarded: Set[int] = set()
            for node in ast.walk(m.tree):
                if isinstance(node, ast.Try) and node.handlers:
                    for inner in ast.walk(ast.Module(body=node.body, type_ignores=[])):
                        guarded.add(id(inner))
            for name, node in _calls(m.tree):
                if name in ("llm_invoke", "llm_invoke_stream") and id(node) not in guarded:
                    out.append(self.at(m, node, f"{name}() not inside try/except"))
        return out


@InspectionRuleRegistry.register
class InferenceTaskTypeRule(BaseInspectionRule):
    rule_id = "K9-LLM-003"
    title = "InferenceRequest names a task_type"
    category = "LLM path"
    severity = Severity.RECOMMENDATION
    description = "The Model Router scores models on task_type; without it every request routes on defaults."
    fix = "Pass task_type=... (e.g. 'extraction', 'reasoning', 'summarization') to InferenceRequest."

    def inspect(self, project: SolutionProject) -> List[Finding]:
        out = []
        for m in project.code_modules():
            for name, node in _calls(m.tree):
                if name == "InferenceRequest" and not any(k.arg == "task_type" for k in node.keywords) \
                        and not any(k.arg is None for k in node.keywords):
                    out.append(self.at(m, node, "InferenceRequest without task_type"))
        return out


@InspectionRuleRegistry.register
class AgentContractRule(BaseInspectionRule):
    rule_id = "K9-CON-001"
    title = "Agents extend a K9-AIF agent ABB"
    category = "ABB contract"
    severity = Severity.VIOLATION
    description = ("A class that acts as an agent (named *Agent with an execute() method) must extend BaseAgent "
                   "or another K9-AIF agent ABB. Otherwise governance by construction never wraps it.")
    fix = "Extend BaseAgent (one-shot), K9ValidationLoopAgent (converge on a score) or K9PlanningLoopAgent."

    def inspect(self, project: SolutionProject) -> List[Finding]:
        out = []
        for c in project.classes():
            if c.name.endswith("Agent") and "execute" in c.methods and c.role != "agent" \
                    and not c.name.startswith(("Base", "Abstract")):
                out.append(self.at(c.module, c.node, f"{c.name} has execute() but does not extend a K9-AIF agent ABB"))
        return out


@InspectionRuleRegistry.register
class LoopAgentContractRule(BaseInspectionRule):
    rule_id = "K9-CON-002"
    title = "Loop agents implement the loop hooks, not execute()"
    category = "ABB contract"
    severity = Severity.VIOLATION
    description = ("Validation, planning and critic-actor agents run their loop inside the ABB's execute(); "
                   "a subclass overriding execute() replaces the loop and its convergence handling.")
    fix = "Remove execute() and implement the loop methods (hypothesize/validate/observe/finalize or equivalents)."

    def inspect(self, project: SolutionProject) -> List[Finding]:
        return [self.at(c.module, c.methods["execute"], f"{c.name} overrides execute() of {', '.join(sorted(c.framework_bases))}")
                for c in project.classes("agent")
                if c.framework_bases & LOOP_AGENT_BASES and "execute" in c.methods]


@InspectionRuleRegistry.register
class LayerDecouplingRule(BaseInspectionRule):
    rule_id = "K9-DEC-001"
    title = "Three-layer decoupling"
    category = "Decoupling"
    severity = Severity.VIOLATION
    description = ("Each layer knows only the layer below: Router → Orchestrators, Orchestrator → Squads, "
                   "Squad → Agents. An agent importing a squad, or an orchestrator importing agents, couples layers "
                   "that must evolve independently.")
    fix = "Reference the layer below only; register agents in the app entry point and resolve them through the registry."

    _FORBIDDEN = {"agent": {"squad", "orchestrator", "router"}, "squad": {"orchestrator", "router"},
                  "orchestrator": {"agent", "router"}, "router": {"agent", "squad"}}

    def inspect(self, project: SolutionProject) -> List[Finding]:
        role_of = {c.name: c.role for c in project.classes() if c.role}
        out = []
        for m in project.code_modules():
            roles = m.roles
            if len(roles) != 1:
                continue              # entry points and mixed modules wire layers on purpose
            mine = next(iter(roles))
            bad: dict = {}
            first_node = {}
            for full, alias, node in _imported_modules(m):
                name = full.split(".")[-1]
                other = role_of.get(name)
                if other and other in self._FORBIDDEN[mine]:
                    bad.setdefault(other, set()).add(name)
                    first_node.setdefault(other, node)
            for other, names in bad.items():
                out.append(self.at(m, first_node[other],
                                   f"{mine} module imports {other} class(es): {', '.join(sorted(names))}"))
        return out


@InspectionRuleRegistry.register
class KafkaOwnershipRule(BaseInspectionRule):
    rule_id = "K9-KAF-001"
    title = "Only Router and Orchestrator touch Kafka"
    category = "Kafka ownership"
    severity = Severity.VIOLATION
    description = ("Agents and squads never publish to Kafka: a publish below the layer that decides whether "
                   "execution continues cannot stop the rest of the flow. To ask for a human decision, raise RequiresHIL.")
    fix = "Return the data to the orchestrator, or raise RequiresHIL; publish from the Orchestrator or Router."

    def inspect(self, project: SolutionProject) -> List[Finding]:
        out = []
        for m in project.code_modules():
            if not (m.roles & {"agent", "squad"}) or m.roles & {"orchestrator", "router"}:
                continue
            for full, _, node in _imported_modules(m):
                if full.split(".")[0] in _KAFKA_IMPORTS:
                    out.append(self.at(m, node, f"agent/squad module imports {full}"))
            for name, node in _calls(m.tree):
                if name in _KAFKA_CALLS or (name == "publish" and "message_bus" in ast.unparse(node.func)):
                    out.append(self.at(m, node, f"agent/squad calls {name}()"))
        return _dedupe(out)


@InspectionRuleRegistry.register
class NoopGovernanceRule(BaseInspectionRule):
    rule_id = "K9-GOV-003"
    title = "No NoopGovernance outside tests"
    category = "Governance"
    severity = Severity.WARNING
    description = "NoopGovernance checks nothing; in production the framework refuses to run with it."
    fix = "Remove it and enable security.shield in config.yaml (every agent is then governed automatically)."

    def inspect(self, project: SolutionProject) -> List[Finding]:
        out = []
        for m in project.code_modules():
            for node in ast.walk(m.tree):
                if isinstance(node, ast.Name) and node.id == "NoopGovernance":
                    out.append(self.at(m, node, "uses NoopGovernance"))
        return _dedupe(out)


@InspectionRuleRegistry.register
class HardcodedAddressRule(BaseInspectionRule):
    rule_id = "K9-CFG-001"
    title = "No hardcoded private IP addresses"
    category = "Configuration"
    severity = Severity.VIOLATION
    description = "Private IP addresses in code or config tie the solution to one network and leak its layout."
    fix = 'Read the address from an environment variable with a localhost default, e.g. os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").'

    def inspect(self, project: SolutionProject) -> List[Finding]:
        out = []
        sources = [(m.rel, m.source) for m in project.modules if not m.is_test] + \
                  [(d.rel, d.text) for d in project.yaml_docs] + \
                  [(project.rel(p), p.read_text(errors="replace")) for p in project.other_files
                   if p.suffix in (".sh", ".env", ".cfg", ".ini", ".toml") or p.name in ("Containerfile", "Dockerfile")]
        for rel, text in sources:
            if rel.endswith((".env", ".env.local")):
                continue                  # the deployment's own env file is where addresses belong
            for i, line in enumerate(text.splitlines(), 1):
                if _PRIVATE_IP.search(line) and not line.lstrip().startswith("#"):
                    out.append(self.finding(f"private IP address {_PRIVATE_IP.search(line).group()}", rel, i, line.strip()))
        return out


@InspectionRuleRegistry.register
class LoopPatternRule(BaseInspectionRule):
    rule_id = "K9-PAT-001"
    title = "Hand-written model loops use a loop ABB"
    category = "Patterns"
    severity = Severity.RECOMMENDATION
    description = ("An execute() that calls llm_invoke() inside a for/while loop re-implements iteration the "
                   "framework provides, with telemetry and disposition routing, in K9ValidationLoopAgent.")
    fix = "Move the loop into K9ValidationLoopAgent (converge on a confidence score) or K9PlanningLoopAgent."

    def inspect(self, project: SolutionProject) -> List[Finding]:
        out = []
        for c in project.classes("agent"):
            if c.framework_bases & LOOP_AGENT_BASES or "execute" not in c.methods:
                continue
            for node in ast.walk(c.methods["execute"]):
                if isinstance(node, (ast.For, ast.While, ast.AsyncFor)) and \
                        any(n == "llm_invoke" for n, _ in _calls(node)):
                    out.append(self.at(c.module, node, f"{c.name}.execute() calls llm_invoke() in a loop"))
                    break
        return out


@InspectionRuleRegistry.register
class SyntaxRule(BaseInspectionRule):
    rule_id = "K9-SYN-001"
    title = "All Python files parse"
    category = "Code"
    severity = Severity.VIOLATION
    description = "A file that does not parse cannot be inspected and will fail at import."
    fix = "Fix the syntax error."

    def inspect(self, project: SolutionProject) -> List[Finding]:
        return [self.finding(f"does not parse ({m.error})", m.rel) for m in project.modules if m.error]


def _dedupe(findings: List[Finding]) -> List[Finding]:
    seen, out = set(), []
    for f in findings:
        key = (f.rule_id, f.file, f.line, f.message)
        if key not in seen:
            seen.add(key)
            out.append(f)
    return out


@InspectionRuleRegistry.register
class GovernanceOptOutRule(BaseInspectionRule):
    rule_id = "K9-GOV-007"
    title = "No agent opts out of the governance wrapper"
    category = "Governance"
    severity = Severity.CRITICAL
    description = ("_governs_own_execute = True tells BaseAgent not to wrap execute() with pre/post governance. "
                   "Only the loop ABBs set it, because they govern around their loop; on any other agent it switches "
                   "the input and output checks off.")
    fix = "Remove _governs_own_execute from the agent; BaseAgent then checks every call automatically."

    def inspect(self, project: SolutionProject) -> List[Finding]:
        out = []
        for c in project.classes("agent"):
            if c.framework_bases & LOOP_AGENT_BASES:
                continue
            for node in c.node.body:
                targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
                if any(isinstance(t, ast.Name) and t.id == "_governs_own_execute" for t in targets) and \
                        isinstance(getattr(node, "value", None), ast.Constant) and node.value.value is True:
                    out.append(self.at(c.module, node, f"{c.name} sets _governs_own_execute = True (governance wrapper off)"))
        for m in project.code_modules():
            for node in ast.walk(m.tree):
                if isinstance(node, ast.Assign) and any(isinstance(t, ast.Attribute) and t.attr == "_governs_own_execute"
                                                        for t in node.targets) \
                        and isinstance(node.value, ast.Constant) and node.value.value is True:
                    out.append(self.at(m, node, "sets _governs_own_execute = True at runtime (governance wrapper off)"))
        return _dedupe(out)


@InspectionRuleRegistry.register
class OrchestratorIngressRule(BaseInspectionRule):
    rule_id = "K9-GOV-008"
    title = "Orchestrators screen their own ingress"
    category = "Governance"
    severity = Severity.WARNING
    description = ("Governance by construction wraps agents, not orchestrators or routers. An orchestrator that "
                   "receives external payloads should screen them (apply_shield / apply_pre_governance, or a "
                   "governance= at construction) and, where identities matter, apply_zero_trust.")
    fix = ("In execute_flow(): sh = self.apply_shield(payload); if not sh['allowed']: return a denial — or build the "
           "orchestrator with governance=ShieldGovernance(config).")

    _HOOKS = ("apply_shield", "apply_pre_governance", "apply_zero_trust", "governance=", "ShieldGovernance(",
              "GuardianGovernance(", "ChainedGovernance(", "assert_governed", "_build_ingress_chain")
    _ADAPTERS = {"CrewAIOrchestratorAdapter", "LangGraphOrchestratorAdapter", "ClaudeAgentSDKOrchestratorAdapter",
                 "BaseHILOrchestrator"}

    def inspect(self, project: SolutionProject) -> List[Finding]:
        wiring = " ".join(m.source for m in project.code_modules() if not m.roles)   # entry points
        out = []
        for c in project.classes("orchestrator"):
            if c.framework_bases & self._ADAPTERS:
                continue                       # adapters govern their own boundary
            body = ast.get_source_segment(c.module.source, c.node) or ""
            screened_here = any(h in body for h in self._HOOKS)
            governed_at_wiring = "governance=" in wiring or "enable_zero_trust" in wiring
            if not screened_here and not governed_at_wiring:
                out.append(self.at(c.module, c.node, f"{c.name} never screens its ingress (acceptable only if every input was screened upstream)"))
        return out


@InspectionRuleRegistry.register
class LegacyAgentHooksRule(BaseInspectionRule):
    rule_id = "K9-GOV-009"
    title = "Pre-1.15 agents call the governance hooks themselves"
    category = "Governance"
    severity = Severity.VIOLATION
    description = ("Before k9-aif 1.15 the base class did not wrap execute(): each agent had to call "
                   "enforce_governance() / apply_pre_governance() and apply_post_governance(). A solution pinned to an "
                   "older framework whose agents do not is ungoverned.")
    fix = "Upgrade to k9-aif>=1.15 (governance by construction), or call the hooks at the top and end of execute()."

    def inspect(self, project: SolutionProject) -> List[Finding]:
        from .config_rules import declared_framework, older
        spec = declared_framework(project)
        if not spec or not spec.get("version") or not older(spec["version"], "1.15") or spec.get("op") in (">=", ">"):
            return []
        out = []
        for c in project.classes("agent"):
            if c.framework_bases & LOOP_AGENT_BASES or "execute" not in c.methods:
                continue
            src = ast.get_source_segment(c.module.source, c.methods["execute"]) or ""
            if not any(h in src for h in ("enforce_governance", "apply_pre_governance", "assert_governed")):
                out.append(self.at(c.module, c.methods["execute"],
                                   f"{c.name}.execute() calls no governance hook on k9-aif {spec['op']}{spec['version']}"))
        return out
