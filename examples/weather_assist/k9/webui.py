from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from examples.weather_assist.k9.weather_orchestrator import WeatherAssistOrchestrator

app = FastAPI(title="K9-AIF Weather Assist (CrewAI Integration)")

_STATIC_DIR = os.path.join(os.path.dirname(__file__), "..", "webui")


class WeatherQuery(BaseModel):
    city: str


@app.get("/")
def index() -> FileResponse:
    return FileResponse(os.path.join(_STATIC_DIR, "index.html"))


@app.post("/api/weather")
def get_weather(query: WeatherQuery) -> JSONResponse:
    orchestrator = WeatherAssistOrchestrator()

    try:
        result = orchestrator.execute_flow({"city": query.city})
        return JSONResponse({"ok": True, "result": result})
    except PermissionError as exc:
        # A real governance BLOCK (ShieldGovernance), not a server error —
        # surfaced to the UI as a governance decision, not a 500.
        return JSONResponse({"ok": False, "blocked": True, "reason": str(exc)})


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
