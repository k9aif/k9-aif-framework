# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

# File: k9_aif_abb/k9_agents/governance/governance_agent.py

import os
from pathlib import Path
import yaml
import re
from typing import Dict, Any, Optional

from k9_aif_abb.k9_core.governance.base_governance import BaseGovernance
from k9_aif_abb.k9_core.inference.ollama_llm import OllamaLLM


class GovernanceAgent(BaseGovernance):
    """
    K9-AIF GovernanceAgent
    ----------------------
    Enforces enterprise safety and compliance policies
    before and after model execution.

    Combines:
    - Keyword / regex-based blocking
    - Intent-domain validation
    - LLM-based reasoning guard
    """

    layer = "Governance ABB"

    def __init__(self, config: Optional[Dict[str, Any]] = None, monitor=None):
        super().__init__(config=config or {}, monitor=monitor)

        default_policy = "k9_aif_abb/policies/governance.yaml"
        policy_path = Path(
            self.config.get("governance", {}).get("policy_path", default_policy)
        )

        try:
            with open(policy_path, "r", encoding="utf-8") as f:
                self.policies = yaml.safe_load(f) or {}
        except FileNotFoundError:
            self.policies = {}

        llm_cfg = self.policies.get(
            "llm_policy_model",
            {"provider": "ollama", "model": "llama-guard-3"},
        )
        self.guard_llm = OllamaLLM(
            host=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434"),
            model=llm_cfg.get("model", "llama-guard-3"),
        )

    async def pre_process(
        self,
        payload: Dict[str, Any],
        ctx: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            await self.log(f"Non-dict payload ({type(payload)}), coercing", "WARN")
            payload = {"input": str(payload)}

        text = str(payload)

        for kw in self.policies.get("blocked_keywords", []):
            if kw.lower() in text.lower():
                await self.log(f"Blocked keyword '{kw}' found", "WARN")
                raise PermissionError(f"GovernanceAgent blocked ingress: blocked keyword '{kw}'")

        if "intent" in payload and self.policies.get("allowed_domains"):
            allowed = self.policies["allowed_domains"]
            if payload["intent"] not in allowed:
                await self.log(f"Intent '{payload['intent']}' not allowed", "WARN")
                raise PermissionError(
                    f"GovernanceAgent blocked ingress: intent '{payload['intent']}' not in allowed_domains"
                )

        prompt = f"Is this request safe under enterprise policy? Answer 'safe' or 'unsafe': {text}"
        result = await self._safe_generate(prompt)
        if result.strip().lower().startswith("unsafe"):
            await self.log(f"LLM pre-check flagged as unsafe -> {result}", "ERROR")
            raise PermissionError(f"GovernanceAgent blocked ingress: LLM guard flagged unsafe ({result})")

        return payload

    async def post_process(
        self,
        payload: Dict[str, Any],
        ctx: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            payload = {"output": str(payload)}

        for rule in self.policies.get("response_redaction", []):
            try:
                _redact_dict(payload, rule["pattern"], rule["replace"])
            except re.error as e:
                await self.log(f"Invalid redaction pattern: {e}", "ERROR")

        prompt = f"Check if this system response is safe: {payload}"
        result = await self._safe_generate(prompt)
        if "unsafe" in result.lower():
            await self.log("LLM post-check flagged unsafe output", "ERROR")
            raise PermissionError(f"GovernanceAgent blocked egress: LLM guard flagged unsafe ({result})")

        return payload

    async def _safe_generate(self, prompt: str) -> str:
        try:
            return str(await self.guard_llm.generate(prompt))
        except Exception as exc:
            await self.log(f"Guard LLM unavailable, failing open to 'safe': {exc}", "WARN")
            return "safe"


def _redact_dict(obj: Any, pattern: str, replace: str) -> None:
    """Recursively apply a redaction regex to every string value in a dict/list, in place."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            if isinstance(value, str):
                obj[key] = re.sub(pattern, replace, value)
            else:
                _redact_dict(value, pattern, replace)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            if isinstance(item, str):
                obj[i] = re.sub(pattern, replace, item)
            else:
                _redact_dict(item, pattern, replace)
