# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
#
# test_learned_model_router.py -- K9ModelRouter learned routing (evidence
# from graded outcomes), against a real in-memory SQLite RoutingStateStore.
#
# Run:
#   pytest k9_aif_abb/tests/test_learned_model_router.py -v

import pytest

from k9_aif_abb.k9_inference.catalog.model_catalog import ModelCatalog
from k9_aif_abb.k9_inference.learning import HashingPromptEmbedder, similarity
from k9_aif_abb.k9_inference.models.inference_request import InferenceRequest
from k9_aif_abb.k9_inference.routers import k9_model_router as kmr
from k9_aif_abb.k9_inference.routers.k9_model_router import K9ModelRouter
from k9_aif_abb.k9_storage.routing_state_store import RoutingStateStore
from k9_aif_abb.k9_storage.sqlite_database_storage import SQLiteDatabaseStorage


MODELS = {
    "fast": {"provider": "ollama", "llm_ref": "fast", "capabilities": ["chat", "summarization"],
             "latency_tier": "realtime", "cost_tier": "minimal"},
    "smart": {"provider": "ollama", "llm_ref": "smart", "capabilities": ["reasoning", "analysis"],
              "latency_tier": "interactive", "cost_tier": "standard"},
    "secure": {"provider": "ollama", "llm_ref": "secure", "capabilities": ["confidential"],
               "latency_tier": "batch", "cost_tier": "premium"},
}

SQL = ["Write a SQL query that returns the top {n} customers by total claim amount.",
       "Write a SQL query joining policies and claims to count open claims per region {n}.",
       "Write a SQL query listing adjusters with more than {n} pending claims.",
       "Write a SQL query that finds duplicate claim numbers in table batch {n}."]
PROOF = ["Prove that the sum of the first {n} odd numbers is a perfect square.",
         "Prove by induction that {n} factorial grows faster than two to the power n.",
         "Prove that there are infinitely many primes, then discuss case {n}.",
         "Prove the triangle inequality holds for vectors in dimension {n}."]


def _store():
    return RoutingStateStore(SQLiteDatabaseStorage(db_path=":memory:"))


def _router(store=None, learning=None, models=None):
    cfg = {"inference": {"router": {"learning": {"refresh_seconds": 0, **(learning or {})}}}}
    return K9ModelRouter(catalog=ModelCatalog({"default_model": "fast", "models": models or MODELS}),
                         config=cfg, state_store=store or _store())


def _teach(router, prompts, alias, quality, task="reasoning", latency_ms=None, n=5):
    for i in range(n):
        for p in prompts:
            router.record_feedback(p.format(n=i + 3), alias, quality, task_type=task, latency_ms=latency_ms)


# ---------------------------------------------------------------------------
# Embedder
# ---------------------------------------------------------------------------

def test_embedder_similar_prompts_score_higher_than_unrelated():
    e = HashingPromptEmbedder()
    a = e.embed(SQL[0].format(n=5), "reasoning")
    b = e.embed(SQL[1].format(n=9), "reasoning")
    c = e.embed(PROOF[0].format(n=5), "reasoning")
    assert similarity(a, a) == pytest.approx(1.0)
    assert similarity(a, b) > similarity(a, c)


def test_embedder_separates_task_types():
    e = HashingPromptEmbedder()
    text = "Summarise this claim note for the adjuster."
    assert similarity(e.embed(text, "summarization"), e.embed(text, "summarization")) > \
        similarity(e.embed(text, "summarization"), e.embed(text, "extraction"))


# ---------------------------------------------------------------------------
# Cold start == rules
# ---------------------------------------------------------------------------

def test_no_evidence_routes_by_rules():
    d = _router().route(InferenceRequest(prompt="Prove it", task_type="reasoning"))
    assert d.model_alias == "smart" and d.strategy == "rules" and d.predictions is None


def test_learning_can_be_switched_off_with_a_string():
    r = _router(learning={"enabled": "false"})
    _teach(r, PROOF, "fast", 95)
    _teach(r, PROOF, "smart", 20)
    assert r.route(InferenceRequest(prompt=PROOF[0].format(n=99), task_type="reasoning")).model_alias == "smart"


