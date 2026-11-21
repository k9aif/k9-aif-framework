# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
K9OpenAIAgent: one OpenAI agent as one step of a K9-AIF squad (1.28.0).

THE SQUAD DECIDES, NOT THE MODEL. With handoffs (``OpenAIAgentsOrchestratorAdapter``) the model
picks the next agent. Here each OpenAI agent is an individual, runnable K9-AIF agent, and the
squad runs them in the order its YAML ``flow:`` sets, with its ``synthesis:`` setting, exactly as
it runs any other agents. The OpenAI Agents SDK runs one agent's turn; it never chooses what runs
next. The SDK's own guide calls this "orchestrating via code".

HOW AN APPLICATION USES IT. One small class per agent, so the squad and ``AgentLoader`` find it by
class name like every other agent::

    # agents/src/weather_agent.py
    from k9_aif_abb.k9_adapters.openai_agents import K9OpenAIAgent
    class WeatherAgent(K9OpenAIAgent):
        pass

    # agents/yaml/weather_agent.yaml
    class: WeatherAgent
    module: myapp.agents.src.weather_agent
    name: WeatherAgent
    role: You report the current weather.
    instructions: [Use the tools; never guess a temperature]
    model: tools                # a K9 model catalog alias
    tools: [current_weather]    # registered ToolCapability names

    # squads.yaml
    squads:
      weather_desk:
        agents: [FrontDeskAgent, WeatherAgent, AttireAdvisorAgent]
        flow:
          - {agent: FrontDeskAgent}
          - {agent: WeatherAgent}
          - {agent: AttireAdvisorAgent}
        synthesis: auto

The tools come from the squad loader: ``SquadLoader.from_agents(agents_dir, config,
agent_kwargs={"capabilities": CAPABILITIES})``.

WHAT IS CHECKED. Governance by construction (``BaseAgent``): Shield on the step's input and on its
output. Every tool call and tool result: the same K9 guardrails as the orchestrator adapter
(``build_function_tool``). Every model call: the K9 Model Router (``model_routing="k9"``, default).
Zero Trust stays where it lives in K9-AIF, on the orchestrator that runs the squad.

