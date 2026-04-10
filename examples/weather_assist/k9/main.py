from __future__ import annotations

from examples.weather_assist.k9.weather_orchestrator import WeatherAssistOrchestrator


def main():
    print("\n=== K9-AIF Weather Assist (CrewAI Integration) ===\n")

    orchestrator = WeatherAssistOrchestrator()

    # K9-style payload
    payload = {
        "message": "Atlanta",
        "intent": "weather_assist",
        "metadata": {
            "user": "demo_user",
            "source": "k9_main"
        }
    }

    result = orchestrator.execute_flow(payload)



if __name__ == "__main__":
    main()