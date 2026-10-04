# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""k9_inspect: each rule finds its violation in a small solution and passes a clean one."""

import textwrap

from k9_aif_abb.k9_inspect import InspectionRuleRegistry, K9Inspector, Severity


def write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(text))


CLEAN_CONFIG = """
enable_zero_trust: true
inference:
  llm_factory:
    models:
      fast: {provider: ollama, model: qwen3.8:27b}
governance:
  guardian: {enabled: true}
security:
  identity: {mode: signed}
  shield:
    enabled: true
    ingress: {checks: [InputSizeCheck, PromptInjectionCheck, PIIBoundaryCheck]}
    egress: {checks: [PIIBoundaryCheck, OutboundLinkCheck]}
"""

CLEAN_AGENT = """
from k9_aif_abb.k9_core.agent.base_agent import BaseAgent
from k9_aif_abb.k9_utils.llm_invoke import llm_invoke
from k9_aif_abb.k9_inference.models.inference_request import InferenceRequest

class SummaryAgent(BaseAgent):
    def execute(self, payload):
        try:
            resp = llm_invoke(self.config, InferenceRequest(prompt="x", task_type="summarization"))
        except RuntimeError as exc:
            return {"status": "failed", "reason": str(exc)}
        return {"output": resp}
"""


def clean(tmp_path):
    write(tmp_path, "config/config.yaml", CLEAN_CONFIG)
    write(tmp_path, "agents/summary_agent.py", CLEAN_AGENT)
    write(tmp_path, "squads/s.yaml", "squads:\n  s1:\n    agents: [SummaryAgent]\n    flow:\n      - {agent: SummaryAgent}\n")
    write(tmp_path, "requirements.txt", "k9-aif>=1.15\n")
    return tmp_path


def ids(report):
    return {f.rule_id for f in report.findings}


def test_clean_solution_is_compliant(tmp_path):
    r = K9Inspector().inspect(clean(tmp_path))
    assert r.verdict == "COMPLIANT", r.to_markdown()
    assert r.score == 100


def test_direct_model_access_in_agent_is_critical(tmp_path):
    clean(tmp_path)
    write(tmp_path, "agents/bad_agent.py", """
        import openai
        from k9_aif_abb.k9_core.agent.base_agent import BaseAgent
        class BadAgent(BaseAgent):
            def execute(self, payload):
                return {"output": openai.chat.completions.create(model="x", messages=[])}
    """)
    r = K9Inspector().inspect(tmp_path)
    f = [f for f in r.findings if f.rule_id == "K9-LLM-001"]
    assert f and f[0].severity == Severity.CRITICAL and r.verdict == "NON-COMPLIANT"


def test_agent_not_extending_abb_and_kafka_and_decoupling(tmp_path):
    clean(tmp_path)
    write(tmp_path, "agents/rogue_agent.py", """
        class RogueAgent:
            def execute(self, payload):
                return {}
    """)
    write(tmp_path, "agents/pub_agent.py", """
        from kafka import KafkaProducer
        from k9_aif_abb.k9_core.agent.base_agent import BaseAgent
        class PubAgent(BaseAgent):
            def execute(self, payload):
                return {}
    """)
    write(tmp_path, "orchestrators/o.py", """
        from k9_aif_abb.k9_core.orchestration.base_orchestrator import BaseOrchestrator
        from agents.summary_agent import SummaryAgent
        class MyOrchestrator(BaseOrchestrator):
            pass
    """)
    r = K9Inspector().inspect(tmp_path)
    assert {"K9-CON-001", "K9-KAF-001", "K9-DEC-001"} <= ids(r)


def test_governance_config_rules(tmp_path):
    clean(tmp_path)
    write(tmp_path, "config/config.yaml", """
        inference: {llm_factory: {models: {fast: {model: m}}}}
        security:
          shield: {enabled: true, ingress: {checks: []}, egress: {checks: []}}
        postgres: {password: Sup3rSecret!}
    """)
    r = K9Inspector().inspect(tmp_path)
    assert {"K9-GOV-002", "K9-GOV-004", "K9-CFG-002"} <= ids(r)
    write(tmp_path, "config/config.yaml", "inference: {llm_factory: {models: {}}}\n")
    assert "K9-GOV-001" in ids(K9Inspector().inspect(tmp_path))


