# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

# File: k9_aif_abb/k9_core/integration/base_connector.py

from abc import ABC
from typing import Dict, Any, Optional
import functools
import inspect
import logging
from k9_aif_abb.k9_core.base_component import BaseComponent
from k9_aif_abb.k9_core.tools.tool_gate_context import (
    ACTIVE_GATE, DISPATCHING, gate_required, warn_ungated_once,
)


def _gated_call_tool(fn):
    """Route a connector's ``call_tool()`` through the tool gate (1.25.0).

    Inside a governed agent call with ``security.tool_gate.enabled``, the call is
    proposed to the gate's ``BaseToolDispatcher`` instead of running. While the
    framework itself runs a tool (``DISPATCHING``) it passes straight through.
    With no gate session: refused in production once any gate is enabled in this
    process (the session can't have been lost legitimately); otherwise it runs,
    with a one-time warning in production that the gate is off."""

    @functools.wraps(fn)
    async def wrapper(self, tool_name, arguments=None, *args, **kwargs):
        if DISPATCHING.get():
            return await fn(self, tool_name, arguments, *args, **kwargs)
        session = ACTIVE_GATE.get()
        if session is None:
            from k9_aif_abb.k9_core.governance.pipeline import is_permissive_env
            if gate_required():
                msg = (f"[ToolGate] {tool_name!r} called through {type(self).__name__} outside a gated "
                       "agent call while the tool gate is enabled")
                if not is_permissive_env():
                    raise PermissionError(msg + " (refused in production)")
                logging.getLogger("k9.tool_gate").warning(msg + " (allowed in development/test)")
            elif not is_permissive_env():
                warn_ungated_once(type(self).__name__, tool_name)
            return await fn(self, tool_name, arguments, *args, **kwargs)
        from k9_aif_abb.k9_core.tools.tool_call import ToolCall
        call = ToolCall(tool_name=tool_name, arguments=dict(arguments or {}),
                        request_id=session.request_id, agent_id=session.agent_id)
        return await session.dispatcher.propose(call, connector=self, session=session)

    wrapper._k9_gated = True
    return wrapper


class BaseConnector(BaseComponent, ABC):
    """
    K9-AIF Integration ABB - BaseConnector
    --------------------------------------
    Abstract base class for all Integration ABB connectors.
    Examples: RESTConnector, S3Connector, AppianConnector, etc.

    Responsibilities:
    - Provide consistent connect / send_request / close lifecycle.
    - Handle telemetry and monitoring through BaseComponent.
    - Offer unified, layer-aware logging (visible in console & log files).

    Tool gate (1.25.0): every subclass's async ``call_tool()`` is wrapped when the
    class is defined, so with ``security.tool_gate.enabled`` a call made inside a
    governed agent call goes through ``BaseToolDispatcher`` first. Overriding
    ``call_tool()`` doesn't bypass it: the override is wrapped too.
    """

    layer = "Integration ABB"

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        fn = cls.__dict__.get("call_tool")
        if fn is not None and inspect.iscoroutinefunction(fn) and not getattr(fn, "_k9_gated", False):
            cls.call_tool = _gated_call_tool(fn)

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        name: Optional[str] = None,
        monitor=None,
    ):
        super().__init__(monitor=monitor)
        self.config = config or {}
        self.name = name or self.__class__.__name__
        self.logger = logging.getLogger("integration")

    async def log(self, msg: str, level: str = "INFO"):
        """Layer-aware async log; streams to monitor and Python logger."""
        await super().log(msg, level)
        line = f"[{self.layer}:{self.name}] {msg}"
        getattr(self.logger, level.lower(), self.logger.info)(line)

    # --- Default Lifecycle Methods ---

    def connect(self) -> bool:
        """Default no-op connect. Override in child if needed."""
        # Note: sync call, but we still log async-safe via logger directly.
        self.logger.debug(f"[{self.layer}:{self.name}] Default connect() called (no-op).")
        return True

    def send_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Default no-op request. Override in child if needed."""
        self.logger.debug(f"[{self.layer}:{self.name}] Default send_request() called with {request}")
        return {"status": "noop", "input": request}

    def close(self) -> None:
        """Default no-op close. Override in child if needed."""
        self.logger.debug(f"[{self.layer}:{self.name}] Default close() called (no-op).")

    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Default execute delegates to send_request()."""
        self.logger.debug(f"[{self.layer}:{self.name}] Executing payload via send_request: {payload}")
        return self.send_request(payload)