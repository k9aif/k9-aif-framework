# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""Is the current call already inside a governed entry point?

An agent's ``execute()`` / ``execute_stream()`` and an orchestration
adapter's ``execute_flow()`` run governance around their whole body and mark
the call path while they do. ``llm_invoke()`` reads the mark: inside, the
caller's input and output checks already cover the model call; outside, it
runs the checks itself. So every model call is governed exactly once.
"""

from __future__ import annotations

import contextvars
from contextlib import contextmanager

# ids of the components currently governing this call path
GOVERNED_CALL: contextvars.ContextVar = contextvars.ContextVar("k9_governed_call", default=frozenset())


def inside_governed_call() -> bool:
    return bool(GOVERNED_CALL.get())


@contextmanager
def governed_call(owner):
    """Mark the call path as governed by *owner* for the duration of the block."""
    token = GOVERNED_CALL.set(GOVERNED_CALL.get() | {id(owner)})
    try:
        yield
    finally:
        GOVERNED_CALL.reset(token)
