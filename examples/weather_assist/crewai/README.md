# Weather Assist (pure CrewAI)

Standalone CrewAI weather assistant using Open-Meteo, with the model served by Ollama. Compare it
with `../k9/`, where the same crew runs inside a governed K9-AIF orchestrator.

## Setup and run (from the repository root)

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r examples/weather_assist/requirements.txt
cp examples/weather_assist/env-example .env      # OLLAMA_BASE_URL, OLLAMA_MODEL
python -m examples.weather_assist.crewai.main "Atlanta"
```
