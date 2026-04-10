from __future__ import annotations

from typing import Any, Dict

from k9_aif_abb.k9_core.orchestration.base_orchestrator import BaseOrchestrator
from k9_aif_abb.k9_adapters.crewai import K9CrewAIAdapter
from examples.weather_assist.crewai.crew import build_weather_assist_crew


class WeatherAssistOrchestrator(BaseOrchestrator):
    """
    K9-AIF application orchestrator for the Weather Assist demo.
    """

    def __init__(self) -> None:
        super().__init__()
        
    def execute_flow(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        city = (
            payload.get("city")
            or payload.get("message")
            or payload.get("input")
            or "Atlanta"
        )

        if isinstance(city, str):
            city = city.strip() or "Atlanta"
        else:
            city = "Atlanta"

        print("\n--- K9-AIF Runtime Trace ---")
        print(f"K9 Base Class      : {BaseOrchestrator.__name__}")
        print(f"K9 Orchestrator    : {self.__class__.__name__}")

        crew = build_weather_assist_crew(city)
        print(f"CrewAI Object      : {crew.__class__.__name__}")

        if hasattr(crew, "agents"):
            print("CrewAI Agents      :")
            for idx, agent in enumerate(crew.agents, start=1):
                role = getattr(agent, "role", f"Agent-{idx}")
                print(f"  {idx}. {role}")

        adapter = K9CrewAIAdapter(crew=crew)
        print(f"K9 Adapter         : {adapter.__class__.__name__}")

        orchestrator_adapter = getattr(adapter, "orchestrator_adapter", None)
        if orchestrator_adapter is not None:
            print(f"CrewAI Bridge      : {orchestrator_adapter.__class__.__name__}")

        print("----------------------------\n")

        adapter_payload = {
            "message": f"What is the weather in {city} today?",
            "intent": "weather_assist",
            "context": payload.get("context", {}),
            "metadata": {
                "source": "weather_assist_k9",
                **payload.get("metadata", {}),
            },
        }

        result = adapter.execute(adapter_payload)

        return {
            "status": "success",
            "orchestrator": "WeatherAssistOrchestrator",
            "intent": "weather_assist",
            "city": city,
            "result": result,
        }