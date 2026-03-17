# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

from __future__ import annotations

from typing import Any, Dict, Optional
import logging

from .acme_base_agent import AcmeBaseAgent

log = logging.getLogger(__name__)


class KnowledgeAgent(AcmeBaseAgent):
    """
    Thin runtime knowledge agent for ACME Support Center.
    RAG-style: tool retrieval + LLM answer synthesis.
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
        self.pattern = self.config.get("pattern", "rag")
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
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        context = context or {}
        triage_result = triage_result or {}
        request = (request or "").strip()

        if not request:
            return {
                "agent": self.name,
                "status": "error",
                "message": "Empty request received.",
            }

        kb_result = self.call_tool(
            "knowledge_retriever",
            {
                "request": request,
                "triage_result": triage_result,
                "context": context,
            },
        )

        answer = self._generate_answer(
            request=request,
            triage_result=triage_result,
            context=context,
            kb_result=kb_result,
        )

        return {
            "agent": self.name,
            "pattern": self.pattern,
            "role": self.role,
            "goal": self.goal,
            "request": request,
            "triage_result": triage_result,
            "knowledge_result": kb_result,
            "response": answer,
            "status": "success",
        }

    def _generate_answer(
        self,
        request: str,
        triage_result: Dict[str, Any],
        context: Dict[str, Any],
        kb_result: Any,
    ) -> str:
        prompt = f"""
You are an ACME support knowledge agent.

Answer clearly and accurately.
Use triage results and knowledge results if available.
If knowledge is insufficient, say so briefly and provide the best guidance.

Customer request:
{request}

Triage result:
{triage_result}

Knowledge results:
{kb_result}

Context:
{context}
""".strip()

        try:
            result = self.run_inference(prompt, task_type="knowledge")
            return (result.get("text") or "").strip() or self._fallback_answer(kb_result)
        except Exception as exc:
            log.warning("Knowledge inference failed in %s: %s", self.name, exc)
            return self._fallback_answer(kb_result)

    def _fallback_answer(self, kb_result: Any) -> str:
        if kb_result:
            return f"Based on the knowledge lookup, here is the relevant information: {kb_result}"
        return "I could not find a strong knowledge match, but your request has been captured for further handling."