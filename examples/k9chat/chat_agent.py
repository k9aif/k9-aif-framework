# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

import json
import os
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from k9_aif_abb.k9_utils.config_loader import load_yaml
from k9_aif_abb.k9_core.agent.base_agent import BaseAgent
from k9_aif_abb.k9_factories.model_router_factory import ModelRouterFactory
from k9_aif_abb.k9_factories.cache_factory import CacheFactory
from k9_aif_abb.k9_inference.models.inference_request import InferenceRequest
from k9_aif_abb.k9_utils.llm_invoke import llm_invoke_stream
from examples.k9chat.guard_agent import GuardAgent

BASE_DIR = os.path.dirname(__file__)


class ChatAgent(BaseAgent):

    def __init__(self, config=None):
        if config is None:
            config = load_yaml(os.path.join(BASE_DIR, "config.yaml"))

        super().__init__(config)

        self.router = ModelRouterFactory.get_router(config)
        self._cache = CacheFactory.create(config)
        self.guard_agent = GuardAgent(config)

        chat_cfg = config.get("chat", {})
        self._session_ttl = int(chat_cfg.get("session_ttl_seconds", 3600))
        self._max_history = int(chat_cfg.get("max_history", 20))

    # ------------------------------------------------------------------
    # Session history — get/append/format
    # ------------------------------------------------------------------
    def _history_key(self, session_id: str) -> str:
        return f"k9chat:history:{session_id}"

    def _get_history(self, session_id: str) -> list:
        raw = self._cache.get(self._history_key(session_id))
        if not raw:
            return []
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return []

    def _save_history(self, session_id: str, history: list) -> None:
        if len(history) > self._max_history:
            history = history[-self._max_history:]
        self._cache.set(
            self._history_key(session_id),
            json.dumps(history),
            ttl=self._session_ttl,
        )

    def clear_history(self, session_id: str) -> None:
        self._cache.delete(self._history_key(session_id))

    def _format_prompt(self, history: list, new_message: str) -> str:
        """Render prior turns + the new message into a single prompt string."""
        lines = []
        for turn in history:
            role = "User" if turn["role"] == "user" else "Assistant"
            lines.append(f"{role}: {turn['content']}")
        lines.append(f"User: {new_message}")
        lines.append("Assistant:")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Execute — full response (synchronous)
    # ------------------------------------------------------------------
    def execute(self, request):
        message = request.get("text") or request.get("prompt", "")
        session_id = request.get("session_id", "default")

        guard_result = self.guard_agent.execute({"text": message})
        if not guard_result["passed"]:
            reply = self.guard_agent.refusal_message
            history = self._get_history(session_id)
            history.append({"role": "user", "content": message})
            history.append({"role": "assistant", "content": reply})
            self._save_history(session_id, history)
            return {"text": reply, "model": None, "session_id": session_id, "blocked": True}

        history = self._get_history(session_id)
        prompt = self._format_prompt(history, message)

        inf_req = InferenceRequest(prompt=prompt, task_type="chat")
        response = self.router.invoke(inf_req)

        history.append({"role": "user", "content": message})
        history.append({"role": "assistant", "content": response.output})
        self._save_history(session_id, history)

        return {
            "text": response.output,
            "model": response.model_alias,
            "session_id": session_id,
        }

    # ------------------------------------------------------------------
    # Execute — streaming
    # ------------------------------------------------------------------
    async def execute_stream(self, request):
        """
        Stream the chat response incrementally. Mirrors ``execute()`` but
        yields text chunks as they arrive from the LLM instead of returning
        a complete dict. Used when ``chat.stream: true`` in config.

        Conversation history is retrieved and persisted the same way as
        ``execute()`` — multi-turn context works identically whether
        streaming is on or off.
        """
        message = request.get("text") or request.get("prompt", "")
        session_id = request.get("session_id", "default")

        guard_result = self.guard_agent.execute({"text": message})
        if not guard_result["passed"]:
            reply = self.guard_agent.refusal_message
            yield reply
            history = self._get_history(session_id)
            history.append({"role": "user", "content": message})
            history.append({"role": "assistant", "content": reply})
            self._save_history(session_id, history)
            return

        history = self._get_history(session_id)
        prompt = self._format_prompt(history, message)

        inf_req = InferenceRequest(prompt=prompt, task_type="chat")

        full_response = []
        async for chunk in llm_invoke_stream(self.config, inf_req):
            full_response.append(chunk)
            yield chunk

        history.append({"role": "user", "content": message})
        history.append({"role": "assistant", "content": "".join(full_response)})
        self._save_history(session_id, history)