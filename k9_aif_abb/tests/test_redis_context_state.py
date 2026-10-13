# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

"""RedisContextState: same behaviour as the in-memory state, shared across workers, bounded by
Redis's least-recently-used eviction with quarantine pinned. Needs a Redis: set
K9_TEST_REDIS_URL (e.g. redis://localhost:16379/0, run with --maxmemory-policy volatile-lru)."""

import os
import threading
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from k9_aif_abb.k9_core.streams import BaseContextProjection, ContextUpdate, EventEnvelope
from k9_aif_abb.k9_origin import K9Origin, OriginConfig
from k9_aif_abb.k9_streams import InMemoryContextState

REDIS_URL = os.environ.get("K9_TEST_REDIS_URL")


def _redis_or_skip():
    if not REDIS_URL:
        pytest.skip("set K9_TEST_REDIS_URL to run Redis tests")
    redis = pytest.importorskip("redis")
    client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    try:
        client.ping()
    except Exception:
        pytest.skip(f"no Redis at {REDIS_URL}")
    return client


class InvoiceProjection(BaseContextProjection):
    entity, id_field = "invoice", "invoice_id"

    def accepts(self, env):
        return env.event_type.startswith("invoice.")

    def project(self, env):
        return {k: v for k, v in env.payload.items() if k != "invoice_id"}


class PaymentProjection(BaseContextProjection):
    def accepts(self, env):
        return env.event_type == "payment.posted"

    def project(self, env):
        return {}

    def updates(self, env):
        return [ContextUpdate("invoice", env.payload["invoice_id"],
                              append={"payments": {"payment_id": env.payload["payment_id"]}}, append_limit=500)]


def ev(event_type, seconds_ago=0, **payload):
    e = EventEnvelope(event_type=event_type, source_system="ap", payload=payload)
    e.timestamp = datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
    return e


@pytest.fixture(params=["memory", "redis"])
def state(request):
    projections = [InvoiceProjection(), PaymentProjection()]
    if request.param == "memory":
        yield InMemoryContextState(projections=projections)
        return
    client = _redis_or_skip()
    from k9_aif_abb.k9_streams.redis_context_state import RedisContextState
    prefix = f"k9test-{uuid.uuid4().hex[:8]}"
    st = RedisContextState({"streams": {"state": {"prefix": prefix}}}, projections=projections, client=client)
    yield st
    st.clear()


# ── identical behaviour on both backends ────────────────────────────────
def test_source_order_late_events_and_versions(state):
    state.apply(ev("invoice.created", 30, invoice_id="I-1", status="approved", amount=100))
    state.apply(ev("invoice.updated", 5, invoice_id="I-1", status="disapproved"))
    state.apply(ev("invoice.updated", 20, invoice_id="I-1", status="approved"))       # late
    state.apply(ev("payment.posted", 60, invoice_id="I-1", payment_id="P-1"))          # late append still counts
    cur = state.get_current("invoice", "I-1")
    assert cur["value"]["status"] == "disapproved" and cur["value"]["amount"] == 100
    assert cur["value"]["payments"] == [{"payment_id": "P-1"}] and cur["version"]
    types = [c["type"] for c in state.recent_changes("invoice", "I-1", 3600)["changes"]]
    assert types == ["payment.posted", "invoice.created", "late:invoice.updated", "invoice.updated"]


def test_quarantine_and_query(state):
    state.apply(ev("invoice.created", 1, invoice_id="I-2", status="approved", amount=20000))
    state.apply(ev("invoice.created", 1, invoice_id="I-3", status="received", amount=50))
    state.quarantine(ev("invoice.note", 1, invoice_id="I-3"), "k9x_Shield blocked ingress [PromptInjectionCheck]")
    assert state.get_current("invoice", "I-3")["quarantined"][0]["blocked_by"] == "PromptInjectionCheck"
    rows = state.query("invoice", filters={"status": "approved"}, minimum={"amount": 10000})["rows"]
    assert [r["id"] for r in rows] == ["I-2"]


# ── Redis only ───────────────────────────────────────────────────────────
def test_concurrent_workers_never_lose_an_update():
    client = _redis_or_skip()
    from k9_aif_abb.k9_streams.redis_context_state import RedisContextState
    prefix = f"k9test-{uuid.uuid4().hex[:8]}"
    workers = [RedisContextState({"streams": {"state": {"prefix": prefix, "changes_per_entity": 500}}},
                                 projections=[PaymentProjection()], client=client) for _ in range(4)]

    errors = []

    def post(w, n):
        try:
            for i in range(n):
                w.apply(ev("payment.posted", 0, invoice_id="I-9", payment_id=f"{id(w)}-{i}"))
        except Exception as exc:   # a lost write must fail the test, not hide in a thread
            errors.append(exc)

    threads = [threading.Thread(target=post, args=(w, 25)) for w in workers]
    [t.start() for t in threads]
    [t.join() for t in threads]
    payments = workers[0].get_current("invoice", "I-9")["value"]["payments"]
    workers[0].clear()
    assert not errors, errors
    assert len(payments) == 100 and len({p["payment_id"] for p in payments}) == 100, "no write lost"


def test_eviction_keeps_quarantine_and_read_through_marks_history_unknown():
    client = _redis_or_skip()
    if client.config_get("maxmemory-policy").get("maxmemory-policy") != "volatile-lru" \
            or int(client.config_get("maxmemory").get("maxmemory", 0)) == 0:
        pytest.skip("needs a Redis with maxmemory set and maxmemory-policy volatile-lru")
    from k9_aif_abb.k9_streams.redis_context_state import RedisContextState
    prefix = f"k9test-{uuid.uuid4().hex[:8]}"
    st = RedisContextState({"streams": {"state": {"prefix": prefix}}}, projections=[InvoiceProjection()],
                           client=client)
    try:
        st.apply(ev("invoice.created", 1, invoice_id="Q-1", status="approved"))
        st.quarantine(ev("invoice.note", 1, invoice_id="Q-1"), "k9x_Shield blocked ingress [PaymentDiversionCheck]")
        filler = "x" * 100_000
        limit = int(client.config_get("maxmemory")["maxmemory"])
        for i in range(int(limit / 100_000 * 1.5)):                    # 1.5x memory: forces eviction
            st.apply(ev("invoice.created", 1, invoice_id=f"F-{i}", blob=filler))
        assert client.exists(f"{prefix}:q:invoice:Q-1"), "quarantine markers are pinned"
        q = st.get_current("invoice", "Q-1")
        assert q["found"] and q["quarantined"][0]["blocked_by"] == "PaymentDiversionCheck"
        evicted = next(f"F-{i}" for i in range(10_000) if not client.exists(f"{prefix}:v:invoice:F-{i}"))
        origin = K9Origin(st, OriginConfig.from_dict({"entities": {"invoice": {"system_of_record": "erp"}}}))
        origin.sources.register("erp", lambda e, i: {"status": "approved", "version": 3})
        a = origin.get_current("invoice", evicted)
        assert a["source"]["kind"] == "system_of_record" and a["history_available"] is False
    finally:
        st.clear()