WHAT THE AGENT READS. The request text (``prompt``, ``query``, ``question``, ``text`` or ``input``,
the first one present), then what earlier steps produced: the squad's digest
(``squad_digest``) when synthesis made one, otherwise each earlier step's ``output``. A step's
reply is returned as ``{"output": text, ...}``, so the next step and the synthesizer read it.
"""

from __future__ import annotations

import contextvars
import json
from typing import Any, Dict, List, Optional

from agents import Agent, RunConfig, Runner

from k9_aif_abb.k9_adapters.tool_capability import ToolCapability
from k9_aif_abb.k9_core.agent.base_agent import BaseAgent
from k9_aif_abb.k9_core.orchestration.base_orchestrator import _run_coro_sync

from .k9_model_provider import K9ModelProvider, run_closing_provider
from .openai_hil_adapter import OpenAIHILAdapter
from .openai_agents_orchestrator_adapter import (
    _instructions,
    _model_settings,
    build_function_tool,
    run_capturing_tool_errors,
)

_REQUEST_KEYS = ("prompt", "query", "question", "text", "input")
_TYPES = {"string": str, "str": str, "number": float, "float": float, "integer": int, "int": int,
          "boolean": bool, "bool": bool}
# The step's payload while its run is in progress: read by conditional approval (needs_approval_when).
_STEP_PAYLOAD: contextvars.ContextVar = contextvars.ContextVar("k9_openai_step_payload", default=None)
_NOT_UPSTREAM = {"squad_id", "squad_digest", "squad_digest_keys"}


def step_prompt(payload: Dict[str, Any]) -> str:
    """The request, then what earlier squad steps produced (their digest, or each ``output``)."""
    request = next((str(payload[k]) for k in _REQUEST_KEYS if payload.get(k)), "")
    earlier: List[str] = []
    if payload.get("squad_digest"):
        earlier.append(str(payload["squad_digest"]))
    else:
        for key, value in payload.items():
            if key in _NOT_UPSTREAM or key in _REQUEST_KEYS:
                continue
            if isinstance(value, dict) and value.get("output"):
                earlier.append(f"{key}: {value['output']}")
    if not earlier:
        return request
    return f"{request}\n\nWhat earlier steps found:\n" + "\n".join(f"- {e}" for e in earlier)


class K9OpenAIAgent(BaseAgent):
    """One OpenAI agent, built from its agent YAML, run as one governed squad step.

    Parameters
    ----------
    capabilities:
        Every tool an agent of this application may call (``ToolCapability``). The agent gets the
        ones its YAML lists under ``tools``; a name not registered is refused at construction.
    model_routing:
        ``"k9"`` (default): the K9 Model Router picks the model, the YAML ``model`` being a catalog
        alias. ``"direct"``: ``model`` goes to the SDK unchanged (with ``model_provider``).
    max_turns:
        Most model turns for this step's run (tool calls included), passed to ``Runner.run``.
    hil_adapter:
        (1.29.0) Maps the SDK's approval pause to K9X HIL and the decision back. Default: an
        ``OpenAIHILAdapter`` with the YAML's ``hil_queue`` / ``hil_priority``, storing paused runs per the
        config (PostgreSQL when ``postgres.enabled``, else SQLite). Tools named in the YAML's
        ``needs_approval`` pause the run for a person.
    """

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        monitor: Any = None,
        governance: Any = None,
        capabilities: Optional[List[ToolCapability]] = None,
        model_routing: str = "k9",
        max_turns: int = 10,
        model_provider: Any = None,
        govern_tool_results: bool = True,
        hil_adapter: Any = None,
    ) -> None:
        super().__init__(config=config, monitor=monitor, governance=governance)
        cls = type(self).__name__
        if model_routing not in ("k9", "direct"):
            raise ValueError(f"[{cls}] model_routing must be 'k9' or 'direct', got {model_routing!r}")
        if model_provider is not None and model_routing != "direct":
            raise ValueError(f"[{cls}] model_provider= is for model_routing='direct'; "
                             "with 'k9' the K9 Model Router chooses the model")
        if self.config.get("handoffs"):
            raise ValueError(
                f"[{cls}] a squad step has no handoffs: the squad's flow sets which agent runs next. "
                "Remove 'handoffs' from its YAML, or run the group with OpenAIAgentsOrchestratorAdapter.")
        if self.config.get("agent_tools"):
            raise ValueError(
                f"[{cls}] a squad step has no agent_tools: the squad's flow sets which agent runs next. "
                "Remove 'agent_tools' from its YAML, or run the manager with OpenAIAgentsOrchestratorAdapter.")
        registered = {c.name: c for c in capabilities or []}
        wanted = list(self.config.get("tools") or [])
        unknown = [t for t in wanted if t not in registered]
        if unknown:
            raise ValueError(
                f"[{cls}] names tool(s) never registered: {unknown}. Registered: {sorted(registered)}. "
                "Pass them as SquadLoader agent_kwargs={'capabilities': [...]}; hosted OpenAI tools "
                "can't be given at all.")
        self.model_routing = model_routing
        self.max_turns = max_turns
        self.govern_tool_results = govern_tool_results
        self._direct_provider = model_provider
        approvals = list(self.config.get("needs_approval") or [])
        conditional = dict(self.config.get("needs_approval_when") or {})
        not_given = [t for t in [*approvals, *conditional] if t not in wanted]
        if not_given:
            raise ValueError(f"[{cls}] needs_approval names tool(s) this agent isn't given: {not_given}. "
                             f"Its tools: {wanted}")
        self.agent_name = (self.config.get("name") or cls).strip()
        self.hil = hil_adapter or OpenAIHILAdapter(config=self.config, queue=self.config.get("hil_queue"),
                                                   priority=self.config.get("hil_priority", "high"))
        self._alias = self.config.get("model") or ("general" if model_routing == "k9" else None)
        self._agent = Agent(
            name=self.agent_name,
            instructions=_instructions(self.config),
            model=self._alias,
            tools=[build_function_tool(registered[t], lambda: self.governance, self._governance_context,
                                       lambda: self.govern_tool_results,
                                       needs_approval=_approval_policy(t in approvals, conditional.get(t)))
                   for t in wanted],
            model_settings=_model_settings(self.config),
            output_type=_output_type(self.agent_name, self.config.get("structured_output")),
        )

    def _governance_context(self) -> Dict[str, Any]:
        return {"layer": self.layer, "component": self.agent_name, "component_type": "agent"}

    def _run_config(self) -> RunConfig:
        export = bool(((self.config or {}).get("openai_agents") or {}).get("export_traces"))
        kwargs: Dict[str, Any] = {"tracing_disabled": not export, "workflow_name": self.agent_name}
        if self.model_routing == "k9":
            kwargs["model_provider"] = K9ModelProvider(
                self.config, tools_by_alias={self._alias: bool(self._agent.tools)},
                agent_name=self.agent_name)
        elif self._direct_provider is not None:
            kwargs["model_provider"] = self._direct_provider
        return RunConfig(**kwargs)

    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        payload = payload or {}
        token = _STEP_PAYLOAD.set(payload)
        try:
            return self._execute(payload)
        finally:
            _STEP_PAYLOAD.reset(token)

    def _execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        saved = self.hil.saved_for(payload, self.agent_name)
        if saved is not None:        # resuming a paused run after the person decided in K9X HIL
            decision = self.hil.adapt_input(payload)["decision"]
            result = _run_coro_sync(run_capturing_tool_errors(lambda: self._resume(saved, decision)))
            prompt = ""
        else:
            prompt = step_prompt(payload)
            if not prompt:
                raise ValueError(f"[{self.agent_name}] no request text in the step's input "
                                 f"(looked for {', '.join(_REQUEST_KEYS)})")
            result = _run_coro_sync(run_capturing_tool_errors(
                lambda: self._run(prompt)))
        if saved is not None:
            self.hil.finished(saved)
        if result.interruptions:     # a tool marked needs_approval wants to run: pause for a person
            raise self.hil.pause(result, agent=self.agent_name, request=prompt)
        final = result.final_output
        if hasattr(final, "model_dump"):                  # structured output: a typed result, sent on as JSON
            final = final.model_dump()
        text = final if isinstance(final, str) else json.dumps(final, default=str)
        return {"output": text, "agent": self.agent_name, "model_calls": len(result.raw_responses)}

    async def _resume(self, saved: Dict[str, Any], decision: Any):
        """Restore the paused run with the person's decision applied, and continue it where it stopped."""
        state = await self.hil.restore(self._agent, saved, decision)
        return await self._run(state)

    async def _run(self, run_input: Any):
        run_config = self._run_config()
        return await run_closing_provider(run_config, lambda: Runner.run(
            self._agent, run_input, run_config=run_config, max_turns=self.max_turns))


