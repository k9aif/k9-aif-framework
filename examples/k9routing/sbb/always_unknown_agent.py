# SPDX-License-Identifier: Apache-2.0
"""
Scenario 3 helper — AlwaysUnknownAgent

An intent agent that never recognises an intent, so the orchestrator's
clarification path can be shown without an LLM. Kept in the SBB package,
not in run.py: the entry point wires layers, it does not define them.
"""

from k9_aif_abb.k9_agents.intent.k9_intent_agent import K9IntentAgent


class AlwaysUnknownAgent(K9IntentAgent):
    def classify(self, payload):
        return "unknown"
