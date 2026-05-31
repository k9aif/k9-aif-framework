# SPDX-License-Identifier: Apache-2.0
# K9-AIF n8n Hello World — FastAPI entry point

from __future__ import annotations

import os
import yaml
import logging
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional

from k9_aif_abb.k9_agents.registry.agent_registry import AgentRegistry
from k9_aif_abb.k9_squad.squad_loader import SquadLoader

from agents.src.hello_world_agent import HelloWorldAgent
from orchestrators.hello_world_orchestrator import HelloWorldOrchestrator

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "../config/config.yaml")
_SQUADS_YAML = os.path.join(os.path.dirname(__file__), "../config/squads.yaml")

with open(_CONFIG_PATH) as f:
    _config = yaml.safe_load(f)

# Bootstrap — register agents and load squad here, not in the orchestrator
_registry = AgentRegistry()
_registry.register("HelloWorldAgent", lambda: HelloWorldAgent(config=_config))
_squad = SquadLoader(_registry).load_one(_SQUADS_YAML, "HelloWorldSquad")
_orchestrator = HelloWorldOrchestrator(squad=_squad, config=_config)

app = FastAPI(
    title="K9-AIF Hello World",
    description="Minimal K9-AIF example — invoke via n8n or any HTTP client.",
    version="1.0.0",
)


class HelloRequest(BaseModel):
    caller: Optional[str] = "n8n"
    message: Optional[str] = ""


@app.get("/")
def root():
    return {"status": "ok", "app": "K9-AIF n8n Hello World", "endpoint": "POST /run"}


@app.post("/run")
def run(payload: HelloRequest):
    try:
        event = payload.model_dump()
        log.info("Received event: %s", event)
        result = _orchestrator.run(event)
        return JSONResponse(content={"status": "success", "result": result})
    except Exception as exc:
        log.error("Error: %s", exc)
        return JSONResponse(status_code=500, content={"status": "error", "detail": str(exc)})


@app.get("/health")
def health():
    return {"status": "healthy", "pipeline": "Orchestrator → Squad → Agent"}
