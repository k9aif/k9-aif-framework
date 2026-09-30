# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
Tool-result guard: govern what a tool *returns* before a model reads it.

Tool calls are governed on the way out (Shield egress / the Claude Agent SDK
adapter's ``can_use_tool``). What comes back — a fetched web page, a document,
a record, another agent's reply — is untrusted input to the model, and is
exactly where indirect prompt injection lives: instructions planted in
content the agent retrieves. Zscaler ThreatLabz's 2026 report predicts
"AI agents will phish other AI agents" through crafted inputs and spoofed
interactions; OWASP LLM01 covers the same ground.

``screen_tool_result()`` runs a result through a governance object's
**ingress** stage (``pre_process``: Shield's ingress checks and, when chained,
Granite Guardian), exactly as an incoming user prompt would be. The text is
placed under ``"query"`` so Guardian — which reads that key first — screens
the real content, not a stringified wrapper.

Use it three ways:
  - Claude Agent SDK: ClaudeAgentSDKOrchestratorAdapter wraps every registered
    tool handler with it automatically (``govern_tool_results=True``).
  - CrewAI tools / plain functions: ``@govern_tool_result(governance)`` —
    a blocked result is replaced by a "withheld" notice the model can read.
  - LangGraph nodes: ``@govern_tool_result(governance, on_block="raise")`` —
    a node can't hand back a notice in place of its state, so it raises
    PermissionError, which the LangGraph adapter surfaces to the caller.

A governance pipeline built for user prompts may be stricter than tool output
needs (e.g. InputSizeCheck on a large fetched page, PIIBoundaryCheck on a
record lookup that legitimately returns personal data). Pass a narrower
governance object for tool results when that matters — typically
PromptInjectionCheck + Granite Guardian.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import functools
import inspect
import json
import logging
from typing import Any, Callable, Dict, Optional

from k9_aif_abb.k9_utils.trace_events import emit_trace_event

log = logging.getLogger("governance.tool_result_guard")

WITHHELD = "[Tool result withheld by K9-AIF governance: {reason}]"


def result_text(result: Any) -> str:
    """Flatten a tool result to the text a model would actually read.
    MCP/Claude-SDK shape ({"content": [{"type": "text", "text": ...}]}) is
    unwrapped; anything else is JSON-serialized (or str()-ed)."""
    if isinstance(result, str):
        return result
    if isinstance(result, dict) and isinstance(result.get("content"), list):
        parts = [c.get("text", "") for c in result["content"] if isinstance(c, dict)]
        if any(parts):
            return "\n".join(p for p in parts if p)
    try:
        return json.dumps(result, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(result)


async def screen_tool_result(governance: Any, tool_name: str, result: Any,
                             ctx: Optional[Dict[str, Any]] = None) -> None:
    """Raise PermissionError when governance refuses this tool result."""
    payload = {"query": result_text(result), "source": "tool_result", "source_tool": tool_name}
    context = {"component": f"tool:{tool_name}", **(ctx or {})}
    try:
        outcome = governance.pre_process(payload, context)
        if inspect.isawaitable(outcome):
            await outcome
    except PermissionError as exc:
        log.warning("[ToolResultGuard] result of tool=%s WITHHELD: %s", tool_name, exc)
        emit_trace_event({"type": "ToolResultScreen", "tool": tool_name, "allowed": False,
                          "reason": str(exc)[:300]})
        raise
    emit_trace_event({"type": "ToolResultScreen", "tool": tool_name, "allowed": True})


def withheld_value(original: Any, reason: str) -> Any:
    """What the model receives instead of a refused result, shaped like the original."""
    notice = WITHHELD.format(reason=reason)
    if isinstance(original, dict) and isinstance(original.get("content"), list):
        return {"content": [{"type": "text", "text": notice}], "is_error": True}
    if isinstance(original, dict):
        return {"error": notice, "withheld_by_governance": True}
    return notice


def govern_tool_result(governance: Any, *, tool_name: Optional[str] = None,
                       on_block: str = "withhold") -> Callable:
    """Decorator for a sync or async tool function.

    on_block="withhold" (default): the model gets a withheld notice instead
    of the content. on_block="raise": PermissionError propagates (use for
    graph nodes, whose return value is state rather than text)."""
    if on_block not in ("withhold", "raise"):
        raise ValueError("on_block must be 'withhold' or 'raise'")

    def decorate(fn: Callable) -> Callable:
        name = tool_name or getattr(fn, "__name__", "tool")

        def refused(original: Any, exc: PermissionError) -> Any:
            if on_block == "raise":
                raise exc
            return withheld_value(original, str(exc))

        if inspect.iscoroutinefunction(fn):
            @functools.wraps(fn)
            async def async_wrapper(*args, **kwargs):
                result = await fn(*args, **kwargs)
                try:
                    await screen_tool_result(governance, name, result)
                except PermissionError as exc:
                    return refused(result, exc)
                return result
            return async_wrapper

        @functools.wraps(fn)
        def sync_wrapper(*args, **kwargs):
            result = fn(*args, **kwargs)
            try:
                _run_coro_sync(screen_tool_result(governance, name, result))
            except PermissionError as exc:
                return refused(result, exc)
            return result
        return sync_wrapper

    return decorate


def _run_coro_sync(coro):
    """Run a coroutine from sync code, safe inside an already-running loop
    (same bridge as BaseOrchestrator / the CrewAI and LangGraph adapters)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()
