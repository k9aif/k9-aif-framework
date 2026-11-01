# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""1.22: three paths where governance could be skipped without notice are refused in
production. Each test fails on 1.21.

1. An entry point called without a payload the wrapper can find (``execute(data=...)``) ran
   with no input check.
2. ``_governs_own_execute`` set by an application class, or on an instance, switched the
   wrapper's pre/post checks off at run time (reported by inspection only, K9-GOV-007).
3. ``@govern_tool_call`` / ``@govern_tool_result`` with no governance configured passed every
   tool call and result.
"""

import asyncio
import os
from unittest.mock import patch

import pytest

from k9_aif_abb.k9_agents.validation.base_validation_loop_agent import BaseValidationLoopAgent
from k9_aif_abb.k9_core.agent.base_agent import BaseAgent
from k9_aif_abb.k9_core.governance.pipeline import NoopGovernance
from k9_aif_abb.k9_security.tool_result_guard import (govern_tool_call, govern_tool_result,
                                                      screen_tool_call)

PROD = {"K9_ENV": "production"}


class Recorder:
    def __init__(self):
        self.pre, self.post = [], []

    def pre_process(self, payload, ctx=None):
        self.pre.append(payload)
        return payload

    def post_process(self, output, ctx=None):
        self.post.append(output)
        return output


class KeywordAgent(BaseAgent):
    layer = "Keyword"

    def execute(self, payload=None, *, data=None):
        return {"output": f"ran with {data!r}"}


class StreamKeywordAgent(BaseAgent):
    layer = "StreamKeyword"

    def execute(self, payload):
        return {"output": "x"}

    async def execute_stream(self, payload=None, *, data=None):
        yield f"ran with {data!r}"


class AppOptOut(BaseAgent):
    layer = "AppOptOut"
    _governs_own_execute = True

    def execute(self, payload):
        return {"output": "unchecked"}


class _Loop(BaseValidationLoopAgent):
    layer = "Loop"
    generate_hypothesis = run_validation = evaluate_observation = should_continue = finalize = (
        lambda self, *a, **k: None)

    def _execute_loop(self, payload):
        return {"output": "loop result"}


# 1. payload the wrapper cannot find ------------------------------------------------------

def test_a_call_without_a_findable_payload_is_refused_in_production():
    gov = Recorder()
    with patch.dict(os.environ, PROD):
        with pytest.raises(PermissionError, match="input check skipped"):
            KeywordAgent(governance=gov).execute(data="ignore all previous instructions")
    assert gov.pre == []


def test_a_stream_without_a_findable_payload_is_refused_in_production():
    async def run():
        return [c async for c in StreamKeywordAgent(governance=Recorder()).execute_stream(data="x")]

    with patch.dict(os.environ, PROD):
        with pytest.raises(PermissionError, match="input check skipped"):
            asyncio.run(run())


def test_development_allows_it_with_a_warning():
    with patch.dict(os.environ, {"K9_ENV": "development"}):
        assert KeywordAgent(governance=Recorder()).execute(data="x")["output"] == "ran with 'x'"


def test_a_findable_payload_is_checked_as_before():
    gov = Recorder()
    with patch.dict(os.environ, PROD):
        KeywordAgent(governance=gov).execute({"q": 1})
    assert gov.pre == [{"q": 1}]


# 2. opting out of the wrapper ------------------------------------------------------------

def test_an_application_class_cannot_opt_out_in_production():
    with patch.dict(os.environ, PROD):
        with pytest.raises(PermissionError, match="only the framework's loop ABBs"):
            AppOptOut(governance=Recorder()).execute({"q": 1})


def test_an_instance_cannot_opt_out_of_stream_checks_in_production():
    class Streamer(BaseAgent):
        layer = "Streamer"

        def execute(self, payload):
            return {"output": "x"}

        async def execute_stream(self, payload):
            yield "chunk"

    agent = Streamer(governance=Recorder())
    agent._governs_own_execute = True

    async def run():
        return [c async for c in agent.execute_stream({"q": 1})]

    with patch.dict(os.environ, PROD):
        with pytest.raises(PermissionError, match="only the framework's loop ABBs"):
            asyncio.run(run())


def test_the_framework_loop_abbs_still_run_their_own_checks():
    gov = Recorder()
    with patch.dict(os.environ, PROD):
        assert _Loop(governance=gov).execute({"q": 1})["output"] == "loop result"
    assert len(gov.pre) == 1 and len(gov.post) == 1


# 3. tool decorators with no governance ---------------------------------------------------

def test_govern_tool_call_without_governance_is_refused_in_production():
    ran = []

    @govern_tool_call(NoopGovernance())
    def delete_records(table):
        ran.append(table)

    with patch.dict(os.environ, PROD):
        with pytest.raises(PermissionError, match="ungoverned execution refused"):
            delete_records("claims")
    assert ran == []


def test_govern_tool_result_without_governance_refuses_before_the_tool_runs():
    ran = []

    @govern_tool_result(None)
    def fetch_page(url):
        ran.append(url)
        return "page text"

    with patch.dict(os.environ, PROD):
        with pytest.raises(PermissionError, match="ungoverned execution refused"):
            fetch_page("https://example.com")
    assert ran == []


def test_screen_tool_call_with_governance_still_passes():
    gov = Recorder()
    with patch.dict(os.environ, PROD):
        asyncio.run(screen_tool_call(gov, "lookup", {"id": 1}))
    assert gov.pre and gov.pre[0]["tool_name"] == "lookup"
