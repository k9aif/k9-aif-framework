# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

"""TriageAgent classifies a request with the model and falls back to its rules when the model is
unavailable. The model is mocked here; run this file directly to try it against a live Ollama:

    K9_ENV=development python -m examples.acme_support_center.tests.triage_agent_test
"""

from types import SimpleNamespace
from unittest.mock import patch

from examples.acme_support_center.agents.src.triage_agent import TriageAgent

_LLM = "examples.acme_support_center.agents.src.acme_base_agent.llm_invoke"
REQUEST = "My login is not working and this is urgent."


class MockTicketTool:
    def run(self, payload):
        return {"ticket_found": False, "message": "No existing ticket found."}


def make_agent():
    return TriageAgent(
        config={
            "description": "Initial triage and classification of support requests",
            "pattern": "react",
            "model": "general",
            "config": {"max_iterations": 3},
            "inference": {"llm_factory": {"provider": "ollama", "base_url": "http://localhost:11434",
                                          "models": {"general": "llama3.2:1b"}}},
        },
        tools={"ticket_tool": MockTicketTool()},
    )


def test_model_classification_is_used():
    reply = '{"intent": "account_help", "category": "login", "priority": "high"}'
    with patch(_LLM, return_value=SimpleNamespace(output=reply, model_alias="general")):
        result = make_agent().run(REQUEST)
    assert result["status"] == "success"
    assert (result["triage"]["intent"], result["triage"]["priority"]) == ("account_help", "high")
    assert result["tool_result"]["ticket_tool"]["ticket_found"] is False


def test_rules_classify_when_the_model_is_unavailable():
    with patch(_LLM, side_effect=RuntimeError("connection refused")):
        result = make_agent().run(REQUEST)
    assert result["status"] == "success"
    assert result["triage"]["intent"]                       # rule-based classification


if __name__ == "__main__":
    print(make_agent().run(REQUEST))
