from __future__ import annotations

import os
from typing import Any, Dict, Optional

from dotenv import load_dotenv

from k9_aif_abb.k9_core.orchestration.base_orchestrator import BaseOrchestrator
from k9_aif_abb.k9_adapters.crewai import K9CrewAIAdapter
from k9_aif_abb.k9_utils.config_loader import load_yaml
from examples.weather_assist.crewai.crew import build_weather_assist_crew
from examples.weather_assist.k9.governance import make_governance

_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CONFIG_PATH = os.path.join(_APP_DIR, "config", "config.yaml")
_ENV_PATH = os.path.join(_APP_DIR, ".env")

# k9_utils.config_loader's own module-level load_dotenv() call resolves
# whichever .env find_dotenv() walks up to first from the CURRENT WORKING
# DIRECTORY -- which, when this app is launched via run.sh (cd's to the
# framework root first), is the framework's own .env, not this app's,
# silently shadowing it. override=True here makes this app's own .env win
# for its own keys regardless of what already loaded, or what cwd the
# process was started from.
if os.path.exists(_ENV_PATH):
    load_dotenv(_ENV_PATH, override=True)


class WeatherAssistOrchestrator(BaseOrchestrator):
    """
    K9-AIF application orchestrator for the Weather Assist demo.

    Loads config.yaml (governance.provider, security.shield) and constructs
    the matching governance instance, then passes it through to
    K9CrewAIAdapter so the CrewAI-wrapped agents are genuinely governed —
    not just structurally eligible to be. With the default config.yaml
    shipped here (governance.provider: shield), this is real enforcement:
    ShieldGovernance raises PermissionError on a BLOCK from either
    configured check.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        cfg = config if config is not None else load_yaml(_CONFIG_PATH)
        super().__init__(config=cfg, governance=make_governance(cfg))

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

        crew = build_weather_assist_crew(city, config=self.config)
        print(f"CrewAI Object      : {crew.__class__.__name__}")

        if hasattr(crew, "agents"):
            print("CrewAI Agents      :")
            for idx, agent in enumerate(crew.agents, start=1):
                role = getattr(agent, "role", f"Agent-{idx}")
                print(f"  {idx}. {role}")

        adapter = K9CrewAIAdapter(crew=crew, config=self.config, governance=self.governance)
        print(f"K9 Adapter         : {adapter.__class__.__name__}")

        orchestrator_adapter = getattr(adapter, "orchestrator_adapter", None)
        if orchestrator_adapter is not None:
            print(f"CrewAI Bridge      : {orchestrator_adapter.__class__.__name__}")
        print(f"Governance         : {self.governance.__class__.__name__}")

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