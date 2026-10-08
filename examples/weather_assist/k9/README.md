# Weather Assist (K9-AIF integrated)

`WeatherAssistOrchestrator` (`weather_orchestrator.py`, a `BaseOrchestrator`) wraps the CrewAI
crew through `K9CrewAIAdapter`, with `ShieldGovernance` built from `../config/config.yaml`, so
the input is screened before CrewAI's `kickoff()` runs.

```bash
python -m examples.weather_assist.k9.main "Atlanta"     # CLI
python -m examples.weather_assist.k9.webui              # web UI on http://127.0.0.1:8000
```
