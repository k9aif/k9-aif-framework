#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-K9AIF-Proprietary
# K9-AIF — Acme Health Insurance Experience Center (Backend)

import asyncio
import json
import traceback
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from aiokafka import AIOKafkaConsumer
from k9_aif_abb.k9_utils.config_loader import load_yaml
from .orchestrators.acme_orchestrator import AcmeOrchestrator
from .orchestrators.user_orchestrator import UserOrchestrator

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config" / "config.yaml"

APP_NAME = "K9-AIF Acme Health Insurance Experience Center"

config = load_yaml(str(CONFIG_FILE))
KAFKA_BOOTSTRAP = "localhost:9092"
KAFKA_TOPIC = "k9_aif_events"

UI_PATH = BASE_DIR / "ui"
STATIC_PATH = UI_PATH / "assets"
INDEX_HTML = UI_PATH / "index.html"
SIGNIN_HTML = UI_PATH / "signin.html"
REGISTER_HTML = UI_PATH / "register.html"

active_clients: Set[WebSocket] = set()

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.acme_orch = AcmeOrchestrator(config=config)
    app.state.user_orch = UserOrchestrator(config=config)
    app.state.kafka_consumer = None
    app.state.kafka_task = None

    try:
        consumer = AIOKafkaConsumer(
            KAFKA_TOPIC,
            bootstrap_servers=KAFKA_BOOTSTRAP,
            value_deserializer=lambda v: v.decode("utf-8"),
            auto_offset_reset="latest",
        )
        await consumer.start()
        app.state.kafka_consumer = consumer
        app.state.kafka_task = asyncio.create_task(kafka_to_ws(app))
        print(f"[LIFESPAN] Kafka consumer started on {KAFKA_BOOTSTRAP} topic={KAFKA_TOPIC}")
    except Exception as e:
        print(f"[LIFESPAN] Kafka not started: {e}")

    if STATIC_PATH.exists():
        app.mount("/assets", StaticFiles(directory=str(STATIC_PATH)), name="assets")
    else:
        print(f"[Static] No assets folder at {STATIC_PATH} (skipping mount)")

    yield

    if app.state.kafka_task:
        app.state.kafka_task.cancel()
        try:
            await app.state.kafka_task
        except Exception:
            pass
    if app.state.kafka_consumer:
        await app.state.kafka_consumer.stop()
        print("[LIFESPAN] Kafka consumer stopped")


app = FastAPI(title=APP_NAME, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"]
)


async def kafka_to_ws(app: FastAPI):
    consumer: AIOKafkaConsumer = app.state.kafka_consumer
    if not consumer:
        return
    try:
        async for msg in consumer:
            try:
                data = json.loads(msg.value)
                text = f"[{data.get('layer')}] {data.get('agent')} → {data.get('event_type')}"
            except Exception:
                text = msg.value
            await broadcast_ws(text)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"[KafkaLoop] Error: {e}")


async def broadcast_ws(msg: str):
    for ws in list(active_clients):
        try:
            await ws.send_text(msg)
        except Exception:
            active_clients.discard(ws)


@app.websocket("/ws/console")
async def ws_console(websocket: WebSocket):
    await websocket.accept()
    active_clients.add(websocket)
    try:
        await websocket.send_text("[Console] Connected to ACME Backend.")
        while True:
            await asyncio.sleep(30)
            await websocket.send_text("[Console] heartbeat")
    except WebSocketDisconnect:
        pass
    except Exception:
        traceback.print_exc()
    finally:
        active_clients.discard(websocket)


@app.get("/", response_class=HTMLResponse)
async def home():
    return INDEX_HTML.read_text(encoding="utf-8") if INDEX_HTML.exists() else "<h3>index.html missing</h3>"


@app.get("/signin", response_class=HTMLResponse)
async def signin_page():
    return SIGNIN_HTML.read_text(encoding="utf-8") if SIGNIN_HTML.exists() else "<h3>signin.html missing</h3>"


@app.get("/register", response_class=HTMLResponse)
async def register_page():
    return REGISTER_HTML.read_text(encoding="utf-8") if REGISTER_HTML.exists() else "<h3>register.html missing</h3>"


@app.post("/api/signin")
async def api_signin(username: str = Form(...), password: str = Form(...), role: str = Form(default="member")):
    payload = {"action": "signin", "username": username, "password": password, "role": role}
    result = await app.state.user_orch.execute_flow(payload)
    await broadcast_ws(f"[Auth] Sign-in: {username} ({role})")
    return JSONResponse(result)


@app.post("/api/register")
async def api_register(
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    role: str = Form(default="member"),
):
    payload = {"action": "register", "username": username, "email": email, "password": password, "role": role}
    result = await app.state.user_orch.execute_flow(payload)
    await broadcast_ws(f"[Auth] Register: {username} ({role})")
    return JSONResponse(result)


if __name__ == "__main__":
    import uvicorn

    print(f"Starting {APP_NAME} on http://localhost:8000")
    uvicorn.run("examples.acme_health_insurance.app_backend:app", host="0.0.0.0", port=8000, reload=False)
