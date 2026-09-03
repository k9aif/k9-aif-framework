# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

import asyncio
import json
import os
import time
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
    is_evaluation_enabled,
    toggle_evaluation,
    evaluate_response,
    get_chat_runtime_info,
    get_health_status,
    run_chat_startup_check,
    clear_session,
    list_models_for,
    apply_settings,
    create_project,
    list_projects,
    get_project,
    update_project,
    delete_project,
    add_project_file,
    remove_project_file,
)
from examples.k9chat.project_manager import ProjectNotFoundError
from examples.k9chat.auth import (
    LoginRequiredMiddleware,
    check_credentials,
    get_session_secret,
    is_login_enabled,
)

BASE_DIR = os.path.dirname(__file__)

app = FastAPI(title="K9Chat UI")

# Login is opt-in (see auth.py) -- only meaningful once K9CHAT_LOGIN_EMAIL
# is set in the environment (e.g. for a public deployment like
# chat.k9x.ai). SessionMiddleware still needs a secret key even when
# login is disabled, since request.session is used unconditionally by
# LoginRequiredMiddleware's dispatch(); falls back to a fixed dev-only
# value when login isn't enabled, since nothing security-sensitive
# depends on it in that mode.
#
# Order matters: Starlette's add_middleware() prepends, so the middleware
# added LAST ends up OUTERMOST (runs first on each request). Add
# LoginRequiredMiddleware first and SessionMiddleware second so
# SessionMiddleware actually wraps it and request.session exists by the
# time LoginRequiredMiddleware.dispatch() reads it -- reversing this order
# throws "SessionMiddleware must be installed" on every single request.
app.add_middleware(LoginRequiredMiddleware)
app.add_middleware(
    SessionMiddleware,
    secret_key=get_session_secret() if is_login_enabled() else "k9chat-dev-only-unused-secret",
)


@app.on_event("startup")
async def startup_event():
    run_chat_startup_check()

app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))


class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"
    project_id: str | None = None


class ProjectRequest(BaseModel):
    name: str
    instructions: str = ""


class ProjectUpdateRequest(BaseModel):
    name: str | None = None
    instructions: str | None = None


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@app.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request):
    form = await request.form()
    email = (form.get("email") or "").strip()
    password = form.get("password") or ""
    if not check_credentials(email, password):
        return templates.TemplateResponse(
            "login.html", {"request": request, "error": "Invalid email or password."}, status_code=401
        )
    request.session["logged_in"] = True
    request.session["email"] = email
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
        },
    )


@app.post("/chat")
def chat(payload: ChatRequest):
    message = payload.message.strip()
    if not message:
        return JSONResponse({"reply": ""})

    start = time.monotonic()
    reply = send_message(message, session_id=payload.session_id, project_id=payload.project_id)
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
    return JSONResponse(response)


@app.post("/chat/stream")
async def chat_stream(payload: ChatRequest):
    """SSE endpoint — used when chat.stream: true in config.yaml."""
    message = payload.message.strip()
    session_id = payload.session_id
    project_id = payload.project_id

    async def event_generator():
        if not message:
            yield f"data: {json.dumps({'done': True})}\n\n"
            return
        start = time.monotonic()
        full_text = ""
        async for chunk in send_message_stream(message, session_id=session_id, project_id=project_id):
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
        yield f"data: {json.dumps(done_payload)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/chat/config")
def chat_config():
    return JSONResponse({"stream": is_streaming_enabled()})


@app.get("/chat/evaluation")
def evaluation_status():
    return JSONResponse({"evaluation_enabled": is_evaluation_enabled()})


@app.post("/chat/evaluation/toggle")
def evaluation_toggle():
    enabled = toggle_evaluation()
    return JSONResponse({"evaluation_enabled": enabled})


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


@app.post("/projects")
def projects_create(payload: ProjectRequest):
    project = create_project(payload.name, instructions=payload.instructions)
    return JSONResponse(project)


@app.get("/projects")
def projects_list():
    return JSONResponse({"projects": list_projects()})


@app.get("/projects/{project_id}")
def projects_get(project_id: str):
    project = get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return JSONResponse(project)


@app.put("/projects/{project_id}")
def projects_update(project_id: str, payload: ProjectUpdateRequest):
    try:
        return JSONResponse(update_project(project_id, name=payload.name, instructions=payload.instructions))
    except ProjectNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")


@app.delete("/projects/{project_id}")
def projects_delete(project_id: str):
    try:
        return JSONResponse(delete_project(project_id))
    except ProjectNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")


@app.post("/projects/{project_id}/files")
async def projects_add_file(project_id: str, file: UploadFile = File(...)):
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
def projects_remove_file(project_id: str, file_id: str):
    try:
        return JSONResponse(remove_project_file(project_id, file_id))
    except ProjectNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")