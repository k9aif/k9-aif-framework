# SPDX-License-Identifier: Apache-2.0
"""
SBB override example 1 — ConfigListIntentAgent

Demonstrates: replace K9IntentAgent with a keyword-matching agent
driven entirely by a config list.  No LLM required.

SBBs override BaseIntentAgent.classify() — that's the only method
they need to implement.  Everything else (normalize, fallback,
confidence, execute lifecycle) is inherited.
"""

from typing import Any, Dict, Optional
from k9_aif_abb.k9_agents.intent.base_intent_agent import BaseIntentAgent


class ConfigListIntentAgent(BaseIntentAgent):
    """
    Intent classification via keyword matching against a config list.

    Config key: ``intent_keywords`` — dict of intent_label → [keyword, ...]
    The first intent whose keywords appear in the message wins.

    Example config::

        intent_keywords:
          fraud:    ["fraud", "scam", "suspicious", "unauthorized"]
          claims:   ["claim", "accident", "damage", "repair"]
          document: ["upload", "document", "attach", "file"]
    """

    layer = "ConfigListIntentAgent SBB"

    def __init__(self, config: Optional[Dict[str, Any]] = None, **kwargs):
        super().__init__(config=config or {}, **kwargs)
        # Check top-level first, then inside routing section (IntentOrchestrator merges them)
        self._keywords: Dict[str, list] = (
            self.config.get("intent_keywords")
            or self.config.get("routing", {}).get("intent_keywords", {})
        )

    def classify(self, payload: Dict[str, Any]) -> str:
        text = str(payload.get("message", payload.get("text", ""))).lower()
        for intent, keywords in self._keywords.items():
            if any(kw.lower() in text for kw in keywords):
                return intent
        return ""
