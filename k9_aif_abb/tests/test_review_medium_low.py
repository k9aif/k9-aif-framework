# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""The medium and low findings of the 2026-10-25 framework review, each as the property it protects.

Property: no component reports success for work it did not do, and every configuration it is given is
actually used. Each test fails on the code before 1.19.0.
"""

import pytest

from k9_aif_abb.k9_core.router.k9_event_router import K9EventRouter


# ── no message bus: no silent "routed" ───────────────────────────────────

def test_router_without_message_bus_refuses_instead_of_reporting_routed():
    router = K9EventRouter(config={"k9_env": "test", "routing": {"table": {"claim": "claims.in"}}})
    with pytest.raises(RuntimeError, match="no message_bus"):
        router.route({"event_type": "claim"})


def test_intent_orchestrator_without_message_bus_refuses():
    from k9_aif_abb.k9_orchestrators.intent_orchestrator import IntentOrchestrator

    class _Squad:
        def execute(self, payload):
            return {"intent": "claims", "confidence": 0.95}

    orch = IntentOrchestrator(config={"k9_env": "test", "routing": {"table": {"claims": "claims.in"}}},
                              squad=_Squad())
    with pytest.raises(RuntimeError, match="no message_bus"):
        orch.execute_flow({"event_type": "mystery"})


# ── intent: one threshold, and the orchestrator knows only squads ───────

def test_intent_squad_and_orchestrator_share_one_default_threshold():
    from k9_aif_abb.k9_orchestrators.intent_orchestrator import IntentOrchestrator
    from k9_aif_abb.k9_squad.intent_squad import DEFAULT_CONFIDENCE_THRESHOLD, IntentSquad
    orch = IntentOrchestrator(config={"k9_env": "test"}, squad=IntentSquad("s", agents=[]))
    assert orch._threshold == DEFAULT_CONFIDENCE_THRESHOLD
    import inspect
    from k9_aif_abb.k9_squad import intent_squad
    assert "0.5" not in inspect.getsource(intent_squad.IntentSquad)


def test_intent_orchestrator_module_never_names_an_agent():
    """No import of, and no reference to, an agent class in the orchestrator's code (docstrings may mention it)."""
    import ast, inspect
    from k9_aif_abb.k9_orchestrators import intent_orchestrator
    tree = ast.parse(inspect.getsource(intent_orchestrator))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
    assert not {x for x in names | imported if x.endswith("Agent")}


# ── factories use the configuration they're given, and fail loudly ─────

def test_monitor_factory_uses_the_application_config(tmp_path, monkeypatch):
    from k9_aif_abb.k9_factories.monitor_factory import MonitorFactory
    monkeypatch.chdir(tmp_path)                          # no k9_aif_abb/ here: the old relative path broke
    cfg = {"monitors": [{"name": "logger", "class": "k9_aif_abb.k9_core.monitoring.logger_monitor.LoggerMonitor"}],
           "common_tags": {"app": "acme"}}
    server = MonitorFactory.create(cfg)
    assert [type(m).__name__ for m in server._monitors] == ["LoggerMonitor"] and server._common == {"app": "acme"}
    assert MonitorFactory.create({"monitors": []})._monitors == []
    assert [type(m).__name__ for m in MonitorFactory.create({})._monitors] == ["LoggerMonitor"]   # framework default


def test_monitor_factory_refuses_a_monitor_it_cannot_build():
    from k9_aif_abb.k9_factories.monitor_factory import MonitorFactory
    with pytest.raises(ValueError, match="can't build monitor"):
        MonitorFactory.create({"monitors": [{"name": "x", "class": "no.such.Monitor"}]})


def test_persistence_factory_raises_for_an_unknown_provider():
    from k9_aif_abb.k9_factories.persistence_factory import PersistenceFactory
    with pytest.raises(ValueError, match="not registered"):
        PersistenceFactory.create({"vectordb": {"backend": "postgress"}})


# ── llm_invoke: short waits when the model server is down ───────────────

