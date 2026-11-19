# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""One sync-over-async bridge for the framework (1.31.0).

Agents, governance backends and adapters may be sync or async; the layers that
call them (``BaseSquad.execute``, ``llm_invoke``, the governance wrapper, the
model router) are sync and may themselves run inside an event loop (FastAPI,
an async orchestrator). ``asyncio.run()`` refuses to nest in a running loop,
so in that case the awaitable runs on a worker thread with its own loop,
carrying the caller's context variables (trace ids, identity).

Before 1.31.0 this lived as five private copies; one of them re-ran the
coroutine when it raised ``RuntimeError`` and replaced the real error with
"cannot reuse already awaited coroutine".
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextvars
import inspect
from typing import Any, Awaitable


def _in_running_loop() -> bool:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


def run_sync(awaitable: Awaitable[Any]) -> Any:
    """Run *awaitable* to completion from sync code and return its result.

    Safe whether or not an event loop is running on this thread. Exceptions
    raised by the awaitable propagate unchanged.
    """
    async def _await() -> Any:
        return await awaitable

    if not _in_running_loop():
        return asyncio.run(_await())
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(contextvars.copy_context().run, asyncio.run, _await()).result()


def resolve(value: Any) -> Any:
    """*value* itself, or its result when it is awaitable (sync-or-async callee)."""
    return run_sync(value) if inspect.isawaitable(value) else value
