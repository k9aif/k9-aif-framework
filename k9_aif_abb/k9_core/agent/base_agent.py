# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

# K9-AIF - Base Agent
# Core abstract base for all K9-AIF domain and orchestration agents.

import asyncio
import concurrent.futures
import contextvars
import functools
import inspect
import logging
import os
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from k9_aif_abb.k9_core.governance.pipeline import (
    NoopGovernance,
    assert_governed,
    governance_from_config,
    require_governance,
)

# Agents currently inside a governed execute() on this call path: a subclass
# calling super().execute(), or one agent's wrapper calling another
# wrapper of the same agent, is governed once, not twice. The same mark tells
# llm_invoke() that the model call it makes is already governed.
from k9_aif_abb.k9_core.governance.call_context import GOVERNED_CALL as _GOVERNING  # noqa: E402


def _resolve_sync(value: Any) -> Any:
    """Return *value*, or run it to completion if it is awaitable (governance
    backends may be sync or async). Safe inside a running event loop."""
    if not inspect.isawaitable(value):
        return value

    async def _await():
        return await value

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        loop_running = False
    else:
        loop_running = True
    if not loop_running:
        # Outside the except block: a governance PermissionError then reads as itself in a
        # traceback, not "during handling of RuntimeError: no running event loop".
        return asyncio.run(_await())
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, _await()).result()


def _payload_of(args, kwargs):
    """The payload argument of an entry point, and how to put a checked one back."""
    if args:
        return args[0], (lambda new: ((new,) + tuple(args[1:]), kwargs))
    if "payload" in kwargs:
        return kwargs["payload"], (lambda new: (args, {**kwargs, "payload": new}))
    for key in ("request",):
        if key in kwargs:
            return kwargs[key], (lambda new, k=key: (args, {**kwargs, k: new}))
    return None, None


def _governed_stream(fn):
    """Wrap a streaming entry point (``execute_stream``) the way
    ``_governed_execute`` wraps ``execute()``: assert real governance,
    pre_process the request before the first chunk, stream, then
    post_process the complete reply. Classes with ``_governs_own_execute``
    get the assertion only. An egress block can only act once the reply is
    complete: it raises after the chunks were sent, so callers report the
    reply as stopped (streaming cannot take back what it already sent)."""

    def _pre(self, args, kwargs):
        assert_governed(self.governance, self.layer, self.logger)
        if getattr(self, "_governs_own_execute", False):
            return args, kwargs, False
        payload, rebuild = _payload_of(args, kwargs)
        if rebuild is not None:
            checked = _resolve_sync(self.governance.pre_process(payload, self._governance_context()))
            args, kwargs = rebuild(checked)
        return args, kwargs, True

    def _post(self, parts, pre_post):
        if pre_post and parts:
            _resolve_sync(self.governance.post_process(
                "".join(p if isinstance(p, str) else str(p) for p in parts), self._governance_context()))

    # The agent's generator runs step by step in the consumer's context, so
    # the governed-call mark is set around each step (not across yields).
    if inspect.isasyncgenfunction(fn):
        @functools.wraps(fn)
        async def wrapper(self, *args, **kwargs):
            args, kwargs, pre_post = _pre(self, args, kwargs)
            parts = []
            agen = fn(self, *args, **kwargs)
            try:
                while True:
                    token = _GOVERNING.set(_GOVERNING.get() | {id(self)})
                    try:
                        chunk = await agen.__anext__()
                    except StopAsyncIteration:
                        break
                    finally:
                        _GOVERNING.reset(token)
                    parts.append(chunk)
                    yield chunk
            finally:
                await agen.aclose()
            _post(self, parts, pre_post)
    else:
        @functools.wraps(fn)
        def wrapper(self, *args, **kwargs):
            args, kwargs, pre_post = _pre(self, args, kwargs)
            parts = []
            gen = fn(self, *args, **kwargs)
            try:
                while True:
                    token = _GOVERNING.set(_GOVERNING.get() | {id(self)})
                    try:
                        chunk = next(gen)
                    except StopIteration:
                        break
                    finally:
                        _GOVERNING.reset(token)
                    parts.append(chunk)
                    yield chunk
            finally:
                gen.close()
            _post(self, parts, pre_post)

    wrapper._k9_governed = True
    return wrapper


def _governed_execute(fn, *, pre_post: bool):
    """Wrap an agent's execute() so governance runs around it automatically:
    assert real governance (refused in production if none), pre_process the
    payload, run the agent, post_process its output. ``pre_post=False`` for
    classes that run pre/post themselves around their own work (the loop
    agents): those get the assertion only."""

    if inspect.iscoroutinefunction(fn):
        @functools.wraps(fn)
        async def wrapper(self, *args, **kwargs):
            active = _GOVERNING.get()
            if id(self) in active:
                return await fn(self, *args, **kwargs)
            token = _GOVERNING.set(active | {id(self)})
            try:
                assert_governed(self.governance, self.layer, self.logger)
                if pre_post:
                    payload, rebuild = _payload_of(args, kwargs)
                    if rebuild is not None:
                        checked = self.governance.pre_process(payload, self._governance_context())
                        if inspect.isawaitable(checked):
                            checked = await checked
                        args, kwargs = rebuild(checked)
                result = await fn(self, *args, **kwargs)
                if pre_post and isinstance(result, dict) and "output" in result:
                    out = self.governance.post_process(result["output"], self._governance_context())
                    if inspect.isawaitable(out):
                        out = await out
                    result = {**result, "output": out}
                return result
            finally:
                _GOVERNING.reset(token)
    else:
        @functools.wraps(fn)
        def wrapper(self, *args, **kwargs):
            active = _GOVERNING.get()
            if id(self) in active:
                return fn(self, *args, **kwargs)
            token = _GOVERNING.set(active | {id(self)})
            try:
                assert_governed(self.governance, self.layer, self.logger)
                if pre_post:
                    payload, rebuild = _payload_of(args, kwargs)
                    if rebuild is not None:
                        checked = _resolve_sync(self.governance.pre_process(payload, self._governance_context()))
                        args, kwargs = rebuild(checked)
                result = fn(self, *args, **kwargs)
                if pre_post and isinstance(result, dict) and "output" in result:
                    out = _resolve_sync(self.governance.post_process(result["output"], self._governance_context()))
                    result = {**result, "output": out}
                return result
            finally:
                _GOVERNING.reset(token)

    wrapper._k9_governed = True
    return wrapper


