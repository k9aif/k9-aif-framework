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
import warnings
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from k9_aif_abb.k9_core.governance.pipeline import (
    NoopGovernance,
    assert_governed,
    governance_from_config,
    is_permissive_env,
    require_governance,
)

# Agents currently inside a governed execute() on this call path: a subclass
# calling super().execute(), or one agent's wrapper calling another
# wrapper of the same agent, is governed once, not twice. The same mark tells
# llm_invoke() that the model call it makes is already governed.
from k9_aif_abb.k9_core.governance.call_context import GOVERNED_CALL as _GOVERNING  # noqa: E402
from k9_aif_abb.k9_core.tools.tool_gate_context import ACTIVE_GATE as _ACTIVE_GATE  # noqa: E402


# Agent classes already told that publish_event() is deprecated: one log line per class, not per call.
_PUBLISH_EVENT_WARNED: set = set()


def _warn_publish_event_deprecated(agent) -> None:
    msg = (f"{type(agent).__qualname__}: BaseAgent.publish_event() is deprecated since k9-aif 1.24; use "
           "notify_monitor(). It is an alias of notify_monitor() and never publishes to Kafka (removed in 2.0).")
    warnings.warn(msg, DeprecationWarning, stacklevel=3)
    if type(agent) not in _PUBLISH_EVENT_WARNED:
        _PUBLISH_EVENT_WARNED.add(type(agent))
        agent.logger.warning(msg)


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
        return pool.submit(contextvars.copy_context().run, asyncio.run, _await()).result()


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


def _no_payload(agent) -> None:
    """The entry point was called without a payload the wrapper can find (first positional
    argument, ``payload=`` or ``request=``), so the input cannot be checked. Refused outside
    development/test (1.22); before, the input check was skipped silently."""
    msg = (f"[{agent.layer}] input check skipped: call execute()/execute_stream() with the payload "
           "as the first argument, payload= or request=")
    if is_permissive_env():
        agent.logger.warning(msg)
        return
    raise PermissionError(msg + " (refused in production)")


# Where the framework's own agent ABBs live (BaseValidationLoopAgent, BaseCriticActorAgent).
_FRAMEWORK_AGENT_ABBS = "k9_aif_abb.k9_agents."


def _opts_out(agent) -> bool:
    """True when the agent runs its own pre/post checks (``_governs_own_execute``), as the
    framework's loop ABBs do. Only an ABB in ``k9_aif_abb.k9_agents`` may declare it: declared by an
    application class, or set on an instance, it is refused outside development/test (1.22;
    before, it was reported by inspection only, K9-GOV-007)."""
    if "_governs_own_execute" in vars(agent):
        owner, flag = None, vars(agent)["_governs_own_execute"]
    else:
        owner = next((k for k in type(agent).__mro__ if "_governs_own_execute" in k.__dict__), None)
        flag = owner.__dict__["_governs_own_execute"] if owner is not None else False
    if not flag:
        return False
    if owner is not None and owner.__module__.startswith(_FRAMEWORK_AGENT_ABBS):
        return True
    where = owner.__qualname__ if owner is not None else f"an instance of {type(agent).__qualname__}"
    msg = (f"[{agent.layer}] _governs_own_execute is set by {where}: only the framework's loop ABBs "
           "may run their own pre/post checks")
    if is_permissive_env():
        agent.logger.warning(msg + " (allowed in development/test)")
        return True
    raise PermissionError(msg + " (refused in production)")


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
        if _opts_out(self):
            return args, kwargs, False
        payload, rebuild = _payload_of(args, kwargs)
        if rebuild is None:
            _no_payload(self)
        else:
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


def _tool_gate_session(agent, args, kwargs):
    """The tool-gate session for one governed call, or None when the gate is off (1.25.0)."""
    from k9_aif_abb.k9_core.tools.base_tool_dispatcher import BaseToolDispatcher, gate_enabled
    from k9_aif_abb.k9_core.tools.tool_gate_context import ACTIVE_GATE, GateSession, require_gate
    if not gate_enabled(agent.config):
        return None
    require_gate()
    dispatcher = agent.__dict__.get("_k9_tool_dispatcher")
    if dispatcher is None:
        dispatcher = BaseToolDispatcher.from_config(agent.config, governance=agent.governance)
        agent.__dict__["_k9_tool_dispatcher"] = dispatcher
    payload, _ = _payload_of(args, kwargs)
    request_id = payload.get("request_id") or payload.get("correlation_id") if isinstance(payload, dict) else None
    # 1.25.0 treats every request as carrying outside content: nothing yet marks a request
    # trusted in a way a caller couldn't forge, so the rules can't use this to loosen anything.
    return GateSession(dispatcher=dispatcher, agent_id=type(agent).__name__, request_id=request_id,
                       untrusted_input=True, parent=ACTIVE_GATE.get())


