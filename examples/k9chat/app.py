# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

import json
import os
import time
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from examples.k9chat.chat import (
    send_message,
    send_message_stream,
    is_streaming_enabled,
    get_chat_runtime_info,
    get_health_status,
    run_chat_startup_check,
    clear_session,
    list_models_for,
    apply_settings,
)

BASE_DIR = os.path.dirname(__file__)

app = FastAPI(title="K9Chat UI")


@app.on_event("startup")
async def startup_event():
    run_chat_startup_check()

app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))


class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"


class SettingsRequest(BaseModel):
    provider: str = "ollama"
    base_url: str
    model: str
    api_key: str = ""


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    runtime = get_chat_runtime_info()

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "provider": runtime["provider"],
            "base_url": runtime["base_url"],
            "model": runtime["model"],
        },
    )


@app.post("/chat")
def chat(payload: ChatRequest):
    message = payload.message.strip()
    if not message:
        return JSONResponse({"reply": ""})

    start = time.monotonic()
    reply = send_message(message, session_id=payload.session_id)
    elapsed_ms = round((time.monotonic() - start) * 1000)
    runtime = get_chat_runtime_info()
    return JSONResponse({
        "reply": reply,
        "elapsed_ms": elapsed_ms,
        "model": runtime["model"],
        "provider": runtime["provider"],
        "base_url": runtime["base_url"],
    })


@app.post("/chat/stream")
async def chat_stream(payload: ChatRequest):
    """SSE endpoint — used when chat.stream: true in config.yaml."""
    message = payload.message.strip()
    session_id = payload.session_id

    async def event_generator():
        if not message:
            yield f"data: {json.dumps({'done': True})}\n\n"
            return
        start = time.monotonic()
        async for chunk in send_message_stream(message, session_id=session_id):
            yield f"data: {json.dumps({'chunk': chunk})}\n\n"
        elapsed_ms = round((time.monotonic() - start) * 1000)
        runtime = get_chat_runtime_info()
        yield f"data: {json.dumps({'done': True, 'elapsed_ms': elapsed_ms, 'model': runtime['model'], 'provider': runtime['provider'], 'base_url': runtime['base_url']})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/chat/config")
def chat_config():
    return JSONResponse({"stream": is_streaming_enabled()})


@app.delete("/chat/session/{session_id}")
def delete_session(session_id: str):
    clear_session(session_id)
    return JSONResponse({"cleared": session_id})


@app.get("/health")
def health():
    status = get_health_status()
    return JSONResponse(status, status_code=200 if status["ok"] else 503)


@app.get("/chat/runtime")
def runtime():
    return JSONResponse(get_chat_runtime_info())


@app.get("/chat/models")
def models(provider: str = "ollama", base_url: str = "", api_key: str = ""):
    try:
        return JSONResponse({"models": list_models_for(provider, base_url, api_key)})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/chat/settings")
def settings(payload: SettingsRequest):
    status = apply_settings(payload.provider, payload.base_url, payload.model, payload.api_key)
    return JSONResponse(status)