def test_yaml_hygiene_and_ip(tmp_path):
    clean(tmp_path)
    write(tmp_path, "squads/bad.yaml", "squads:\n  s2:\n    orchestrator: X\n    agents: [A]\n    flow: [A, {agent: B}]\n")
    write(tmp_path, "agents/a.yaml", "agents:\n  A: {squad: s2, model: missing_alias}\n")
    write(tmp_path, "agents/net.py", 'URL = "http://192.168.1.50:11434"\n')
    write(tmp_path, "Containerfile", "ENV K9_ENV=development\n")
    write(tmp_path, "requirements.txt", "k9-aif==1.12.10\n")
    r = K9Inspector().inspect(tmp_path)
    assert {"K9-YAML-001", "K9-YAML-002", "K9-CFG-004", "K9-CFG-001", "K9-GOV-005", "K9-DEP-001"} <= ids(r)


def test_inspector_never_executes_code(tmp_path):
    clean(tmp_path)
    marker = tmp_path / "executed.txt"
    write(tmp_path, "agents/boom.py", f'open(r"{marker}", "w").write("x")\nraise SystemExit(1)\n')
    K9Inspector().inspect(tmp_path)
    assert not marker.exists()


def test_custom_rule_registers(tmp_path):
    from k9_aif_abb.k9_inspect import BaseInspectionRule

    class Always(BaseInspectionRule):
        rule_id, title, category = "ORG-001", "org rule", "Org"
        def inspect(self, project):
            return [self.finding("org finding")]

    InspectionRuleRegistry.register(Always)
    try:
        assert "ORG-001" in ids(K9Inspector().inspect(clean(tmp_path)))
    finally:
        InspectionRuleRegistry.unregister("ORG-001")


def test_reports_render(tmp_path):
    r = K9Inspector().inspect(clean(tmp_path))
    assert "# K9-AIF Compliance Report" in r.to_markdown()
    assert '"verdict"' in r.to_json()


def test_governance_switched_off_is_reported(tmp_path):
    clean(tmp_path)
    write(tmp_path, "config/config.yaml", CLEAN_CONFIG.replace("enabled: true\n    ingress", "enabled: false\n    ingress")
          .replace("guardian: {enabled: true}", "guardian: {enabled: false, on_unavailable: fail_open}"))
    write(tmp_path, "agents/optout_agent.py", """
        from k9_aif_abb.k9_core.agent.base_agent import BaseAgent
        class OptOutAgent(BaseAgent):
            _governs_own_execute = True
            def execute(self, payload):
                return {}
    """)
    r = K9Inspector().inspect(tmp_path)
    msgs = {f.rule_id: f.message for f in r.findings}
    assert "explicitly disabled" in msgs["K9-GOV-001"]
    assert "explicitly disabled" in msgs["K9-GOV-004"]
    assert {"K9-GOV-007", "K9-GOV-010"} <= set(msgs)
    assert [f for f in r.findings if f.rule_id == "K9-GOV-007"][0].severity == Severity.CRITICAL


def test_framework_version_reported(tmp_path):
    clean(tmp_path)
    write(tmp_path, "pyproject.toml", 'description = "K9-AIF app"\ndependencies = ["k9-aif==1.14.1", "fastapi"]\n')
    write(tmp_path, "requirements.txt", "fastapi\n")
    r = K9Inspector(config={"latest_version": "1.15.0"}).inspect(tmp_path)
    assert r.framework["status"] == "outdated" and r.framework["version"] == "1.14.1"
    assert "K9-DEP-002" in ids(r) and "latest k9-aif 1.15.0" in r.to_markdown()