def _surface_review(session, error=None):
    """A tool call in this agent call is waiting for a person, but the agent's code caught the
    review and carried on (or raised something else): raise the review again. Framework code,
    around the agent's own code, so the agent can't stop it."""
    if session is not None and session.pending:
        review = session.pending[0]
        if error is not review:
            if error is not None:
                raise review from error
            raise review


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
                if not pre_post:
                    _opts_out(self)  # an opt-out outside the framework is refused in production
                if pre_post:
                    payload, rebuild = _payload_of(args, kwargs)
                    if rebuild is None:
                        _no_payload(self)
                    else:
                        checked = self.governance.pre_process(payload, self._governance_context())
                        if inspect.isawaitable(checked):
                            checked = await checked
                        args, kwargs = rebuild(checked)
                session = _tool_gate_session(self, args, kwargs)
                gate_token = _ACTIVE_GATE.set(session) if session is not None else None
                try:
                    result = await fn(self, *args, **kwargs)
                except BaseException as exc:
                    _surface_review(session, exc)
                    raise
                finally:
                    if gate_token is not None:
                        _ACTIVE_GATE.reset(gate_token)
                _surface_review(session)
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
                if not pre_post:
                    _opts_out(self)  # an opt-out outside the framework is refused in production
                if pre_post:
                    payload, rebuild = _payload_of(args, kwargs)
                    if rebuild is None:
                        _no_payload(self)
                    else:
                        checked = _resolve_sync(self.governance.pre_process(payload, self._governance_context()))
                        args, kwargs = rebuild(checked)
                session = _tool_gate_session(self, args, kwargs)
                gate_token = _ACTIVE_GATE.set(session) if session is not None else None
                try:
                    result = fn(self, *args, **kwargs)
                except BaseException as exc:
                    _surface_review(session, exc)
                    raise
                finally:
                    if gate_token is not None:
                        _ACTIVE_GATE.reset(gate_token)
                _surface_review(session)
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
    ``_governs_own_execute = True`` and get the assertion only; from 1.22 only
    a framework agent ABB (``k9_aif_abb.k9_agents``) may set it (elsewhere it is refused in
    production), and a call whose payload the wrapper cannot find is refused
    in production instead of running unchecked.

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
        # Kafka ownership, enforced at run time (1.26): only Routers and Orchestrators publish.
        # An agent built with a message bus is refused; before 1.26 only K9-KAF-001 caught it.
        if message_bus is not None:
            raise TypeError(
                f"{type(self).__qualname__}: agents are built without a message bus. Only the "
                "Router and the Orchestrators publish to Kafka; an agent reports with "
                "notify_monitor() or raises RequiresHIL (k9-aif 1.26, K9-KAF-001)."
            )
        self.config = config or {}
        self.monitor = monitor
        self.message_bus = None  # always None for agents; kept for code that reads the attribute
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
    def notify_monitor(self, event: Dict[str, Any]) -> None:
        """Hand a structured event (``{"type": ..., ...}``) to this agent's monitor, when it has
        one, and log it.

        This never publishes to Kafka: an agent cannot hold a message bus (``__init__`` refuses one,
        1.26); only the Router and the Orchestrators publish. Replaced ``publish_event`` (1.24;
        removed in 2.0)."""
        if self.monitor:
            self.monitor.record_event(event)
        self.logger.info("[%s] Event: %s", self.layer, event)

    def publish_event(self, event: Dict[str, Any]) -> None:
        """Deprecated since 1.24: use :meth:`notify_monitor`. Kept as an alias of it (removal in 2.0), so
        applications and generated scaffolds that still call it keep working. It cannot publish to Kafka:
        from 1.26 an agent cannot hold a message bus."""
        _warn_publish_event_deprecated(self)
        self.notify_monitor(event)

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
