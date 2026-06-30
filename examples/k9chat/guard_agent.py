# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework — k9chat guardrail check
#
# Screens user input through a dedicated guardian model (e.g. IBM Granite
# Guardian) before it reaches the main chat model. The guardian alias is
# routed via task_type="guardrails" + capabilities: [guardrails] in
# config.yaml's model_catalog — the same K9ModelRouter scoring pattern the
# EOC example's GuardAgent uses, just without the PII-tokenization layer
# (k9chat is a plain reference chat app, not a regulated-data pipeline).
#
# Purpose-built guardian models (Granite Guardian, Llama Guard, etc.) are
# already tuned via their Ollama Modelfile template to answer a content-risk
# question directly from the raw input — no wrapper prompt or system_prompt
# override is sent here, so the model's own baked-in instruction governs.

import os

from k9_aif_abb.k9_core.agent.base_agent import BaseAgent
from k9_aif_abb.k9_inference.models.inference_request import InferenceRequest
from k9_aif_abb.k9_utils.config_loader import load_yaml
from k9_aif_abb.k9_utils.llm_invoke import llm_invoke

BASE_DIR = os.path.dirname(__file__)


class GuardAgent(BaseAgent):
    """Pre-inference content-safety check for k9chat."""

    layer = "k9chat Guard SBB"

    def __init__(self, config=None):
        if config is None:
            config = load_yaml(os.path.join(BASE_DIR, "config.yaml"))
        super().__init__(config)

        guard_cfg = config.get("guardrails", {})
        self.enabled = bool(guard_cfg.get("enabled", False))
        self.fail_closed = bool(guard_cfg.get("fail_closed", False))
        self.refusal_message = guard_cfg.get(
            "refusal_message", "I can't help with that request."
        )

    def execute(self, payload: dict) -> dict:
        text = payload.get("text", "")

        if not self.enabled or not text:
            return {"agent": "GuardAgent", "passed": True, "checked": False}

        req = InferenceRequest(
            prompt=text,
            task_type="guardrails",
            metadata={"agent": "GuardAgent"},
        )

        try:
            resp = llm_invoke(self.config, req)
            verdict = (resp.output or "").strip().lower()
            flagged = verdict.startswith("yes")
            return {
                "agent": "GuardAgent",
                "passed": not flagged,
                "checked": True,
                "guardian_output": resp.output,
                "model": resp.model_alias,
            }
        except Exception as exc:
            self.logger.warning(f"[{self.layer}] Guardian check failed: {exc}")
            return {
                "agent": "GuardAgent",
                "passed": not self.fail_closed,
                "checked": False,
                "error": str(exc),
            }
