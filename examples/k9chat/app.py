# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

import asyncio
import json
import os
import sys
import time
import uuid

# app.py is uvicorn's actual import target (examples.k9chat.app:app) -- the
# one file in k9chat that most needs to be self-sufficient regardless of
# which Python/uvicorn launches it. Relying on cwd already being on
# sys.path (true for a plain `python`/`uvicorn` invocation from the repo
# root) breaks the moment a *different* environment's uvicorn is on PATH
# (e.g. a global/Homebrew install with its own old pip-installed k9-aif)
# or --reload's spawned subprocess doesn't inherit it -- confirmed live,
# 2026-09-20: `ModuleNotFoundError: No module named 'examples.k9chat'`
# from exactly that combination. Same pattern chat.py/chat_agent.py/
# seed_knowledge_base.py already use; this was the one file missing it.
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware
from examples.k9chat.chat import (
    send_message,
    send_message_stream,
    is_streaming_enabled,
    toggle_streaming,
    is_evaluation_enabled,
    toggle_evaluation,
    evaluate_response,
    get_chat_runtime_info,
    get_health_status,
    run_chat_startup_check,
    clear_session,
    truncate_session,
    list_models_for,
    get_selectable_models,
    apply_settings,
    create_project,
    list_projects,
    get_project,
    update_project,
    delete_project,
    add_project_file,
    remove_project_file,
    get_last_assistant_reply,
    is_correction_learning_enabled,
    toggle_correction_learning,
    learn_from_correction,
)
from examples.k9chat.project_manager import ProjectNotFoundError
from examples.k9chat.auth import (
    LoginRequiredMiddleware,
    current_owner_id,
    get_session_secret,
    sanitize_username,
)
from examples.k9chat.queue_control import QueueSlot
from examples.k9chat import queue_control
from examples.k9chat import gpu_telemetry

BASE_DIR = os.path.dirname(__file__)

app = FastAPI(title="K9Chat UI")

# Always active now (see auth.py's module docstring for why the old
# opt-in password gate was dropped) -- every visitor passes through the
# name-entry step once.
#
# Order matters: Starlette's add_middleware() prepends, so the middleware
# added LAST ends up OUTERMOST (runs first on each request). Add
# LoginRequiredMiddleware first and SessionMiddleware second so
# SessionMiddleware actually wraps it and request.session exists by the
# time LoginRequiredMiddleware.dispatch() reads it -- reversing this order
# throws "SessionMiddleware must be installed" on every single request.
app.add_middleware(LoginRequiredMiddleware)
app.add_middleware(SessionMiddleware, secret_key=get_session_secret())


@app.on_event("startup")
async def startup_event():
    run_chat_startup_check()

app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))


class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"
    project_id: str | None = None
    # Two independent 0-4 dials, purely style/register for this local demo
    # tool -- see chat_agent.py's UNHINGED_INSTRUCTIONS/PROFANITY_INSTRUCTIONS.
    # Never sent to the model as anything but a style instruction; doesn't
    # change what's retrieved or what governance/guardrails run.
    unhinged_level: int = 0
    profanity_level: int = 0
    length_level: int = 1


class ProjectRequest(BaseModel):
    name: str
    instructions: str = ""


class ProjectUpdateRequest(BaseModel):
    name: str | None = None
    instructions: str | None = None


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {
        "request": request,
        "display_name": os.environ.get("OLLAMA_DISPLAY_NAME", ""),
    })


@app.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request):
    form = await request.form()
    # No password, no rejection path -- see auth.py's module docstring for
    # why. sanitize_username() never rejects either; a blank/blocked name
    # just becomes a generated codename.
    username = sanitize_username(form.get("username") or "")
    request.session["logged_in"] = True
    request.session["visitor_id"] = str(uuid.uuid4())
    request.session["username"] = username
    return RedirectResponse(url="/", status_code=303)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login")


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
            "display_name": runtime["display_name"],
            "selectable_models": get_selectable_models(),
        },
    )


