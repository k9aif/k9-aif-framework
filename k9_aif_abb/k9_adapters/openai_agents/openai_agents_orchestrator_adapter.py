# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
OpenAIAgentsOrchestratorAdapter: OpenAI agents under K9-AIF governance (1.27.0).

Verified against openai-agents 0.24.0. Re-verify ``RunHooks``, tool guardrails, ``FunctionTool``
and ``set_function_tool_failure_error_function`` after a version bump.

WHERE IT SITS. The adapter is an orchestrator (``BaseOrchestrator`` + ``BaseAdapter``): the
Router sends it an ``event_type`` like any other orchestrator, and the SDK's Runner and its
agents take the place of Squad -> Agent on that path.

SOLE BROKER. The adapter builds every ``Agent`` itself from agent YAML specs (the K9-AIF agent
format: ``name``, ``description``, ``role``, ``goal``, ``instructions``, ``model``, plus
``tools``, ``handoffs`` and ``agent_tools``) and every tool from registered ``ToolCapability``
entries. It never accepts a pre-built ``Agent`` or tool. So:

- an agent can only call tools the adapter registered, and each carries K9 guardrails;
- hosted OpenAI tools (web search, file search, code interpreter, hosted MCP) can't be given
  to an agent at all: they run on OpenAI's servers, where no check of ours sees them;
- a tool or handoff name that isn't registered fails at construction (``ValueError``);
- the number of agents a run can hand off to is capped (``max_handoffs``, default 3).

TWO LLM-ORCHESTRATION PATTERNS (OpenAI's "A practical guide to building agents"):

- Decentralized, ``handoffs: [...]``: the model hands the conversation to another agent, which
  takes over and answers.
- Manager, ``agent_tools: [...]`` (1.33.0): the agent calls the named agents as tools
  (``Agent.as_tool``), gets each answer back, and writes the one reply itself. Each delegation is
  a tool call with the same K9 guardrails as any tool (Shield on what the manager sends and on what
  comes back); the specialist's own run gets the same hooks as the run around it (Zero Trust on its
  turn, Shield egress on its replies, trace events) and the same ``RunConfig`` (K9 Model Router).
  Names are validated at construction, each specialist needs a ``description`` (the model chooses
  from it), the graph may not loop, and the number of specialists is capped (``max_agent_tools``,
  default 5).

The third way, orchestrating via code, is a K9 squad of ``K9OpenAIAgent`` steps (1.28.0).

WHAT IS CHECKED, AND WHERE
1. Before the run: Zero Trust (``apply_zero_trust``) and Shield ingress
   (``apply_pre_governance``) on the request.
2. Every agent that takes a turn (``on_agent_start``): Zero Trust for the action
   ``openai_agent:<name>``, so a role policy can restrict which agents a principal may reach.
3. Every tool call: Shield screens the tool name and arguments (``screen_tool_call``) before the
   handler runs. A refusal becomes ``reject_content``: the model is told, the tool doesn't run.
4. Every tool result: Shield screens it (``screen_tool_result``) before the model reads it. A
   refusal replaces the result with a notice.
5. Every model reply (``on_llm_end``): Shield egress on the reply text, for every agent in the
   chain, not only the last. A block raises ``PermissionError`` and ends the run.
6. Every model call: with ``model_routing="k9"`` the K9 Model Router picks the model
   (``K9ModelProvider``); with ``"direct"`` the agent's ``model`` is passed to the SDK as is.
7. After the run: Shield egress on the final output, then ``publish_status``.

Everything that enters an agent's context passed a check where it entered: the request at
ingress, each tool result at the tool, each agent's reply at ``on_llm_end``. That is why
there is no separate per-agent input check: it would re-screen the same text, and repeated
text is exactly what ``SemanticDriftCheck`` flags (see k9_security/CLAUDE.md).

FAILURES PROPAGATE. Tool handler exceptions are not turned into model-visible text (the SDK's
default): ``set_function_tool_failure_error_function(tool, None)`` makes them raise, so the run
ends and the orchestrator above records it. ``PermissionError`` and ``RequiresHIL`` propagate.

TRACING. The SDK exports traces to OpenAI by default. The adapter turns that off
(``RunConfig.tracing_disabled=True``) unless ``openai_agents.export_traces: true`` is set; the
hooks report agents, handoffs, tools and model calls as K9-AIF trace events instead.

