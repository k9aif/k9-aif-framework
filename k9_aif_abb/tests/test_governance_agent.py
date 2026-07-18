# SPDX-License-Identifier: Apache-2.0
"""
Tests for GovernanceAgent — contract-conformance and bug fixes.

Fixes three real bugs found in this class:
  1. __init__ called LLMFactory.from_config(...), a method that doesn't
     exist on LLMFactory — every construction silently fell back to a
     StubLLM that always returned "safe", never calling a real LLM.
  2. Neither pre_process nor post_process awaited self.guard_llm.generate()
     (an async method) — even with (1) fixed, this would have produced a
     coroutine's string repr instead of real model output.
  3. pre_process returned {"blocked": True, "answer": ...} on block instead
     of raising PermissionError + returning the payload, and post_process
     ALWAYS collapsed the payload into {"answer": text} regardless of
     safe/unsafe — neither matched the contract every other BaseGovernance
     implementation follows.
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from k9_aif_abb.k9_agents.governance.governance_agent import GovernanceAgent


def _make_agent(guard_response: str = "safe", config=None):
    with patch(
        "k9_aif_abb.k9_agents.governance.governance_agent.OllamaLLM"
    ) as mock_llm_cls:
        mock_llm_cls.return_value = AsyncMock(generate=AsyncMock(return_value=guard_response))
        return GovernanceAgent(config=config or {})


# ── construction ───────────────────────────────────────────────────────────

def test_constructs_a_real_ollama_llm_not_a_stub():
    agent = _make_agent()
    assert type(agent.guard_llm).__name__ != "StubLLM"


def test_missing_policy_file_falls_back_to_empty_policies():
    agent = _make_agent(config={"governance": {"policy_path": "/nonexistent/path.yaml"}})
    assert agent.policies == {}


# ── pre_process ───────────────────────────────────────────────────────────

def test_pre_process_returns_payload_on_safe():
    agent = _make_agent(guard_response="safe")
    payload = {"text": "What is the status of claim C001?"}
    result = asyncio.run(agent.pre_process(payload))
    assert result == payload


def test_pre_process_raises_on_llm_unsafe():
    agent = _make_agent(guard_response="unsafe: policy violation")
    with pytest.raises(PermissionError, match="LLM guard flagged unsafe"):
        asyncio.run(agent.pre_process({"text": "do something bad"}))


def test_pre_process_raises_on_blocked_keyword():
    agent = _make_agent(guard_response="safe", config={"governance": {"policy_path": "/nonexistent.yaml"}})
    agent.policies = {"blocked_keywords": ["confidential"]}
    with pytest.raises(PermissionError, match="blocked keyword"):
        asyncio.run(agent.pre_process({"text": "this is confidential info"}))


def test_pre_process_raises_on_disallowed_intent():
    agent = _make_agent(guard_response="safe")
    agent.policies = {"allowed_domains": ["support"]}
    with pytest.raises(PermissionError, match="allowed_domains"):
        asyncio.run(agent.pre_process({"intent": "sales", "text": "hello"}))


def test_pre_process_coerces_non_dict_payload():
    agent = _make_agent(guard_response="safe")
    result = asyncio.run(agent.pre_process("just a string"))
    assert result == {"input": "just a string"}


def test_pre_process_fails_open_when_guard_llm_raises():
    """A crashing/unreachable guard LLM should not block every request by default."""
    with patch(
        "k9_aif_abb.k9_agents.governance.governance_agent.OllamaLLM"
    ) as mock_llm_cls:
        mock_llm_cls.return_value = AsyncMock(generate=AsyncMock(side_effect=RuntimeError("connection refused")))
        agent = GovernanceAgent()
    payload = {"text": "hello"}
    result = asyncio.run(agent.pre_process(payload))
    assert result == payload


# ── post_process ──────────────────────────────────────────────────────────

def test_post_process_returns_payload_dict_on_safe():
    agent = _make_agent(guard_response="safe")
    payload = {"response": "Claim C001 approved."}
    result = asyncio.run(agent.post_process(payload))
    assert result == payload


def test_post_process_raises_on_unsafe():
    agent = _make_agent(guard_response="unsafe: leaked data")
    with pytest.raises(PermissionError, match="blocked egress"):
        asyncio.run(agent.post_process({"response": "here is the data"}))


def test_post_process_redacts_ssn_in_place():
    agent = _make_agent(guard_response="safe")
    agent.policies = {
        "response_redaction": [
            {"pattern": r"\b\d{3}-\d{2}-\d{4}\b", "replace": "[REDACTED-SSN]"},
        ]
    }
    payload = {"output": "customer ssn is 123-45-6789, all set"}
    result = asyncio.run(agent.post_process(payload))
    assert result["output"] == "customer ssn is [REDACTED-SSN], all set"


def test_post_process_redacts_nested_dict_values():
    agent = _make_agent(guard_response="safe")
    agent.policies = {
        "response_redaction": [
            {"pattern": r"\b\d{16}\b", "replace": "[REDACTED-CC]"},
        ]
    }
    payload = {"customer": {"card": "4111111111111111", "name": "Jane"}}
    result = asyncio.run(agent.post_process(payload))
    assert result["customer"]["card"] == "[REDACTED-CC]"
    assert result["customer"]["name"] == "Jane"


def test_post_process_coerces_non_dict_payload():
    agent = _make_agent(guard_response="safe")
    result = asyncio.run(agent.post_process("plain string output"))
    assert result == {"output": "plain string output"}