@app.get("/chat/queue-status")
def chat_queue_status():
    """Polled by the frontend's waitlist widget -- see queue_control.py."""
    return JSONResponse(queue_control.status())


@app.get("/telemetry")
def telemetry():
    """Polled by the right-side telemetry panel -- real nvidia-smi/os-module
    data proxied from gpu_telemetry.py, cached briefly there. Same data
    queue_control.py's thermal guard actually enforces against, not a
    separate/fake readout."""
    data = gpu_telemetry.get_telemetry()
    data["temp_limit_c"] = gpu_telemetry.temp_limit_c()
    return JSONResponse(data)


@app.post("/chat")
def chat(payload: ChatRequest):
    message = payload.message.strip()
    if not message:
        return JSONResponse({"reply": ""})

    prior_reply = get_last_assistant_reply(payload.session_id)

    start = time.monotonic()
    with QueueSlot():
        reply = send_message(
            message, session_id=payload.session_id, project_id=payload.project_id,
            unhinged_level=payload.unhinged_level, profanity_level=payload.profanity_level,
            length_level=payload.length_level,
        )
    elapsed_ms = round((time.monotonic() - start) * 1000)
    runtime = get_chat_runtime_info()
    response = {
        "reply": reply,
        "elapsed_ms": elapsed_ms,
        "model": runtime["model"],
        "provider": runtime["provider"],
        "base_url": runtime["base_url"],
    }
    eval_result = evaluate_response(message, reply)
    if eval_result:
        response["evaluation"] = eval_result
    learned = learn_from_correction(prior_reply, message, session_id=payload.session_id)
    if learned:
        response["learned_correction"] = learned
    return JSONResponse(response)


@app.post("/chat/stream")
async def chat_stream(payload: ChatRequest):
    """SSE endpoint — used when chat.stream: true in config.yaml."""
    message = payload.message.strip()
    session_id = payload.session_id
    project_id = payload.project_id
    unhinged_level = payload.unhinged_level
    profanity_level = payload.profanity_level
    length_level = payload.length_level

    async def event_generator():
        if not message:
            yield f"data: {json.dumps({'done': True})}\n\n"
            return

        prior_reply = get_last_assistant_reply(session_id)

        slot = QueueSlot()
        async with slot:
            if slot.position > 0:
                # Reported once, right when this request actually had to
                # wait -- a real number (how many were ahead), not a guess.
                yield f"data: {json.dumps({'queued': True, 'position': slot.position})}\n\n"

            start = time.monotonic()
            full_text = ""
            async for chunk in send_message_stream(
                message, session_id=session_id, project_id=project_id,
                unhinged_level=unhinged_level, profanity_level=profanity_level,
                length_level=length_level,
            ):
                full_text += chunk
                yield f"data: {json.dumps({'chunk': chunk})}\n\n"
        elapsed_ms = round((time.monotonic() - start) * 1000)
        runtime = get_chat_runtime_info()
        done_payload = {
            "done": True,
            "elapsed_ms": elapsed_ms,
            "model": runtime["model"],
            "provider": runtime["provider"],
            "base_url": runtime["base_url"],
        }
        eval_result = await asyncio.get_event_loop().run_in_executor(
            None, evaluate_response, message, full_text
        )
        if eval_result:
            done_payload["evaluation"] = eval_result
        learned = await asyncio.get_event_loop().run_in_executor(
            None, learn_from_correction, prior_reply, message, session_id
        )
        if learned:
            done_payload["learned_correction"] = learned
        yield f"data: {json.dumps(done_payload)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/chat/config")
def chat_config():
    return JSONResponse({"stream": is_streaming_enabled()})


@app.post("/chat/stream/toggle")
def stream_toggle():
    enabled = toggle_streaming()
    return JSONResponse({"stream": enabled})


