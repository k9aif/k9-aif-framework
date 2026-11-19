# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""Async agents in squads (1.31.0) and the one sync-over-async bridge.

Property: a squad runs an agent whose ``execute()`` is ``async`` to completion,
in or outside a running event loop, and the next step gets its real result.
Before 1.31.0 ``BaseSquad`` stored the un-awaited coroutine as the step's result
and reported the squad ``completed``: a silent failure.
"""

import asyncio
import contextvars

import pytest

from k9_aif_abb.k9_core.agent.base_agent import BaseAgent
from k9_aif_abb.k9_core.orchestration.hil_signal import RequiresHIL
from k9_aif_abb.k9_squad.base_squad import BaseSquad
from k9_aif_abb.k9_utils.async_bridge import resolve, run_sync


class AsyncLookup(BaseAgent):
    async def execute(self, payload):
        await asyncio.sleep(0)
        return {"output": f"found {payload['query']}"}


class SyncFormatter(BaseAgent):
    def execute(self, payload):
        upstream = payload["lookup"]
        assert isinstance(upstream, dict), f"got {type(upstream).__name__}, not the lookup's result"
        return {"output": upstream["output"].upper()}


class AsyncBroken(BaseAgent):
    async def execute(self, payload):
        raise RuntimeError("retriever down")


class AsyncNeedsHuman(BaseAgent):
    async def execute(self, payload):
        raise RequiresHIL(reason="needs review", queue="claims")


def _squad(*agents, flow):
    s = BaseSquad("s1", list(agents))
    s.flow = flow
    s.metadata = {}
    return s


FLOW = [{"agent": "AsyncLookup", "result_key": "lookup"}, {"agent": "SyncFormatter", "result_key": "reply"}]


def test_async_agent_result_reaches_the_next_step():
    out = _squad(AsyncLookup({}), SyncFormatter({}), flow=FLOW).execute({"query": "gold plan"})
    assert out["lookup"] == {"output": "found gold plan"}
    assert out["reply"] == {"output": "FOUND GOLD PLAN"}


def test_async_agent_inside_a_running_event_loop():
    """An async orchestrator (FastAPI, execute_flow) calling the sync squad."""
    async def orchestrator():
        return _squad(AsyncLookup({}), SyncFormatter({}), flow=FLOW).execute({"query": "x"})
    assert asyncio.run(orchestrator())["reply"] == {"output": "FOUND X"}


def test_async_agent_failure_stops_the_squad_with_the_real_error():
    s = _squad(AsyncBroken({}), SyncFormatter({}),
               flow=[{"agent": "AsyncBroken", "result_key": "lookup"}, {"agent": "SyncFormatter"}])
    with pytest.raises(RuntimeError, match="retriever down"):
        s.execute({"query": "x"})


def test_async_agent_requires_hil_propagates():
    s = _squad(AsyncNeedsHuman({}), flow=[{"agent": "AsyncNeedsHuman"}])
    with pytest.raises(RequiresHIL):
        s.execute({})


def test_run_sync_keeps_a_runtime_error_inside_a_loop():
    """The web-search copy re-ran a coroutine that raised RuntimeError and masked the error."""
    async def boom():
        raise RuntimeError("the real error")

    async def caller():
        return run_sync(boom())
    with pytest.raises(RuntimeError, match="the real error"):
        asyncio.run(caller())


def test_run_sync_carries_context_variables_into_the_worker_thread():
    trace = contextvars.ContextVar("trace", default=None)

    async def read():
        return trace.get()

    async def caller():
        trace.set("t-123")
        return run_sync(read())
    assert asyncio.run(caller()) == "t-123"


def test_resolve_passes_plain_values_through():
    assert resolve({"a": 1}) == {"a": 1}
    assert resolve(None) is None
