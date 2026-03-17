from __future__ import annotations

from typing import Any, Dict, Optional
import logging
import json

from .acme_base_agent import AcmeBaseAgent

log = logging.getLogger(__name__)


class TriageAgent(AcmeBaseAgent):
    """
    Intelligent triage agent with:
    - LLM classification (primary)
    - Rule-based fallback (deterministic safety)
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
        self.routing = self.config.get("routing", {})
        self.agent_config = self.config.get("config", {}) or {}

        log.info(
            "Initialized %s | pattern=%s | model=%s",
            self.name,
            self.pattern,
            self.model,
        )

    # =========================
    # MAIN ENTRY
    # =========================
    def run(
        self,
        request: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:

        context = context or {}
        request = (request or "").strip()

        if not request:
            return {
                "agent": self.name,
                "status": "error",
                "message": "Empty request received.",
            }

        triage = self._classify_request(request)
        next_agent = self.routing.get(triage["intent"], "knowledge_agent")

        result = {
            "agent": self.name,
            "pattern": self.pattern,
            "role": self.role,
            "goal": self.goal,
            "request": request,
            "triage": {
                "intent": triage["intent"],
                "category": triage["category"],
                "priority": triage["priority"],
                "next_action": next_agent,
            },
            "summary": (
                f"Request classified as '{triage['intent']}' "
                f"with priority '{triage['priority']}'."
            ),
            "status": "success",
        }

        if "ticket_tool" in self.tools:
            tool_result = self.call_tool(
                "ticket_tool",
                {"request": request, "context": context},
            )
            result["tool_result"] = {"ticket_tool": tool_result}

        return result

    # =========================
    # CLASSIFICATION
    # =========================
    def _classify_request(self, request: str) -> Dict[str, str]:
        if not request or len(request.strip()) < 3:
            return {
                "intent": "general_support",
                "category": "general",
                "priority": "low",
            }

        llm_result = self._classify_with_llm(request)
        if llm_result:
            return llm_result

        return self._classify_with_rules(request)

    def _classify_with_llm(self, request: str) -> Optional[Dict[str, str]]:
        try:
            prompt = f"""
                Classify this customer support request.

                Return ONLY valid JSON.
                Do not add markdown.
                Do not add explanation.

                Schema:
                {{
                    "intent": "account_help | troubleshooting | knowledge_lookup | escalation | general_support",
                    "category": "string",
                    "priority": "low | medium | high"
                }}

                Request:
                {request}
            exir
            """.strip()

            result = self.run_inference(prompt, task_type="classification")
            text = (result.get("text") or "").strip()

            log.info("Triage raw model output: %r", text)

            if not text:
                return None

            if text.startswith("```"):
                text = text.strip("`")
                text = text.replace("json", "", 1).strip()

            parsed = json.loads(text)

            if all(k in parsed for k in ("intent", "category", "priority")):
                return {
                    "intent": parsed["intent"],
                    "category": parsed["category"],
                    "priority": parsed["priority"],
                }

        except Exception as exc:
            log.warning("LLM triage failed in %s: %s", self.name, exc)

        return None

    # =========================
    # RULE FALLBACK (CRITICAL)
    # =========================
    def _classify_with_rules(self, request: str) -> Dict[str, str]:
        text = request.lower()

        if any(x in text for x in ["login", "password", "account locked", "sign in"]):
            return {
                "intent": "account_help",
                "category": "account",
                "priority": "high" if any(y in text for y in ["urgent", "asap", "immediately"]) else "medium",
            }

        if any(x in text for x in ["error", "issue", "failed", "not working", "broken", "problem"]):
            return {
                "intent": "troubleshooting",
                "category": "technical_support",
                "priority": "high" if any(y in text for y in ["urgent", "critical", "outage"]) else "medium",
            }

        if any(x in text for x in ["policy", "faq", "how do i", "what is", "where can i"]):
            return {
                "intent": "knowledge_lookup",
                "category": "knowledge",
                "priority": "low",
            }

        if any(x in text for x in ["refund", "complaint", "manager", "escalate", "cancel"]):
            return {
                "intent": "escalation",
                "category": "case_management",
                "priority": "high",
            }

        return {
            "intent": "general_support",
            "category": "general",
            "priority": "low",
        }