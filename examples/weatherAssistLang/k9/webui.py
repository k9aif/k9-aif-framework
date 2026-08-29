from __future__ import annotations

import os

import requests
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from k9_aif_abb.k9_utils.config_loader import load_yaml
from examples.weatherAssistLang.k9.weather_orchestrator import (
    WeatherAssistLangOrchestrator,
    _CONFIG_PATH,
    _ENV_PATH,
)

app = FastAPI(title="K9-AIF Weather Assist Lang (LangGraph Integration)")

_STATIC_DIR = os.path.join(os.path.dirname(__file__), "..", "webui")
_DIAGRAMS_DIR = os.path.join(os.path.dirname(__file__), "..", "diagrams")
app.mount("/diagrams", StaticFiles(directory=_DIAGRAMS_DIR), name="diagrams")


class WeatherQuery(BaseModel):
    city: str


@app.get("/")
def index() -> FileResponse:
    return FileResponse(os.path.join(_STATIC_DIR, "index.html"))


@app.get("/api/health")
def health() -> JSONResponse:
    """
    Same pre-flight check as weather_assist's webui.py: is the configured
    Ollama backend actually reachable, and does it have the configured
    model pulled? Checked before the UI ever lets a request through to
    graph.invoke() -- a connection-refused or missing-model error is much
    more informative here, with the exact base_url and model this app
    actually resolved, than as a stack trace from inside
    langchain_ollama/ollama after the user clicks "Get Weather".
    """
    cfg = load_yaml(_CONFIG_PATH)
    ollama_cfg = cfg.get("ollama", {})
    base_url = ollama_cfg.get("base_url", "http://localhost:11434")
    model = ollama_cfg.get("model", "llama3.2:1b")

    try:
        resp = requests.get(f"{base_url}/api/tags", timeout=3)
        resp.raise_for_status()
        available = {m.get("name") for m in resp.json().get("models", [])}
        model_present = any(
            model == name or name.startswith(f"{model}") for name in available
        )
        if not model_present:
            return JSONResponse({
                "ok": False,
                "reason": (
                    f"Ollama is reachable at {base_url}, but model '{model}' "
                    f"is not pulled. Run: ollama pull {model}"
                ),
                "base_url": base_url,
                "model": model,
            })
        return JSONResponse({"ok": True, "base_url": base_url, "model": model})
    except requests.RequestException as exc:
        return JSONResponse({
            "ok": False,
            "reason": (
                f"Cannot reach Ollama at {base_url}: {exc}. "
                f"Check {_ENV_PATH} (OLLAMA_BASE_URL) and that Ollama is running."
            ),
            "base_url": base_url,
            "model": model,
        })


@app.post("/api/weather")
def get_weather(query: WeatherQuery) -> JSONResponse:
    orchestrator = WeatherAssistLangOrchestrator()

    try:
        result = orchestrator.execute_flow({"city": query.city})
        return JSONResponse({"ok": True, "result": result})
    except PermissionError as exc:
        # A real governance BLOCK (ShieldGovernance), not a server error --
        # surfaced to the UI as a governance decision, not a 500.
        return JSONResponse({"ok": False, "blocked": True, "reason": str(exc)})


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8001)


if __name__ == "__main__":
    main()
