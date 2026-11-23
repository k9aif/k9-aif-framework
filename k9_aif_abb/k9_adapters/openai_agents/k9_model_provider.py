# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
K9ModelProvider: the K9 Model Router chooses the model for every OpenAI agent (1.27.0).

The OpenAI Agents SDK accepts a ``ModelProvider`` per run; it asks the provider for a
model by name whenever an agent needs one. This provider treats the agent's ``model``
(its agent-YAML catalog alias) as the request's task type and asks the router through
``llm_route()``. The router applies its eligibility rules first (``tool_calling`` is
required whenever the agent has tools, plus anything in ``required_capabilities`` and
``confidential`` for a confidential request) and fails closed when no model qualifies.

The SDK then calls the chosen endpoint itself, through ``OpenAIChatCompletionsModel``.
That is why only OpenAI-compatible backends are served here (``ollama``, ``openai``);
any other backend raises ``ValueError`` rather than being called some other way.

This is the seam the Claude Agent SDK does not have: there the model is a fixed string
the SDK consumes, so its adapter governs actions only.
"""

from __future__ import annotations

import contextvars

import os
import time
from typing import Any, Dict, List, Optional

from agents.models.interface import Model, ModelProvider
from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel
from openai import AsyncOpenAI

from k9_aif_abb.k9_inference.models.inference_request import InferenceRequest
from k9_aif_abb.k9_utils.llm_invoke import llm_route
from k9_aif_abb.k9_utils.trace_events import emit_trace_event

_OPENAI_COMPATIBLE = ("ollama", "openai")


class K9GovernedModel(Model):
    """The SDK model for one routed endpoint, with every call reported as an ``LLMCall``
    trace event (model, alias, latency, tokens), like a call through ``llm_invoke()``."""

    def __init__(self, inner: Model, *, alias: str, model_name: str, backend: str, agent: str):
        self._inner = inner
        self.alias = alias
        self.model_name = model_name
        self.backend = backend
        self.agent = agent

    def _report(self, t0: float, usage: Any) -> None:
        emit_trace_event({
            "type": "LLMCall", "agent": self.agent, "task_type": self.alias,
            "model": self.model_name, "model_alias": self.alias, "provider": self.backend,
            "latency_ms": int((time.monotonic() - t0) * 1000),
            "tokens_in": getattr(usage, "input_tokens", None),
            "tokens_out": getattr(usage, "output_tokens", None),
        })

    async def get_response(self, *args: Any, **kwargs: Any):
        t0 = time.monotonic()
        response = await self._inner.get_response(*args, **kwargs)
        self._report(t0, getattr(response, "usage", None))
        return response

    async def stream_response(self, *args: Any, **kwargs: Any):
        t0 = time.monotonic()
        async for event in self._inner.stream_response(*args, **kwargs):
            yield event
        self._report(t0, None)

    async def close(self) -> None:
        await self._inner.close()


class K9ModelProvider(ModelProvider):
    """
    Parameters
    ----------
    config:
        The application config (its ``inference`` section feeds the router and LLMFactory).
    tools_by_alias:
        Catalog alias -> whether an agent using it has tools; such agents require
        ``tool_calling``. Built by the adapter from the agent specs.
    sensitivity, required_capabilities:
        Request-wide routing constraints (for example ``"confidential"``, ``["on_prem"]``).
    """

    def __init__(self, config: Dict[str, Any], *, tools_by_alias: Optional[Dict[str, bool]] = None,
                 sensitivity: Optional[str] = None, required_capabilities: Optional[List[str]] = None,
                 agent_name: str = "OpenAIAgent"):
        self.config = config or {}
        self.tools_by_alias = tools_by_alias or {}
        self.sensitivity = sensitivity
        self.required_capabilities = list(required_capabilities or [])
        self.agent_name = agent_name
        self.last_route: Optional[Dict[str, Any]] = None
        self._clients: List[AsyncOpenAI] = []

    def get_model(self, model_name: Optional[str]) -> Model:
        alias = model_name or "general"
        required = list(self.required_capabilities)
        if self.tools_by_alias.get(alias, True) and "tool_calling" not in required:
            required.append("tool_calling")
        request = InferenceRequest(
            prompt="", task_type=alias, sensitivity=self.sensitivity,
            required_capabilities=required or None,
            metadata={"agent": self.agent_name, "runtime": "openai_agents"},
        )
        route = llm_route(self.config, request)
        self.last_route = route
        backend = (route["backend"] or "").lower()
        if backend not in _OPENAI_COMPATIBLE:
            raise ValueError(
                f"[K9ModelProvider] model alias '{route['alias']}' is served by backend '{backend}', which the "
                f"OpenAI Agents SDK can't call. Eligible backends: {_OPENAI_COMPATIBLE}. Give this agent a "
                "catalog alias served by an OpenAI-compatible backend, or mark the others without 'tool_calling'."
            )
        client = AsyncOpenAI(base_url=_base_url(backend, route["connection"]),
                             api_key=_api_key(backend, route["connection"]))
        self._clients.append(client)
        inner = OpenAIChatCompletionsModel(model=route["model"], openai_client=client)
        return K9GovernedModel(inner, alias=route["alias"], model_name=route["model"], backend=backend,
                               agent=self.agent_name)


    async def aclose(self) -> None:
        """Close the clients this provider opened, on the event loop that used them. A run is bridged from sync code
        on a loop of its own; a client left open is closed later on that closed loop ('Event loop is closed')."""
        clients, self._clients = self._clients, []
        for client in clients:
            await client.close()


# The RunConfig of the K9-governed run in progress (1.35.0): what a guardrail's own Runner.run passes, so the
# check's model call goes through the K9 Model Router on this run's provider (see current_run_config()).
_CURRENT_RUN_CONFIG: contextvars.ContextVar = contextvars.ContextVar("k9_openai_run_config", default=None)


def current_run_config() -> Any:
    """The RunConfig of the K9-governed OpenAI run in progress. A guardrail that runs an agent of its own passes it
    on, ``Runner.run(check_agent, input, run_config=current_run_config())``, so that model call is routed by the K9
    Model Router (and its client lives on this run's event loop). Outside a run it raises: the check would otherwise
    call a model no one governs."""
    run_config = _CURRENT_RUN_CONFIG.get()
    if run_config is None:
        raise RuntimeError("current_run_config(): no K9-governed OpenAI run is in progress")
    return run_config


async def run_closing_provider(run_config: Any, run: Any) -> Any:
    """Await ``run()``, then close the run's K9ModelProvider clients (same loop), whatever the outcome."""
    token = _CURRENT_RUN_CONFIG.set(run_config)
    try:
        return await run()
    finally:
        _CURRENT_RUN_CONFIG.reset(token)
        provider = getattr(run_config, "model_provider", None)
        if isinstance(provider, K9ModelProvider):
            await provider.aclose()


def _base_url(backend: str, connection: Dict[str, Any]) -> Optional[str]:
    url = connection.get("base_url") or ""
    if backend == "ollama":
        url = (url or os.environ.get("OLLAMA_BASE_URL") or "http://localhost:11434").rstrip("/")
        return url if url.endswith("/v1") else url + "/v1"
    return url or None                      # openai: the client's default endpoint


def _api_key(backend: str, connection: Dict[str, Any]) -> str:
    if backend == "ollama":
        return "ollama"                     # Ollama ignores the key; the client requires one
    env = connection.get("api_key_env") or "OPENAI_API_KEY"
    key = os.environ.get(env)
    if not key:
        raise RuntimeError(f"[K9ModelProvider] backend 'openai' needs an API key in ${env}")
    return key