class BaseAgent(ABC):
    """
    BaseAgent
    =========
    Abstract foundation for all K9-AIF agents.

    Governance by construction: every subclass's ``execute()`` is wrapped
    when the class is defined, so governance runs on every call without the
    agent doing anything:

    1. assert real governance is configured (``PermissionError`` outside
       development/test if it is NoopGovernance);
    2. ``governance.pre_process(payload)``;
    3. the agent's own ``execute()``;
    4. ``governance.post_process(result["output"])`` (a dict result's output;
       the result's audit fields are left as they are).

    A ``PermissionError`` from governance (e.g. Shield BLOCK) propagates to
    the caller. Overriding ``execute()`` does not bypass this: the override is
    wrapped too. Classes that run pre/post themselves around their own work
    (``BaseValidationLoopAgent``, ``BaseCriticActorAgent``) set
    ``_governs_own_execute = True`` and get the assertion only.

    With no ``governance=`` argument, governance is built from the agent's
    config (``security.shield.enabled: true`` → ShieldGovernance), so one
    config setting governs every agent of an application.
    """

    layer: str = "Agent Base"
    _governs_own_execute: bool = False

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        stream = cls.__dict__.get("execute_stream")
        if stream is not None and not getattr(stream, "_k9_governed", False) and (
                inspect.isasyncgenfunction(stream) or inspect.isgeneratorfunction(stream)):
            cls.execute_stream = _governed_stream(stream)
        fn = cls.__dict__.get("execute")
        if fn is None or getattr(fn, "_k9_governed", False) or getattr(fn, "__isabstractmethod__", False):
            return
        own = cls.__dict__.get("_governs_own_execute", False)
        cls.execute = _governed_execute(fn, pre_post=not own)

    # ------------------------------------------------------------------
    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        monitor=None,
        message_bus=None,
        governance=None,
    ):
        self.config = config or {}
        self.monitor = monitor
        self.message_bus = message_bus
        if governance is None:
            governance = governance_from_config(self.config)
        self.governance = require_governance(
            governance, self.config.get("k9_env")
        )
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.debug(f"[{self.layer}] Initialized with config: {self.config}")

    # ------------------------------------------------------------------
    @abstractmethod
    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError("Subclasses must implement execute()")

    # ------------------------------------------------------------------
    async def execute_stream(self, payload: Dict[str, Any]):
        """Streaming entry point; governed like ``execute()`` (request checked
        before the first chunk, complete reply checked at the end). The
        default yields ``execute()``'s output as one chunk; agents that stream
        model output override it (an async or sync generator) and are
        governed automatically. ``execute()`` and ``execute_stream()`` are an
        agent's entry points: callers do not invoke other public methods to
        run an agent."""
        token = _GOVERNING.set(_GOVERNING.get() | {id(self)})   # governed by this wrapper, not twice
        try:
            result = self.execute(payload)
            if inspect.isawaitable(result):
                result = await result
        finally:
            _GOVERNING.reset(token)
        yield result.get("output", "") if isinstance(result, dict) else str(result)

    # ------------------------------------------------------------------
    def publish_event(self, event: Dict[str, Any]):
        if self.message_bus:
            self.message_bus.publish(event)
        if self.monitor:
            self.monitor.record_event(event)
        self.logger.info(f"[{self.layer}] Event published: {event}")

    # ------------------------------------------------------------------
    async def apply_pre_governance(
        self,
        payload: Dict[str, Any],
        ctx: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:

        result = self.governance.pre_process(
            payload,
            ctx or self._governance_context(),
        )
        if inspect.isawaitable(result):
            result = await result
        return result

    # ------------------------------------------------------------------
    async def apply_post_governance(
        self,
        payload: Dict[str, Any],
        ctx: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:

        result = self.governance.post_process(
            payload,
            ctx or self._governance_context(),
        )
        if inspect.isawaitable(result):
            result = await result
        return result

    # ------------------------------------------------------------------
    def enforce_governance(self) -> None:
        """
        Assert that a real governance pipeline is wired up.

        Called automatically around every ``execute()`` (see the class
        docstring); explicit calls remain valid and are harmless. In
        development/test NoopGovernance is tolerated with a WARNING;
        anywhere else (``K9_ENV`` unset means production) it raises.

        Raises:
            PermissionError: if governance is NoopGovernance outside dev/test.
        """
        assert_governed(self.governance, self.layer, self.logger)

    # ------------------------------------------------------------------
    def _governance_context(self) -> Dict[str, Any]:
        return {
            "layer": self.layer,
            "component": self.__class__.__name__,
            "component_type": "agent",
        }


BaseAgent.execute_stream = _governed_stream(BaseAgent.__dict__["execute_stream"])
