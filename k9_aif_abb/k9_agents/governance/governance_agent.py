# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

# File: k9_aif_abb/k9_agents/governance/governance_agent.py

import logging
from pathlib import Path
import yaml
import re

from k9_aif_abb.k9_core.agent.base_agent import BaseAgent
from k9_aif_abb.k9_factories.llm_factory import LLMFactory


class GovernanceAgent(BaseAgent):
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

    def __init__(self, config=None):
        super().__init__(config or {}, name="GovernanceAgent")

        # ------------------------------------------------------------------
        # Load policy configuration
        # ------------------------------------------------------------------
        default_policy = "k9_aif_abb/policies/governance.yaml"
        policy_path = Path(
            self.config.get("governance", {}).get("policy_path", default_policy)
        )

        try:
            with open(policy_path, "r") as f:
                self.policies = yaml.safe_load(f) or {}
            self.log(f"[{self.layer}] Loaded governance policy from {policy_path}", "INFO")
        except FileNotFoundError:
            self.policies = {}
            self.log(f"[{self.layer}] Policy file not found, using defaults", "WARN")

        # ------------------------------------------------------------------
        # Initialize LLM policy guard
        # ------------------------------------------------------------------
        llm_cfg = self.policies.get(
            "llm_policy_model",
            {"provider": "ollama", "model": "llama-guard-3"},
        )

        try:
            llm = LLMFactory.from_config(llm_cfg)
            if callable(llm) and not hasattr(llm, "generate"):
                class Wrapper:
                    def __init__(self, fn): self.fn = fn
                    def generate(self, prompt: str): return self.fn(prompt)
                self.guard_llm = Wrapper(llm)
            else:
                self.guard_llm = llm
        except Exception as e:
            self.log(f"[{self.layer}] LLMFactory failed ({e}) - using stub guard_llm", "WARN")

            class StubLLM:
                def generate(self, prompt: str): return "safe"

            self.guard_llm = StubLLM()

    # ----------------------------------------------------------------------
    # Main entrypoint
    # ----------------------------------------------------------------------
    def execute(self, request: dict) -> dict:
        """Run governance pre-checks and return sanitized request or block."""
        if not isinstance(request, dict):
            self.log(f"[{self.layer}] Non-dict request ({type(request)}), coercing", "WARN")
            request = {"input": str(request)}

        if not self.pre_check(request):
            self.log(f"[{self.layer}] Pre-check failed; blocking request", "ERROR")
            return {"answer": "Request blocked by governance policy"}

        return request

    # ----------------------------------------------------------------------
    # Pre-check (incoming request validation)
    # ----------------------------------------------------------------------
    def pre_check(self, request: dict) -> bool:
        text = str(request)

        # 1. Keyword blocking
        for kw in self.policies.get("blocked_keywords", []):
            if kw.lower() in text.lower():
                self.log(f"[{self.layer}] Blocked keyword '{kw}' found", "WARN")
                return False

        # 2. Intent validation
        if "intent" in request and self.policies.get("allowed_domains"):
            allowed = self.policies["allowed_domains"]
            if request["intent"] not in allowed:
                self.log(f"[{self.layer}] Intent '{request['intent']}' not allowed", "WARN")
                return False

        # 3. LLM reasoning guard
        prompt = f"Is this request safe under enterprise policy? Answer 'safe' or 'unsafe': {text}"
        result = str(self.guard_llm.generate(prompt))
        if result.strip().lower().startswith("unsafe"):
            self.log(f"[{self.layer}] LLM pre-check flagged as unsafe -> {result}", "ERROR")
            return False

        return True

    # ----------------------------------------------------------------------
    # Post-check (outgoing response sanitization)
    # ----------------------------------------------------------------------
    def post_check(self, response: dict) -> dict:
        """Run redaction and LLM-based validation on responses."""
        text = str(response)

        # 1. Apply regex redaction rules
        for rule in self.policies.get("response_redaction", []):
            try:
                text = re.sub(rule["pattern"], rule["replace"], text)
            except re.error as e:
                self.log(f"[{self.layer}] Invalid redaction pattern: {e}", "ERROR")

        # 2. LLM post-validation
        prompt = f"Check if this system response is safe: {text}"
        result = str(self.guard_llm.generate(prompt))
        if "unsafe" in result.lower():
            self.log(f"[{self.layer}] LLM post-check flagged unsafe output", "ERROR")
            return {"answer": "Response withheld by governance policy"}

        return {"answer": text}