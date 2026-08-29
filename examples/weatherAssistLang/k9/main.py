from __future__ import annotations

from examples.weatherAssistLang.k9.weather_orchestrator import WeatherAssistLangOrchestrator


def main():
    print("\n=== K9-AIF Weather Assist Lang (LangGraph Integration) ===\n")

    orchestrator = WeatherAssistLangOrchestrator()

    payload = {
        "city": "Atlanta",
        "intent": "weather_assist",
        "metadata": {
            "user": "demo_user",
            "source": "k9_main"
        }
    }

    result = orchestrator.execute_flow(payload)


if __name__ == "__main__":
    main()
