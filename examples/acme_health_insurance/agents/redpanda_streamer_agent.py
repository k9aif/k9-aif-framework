# SPDX-License-Identifier: LicenseRef-K9AIF-Proprietary
# K9-AIF  Acme Health Insurance  Redpanda Streamer Agent

import asyncio
import json
import uuid
from pathlib import Path
from starlette.websockets import WebSocketState

from k9_aif_abb.k9_core.agent.base_agent import BaseAgent
from k9_aif_abb.k9_factories.streaming_factory import StreamingFactory
from k9_aif_abb.k9_utils.config_loader import load_config


class RedpandaStreamerAgent(BaseAgent):
    """SBB Agent for real-time Redpanda event streaming (Acme version)."""

    def __init__(self):
        super().__init__(name="RedpandaStreamerAgent")

        #  Load Acme project-specific config instead of ABB global CONFIG
        cfg_path = Path("examples/acme_health_insurance/config/config.yaml")
        config = load_config(cfg_path)

        messaging_cfg = config.get("messaging", {})
        self.topic = messaging_cfg.get("topic", "acme-events")

        # Unique group ID per stream (ensures clean offsets)
        base_group = messaging_cfg.get("group_id", "acme-core")
        self.group_id = f"{base_group}-stream-{uuid.uuid4().hex[:4]}"
        self.client_id = messaging_cfg.get("client_id", "acme-console")

        self.provider = StreamingFactory.get(messaging_cfg.get("backend", "redpanda_logs"))

    # ------------------------------------------------------------------
    async def execute(self, websocket):
        """Stream live Redpanda messages to the web console."""
        await websocket.accept()

        await websocket.send_text(
            json.dumps(
                {
                    "status": "connected",
                    "agent": self.name,
                    "topic": self.topic,
                    "message": "RedpandaStreamerAgent active  awaiting events",
                }
            )
        )

        print(f"[{self.name}] Subscribing to topic={self.topic}, group_id={self.group_id}")

        loop = asyncio.get_running_loop()
        connected = True

        # --------------------------------------------------------------
        # Callback to forward Redpanda messages  WebSocket
        # --------------------------------------------------------------
        def on_message(data):
            if not connected or websocket.client_state != WebSocketState.CONNECTED:
                return

            payload = json.dumps(data)

            async def safe_send():
                try:
                    if websocket.client_state == WebSocketState.CONNECTED:
                        await websocket.send_text(payload)
                except Exception as e:
                    print(f"[{self.name}]  Send failed: {e}")

            try:
                loop.create_task(safe_send())
            except RuntimeError:
                asyncio.run(safe_send())

        # --------------------------------------------------------------
        # Background consumer
        # --------------------------------------------------------------
        loop.run_in_executor(
            None, self.provider.subscribe, self.topic, self.group_id, on_message
        )

        # --------------------------------------------------------------
        # Keep connection alive
        # --------------------------------------------------------------
        try:
            while True:
                await asyncio.sleep(1)
                if websocket.client_state != WebSocketState.CONNECTED:
                    connected = False
                    print(f"[{self.name}] Client disconnected.")
                    break
        except asyncio.CancelledError:
            connected = False
            print(f"[{self.name}] Stream cancelled.")
        except Exception as e:
            connected = False
            print(f"[{self.name}]  Stream error: {e}")
        finally:
            if websocket.client_state != WebSocketState.DISCONNECTED:
                try:
                    await websocket.close()
                except Exception:
                    pass
            print(f"[{self.name}] Stream closed gracefully.")