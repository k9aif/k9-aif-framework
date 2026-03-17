# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

from __future__ import annotations

from typing import Any, Dict, Optional
import logging

from .acme_base_agent import AcmeBaseAgent

log = logging.getLogger(__name__)


class QualityAgent(AcmeBaseAgent):
    """
    Thin runtime quality/review agent for ACME Support Center.
    Improves responses for clarity, tone, and professionalism.
    """

    def __init__(
        self,
        name: str = None,
        config: Optional[Dict[str, Any]] = None,
        tools: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(config)

        self.name = name or self.__class__.__name__
        self.config = config or {}
        self.tools = tools or {}

        self.description = self.config.get("description", "")
        self.pattern = self.config.get("pattern", "review")
        self.model = self.config.get("model", "general")
        self.role = self.config.get("role", "")
        self.goal = self.config.get("goal", "")
        self.instructions = self.config.get("instructions", [])
        self.agent_config = self.config.get("config", {}) or {}

        log.info(
            "Initialized %s | pattern=%s | model=%s",
            self.name,
            self.pattern,
            self.model,
        )

    def run(
        self,
        request: str,
        triage_result: Optional[Dict[str, Any]] = None,
        knowledge_result: Optional[Dict[str, Any]] = None,
        resolution_result: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        context = context or {}
        triage_result = triage_result or {}
        knowledge_result = knowledge_result or {}
        resolution_result = resolution_result or {}
        request = (request or "").strip()

        if not request:
            return {
                "agent": self.name,
                "status": "error",
                "message": "Empty request received.",
            }

        draft = (
            resolution_result.get("resolution")
            or context.get("draft_response")
            or context.get("resolution")
            or request
        )

        reviewed = self._review_response(
            request=request,
            draft=draft,
            triage_result=triage_result,
            knowledge_result=knowledge_result,
            resolution_result=resolution_result,
            context=context,
        )

        return {
            "agent": self.name,
            "pattern": self.pattern,
            "role": self.role,
            "goal": self.goal,
            "request": request,
            "triage_result": triage_result,
            "knowledge_result": knowledge_result,
            "resolution_result": resolution_result,
            "draft_response": draft,
            "final_response": reviewed,
            "status": "success",
        }

    def _review_response(
        self,
        request: str,
        draft: str,
        triage_result: Dict[str, Any],
        knowledge_result: Dict[str, Any],
        resolution_result: Dict[str, Any],
        context: Dict[str, Any],
    ) -> str:
        prompt = f"""
You are an ACME support quality agent.

Review and improve the draft response.

Requirements:
- clear
- concise
- polite
- professional
- customer-friendly
- do not invent policies or facts

Customer request:
{request}

Triage result:
{triage_result}

Knowledge result:
{knowledge_result}

Resolution result:
{resolution_result}

Draft response:
{draft}

Additional context:
{context}
""".strip()

        try:
            result = self.run_inference(prompt, task_type="quality_review")
            return (result.get("text") or "").strip() or self._fallback_review(draft)
        except Exception as exc:
            log.warning("Quality inference failed in %s: %s", self.name, exc)
            return self._fallback_review(draft)

    def _fallback_review(self, draft: str) -> str:
        return f"Here is the reviewed customer response:\n\n{draft}"