@app.get("/chat/evaluation")
def evaluation_status():
    return JSONResponse({"evaluation_enabled": is_evaluation_enabled()})


@app.post("/chat/evaluation/toggle")
def evaluation_toggle():
    enabled = toggle_evaluation()
    return JSONResponse({"evaluation_enabled": enabled})


@app.get("/chat/learning")
def learning_status():
    return JSONResponse({"learning_enabled": is_correction_learning_enabled()})


@app.post("/chat/learning/toggle")
def learning_toggle():
    enabled = toggle_correction_learning()
    return JSONResponse({"learning_enabled": enabled})


@app.delete("/chat/session/{session_id}")
def delete_session(session_id: str):
    clear_session(session_id)
    return JSONResponse({"cleared": session_id})


class TruncateRequest(BaseModel):
    keep_count: int


@app.post("/chat/session/{session_id}/truncate")
def truncate_session_route(session_id: str, payload: TruncateRequest):
    """Server-side half of edit-and-resubmit -- drops the model's own
    memory of every turn from keep_count onward, not just what's visible
    in the browser. See ChatAgent.truncate_history()."""
    truncate_session(session_id, payload.keep_count)
    return JSONResponse({"session_id": session_id, "keep_count": payload.keep_count})


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
    """Model switching is a heavier, different cost than a normal chat
    message -- it loads a fresh multi-GB model into VRAM (apply_settings()'s
    warm-up call is a real generation). Two people casually flipping
    between models, zero malice, would still mean real repeated GPU
    reload cost -- guarded two ways: a cooldown between switches (global,
    since the cost is per-switch not per-visitor) and the same
    concurrency/thermal QueueSlot every chat message already goes
    through."""
    allowed, retry_after = queue_control.check_switch_cooldown()
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Model was switched too recently -- try again in {retry_after}s.",
        )
    with QueueSlot():
        status = apply_settings(payload.provider, payload.base_url, payload.model, payload.api_key)
    return JSONResponse(status)


def _require_owned_project(project_id: str, owner_id: str | None) -> dict:
    """404s (not a silent empty result) if the project doesn't exist OR
    belongs to a different visitor -- same response either way so a
    guessed project_id can't be used to probe which IDs are real."""
    project = get_project(project_id, owner_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@app.post("/projects")
def projects_create(payload: ProjectRequest, request: Request):
    project = create_project(payload.name, instructions=payload.instructions, owner_id=current_owner_id(request))
    return JSONResponse(project)


@app.get("/projects")
def projects_list(request: Request):
    return JSONResponse({"projects": list_projects(current_owner_id(request))})


@app.get("/projects/{project_id}")
def projects_get(project_id: str, request: Request):
    return JSONResponse(_require_owned_project(project_id, current_owner_id(request)))


@app.put("/projects/{project_id}")
def projects_update(project_id: str, payload: ProjectUpdateRequest, request: Request):
    _require_owned_project(project_id, current_owner_id(request))
    try:
        return JSONResponse(update_project(project_id, name=payload.name, instructions=payload.instructions))
    except ProjectNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")


@app.delete("/projects/{project_id}")
def projects_delete(project_id: str, request: Request):
    _require_owned_project(project_id, current_owner_id(request))
    try:
        return JSONResponse(delete_project(project_id))
    except ProjectNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")


@app.post("/projects/{project_id}/files")
async def projects_add_file(project_id: str, request: Request, file: UploadFile = File(...)):
    _require_owned_project(project_id, current_owner_id(request))
    raw = await file.read()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="Only UTF-8 text files are supported")
    try:
        result = add_project_file(project_id, file.filename, text)
    except ProjectNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    return JSONResponse(result)


@app.delete("/projects/{project_id}/files/{file_id}")
def projects_remove_file(project_id: str, file_id: str, request: Request):
    _require_owned_project(project_id, current_owner_id(request))
    try:
        return JSONResponse(remove_project_file(project_id, file_id))
    except ProjectNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")