# ---------------------------------------------------------------------------
# Evidence overrules the rules -- per prompt, not per task type
# ---------------------------------------------------------------------------

def test_evidence_overrules_capability_when_clearly_better():
    r = _router()
    _teach(r, PROOF, "fast", 90)
    _teach(r, PROOF, "smart", 50)
    d = r.route(InferenceRequest(prompt=PROOF[1].format(n=42), task_type="reasoning"))
    assert d.model_alias == "fast" and d.strategy == "learned"
    assert d.predicted_quality == pytest.approx(90, abs=0.5)
    assert "beats rules' pick smart" in d.rationale


def test_small_difference_keeps_the_rules_pick():
    r = _router()
    _teach(r, PROOF, "fast", 52)
    _teach(r, PROOF, "smart", 50)
    d = r.route(InferenceRequest(prompt=PROOF[1].format(n=42), task_type="reasoning"))
    assert d.model_alias == "smart" and "within margin" in d.rationale


def test_routes_differently_per_prompt_within_one_task_type():
    """The Not Diamond property: same task type, different best model."""
    r = _router()
    _teach(r, SQL, "fast", 92)
    _teach(r, SQL, "smart", 60)
    _teach(r, PROOF, "fast", 40)
    _teach(r, PROOF, "smart", 88)
    sql = r.route(InferenceRequest(prompt="Write a SQL query returning claims above 10000 by region.",
                                   task_type="reasoning"))
    proof = r.route(InferenceRequest(prompt="Prove that the square root of two is irrational.",
                                     task_type="reasoning"))
    assert sql.model_alias == "fast"
    assert proof.model_alias == "smart"


def test_evidence_for_another_task_type_is_ignored():
    r = _router()
    _teach(r, SQL, "fast", 95, task="extraction")
    _teach(r, SQL, "smart", 10, task="extraction")
    d = r.route(InferenceRequest(prompt="Hello, what can you do?", task_type="chat"))
    assert d.model_alias == "fast" and d.strategy == "rules" and d.predictions is None


# ---------------------------------------------------------------------------
# Latency / cost trade-off
# ---------------------------------------------------------------------------

def test_realtime_budget_trades_quality_for_speed():
    r = _router()
    _teach(r, PROOF, "smart", 90, latency_ms=20000)
    _teach(r, PROOF, "fast", 80, latency_ms=1000)
    prompt = PROOF[2].format(n=7)
    assert r.route(InferenceRequest(prompt=prompt, task_type="reasoning")).model_alias == "smart"
    fast = r.route(InferenceRequest(prompt=prompt, task_type="reasoning", latency_budget="realtime"))
    assert fast.model_alias == "fast" and fast.predicted_latency_ms == 1000


def test_minimal_cost_profile_penalises_expensive_models():
    r = _router()
    _teach(r, PROOF, "smart", 88)   # standard tier
    _teach(r, PROOF, "fast", 82)    # minimal tier
    prompt = PROOF[3].format(n=4)
    assert r.route(InferenceRequest(prompt=prompt, task_type="reasoning")).model_alias == "smart"
    assert r.route(InferenceRequest(prompt=prompt, task_type="reasoning",
                                    cost_profile="minimal")).model_alias == "fast"


# ---------------------------------------------------------------------------
# Guard rails evidence can't cross
# ---------------------------------------------------------------------------

def test_confidential_request_stays_on_confidential_models():
    r = _router()
    _teach(r, PROOF, "fast", 99)
    _teach(r, PROOF, "smart", 95)
    _teach(r, PROOF, "secure", 40)
    d = r.route(InferenceRequest(prompt=PROOF[0].format(n=8), task_type="reasoning",
                                 sensitivity="confidential"))
    assert d.model_alias == "secure"


def test_circuit_breaker_skips_a_failing_model():
    store = _store()
    r = _router(store)
    for _ in range(6):
        store.record_outcome(model_alias="smart", task_type="reasoning", success=False, latency_ms=5)
    d = r.route(InferenceRequest(prompt="Prove it", task_type="reasoning"))
    assert d.model_alias != "smart" and "skipped (failing): smart" in d.rationale


