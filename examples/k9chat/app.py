# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

import os
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from examples.k9chat.chat import send_message, get_chat_runtime_info

BASE_DIR = os.path.dirname(__file__)

app = FastAPI(title="K9Chat UI")

app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))


class ChatRequest(BaseModel):
    message: str


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

    reply = send_message(message)
    return JSONResponse({"reply": reply})