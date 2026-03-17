from __future__ import annotations

from typing import Any, Dict, Optional
import logging


log = logging.getLogger(__name__)


class SupportOrchestrator:
    def __init__(
        self,
        name: str = "support_orchestrator",
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.name = name
        self.config = config or {}
        log.info("Initialized orchestrator: %s", self.name)

    def start(
        self,
        squads: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        context = context or {}

        log.info("Starting orchestrator runtime: %s", self.name)
        print("ACME Support Center runtime started.")
        print("Type 'exit' to stop.\n")

        while True:
            request = input("Enter your support request: ").strip()

            if request.lower() in {"exit", "quit"}:
                print("\nShutting down orchestrator.\n")
                break

            result = self.run(
                request=request,
                squads=squads,
                context=context,
            )

            triage = result.get("triage_result", {}).get("triage", {})
            final_response = (
                result.get("final_result", {}).get("final_response")
                or result.get("quality_result", {}).get("final_response")
                or result.get("resolution_result", {}).get("resolution")
                or result.get("knowledge_result", {}).get("response")
                or result.get("triage_result", {}).get("summary")
                or "No response available."
            )

            print("\n----------------------------------")
            print(f"Intent   : {triage.get('intent', 'n/a')}")
            print(f"Category : {triage.get('category', 'n/a')}")
            print(f"Priority : {triage.get('priority', 'n/a')}")
            print("\nResponse:")
            print(final_response)
            print("----------------------------------\n")

    def run(
        self,
        request: str,
        squads: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        context = context or {}
        request = (request or "").strip()

        if not request:
            return {
                "orchestrator": self.name,
                "status": "error",
                "message": "Empty request received.",
            }

        support_squad = squads.get("support_squad")
        if support_squad is None:
            return {
                "orchestrator": self.name,
                "status": "error",
                "message": "support_squad not found.",
            }

        agents = support_squad.agents or []
        agent_map = {agent.__class__.__name__: agent for agent in agents}

        triage_agent = agent_map.get("TriageAgent")
        knowledge_agent = agent_map.get("KnowledgeAgent")
        resolution_agent = agent_map.get("ResolutionAgent")
        quality_agent = agent_map.get("QualityAgent")

        if triage_agent is None:
            return {
                "orchestrator": self.name,
                "status": "error",
                "message": "triage_agent is missing from support_squad.",
            }

        triage_result = triage_agent.run(request=request, context=context)

        triage = triage_result.get("triage", {}) or {}
        next_action = triage.get("next_action", "knowledge_agent")
        intent = triage.get("intent", "general_support")

        knowledge_result: Dict[str, Any] = {}
        resolution_result: Dict[str, Any] = {}
        quality_result: Dict[str, Any] = {}

        if next_action == "knowledge_agent" and knowledge_agent is not None:
            knowledge_result = knowledge_agent.run(
                request=request,
                triage_result=triage_result,
                context=context,
            )

        elif next_action == "resolution_agent" and resolution_agent is not None:
            resolution_result = resolution_agent.run(
                request=request,
                triage_result=triage_result,
                knowledge_result=knowledge_result,
                context=context,
            )

        elif next_action == "quality_agent":
            pass

        else:
            if knowledge_agent is not None:
                knowledge_result = knowledge_agent.run(
                    request=request,
                    triage_result=triage_result,
                    context=context,
                )

            if resolution_agent is not None:
                resolution_result = resolution_agent.run(
                    request=request,
                    triage_result=triage_result,
                    knowledge_result=knowledge_result,
                    context=context,
                )

        if (
            not resolution_result
            and resolution_agent is not None
            and intent in {"account_help", "troubleshooting"}
        ):
            resolution_result = resolution_agent.run(
                request=request,
                triage_result=triage_result,
                knowledge_result=knowledge_result,
                context=context,
            )

        if quality_agent is not None:
            quality_result = quality_agent.run(
                request=request,
                triage_result=triage_result,
                knowledge_result=knowledge_result,
                resolution_result=resolution_result,
                context=context,
            )
            final_result = quality_result
        else:
            final_result = resolution_result or knowledge_result or triage_result

        return {
            "orchestrator": self.name,
            "request": request,
            "squad_used": "support_squad",
            "triage_result": triage_result,
            "knowledge_result": knowledge_result,
            "resolution_result": resolution_result,
            "quality_result": quality_result,
            "final_result": final_result,
            "status": "success",
        }