def test_breaker_never_trips_every_model():
    store = _store()
    r = _router(store)
    for alias in MODELS:
        for _ in range(6):
            store.record_outcome(model_alias=alias, success=False)
    assert r.route(InferenceRequest(prompt="Prove it", task_type="reasoning")).model_alias == "smart"


# ---------------------------------------------------------------------------
# Session affinity (tie-break only)
# ---------------------------------------------------------------------------

def test_session_affinity_breaks_a_tie():
    models = {**MODELS, "chatty": {"provider": "ollama", "llm_ref": "chatty", "capabilities": ["chat"]}}
    store = _store()
    r = _router(store, models=models)
    req = InferenceRequest(prompt="hi", task_type="chat", session_id="conv-42")
    assert r.route(req).model_alias == "fast"                   # catalog order on the tie
    sid = r._resolve_session_id(req)
    store.ensure_session(sid, "u1")
    store.update_model_affinity(sid, "chatty")
    assert r.route(req).model_alias == "chatty"                 # the conversation stays put
    reasoning = InferenceRequest(prompt="prove", task_type="reasoning", session_id="conv-42")
    assert r.route(reasoning).model_alias == "smart"            # affinity never beats capability


def test_string_session_ids_map_to_stable_uuids():
    r = _router()
    a = r._resolve_session_id(InferenceRequest(prompt="x", session_id="conv-42"))
    b = r._resolve_session_id(InferenceRequest(prompt="x", session_id="conv-42"))
    assert a == b and len(a) == 36


# ---------------------------------------------------------------------------
# Feedback API, persistence, runtime outcomes
# ---------------------------------------------------------------------------

def test_record_feedback_validates_input():
    r = _router()
    with pytest.raises(ValueError):
        r.record_feedback("x", "nope", 50)
    with pytest.raises(ValueError):
        r.record_feedback("x", "fast", 150)


def test_evidence_is_persisted_and_shared_across_router_instances():
    store = _store()
    teacher = _router(store)
    _teach(teacher, PROOF, "fast", 90)
    _teach(teacher, PROOF, "smart", 45)
    fresh = _router(store)
    assert fresh.route(InferenceRequest(prompt=PROOF[0].format(n=11), task_type="reasoning")).model_alias == "fast"
    rows = store.load_outcomes(graded_only=True)
    assert len(rows) == 40 and all(r["source"] == "feedback" for r in rows)


def test_invoke_records_runtime_outcomes(monkeypatch):
    class Stub:
        def invoke(self, prompt, system_prompt=None):
            return "ok"

    class Boom:
        def invoke(self, prompt, system_prompt=None):
            raise RuntimeError("model down")

    store = _store()
    r = _router(store)
    monkeypatch.setattr(kmr.LLMFactory, "get", staticmethod(lambda ref: Stub()))
    resp = r.invoke(InferenceRequest(prompt="Prove it", task_type="reasoning"))
    assert resp.output == "ok" and resp.latency_ms is not None
    monkeypatch.setattr(kmr.LLMFactory, "get", staticmethod(lambda ref: Boom()))
    with pytest.raises(RuntimeError):
        r.invoke(InferenceRequest(prompt="Prove it", task_type="reasoning"))
    rows = store.load_outcomes()
    assert [(x["model_alias"], x["success"], x["source"]) for x in rows] == \
        [("smart", False, "runtime"), ("smart", True, "runtime")]


def test_confidential_request_never_goes_to_an_uncleared_model_even_on_rules():
    """Regression: +3 capability used to beat +2 confidential."""
    d = _router().route(InferenceRequest(prompt="Prove it", task_type="reasoning",
                                         sensitivity="confidential"))
    assert d.model_alias == "secure" and d.strategy == "rules"


def test_confidential_without_any_cleared_model_keeps_old_behaviour():
    models = {k: v for k, v in MODELS.items() if k != "secure"}
    d = _router(models=models).route(InferenceRequest(prompt="Prove it", task_type="reasoning",
                                                      sensitivity="confidential"))
    assert d.model_alias == "smart"