def _approval_policy(always: bool, when: Any):
    """``needs_approval`` for one tool: True (always), False, or (1.29.0) a policy that asks the step's payload,
    with the squad's ``when:`` syntax, e.g. ``{key: rules_check.output.decision, eq: needs_approval}``."""
    if always or when is None:
        return bool(always)
    from k9_aif_abb.k9_squad.base_squad import _eval_when

    async def policy(_ctx: Any, _params: Any, _call_id: str) -> bool:
        return bool(_eval_when(when, _parsed(_STEP_PAYLOAD.get() or {})))
    return policy


def _parsed(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Earlier steps' outputs may be JSON text (structured output); parse them so a condition can reach inside."""
    out: Dict[str, Any] = {}
    for key, value in payload.items():
        if isinstance(value, dict) and isinstance(value.get("output"), str):
            try:
                value = {**value, "output": json.loads(value["output"])}
            except ValueError:
                pass
        out[key] = value
    return out


def _output_type(agent: str, schema: Any):
    """A pydantic model from ``structured_output: {field: type}`` (string, number, integer, boolean); None = text."""
    if not schema:
        return None
    from pydantic import create_model
    fields = {}
    for name, kind in dict(schema).items():
        py = _TYPES.get(str(kind).lower())
        if py is None:
            raise ValueError(f"[{agent}] structured_output field {name!r} has unknown type {kind!r}; "
                             f"use one of {sorted(_TYPES)}")
        fields[name] = (py, ...)
    return create_model(f"{agent}Output", **fields)

