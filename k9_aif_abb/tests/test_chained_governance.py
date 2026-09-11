# SPDX-License-Identifier: Apache-2.0
"""
Tests for ChainedGovernance — composing multiple governance stages, additive
not substitutive (see k9_governance/chained_governance.py docstring).
"""

import asyncio

import pytest

from k9_aif_abb.k9_core.governance.base_governance import BaseGovernance
from k9_aif_abb.k9_governance.chained_governance import ChainedGovernance


class _SyncStage(BaseGovernance):
    """Mimics ShieldGovernance's shape: sync pre/post, no await needed."""

    def __init__(self, name, block_on=None, config=None):
        super().__init__(config=config)
        self.name = name
        self.block_on = block_on or {}
        self.calls = []

    def pre_process(self, payload, ctx=None):
        self.calls.append(("pre", payload.get("marker")))
        if self.block_on.get("pre"):
            raise PermissionError(f"{self.name} blocked pre")
        return {**payload, self.name: "pre_ok"}

    def post_process(self, payload, ctx=None):
        self.calls.append(("post", payload.get("marker")))
        if self.block_on.get("post"):
            raise PermissionError(f"{self.name} blocked post")
        return {**payload, self.name: "post_ok"}


class _AsyncStage(BaseGovernance):
    """Mimics ProfanityGovernance's shape: async pre/post."""

    def __init__(self, name, block_on=None, config=None):
        super().__init__(config=config)
        self.name = name
        self.block_on = block_on or {}
        self.calls = []

    async def pre_process(self, payload, ctx=None):
        self.calls.append(("pre", payload.get("marker")))
        if self.block_on.get("pre"):
            raise PermissionError(f"{self.name} blocked pre")
        return {**payload, self.name: "pre_ok"}

    async def post_process(self, payload, ctx=None):
        self.calls.append(("post", payload.get("marker")))
        if self.block_on.get("post"):
            raise PermissionError(f"{self.name} blocked post")
        return {**payload, self.name: "post_ok"}


def test_stages_run_in_order_and_results_thread_through():
    a = _SyncStage("a")
    b = _SyncStage("b")
    chain = ChainedGovernance(a, b)
    result = asyncio.run(chain.pre_process({"marker": 1}))
    assert result == {"marker": 1, "a": "pre_ok", "b": "pre_ok"}


def test_sync_and_async_stages_mix_correctly():
    a = _SyncStage("shield_like")
    b = _AsyncStage("guardian_like")
    chain = ChainedGovernance(a, b)
    result = asyncio.run(chain.pre_process({"marker": "x"}))
    assert result == {"marker": "x", "shield_like": "pre_ok", "guardian_like": "pre_ok"}


def test_post_process_runs_all_stages_too():
    a = _SyncStage("a")
    b = _AsyncStage("b")
    chain = ChainedGovernance(a, b)
    result = asyncio.run(chain.post_process({"marker": 1}))
    assert result == {"marker": 1, "a": "post_ok", "b": "post_ok"}


def test_first_stage_block_prevents_second_stage_running():
    a = _SyncStage("a", block_on={"pre": True})
    b = _SyncStage("b")
    chain = ChainedGovernance(a, b)
    with pytest.raises(PermissionError, match="a blocked pre"):
        asyncio.run(chain.pre_process({"marker": 1}))
    assert b.calls == []  # never reached


def test_second_stage_block_still_runs_first_stage_first():
    a = _SyncStage("a")
    b = _AsyncStage("b", block_on={"post": True})
    chain = ChainedGovernance(a, b)
    with pytest.raises(PermissionError, match="b blocked post"):
        asyncio.run(chain.post_process({"marker": 1}))
    assert a.calls == [("post", 1)]  # first stage did run before the block


def test_none_entries_are_filtered_out():
    a = _SyncStage("a")
    chain = ChainedGovernance(a, None, None)
    result = asyncio.run(chain.pre_process({"marker": 1}))
    assert result == {"marker": 1, "a": "pre_ok"}


def test_empty_chain_passes_payload_through_unchanged():
    chain = ChainedGovernance()
    payload = {"marker": 1}
    assert asyncio.run(chain.pre_process(payload)) == payload
    assert asyncio.run(chain.post_process(payload)) == payload
