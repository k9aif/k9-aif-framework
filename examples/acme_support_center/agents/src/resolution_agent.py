from __future__ import annotations

from typing import Any, Dict, Optional
import logging

from .acme_base_agent import AcmeBaseAgent

log = logging.getLogger(__name__)


class ResolutionAgent(AcmeBaseAgent):
    """
    Thin runtime resolution agent for ACME Support Center.
    Generates actionable resolution plans.
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
        self.pattern = self.config.get("pattern", "react")
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
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:

        context = context or {}
        triage_result = triage_result or {}
        knowledge_result = knowledge_result or {}
        request = (request or "").strip()

        if not request:
            return {
                "agent": self.name,
                "status": "error",
                "message": "Empty request received.",
            }

        resolution = self._build_resolution(
            request=request,
            triage_result=triage_result,
            knowledge_result=knowledge_result,
            context=context,
        )

        action_result = None
        if "resolution_tool" in self.tools:
            action_result = self.call_tool(
                "resolution_tool",
                {
                    "request": request,
                    "triage_result": triage_result,
                    "knowledge_result": knowledge_result,
                    "context": context,
                    "resolution": resolution,
                },
            )

        return {
            "agent": self.name,
            "pattern": self.pattern,
            "role": self.role,
            "goal": self.goal,
            "request": request,
            "triage_result": triage_result,
            "knowledge_result": knowledge_result,
            "resolution": resolution,
            "tool_result": {"resolution_tool": action_result} if action_result else {},
            "status": "success",
        }

    def _build_resolution(
        self,
        request: str,
        triage_result: Dict[str, Any],
        knowledge_result: Dict[str, Any],
        context: Dict[str, Any],
    ) -> str:
        prompt = f"""
You are an ACME support resolution agent.

Create a practical resolution plan.
Be specific, concise, and action-oriented.

Customer request:
{request}

Triage result:
{triage_result}

Knowledge result:
{knowledge_result}

Available context:
{context}
""".strip()

        try:
            result = self.run_inference(prompt, task_type="resolution")
            return (result.get("text") or "").strip() or self._fallback_resolution()
        except Exception as exc:
            log.warning("Resolution inference failed in %s: %s", self.name, exc)
            return self._fallback_resolution()

    def _fallback_resolution(self) -> str:
        return (
            "1. Review the customer request.\n"
            "2. Confirm issue category and relevant details.\n"
            "3. Provide next best action or escalate if needed."
        )