TOOL GATE. With ``security.tool_gate.enabled``, the run executes inside a gate session, so a
handler that calls an MCP tool through a ``BaseConnector`` is proposed to the dispatcher. A
review raised inside the run is raised again after it, even if the SDK swallowed it.
"""

from __future__ import annotations

import asyncio
import contextvars
import json
import re
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

import yaml
from agents import (
    Agent,
    FunctionTool,
    ModelSettings,
    RunConfig,
    RunHooks,
    Runner,
    ToolGuardrailFunctionOutput,
    tool_input_guardrail,
    tool_output_guardrail,
)
from agents.tool import set_function_tool_failure_error_function

from k9_aif_abb.k9_adapters.tool_capability import ToolCapability
from k9_aif_abb.k9_core.base_adapter import BaseAdapter
from k9_aif_abb.k9_core.governance.call_context import governed_call
from k9_aif_abb.k9_core.governance.pipeline import assert_governed
from k9_aif_abb.k9_core.orchestration.base_orchestrator import BaseOrchestrator
from k9_aif_abb.k9_core.tools.base_tool_dispatcher import BaseToolDispatcher, gate_enabled
from k9_aif_abb.k9_core.tools.tool_gate_context import GateSession, gate_session
from k9_aif_abb.k9_security.tool_result_guard import screen_tool_call, screen_tool_result
from k9_aif_abb.k9_utils.trace_events import emit_trace_event, trace_id_from, trace_scope

from .k9_model_provider import K9ModelProvider, run_closing_provider

# Exceptions raised by tool handlers during the current run. The SDK re-raises a handler's
# exception wrapped in its own UserError; the adapter raises the original instead, so a
# RequiresHIL (tool gate review) or PermissionError keeps its type for the orchestrator.
_TOOL_ERRORS: contextvars.ContextVar = contextvars.ContextVar("k9_openai_tool_errors", default=None)

# The hooks of the run in progress. An agent used as a tool is built once, with the adapter, but
# K9 hooks are built per run (they carry the caller's identity); the specialist's nested run gets
# _CurrentRunHooks, which forwards to these.
_RUN_HOOKS: contextvars.ContextVar = contextvars.ContextVar("k9_openai_run_hooks", default=None)

_IDENTITY_KEYS = ("principal_id", "roles", "tenant_id", "trust_zone", "request_id", "session_id",
                  "data_sensitivity", "_k9_identity")


def load_agent_specs(agents_dir: str | Path) -> Dict[str, Dict[str, Any]]:
    """Read agent YAML files (K9-AIF agent format) keyed by ``name``.

    ``AgentLoader`` indexes by ``class:``, which these agents don't have: an OpenAI agent is
    built by the adapter, not imported. Files without ``name`` are refused, not skipped.
    """
    specs: Dict[str, Dict[str, Any]] = {}
    for path in sorted(Path(agents_dir).glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        name = (data.get("name") or "").strip()
        if not name:
            raise ValueError(f"[OpenAIAgentsOrchestratorAdapter] agent YAML {path.name} has no 'name'")
        if name in specs:
            raise ValueError(f"[OpenAIAgentsOrchestratorAdapter] agent '{name}' is defined twice ({path.name})")
        specs[name] = data
    if not specs:
        raise ValueError(f"[OpenAIAgentsOrchestratorAdapter] no agent YAML in {agents_dir}")
    return specs


def _instructions(spec: Dict[str, Any]) -> str:
    parts: List[str] = []
    for key in ("role", "goal"):
        if spec.get(key):
            parts.append(str(spec[key]).strip())
    rules = spec.get("instructions")
    if isinstance(rules, list):
        parts.append("\n".join(f"- {r}" for r in rules))
    elif rules:
        parts.append(str(rules).strip())
    return "\n\n".join(parts)


def _model_settings(spec: Dict[str, Any]) -> ModelSettings:
    """``temperature`` / ``max_tokens`` from the agent YAML, as for framework agents."""
    kwargs = {k: spec[k] for k in ("temperature", "max_tokens") if spec.get(k) is not None}
    return ModelSettings(**kwargs)


def _json_schema(schema: Any) -> Dict[str, Any]:
    """A JSON Schema object, or the ``{"name": type}`` shorthand the Claude adapter accepts."""
    if isinstance(schema, dict) and schema.get("type") == "object":
        return schema
    names = {str: "string", int: "integer", float: "number", bool: "boolean"}
    props = {k: {"type": names.get(v, "string")} for k, v in (schema or {}).items()}
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def build_function_tool(cap: ToolCapability, governance: Callable[[], Any],
                        governance_context: Callable[[], Dict[str, Any]],
                        govern_results: Callable[[], bool], needs_approval: bool = False) -> FunctionTool:
    """A ``FunctionTool`` for one registered capability, with K9 guardrails on its call and its
    result. Shared by the orchestrator adapter and ``K9OpenAIAgent`` (1.28.0); the callables are
    read when the tool runs, so a governance object swapped after construction is the one used."""

    async def invoke(ctx: Any, args_json: str) -> str:
        args = json.loads(args_json or "{}")
        try:
            result = await cap.handler(args)
        except Exception as exc:
            _record_tool_error(exc)
            raise
        return result if isinstance(result, str) else json.dumps(result, default=str)

    call_check, result_check = _k9_tool_guardrails(cap.name, governance, governance_context, govern_results)
    tool = FunctionTool(
        name=cap.name,
        description=cap.description,
        params_json_schema=_json_schema(cap.input_schema),
        on_invoke_tool=invoke,
        strict_json_schema=False,
        tool_input_guardrails=[call_check],
        tool_output_guardrails=[result_check],
        needs_approval=needs_approval,       # 1.29.0: the run pauses for a person before this tool runs
    )
    return set_function_tool_failure_error_function(tool, None)   # handler errors raise


def agent_tool_name(agent_name: str) -> str:
    """The tool name a manager sees for a specialist: ``SpanishAgent`` -> ``spanish_agent``.
    (The SDK's own default, ``spanishagent``, is hard to read in a trace.)"""
    name = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", agent_name.strip())
    return re.sub(r"[^0-9a-zA-Z_]+", "_", name).strip("_").lower()


def _record_tool_error(exc: BaseException) -> None:
    errors = _TOOL_ERRORS.get()
    if errors is not None:
        errors.append(exc)


def _k9_tool_guardrails(tool_name: str, governance: Callable[[], Any],
                        governance_context: Callable[[], Dict[str, Any]], govern_results: Callable[[], bool]):
    """The K9 input and output guardrails for one tool: Shield on the call's arguments before it
    runs, and on its result before the model reads it. Shared by function tools and agents used
    as tools."""

    @tool_input_guardrail
    async def k9_tool_call_check(data):
        args = json.loads(data.context.tool_arguments or "{}")
        try:
            await screen_tool_call(governance(), tool_name, args, ctx={**governance_context(), "checkpoint": "tool_call"})
        except PermissionError as exc:
            return ToolGuardrailFunctionOutput.reject_content(
                f"Tool call refused by governance: {exc}", output_info={"refused": True})
        return ToolGuardrailFunctionOutput.allow()

    @tool_output_guardrail
    async def k9_tool_result_check(data):
        if not govern_results():
            return ToolGuardrailFunctionOutput.allow()
        try:
            await screen_tool_result(governance(), tool_name, data.output,
                                     ctx={**governance_context(), "checkpoint": "tool_result"})
        except PermissionError as exc:
            return ToolGuardrailFunctionOutput.reject_content(
                f"Tool result withheld by governance: {exc}. Do not guess its content.",
                output_info={"withheld": True})
        return ToolGuardrailFunctionOutput.allow()

    return k9_tool_call_check, k9_tool_result_check


async def run_capturing_tool_errors(run: Callable[[], Awaitable[Any]]) -> Any:
    """Await ``run()``; if it fails after a tool handler raised, raise the handler's own exception
    (the SDK wraps it in ``UserError``), so ``RequiresHIL`` / ``PermissionError`` keep their type."""
    errors: List[BaseException] = []
    token = _TOOL_ERRORS.set(errors)
    try:
        return await run()
    except Exception:
        if errors:                 # the handler's own exception, not the SDK's wrapper
            raise errors[0]
        raise
    finally:
        _TOOL_ERRORS.reset(token)


def _reply_text(response: Any) -> str:
    texts: List[str] = []
    for item in getattr(response, "output", None) or []:
        for part in getattr(item, "content", None) or []:
            text = getattr(part, "text", None)
            if text:
                texts.append(text)
    return "\n".join(texts)


class _K9RunHooks(RunHooks):
    """Zero Trust per agent, Shield egress per model reply, and K9 trace events."""

    def __init__(self, adapter: "OpenAIAgentsOrchestratorAdapter", identity: Dict[str, Any]):
        self.adapter = adapter
        self.identity = identity
        self.trace: List[Dict[str, Any]] = []

    def _event(self, **event: Any) -> None:
        self.trace.append(event)
        emit_trace_event({"agent": event.get("agent", self.adapter.adapter_name), **event})

    async def on_agent_start(self, context, agent) -> None:
        zt = self.adapter.apply_zero_trust({**self.identity, "action_type": f"openai_agent:{agent.name}"})
        self._event(type="OpenAIAgentStart", agent=agent.name, zero_trust=zt["decision"])
        if not zt["allowed"]:
            raise PermissionError(f"[OpenAIAgentsOrchestratorAdapter] Zero Trust denied agent "
                                  f"'{agent.name}': {zt.get('reason')}")

    async def on_handoff(self, context, from_agent, to_agent) -> None:
        self._event(type="OpenAIHandoff", agent=from_agent.name, to_agent=to_agent.name)

    async def on_llm_end(self, context, agent, response) -> None:
        text = _reply_text(response)
        if text:
            # A PermissionError here ends the run: a blocked reply never reaches the next step.
            # a reply in a group of agents may be what the next agent reads: a handoff point
            point = "handoff" if len(self.adapter._specs) > 1 else "reply"
            await self.adapter.apply_post_governance({"output": text},
                                                     {**self.adapter._governance_context(), "checkpoint": point})
        self._event(type="OpenAIModelReply", agent=agent.name, screened=bool(text))


class _CurrentRunHooks(RunHooks):
    """Given to each agent used as a tool: forwards to the K9 hooks of the run in progress, so the
    specialist's turns are checked like any other agent's. No run in progress means the agent is
    being run outside the adapter; that is refused, never run unchecked."""

    @staticmethod
    def _current() -> _K9RunHooks:
        hooks = _RUN_HOOKS.get()
        if hooks is None:
            raise PermissionError("[OpenAIAgentsOrchestratorAdapter] an agent used as a tool ran outside a "
                                  "governed adapter run")
        return hooks

    async def on_agent_start(self, context, agent) -> None:
        await self._current().on_agent_start(context, agent)

    async def on_handoff(self, context, from_agent, to_agent) -> None:
        await self._current().on_handoff(context, from_agent, to_agent)

    async def on_llm_end(self, context, agent, response) -> None:
        await self._current().on_llm_end(context, agent, response)


class OpenAIAgentsOrchestratorAdapter(BaseOrchestrator, BaseAdapter):
    """
    Parameters
    ----------
    capabilities:
        Every tool any agent may call. Nothing else becomes a tool.
    agents:
        Agent specs keyed by name (``load_agent_specs(dir)`` reads them from YAML).
    entry_agent:
        The agent a run starts with.
    model_routing:
        ``"k9"`` (default): the K9 Model Router picks each agent's model, its ``model`` field
        being a catalog alias. ``"direct"``: ``model`` is passed to the SDK unchanged.
    max_handoffs:
        Most agents a run can reach besides the entry agent (default 3).
    max_agent_tools:
        Most agents used as tools (``agent_tools:``) across the group (default 5).
    max_turns:
        Passed to ``Runner.run``.
    sensitivity, required_capabilities:
        Routing constraints for every model call in this adapter's runs.
    model_provider:
        ``model_routing="direct"`` only: the SDK ``ModelProvider`` that resolves each agent's
        ``model`` (default: the SDK's own, which calls OpenAI). Refused with ``"k9"``, where the
        K9 Model Router is the provider.
    """

    def __init__(
        self,
        capabilities: List[ToolCapability],
        agents: Dict[str, Dict[str, Any]],
        entry_agent: str,
        model_routing: str = "k9",
        max_handoffs: int = 3,
        max_agent_tools: int = 5,
        max_turns: int = 10,
        sensitivity: Optional[str] = None,
        required_capabilities: Optional[List[str]] = None,
        govern_tool_results: bool = True,
        model_provider: Any = None,
        name: Optional[str] = None,
        **base_orchestrator_kwargs: Any,
    ) -> None:
        BaseAdapter.__init__(self, adapter_name=name or "OpenAIAgentsOrchestratorAdapter")
        BaseOrchestrator.__init__(self, **base_orchestrator_kwargs)
        if model_routing not in ("k9", "direct"):
            raise ValueError(f"[OpenAIAgentsOrchestratorAdapter] model_routing must be 'k9' or 'direct', "
                             f"got {model_routing!r}")
        self.model_routing = model_routing
        if model_provider is not None and model_routing != "direct":
            raise ValueError("[OpenAIAgentsOrchestratorAdapter] model_provider= is for model_routing='direct'; "
                             "with 'k9' the K9 Model Router chooses every model")
        self._direct_provider = model_provider
        self.max_turns = max_turns
        self.sensitivity = sensitivity
        self.required_capabilities = list(required_capabilities or [])
        self.govern_tool_results = govern_tool_results
        self._capabilities: Dict[str, ToolCapability] = {c.name: c for c in capabilities}
        self._specs = dict(agents)
        self._entry_name = entry_agent
        self._validate(max_handoffs, max_agent_tools)
        self._agents = self._build_agents()

    # ── construction-time validation ─────────────────────────────────────

    def _validate(self, max_handoffs: int, max_agent_tools: int) -> None:
        if self._entry_name not in self._specs:
            raise ValueError(f"[OpenAIAgentsOrchestratorAdapter] entry agent '{self._entry_name}' has no spec. "
                             f"Known agents: {sorted(self._specs)}")
        for name, spec in self._specs.items():
            unknown_tools = [t for t in spec.get("tools") or [] if t not in self._capabilities]
            if unknown_tools:
                raise ValueError(
                    f"[OpenAIAgentsOrchestratorAdapter] agent '{name}' names tool(s) the adapter never "
                    f"registered: {unknown_tools}. Registered: {sorted(self._capabilities)}. An agent can only "
                    "be given registered capabilities; hosted OpenAI tools can't be given at all.")
            unknown_agents = [h for h in spec.get("handoffs") or [] if h not in self._specs]
            if unknown_agents:
                raise ValueError(f"[OpenAIAgentsOrchestratorAdapter] agent '{name}' hands off to unknown "
                                 f"agent(s): {unknown_agents}")
            self._validate_agent_tools(name, spec)
        self._validate_agent_tool_graph(max_agent_tools)
        reachable, frontier = set(), [self._entry_name]
        while frontier:
            for target in self._specs[frontier.pop()].get("handoffs") or []:
                if target != self._entry_name and target not in reachable:
                    reachable.add(target)
                    frontier.append(target)
        if len(reachable) > max_handoffs:
            raise ValueError(
                f"[OpenAIAgentsOrchestratorAdapter] a run can reach {len(reachable)} agents by handoff "
                f"({sorted(reachable)}), more than max_handoffs={max_handoffs}. A known multi-step process "
                "belongs in a K9 squad, where its flow is declared; keep handoff groups small.")

    def _validate_agent_tools(self, name: str, spec: Dict[str, Any]) -> None:
        targets = spec.get("agent_tools") or []
        if not isinstance(targets, list):
            raise ValueError(f"[OpenAIAgentsOrchestratorAdapter] agent '{name}': agent_tools must be a list "
                             f"of agent names, got {type(targets).__name__}")
        unknown = [t for t in targets if t not in self._specs]
        if unknown:
            raise ValueError(f"[OpenAIAgentsOrchestratorAdapter] agent '{name}' uses unknown agent(s) as tools: "
                             f"{unknown}. Known agents: {sorted(self._specs)}")
        if name in targets:
            raise ValueError(f"[OpenAIAgentsOrchestratorAdapter] agent '{name}' lists itself in agent_tools")
        clashes = [t for t in targets if agent_tool_name(t) in self._capabilities]
        if clashes:
            raise ValueError(f"[OpenAIAgentsOrchestratorAdapter] agent '{name}': agent(s) {clashes} would be tools "
                             "named like a registered capability; rename the agent or the capability")
        for target in targets:
            if not (self._specs[target].get("description") or "").strip():
                raise ValueError(
                    f"[OpenAIAgentsOrchestratorAdapter] agent '{target}' is used as a tool by '{name}' but has "
                    "no 'description'. The manager's model chooses specialists by their descriptions.")

    def _validate_agent_tool_graph(self, max_agent_tools: int) -> None:
        """No loop among agents used as tools (A asks B, B asks A), and at most
        ``max_agent_tools`` of them."""
        state: Dict[str, int] = {}          # 1 = on the current path, 2 = done

        def visit(name: str, path: List[str]) -> None:
            state[name] = 1
            for target in self._specs[name].get("agent_tools") or []:
                if state.get(target) == 1:        # path ends with name; target is on it
                    loop = " -> ".join(path[path.index(target):] + [target])
                    raise ValueError(f"[OpenAIAgentsOrchestratorAdapter] agents used as tools form a loop: "
                                     f"{loop}")
                if state.get(target) != 2:
                    visit(target, path + [target])
            state[name] = 2

        for name in self._specs:
            if state.get(name) is None:
                visit(name, [name])
        used = {t for spec in self._specs.values() for t in spec.get("agent_tools") or []}
        if len(used) > max_agent_tools:
            raise ValueError(
                f"[OpenAIAgentsOrchestratorAdapter] {len(used)} agents are used as tools ({sorted(used)}), "
                f"more than max_agent_tools={max_agent_tools}. Keep a manager's team small.")

    # ── building agents and tools (never accepted pre-built) ─────────────

    def _build_agents(self) -> Dict[str, Agent]:
        built: Dict[str, Agent] = {}
        for name, spec in self._specs.items():
            built[name] = Agent(
                name=name,
                handoff_description=(spec.get("description") or "").strip() or None,
                instructions=_instructions(spec),
                model=spec.get("model") or ("general" if self.model_routing == "k9" else None),
                tools=[self._function_tool(self._capabilities[t]) for t in spec.get("tools") or []],
                model_settings=_model_settings(spec),
            )
        for name, spec in self._specs.items():
            built[name].handoffs = [built[h] for h in spec.get("handoffs") or []]
            built[name].tools.extend(self._agent_tool(built[t]) for t in spec.get("agent_tools") or [])
        return built

    def _agent_tool(self, specialist: Agent) -> FunctionTool:
        """One specialist as a tool of its manager (``Agent.as_tool``), governed like any tool: K9
        guardrails on what the manager sends and on what comes back, the run's K9 hooks on the
        specialist's own turns, and errors that keep their type."""
        tool = specialist.as_tool(
            tool_name=agent_tool_name(specialist.name),
            tool_description=specialist.handoff_description,
            hooks=_CurrentRunHooks(),
            max_turns=self.max_turns,
            failure_error_function=None,                     # errors raise, never become model text
        )
        call_check, result_check = _k9_tool_guardrails(
            tool.name, lambda: self.governance, self._governance_context, lambda: self.govern_tool_results)
        tool.tool_input_guardrails = [call_check]
        tool.tool_output_guardrails = [result_check]
        run_specialist = tool.on_invoke_tool

        async def invoke(ctx: Any, args_json: str) -> Any:
            manager = getattr(getattr(ctx, "agent", None), "name", None)
            emit_trace_event({"type": "OpenAIAgentAsTool", "agent": manager or self.adapter_name,
                              "to_agent": specialist.name, "tool": tool.name})
            try:
                return await run_specialist(ctx, args_json)
            except Exception as exc:
                _record_tool_error(exc)
                raise

        tool.on_invoke_tool = invoke
        return tool

    def _function_tool(self, cap: ToolCapability) -> FunctionTool:
        return build_function_tool(cap, lambda: self.governance, self._governance_context,
                                   lambda: self.govern_tool_results)

    # ── BaseAdapter contract (thin; the mapper normalizes once, at the facade) ──

    def adapt_input(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return payload or {}

    def adapt_output(self, result: Any) -> Any:
        return result

    # ── BaseOrchestrator contract ─────────────────────────────────────────

    def execute_flow(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        assert_governed(self.governance, self.layer, self.logger)
        self.validate_payload(payload)
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self._execute_flow_governed(payload))
        raise RuntimeError("[OpenAIAgentsOrchestratorAdapter] execute_flow() was called inside a running event "
                           "loop. Use 'await adapter.execute_flow_async(payload)' there.")

    async def execute_flow_async(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        assert_governed(self.governance, self.layer, self.logger)
        self.validate_payload(payload)
        return await self._execute_flow_governed(payload)

    async def _execute_flow_governed(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        with governed_call(self), trace_scope(trace_id_from(payload)):
            sdk_input = self.adapt_input(payload)

            zt = self.apply_zero_trust(sdk_input)
            if not zt["allowed"]:
                raise PermissionError(f"[OpenAIAgentsOrchestratorAdapter] Zero Trust denied run: {zt.get('reason')}")

            governed = await self.apply_pre_governance(sdk_input, {**self._governance_context(), "checkpoint": "ingress"})
            emit_trace_event({"type": "OpenAIRunCheck", "agent": self.adapter_name, "gate": "ingress",
                              "allowed": True})
            prompt = (governed or sdk_input).get("prompt") or ""
            identity = {k: sdk_input[k] for k in _IDENTITY_KEYS if k in sdk_input}
            hooks = _K9RunHooks(self, identity)

            self.publish_status("OpenAIAgentsRunStarted", {"adapter": self.adapter_name,
                                                           "entry_agent": self._entry_name})
            hooks_token = _RUN_HOOKS.set(hooks)
            try:
                run_result = await self._run(prompt, hooks)
            finally:
                _RUN_HOOKS.reset(hooks_token)

            final = run_result.final_output
            await self.apply_post_governance({"output": final if isinstance(final, str) else repr(final)},
                                             {**self._governance_context(), "checkpoint": "egress"})
            emit_trace_event({"type": "OpenAIRunCheck", "agent": self.adapter_name, "gate": "egress",
                              "allowed": True})
            self.publish_status("OpenAIAgentsRunCompleted", {
                "adapter": self.adapter_name, "last_agent": getattr(run_result.last_agent, "name", None),
                "model_calls": len(run_result.raw_responses)})
            return self.adapt_output({"run_result": run_result, "trace": hooks.trace})

    def _run_config(self) -> RunConfig:
        export = bool(((self.config or {}).get("openai_agents") or {}).get("export_traces"))
        kwargs: Dict[str, Any] = {"tracing_disabled": not export, "workflow_name": self.adapter_name}
        if self.model_routing == "k9":
            tools_by_alias: Dict[str, bool] = {}
            for spec in self._specs.values():
                alias = spec.get("model") or "general"
                # a handoff, and an agent used as a tool, are function calls too: such an agent needs a
                # tool-calling model just like one with tools, or it writes the call out as text and
                # the run ends there
                calls = bool(spec.get("tools")) or bool(spec.get("handoffs")) or bool(spec.get("agent_tools"))
                tools_by_alias[alias] = tools_by_alias.get(alias, False) or calls
            kwargs["model_provider"] = K9ModelProvider(
                self.config, tools_by_alias=tools_by_alias, sensitivity=self.sensitivity,
                required_capabilities=self.required_capabilities, agent_name=self.adapter_name)
        elif self._direct_provider is not None:
            kwargs["model_provider"] = self._direct_provider
        return RunConfig(**kwargs)

    async def _run(self, prompt: str, hooks: _K9RunHooks):
        return await run_capturing_tool_errors(lambda: self._run_gated(prompt, hooks))

    async def _run_gated(self, prompt: str, hooks: _K9RunHooks):
        entry = self._agents[self._entry_name]
        if not gate_enabled(self.config):
            run_config = self._run_config()
            return await run_closing_provider(run_config, lambda: Runner.run(
                entry, prompt, run_config=run_config, hooks=hooks, max_turns=self.max_turns))
        session = GateSession(BaseToolDispatcher.from_config(self.config, governance=self.governance),
                              agent_id=self.adapter_name)
        with gate_session(session):
            run_config = self._run_config()
            result = await run_closing_provider(run_config, lambda: Runner.run(
                entry, prompt, run_config=run_config, hooks=hooks, max_turns=self.max_turns))
        if session.pending:            # a review the SDK swallowed is raised again
            raise session.pending[0]
        return result
