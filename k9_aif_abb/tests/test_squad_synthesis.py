# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""Squad coordinator (1.16): BaseSquad ``synthesis:`` and K9ContextSynthesizerAgent."""

import types

import pytest

from k9_aif_abb.k9_agents.synthesis import K9ContextSynthesizerAgent
from k9_aif_abb.k9_core.agent.base_agent import BaseAgent
from k9_aif_abb.k9_squad.base_squad import BaseSquad, synthesis_config


class Recorder(BaseAgent):
    """Records the context it was given; returns a large output."""
    size = 400

    def __init__(self, config=None):
        super().__init__(config or {})
        self.seen = []

    def execute(self, payload):
        self.seen.append(dict(payload))
        return {"output": self.__class__.__name__ * self.size}


class A(Recorder): pass
class B(Recorder): pass
class C(Recorder): pass


class FakeSynth:
    def __init__(self):
        self.calls = []

    def execute(self, payload):
        self.calls.append(payload)
        return {"output": "DIGEST of " + ",".join(payload["results"])}


def squad(synthesis=None, flow=None):
    agents = [A(), B(), C()]
    s = BaseSquad("s1", agents)
    s.description = "test squad"
    s.flow = flow or [{"agent": "A"}, {"agent": "B"}, {"agent": "C"}]
    s.metadata = {"synthesis": synthesis} if synthesis is not None else {}
    s.synthesizer = FakeSynth()
    return s, agents


def test_off_by_default_every_agent_sees_full_results():
    s, (a, b, c) = squad()
    out = s.execute({"q": 1})
    assert "A" in c.seen[0] and "B" in c.seen[0] and "squad_digest" not in c.seen[0]
    assert s.synthesizer.calls == [] and "squad_synthesis" not in out


def test_auto_below_threshold_changes_nothing():
    s, (a, b, c) = squad({"mode": "auto", "max_context_chars": 10_000_000})
    s.execute({"q": 1})
    assert "A" in c.seen[0] and s.synthesizer.calls == []


def test_auto_above_threshold_gives_a_digest_and_keeps_full_results():
    s, (a, b, c) = squad({"mode": "auto", "max_context_chars": 1000})
    out = s.execute({"q": 1})
    # B sees A's output (400 chars, under 1000); C would see A+B (800 + json) ... force via size
    assert out["A"]["output"].startswith("AA") and out["B"]["output"].startswith("BB")
    assert all("q" in seen for seen in c.seen)   # original payload always passed


def test_always_gives_each_later_step_a_digest_not_the_full_outputs():
    s, (a, b, c) = squad("always")
    out = s.execute({"q": 1})
    assert "squad_digest" not in a.seen[0]                      # nothing upstream yet
    assert b.seen[0]["squad_digest"] == "DIGEST of A" and "A" not in b.seen[0]
    assert c.seen[0]["squad_digest"] == "DIGEST of A,B" and "B" not in c.seen[0]
    assert c.seen[0]["q"] == 1 and c.seen[0]["squad_digest_keys"] == ["A", "B"]
    assert out["A"]["output"] == "A" * 400                      # full outputs kept for audit
    assert [e["step"] for e in out["squad_synthesis"]] == [2, 3]
    assert out["squad_synthesis"][1]["chars_in"] > out["squad_synthesis"][1]["chars_out"]


def test_auto_engages_once_upstream_passes_the_size():
    s, (a, b, c) = squad({"mode": "auto", "max_context_chars": 500})
    out = s.execute({"q": 1})
    assert "A" in b.seen[0]                                     # A alone is under 500 chars
    assert c.seen[0]["squad_digest"] == "DIGEST of A,B"         # A+B is over
    assert [e["step"] for e in out["squad_synthesis"]] == [3]


def test_explicit_context_keys_and_step_opt_out_are_never_synthesized():
    flow = [{"agent": "A"}, {"agent": "B", "context_keys": ["A"]}, {"agent": "C", "synthesis": False}]
    s, (a, b, c) = squad("always", flow)
    s.execute({"q": 1})
    assert "A" in b.seen[0] and "squad_digest" not in b.seen[0]
    assert "B" in c.seen[0] and "squad_digest" not in c.seen[0]
    assert s.synthesizer.calls == []


def test_synthesis_config_forms_and_bad_mode():
    assert synthesis_config({})["mode"] == "off"
    assert synthesis_config({"synthesis": True})["mode"] == "auto"
    assert synthesis_config({"synthesis": "always"})["mode"] == "always"
    assert synthesis_config({"synthesis": {"mode": "auto"}})["max_context_chars"] == 24000
    with pytest.raises(ValueError):
        synthesis_config({"synthesis": "sometimes"})


def test_default_synthesizer_is_a_governed_agent_calling_llm_invoke(monkeypatch):
    import k9_aif_abb.k9_agents.synthesis.context_synthesizer_agent as mod
    seen = {}

    def fake_invoke(config, req):
        seen["req"] = req
        return types.SimpleNamespace(output="  the digest  ", model_alias="m")

    monkeypatch.setattr(mod, "llm_invoke", fake_invoke)
    agent = K9ContextSynthesizerAgent(config={})
    assert isinstance(agent, BaseAgent)
    out = agent.execute({"results": {"criteria": "12 criteria", "score": 0.82}, "task": "gate readiness"})
    assert out == {"output": "the digest", "source_keys": ["criteria", "score"]}
    assert "12 criteria" in seen["req"].prompt and seen["req"].task_type == "summarization"


def test_squad_creates_the_default_synthesizer_when_none_given(monkeypatch):
    import k9_aif_abb.k9_agents.synthesis.context_synthesizer_agent as mod
    monkeypatch.setattr(mod, "llm_invoke",
                        lambda c, r: types.SimpleNamespace(output="D", model_alias="m"))
    s, (a, b, c) = squad("always")
    s.synthesizer = None
    s.execute({"q": 1})
    assert isinstance(s.synthesizer, K9ContextSynthesizerAgent) and c.seen[0]["squad_digest"] == "D"