def _invoke_with(outputs_or_errors, **kw):
    from unittest.mock import MagicMock, patch
    import k9_aif_abb.k9_utils.llm_invoke as mod
    from k9_aif_abb.k9_inference.models.inference_request import InferenceRequest
    seq = []
    for x in outputs_or_errors:
        if isinstance(x, Exception):
            seq.append(x)
        else:
            r = MagicMock(); r.output = x; r.model_alias = "m"; r.provider = "p"; r.latency_ms = 1; r.token_usage = {}
            seq.append(r)
    with patch.object(mod, "ModelRouterFactory") as f, patch.object(mod.time, "sleep") as sleep:
        f.get_router.return_value.invoke.side_effect = seq
        try:
            mod.llm_invoke(kw.pop("config", {}), InferenceRequest(prompt="x", task_type="general"), **kw)
        except RuntimeError:
            pass
        return [c.args[0] for c in sleep.call_args_list]


def test_unreachable_model_waits_briefly():
    assert _invoke_with([ConnectionRefusedError("refused")] * 3) == [5.0, 5.0]
    assert _invoke_with(["[WARN] connection refused"] * 3) == [5.0, 5.0]       # OllamaLLM's way of saying it


def test_empty_reply_keeps_the_long_wait():
    assert _invoke_with(["", "", ""]) == [60.0, 60.0]


def test_retry_settings_come_from_config_and_explicit_args_win():
    cfg = {"inference": {"retry": {"attempts": 2, "delay_seconds": 30, "unreachable_delay_seconds": 1}}}
    assert _invoke_with(["", ""], config=cfg) == [30.0]
    assert _invoke_with([ConnectionError("x")] * 2, config=cfg) == [1.0]
    assert _invoke_with(["", "", ""], config=cfg, max_retries=3, retry_delay_s=10) == [10.0, 10.0]


# ── the LLMCall trace names the model that really answered ─────────────

def test_trace_resolves_the_model_through_llm_ref():
    from unittest.mock import MagicMock, patch
    import k9_aif_abb.k9_utils.llm_invoke as mod
    from k9_aif_abb.k9_inference.models.inference_request import InferenceRequest
    cfg = {"inference": {"model_catalog": {"models": {"secure": {"llm_ref": "granite"}}},
                         "llm_factory": {"models": {"granite": {"model": "granite3.3:8b"}, "secure": "wrong-model"}}}}
    r = MagicMock(); r.output = "ok"; r.model_alias = "secure"; r.provider = "ollama"; r.latency_ms = 1; r.token_usage = {}
    events = []
    with patch.object(mod, "ModelRouterFactory") as f, patch.object(mod, "emit_trace_event", events.append):
        f.get_router.return_value.invoke.return_value = r
        mod.llm_invoke(cfg, InferenceRequest(prompt="x", task_type="general"))
    assert events[0]["model"] == "granite3.3:8b"


# ── configured but broken is an error, not "not configured" ────────────

def test_router_with_a_broken_object_storage_block_refuses_to_start(monkeypatch):
    from k9_aif_abb.k9_factories.object_storage_factory import ObjectStorageFactory
    monkeypatch.setattr(ObjectStorageFactory, "create", staticmethod(lambda cfg: (_ for _ in ()).throw(ValueError("bad endpoint"))))
    with pytest.raises(ValueError, match="bad endpoint"):
        K9EventRouter(config={"k9_env": "test", "object_storage": {"provider": "s3"}})
    assert K9EventRouter(config={"k9_env": "test"}).object_store is None          # absent block: None, as before


# ── the squad's digest writer doesn't borrow another agent's persona ───

def test_synthesizer_does_not_inherit_the_first_agents_role(monkeypatch):
    from k9_aif_abb.k9_squad.base_squad import BaseSquad
    from k9_aif_abb.k9_core.agent.base_agent import BaseAgent

    class IntakeAgent(BaseAgent):
        def execute(self, payload):
            return {"output": "x"}

    agent = IntakeAgent(config={"k9_env": "test", "role": "You are a claims intake clerk", "goal": "intake",
                                "inference": {"x": 1}})
    squad = BaseSquad("s", [agent])
    synth = squad._get_synthesizer({"mode": "always"})
    assert "role" not in synth.config and "goal" not in synth.config and synth.config.get("inference") == {"x": 1}
    squad2 = BaseSquad("s2", [agent]); squad2.config = {"k9_env": "test", "inference": {"y": 2}}
    assert squad2._get_synthesizer({"mode": "always"}).config.get("inference") == {"y": 2}
