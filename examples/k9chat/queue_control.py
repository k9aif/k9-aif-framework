# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

"""
Concurrency cap on real LLM generations -- separate concern from
auth.py's per-visitor identity. The actual guard against "someone spawns
a pile of concurrent bot requests and pegs the GPU": at most
K9CHAT_MAX_CONCURRENT (default 5, matching dow-k9-aif/DAS's own
MAX_QUEUE_SIZE convention) generations run against Ollama at once,
process-wide, across every visitor. A request beyond that WAITS (not
rejected) until a slot frees -- same shape DAS uses for its job queue,
except DAS rejects at capacity and this waits, per Ravi's explicit
"wait... you are in the queue" spec (2026-09-20).

threading.Semaphore, not asyncio.Semaphore -- /chat is a sync route
(FastAPI runs it in a thread pool) and /chat/stream is async, so this
needs to work correctly acquired from both. The async path awaits the
blocking acquire via run_in_executor rather than blocking the event loop.

Also enforces the real GPU thermal limit (see gpu_telemetry.py): a
request won't be admitted into a processing slot while the GPU is at or
above K9CHAT_GPU_TEMP_LIMIT_C, even if a slot is technically free --
polls every _TEMP_POLL_SECONDS until it cools. Deliberately does NOT
kill an already-admitted, in-flight generation -- aborting a running
Ollama request safely is a harder problem than just not starting new
ones while hot, and "stop admitting new work" is the honest, buildable
version of "regulate it" from Ravi's spec (2026-09-20).
"""

from __future__ import annotations

import os
import threading
import time
from typing import Optional

from examples.k9chat import gpu_telemetry

_MAX_CONCURRENT = int(os.environ.get("K9CHAT_MAX_CONCURRENT", "5"))
_TEMP_POLL_SECONDS = 1.0

_lock = threading.Lock()
_active = 0
_waiting = 0
_semaphore = threading.Semaphore(_MAX_CONCURRENT)


def status() -> dict:
    """Live snapshot for the waitlist UI widget -- polled, not pushed."""
    with _lock:
        return {"active": _active, "waiting": _waiting, "max_concurrent": _MAX_CONCURRENT}


class QueueSlot:
    """Context manager wrapping one generation's turn at a processing
    slot. `position` is set once __enter__/aenter starts waiting -- how
    many requests were already ahead of this one (0 = got a free slot
    immediately, no real queuing happened)."""

    def __init__(self) -> None:
        self.position = 0
        self.throttled_seconds = 0.0  # how long this call waited on temperature, not queue depth
        self._t0 = 0.0

    def _mark_waiting(self) -> None:
        global _waiting
        with _lock:
            _waiting += 1
            self.position = _waiting - 1  # how many were ahead of me, not counting myself
        self._t0 = time.monotonic()

    def _mark_acquired(self) -> None:
        global _waiting, _active
        with _lock:
            _waiting -= 1
            _active += 1

    def __enter__(self) -> "QueueSlot":
        self._mark_waiting()
        throttle_start = time.monotonic()
        while gpu_telemetry.is_over_temp_limit():
            time.sleep(_TEMP_POLL_SECONDS)
        self.throttled_seconds = time.monotonic() - throttle_start
        _semaphore.acquire()
        self._mark_acquired()
        return self

    def __exit__(self, *exc) -> bool:
        global _active
        with _lock:
            _active -= 1
        _semaphore.release()
        return False

    async def __aenter__(self) -> "QueueSlot":
        import asyncio
        self._mark_waiting()
        loop = asyncio.get_event_loop()
        throttle_start = time.monotonic()
        while await loop.run_in_executor(None, gpu_telemetry.is_over_temp_limit):
            await asyncio.sleep(_TEMP_POLL_SECONDS)
        self.throttled_seconds = time.monotonic() - throttle_start
        await loop.run_in_executor(None, _semaphore.acquire)
        self._mark_acquired()
        return self

    async def __aexit__(self, *exc) -> bool:
        global _active
        with _lock:
            _active -= 1
        _semaphore.release()
        return False

    @property
    def waited_seconds(self) -> float:
        return time.monotonic() - self._t0 if self._t0 else 0.0
