# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
GoRulesAdapter (1.29.0): a GoRules decision service (the GoRules agent) as a K9-AIF rules adapter.

The rules live in GoRules decision models (JDM files: decision tables and graphs), served by the GoRules agent;
K9-AIF only calls them, so a rule change is a change to a reviewed file, not to application code. In the K9X
ecosystem this is the K9X Rules Engine (currently GoRules, ``k9x-ecosystem/k9x_rules_engine``).

Calls ``POST {engine_url}/api/projects/{project}/evaluate/{ruleset}`` with ``{"context": facts}`` and returns the
model's result (e.g. ``{"decision", "rule", "reason", ...}``). Registered as ``gorules`` in
``IntegrationAdapterFactory``; used by ``K9RulesAgent`` like any ``BaseRulesAdapter``.

Config::

    rules_agent:
      adapter: gorules
      engine_url: "${K9X_RULES_ENGINE_URL:-http://localhost:8130}"
      project: accounts-payable          # a folder in the agent's rules directory
      ruleset: invoice-approval.json     # the decision model in it
      facts: invoice_agent.output        # optional: dotted path to the facts in the payload (JSON text is parsed)
      timeout: 10
"""

from __future__ import annotations

import json
from typing import Any, Dict

from .base_rules_adapter import BaseRulesAdapter


class GoRulesAdapter(BaseRulesAdapter):

    def facts_from(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """The facts sent to GoRules: the payload, or the value at ``facts`` (a dotted path); JSON text is parsed."""
        value: Any = payload
        path = self.config.get("facts")
        if path:
            for part in str(path).split("."):
                if isinstance(value, str):
                    value = _parse(value)
                value = value.get(part) if isinstance(value, dict) else None
        if isinstance(value, str):
            value = _parse(value)
        if not isinstance(value, dict):
            raise ValueError(f"[GoRulesAdapter] no facts at {path!r} in the payload (got {type(value).__name__})")
        return value

    def evaluate(self, ruleset: str, facts: Dict[str, Any]) -> Any:
        import requests
        base = self.config["engine_url"].rstrip("/")
        project = self.config["project"]
        url = f"{base}/api/projects/{project}/evaluate/{ruleset}"
        resp = requests.post(url, json={"context": self.facts_from(facts)},
                             headers=self.config.get("headers") or {}, timeout=float(self.config.get("timeout", 10)))
        resp.raise_for_status()
        body = resp.json()
        return body.get("result", body) if isinstance(body, dict) else body


def _parse(text: str) -> Any:
    try:
        return json.loads(text)
    except ValueError:
        return text
