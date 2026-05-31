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

from orchestrators.hello_world_orchestrator import HelloWorldOrchestrator

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "../config/config.yaml")

with open(_CONFIG_PATH) as f:
    _config = yaml.safe_load(f)

_orchestrator = HelloWorldOrchestrator(config=_config)

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
    return {"status": "healthy", "pipeline": "Router → Orchestrator → Squad → Agent"}
