# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""1.18.6: one trace id across a run's events (monitoring: stitch the execution path), and pinned
model digests (supply chain: the weights behind a tag cannot change unnoticed). Offline."""

import asyncio

import pytest

from k9_aif_abb.k9_core.inference.model_integrity import ModelIntegrityError, check_digest
from k9_aif_abb.k9_core.inference.ollama_llm import OllamaLLM
from k9_aif_abb.k9_core.orchestration.base_orchestrator import BaseOrchestrator
from k9_aif_abb.k9_squad.base_squad import BaseSquad
from k9_aif_abb.k9_utils import trace_events
from k9_aif_abb.k9_utils.trace_events import emit_trace_event, register_trace_callback, trace_scope

DIGEST = "a" * 64
TAGS = {"models": [{"name": "granite3.3:8b", "model": "granite3.3:8b", "digest": DIGEST}]}


@pytest.fixture
def events(monkeypatch):
    got = []
    monkeypatch.setattr(trace_events, "_trace_callback", None)
    register_trace_callback(got.append)
    return got


class _Gov:
    def pre_process(self, payload, ctx=None):
        return payload

    def post_process(self, payload, ctx=None):
        return payload


class _Orch(BaseOrchestrator):
    layer = "TraceTest"

    def execute_flow(self, payload):
        return {}


def _squad(squad_id):
    def execute(self, context):
        emit_trace_event({"type": "LLMCall", "agent": squad_id})      # what an agent's model call emits
        return {"ok": True}
    agent = type(f"{squad_id}Agent", (), {"execute": execute})()
    squad = BaseSquad(squad_id=squad_id, agents=[agent])
    squad.flow = [{"agent": f"{squad_id}Agent", "result_key": "r"}]
    return squad


def test_every_event_of_a_run_carries_the_runs_id_sequential_and_parallel(events):
    orch = _Orch(config={}, governance=_Gov())
    orch.execute_squads([_squad("A"), _squad("B")], {"job_id": "job-42"})
    orch.execute_squads([_squad("C"), _squad("D")], {"correlation_id": "corr-7"}, parallel=True)
    by_agent = {e["agent"]: e["trace_id"] for e in events if e["type"] == "LLMCall"}
    assert by_agent == {"A": "job-42", "B": "job-42", "C": "corr-7", "D": "corr-7"}


def test_a_run_without_an_id_gets_one_and_events_outside_a_run_get_none(events):
    orch = _Orch(config={}, governance=_Gov())
    orch.execute_squads([_squad("A"), _squad("B")], {"input": "x"})
    ids = {e["trace_id"] for e in events if e["type"] == "LLMCall"}
    assert len(ids) == 1 and len(ids.pop()) == 32
    emit_trace_event({"type": "LLMCall", "agent": "loose"})
    assert "trace_id" not in events[-1]
    with trace_scope("outer"):
        with trace_scope():                      # nested scope keeps the request's id
            emit_trace_event({"type": "X"})
    assert events[-1]["trace_id"] == "outer"


def test_pinned_digest_matches_and_mismatch_is_refused(events):
    check_digest("granite3.3:8b", f"sha256:{DIGEST}", TAGS)                      # same weights: fine
    with pytest.raises(ModelIntegrityError, match="weights behind this tag changed"):
        check_digest("granite3.3:8b", "sha256:" + "b" * 64, TAGS)
    with pytest.raises(ModelIntegrityError, match="does not list it"):
        check_digest("qwen3:32b", DIGEST, TAGS)
    assert [e["allowed"] for e in events if e["type"] == "ModelIntegrity"] == [True, False, False]


def test_ollama_refuses_before_sending_the_prompt(monkeypatch):
    llm = OllamaLLM(model="granite3.3:8b", digest="sha256:" + "b" * 64)
    sent = []

    async def fake_tags(self):
        self._pin.verify(TAGS)
    monkeypatch.setattr(OllamaLLM, "_verify_model", fake_tags)
    monkeypatch.setattr("aiohttp.ClientSession.post", lambda *a, **k: sent.append(a))
    with pytest.raises(ModelIntegrityError):
        asyncio.run(llm.generate("hello"))
    assert sent == []                                            # no prompt reached the server
    assert "digest" not in llm.kwargs                            # not passed on as a model option


def test_unpinned_model_is_not_checked():
    llm = OllamaLLM(model="granite3.3:8b")
    assert not llm._pin.due()
