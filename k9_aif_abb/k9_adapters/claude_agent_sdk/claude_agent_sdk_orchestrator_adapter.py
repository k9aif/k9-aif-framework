# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
ClaudeAgentSDKOrchestratorAdapter — wraps a Claude Agent SDK session and
exposes it through K9-AIF orchestration contracts.

Verified against claude-agent-sdk 0.2.128. If a future SDK version changes
any of ``ClaudeAgentOptions``, ``AgentDefinition``, ``can_use_tool``, or the
``create_sdk_mcp_server``/``@tool`` signatures, re-verify against the
installed package before trusting this file's assumptions.

STRONG ENCAPSULATION — this adapter is the sole capability broker for the
SDK it wraps. Unlike CrewAIOrchestratorAdapter (which accepts a fully
pre-built external ``crew`` object and trusts whatever tools/agents were
already configured on it), this adapter never accepts a pre-built
``ClaudeAgentOptions``. It builds one, every time, from its own internal
registry:

1. Tool registration — the constructor accepts plain capability
   definitions (name, description, input_schema, handler). Each is wrapped
   with the SDK's own ``@tool`` decorator *inside* this adapter and served
   through exactly one ``create_sdk_mcp_server()`` this adapter owns. The
   SDK is never given a caller-supplied tool object directly, and nothing
   about this adapter lets a caller register a tool that bypasses that
   server.

2. can_use_tool — every tool call the SDK attempts is routed through
   ``self.apply_post_governance()`` (inherited from BaseOrchestrator,
   which resolves to whatever governance pipeline was configured — e.g.
   k9x_Shield's ShieldGovernance egress chain: SemanticDriftCheck,
   ToolArgumentCheck, ExecutionGuardCheck, ...). A PermissionError from
   governance becomes PermissionResultDeny. This is a real, structural
   gate — not a prompt instruction the model could talk its way past.
   Verified (not assumed) that subagent-originated tool calls hit this
   same callback: the SDK's internal control protocol (_internal/query.py)
   routes every ``can_use_tool`` control request -- top-level agent or any
   subagent -- through one handler, and ``ToolPermissionContext.agent_id``
   identifies which one issued it. That is the routing guarantee, and it
   is verified. A *separate* bypass exists for the top-level agent: a
   whole-tool entry in ``allowed_tools`` skips can_use_tool entirely
   (CanUseToolShadowedWarning) -- this is why ``_build_options()`` below
   deliberately never populates ``allowed_tools``. Whether
   ``AgentDefinition.tools`` has the same shadowing behavior for a
   subagent's own grants is NOT yet verified either way -- see CLAUDE.md
   "Verified facts" before trusting subagent containment at the same
   level as the now-confirmed top-level path.

3. Subagent spawning — if ``subagents`` is supplied, each subagent's tool
   list is validated against this adapter's own registered tool names at
   construction time. A subagent cannot reference a tool this adapter did
   not register; attempting to do so raises ValueError immediately rather
   than silently narrowing or silently ignoring the mistake. Subagents
   inherit confined authority — never fresh authority, enforced both
   declaratively (construction-time validation) and at runtime (point 2).

No SDK subagent is enabled by default. Pass ``subagents=`` explicitly, on
purpose, if a solution genuinely needs delegation.

Beyond tool-call egress, this adapter also applies:

- **Ingress governance** — the prompt passes through
  ``apply_pre_governance()`` (Shield's ingress chain: InputSizeCheck,
  PromptInjectionCheck, PIIBoundaryCheck, ...) before ``query()`` is ever
  called. A PermissionError here propagates to the caller, same
  convention as every other K9-AIF component -- it is not swallowed.
- **Zero Trust** — ``apply_zero_trust()`` (inherited, opt-in via
  ``enable_zero_trust``) is evaluated before the session starts; a denied
  decision raises PermissionError before any SDK call happens.
- **Final-output egress** — the assembled assistant output passes through
  ``apply_post_governance()`` a second time (OutputSanitizationCheck,
  PIIBoundaryCheck, ...) before being returned, catching anything in the
  finished response that individual tool-call checks wouldn't see.
- **Audit trail** — ``publish_status()`` (inherited from ``BaseOrchestrator``
  -- *not* ``publish_event()``, which is a ``BaseAgent``-only method;
  ``BaseRouter`` has neither) fires at session start and completion.

CONFORMANCE TIER — read this before assuming parity with a native K9-AIF
agent. This adapter provides full **action governance**: every tool call
and subagent spawn is gated, ingress and egress and zero-trust all apply,
and the audit trail is real. It does **not** provide **inference
governance** -- see the "Model routing" note below. That is a permanent,
structural property of the Claude Agent SDK, not a gap to be closed later.
Solutions that require inference to route through llm_invoke/K9ModelRouter
should use the direct-API path instead (a plain ``BaseLLM`` adapter calling
the Anthropic Messages API, the same relationship Pet Store Agentic's
DirectApiDiagnosisAgent has to SdkDiagnosisAgent) -- that path is fully
governed on both axes. This adapter exists for the different, narrower
case: solutions that specifically need the Claude Agent SDK's own
autonomous multi-turn tool-use loop, with its actions safely contained
even though its inference is not.

This adapter also wraps a Claude-only runtime -- unlike llm_invoke-routed
agents (including CrewAI agents behind K9XLiteLLMBridgeAdapter), which are
provider-agnostic by config (Ollama, OpenAI, Watsonx, ... swappable with
no code change), the Claude Agent SDK cannot be pointed at a different
model family at all. That is a property of the SDK, not a limitation of
this adapter, but it means adopting this adapter for a given capability is
also a permanent, non-config-reversible choice to make that capability
Claude-only.

DIVERGENCE FROM CrewAIOrchestratorAdapter (read before assuming parity):

CrewAI is crew/task-oriented — a Crew already coordinates multiple Agents
and Tasks; the adapter's job is just to bridge in and out of that.
The Claude Agent SDK is a single autonomous agent-loop (query() /
ClaudeSDKClient) with an *optional* subagent-spawning capability
(``ClaudeAgentOptions.agents``) that has no clean CrewAI analog — a Crew's
multi-agent structure is declared up front by the caller; SDK subagents
are delegated to *by the model, at runtime*, during the loop. That
difference is exactly why encapsulation has to be enforced here, in the
adapter, rather than trusted to whatever the caller assembled beforehand.
Forcing this into the same "accept a pre-built object and call
kickoff()/run()" shape as CrewAI would silently reopen the authority the
Pet Store Agentic project deliberately closed by never populating
``agents`` at all (see that project's DEVIATIONS.md #3) — so this file
does not attempt that parallel.

Model routing: the Claude Agent SDK does not go through K9ModelRouter /
llm_invoke, and there is no k9x_litellm_bridge_adapter equivalent for it.
CrewAI's ``Agent(llm=...)`` is an injectable seam — any object implementing
``BaseLLM.call()`` can be substituted, which is exactly what
K9XLiteLLMBridgeAdapter exploits. The Claude Agent SDK has no such seam:
model selection is a plain string (``ClaudeAgentOptions.model``) consumed
by the SDK's own harness, which owns its own inference loop end to end
(authenticating directly, via CLI credentials or ANTHROPIC_API_KEY). There
is nothing for a bridge to intercept. Duplicating the litellm bridge here
would be fabricating a seam that does not exist — so this package does not
include one. If a future SDK version exposes a pluggable model client,
re-verify before revisiting this.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional

from claude_agent_sdk import (
    AgentDefinition,
    ClaudeAgentOptions,
    PermissionResultAllow,
    PermissionResultDeny,
    ToolPermissionContext,
    create_sdk_mcp_server,
    query,
    tool as sdk_tool,
)

from k9_aif_abb.k9_core.base_adapter import BaseAdapter
from k9_aif_abb.k9_core.orchestration.base_orchestrator import BaseOrchestrator

_MCP_SERVER_NAME = "k9x_adapter_tools"


@dataclass(frozen=True)
class ToolCapability:
    """One capability this adapter is willing to broker to the SDK.

    ``handler`` is an async callable matching the SDK's own tool-handler
    contract: ``async def handler(args: dict) -> dict``. It is wrapped
    with the SDK's ``@tool`` decorator inside ``_build_mcp_server`` — the
    caller never touches the SDK's tool machinery directly.
    """

    name: str
    description: str
    input_schema: Any
    handler: Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]


class ClaudeAgentSDKOrchestratorAdapter(BaseOrchestrator, BaseAdapter):
    """
    Adapter that wraps a Claude Agent SDK session and exposes it through
    K9-AIF orchestration contracts.

    Parameters
    ----------
    capabilities:
        The complete, closed set of tools the SDK session may ever call.
        This adapter is the only thing that turns these into SDK tools —
        there is no path for the SDK to acquire a tool this list didn't
        name.
    subagents:
        Optional. Maps subagent name -> a plain dict of AgentDefinition
        fields (description, prompt, tools, model, ...). Every entry in
        each subagent's ``tools`` list must already appear in
        ``capabilities`` — validated eagerly, at construction, not at
        call time.
    system_prompt, model, max_turns, permission_mode:
        Passed straight through to ClaudeAgentOptions. None of these
        affect the encapsulation guarantees above.
    name:
        Adapter name for BaseAdapter bookkeeping.
    """

    def __init__(
        self,
        capabilities: List[ToolCapability],
        subagents: Optional[Dict[str, Dict[str, Any]]] = None,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        max_turns: Optional[int] = None,
        permission_mode: Optional[str] = None,
        name: Optional[str] = None,
        **base_orchestrator_kwargs: Any,
    ) -> None:
        BaseAdapter.__init__(self, adapter_name=name or "ClaudeAgentSDKOrchestratorAdapter")
        BaseOrchestrator.__init__(self, **base_orchestrator_kwargs)

        self._capabilities: Dict[str, ToolCapability] = {c.name: c for c in capabilities}
        self._registered_tool_names = frozenset(self._capabilities)
        self._agent_definitions = self._build_agent_definitions(subagents or {})

        self._system_prompt = system_prompt
        self._model = model
        self._max_turns = max_turns
        self._permission_mode = permission_mode

        self._mcp_server = self._build_mcp_server()

    # ── construction-time validation ─────────────────────────────────────

    def _build_agent_definitions(
        self, subagents: Dict[str, Dict[str, Any]]
    ) -> Dict[str, AgentDefinition]:
        definitions: Dict[str, AgentDefinition] = {}
        for sub_name, spec in subagents.items():
            requested_tools = list(spec.get("tools") or [])
            unregistered = [t for t in requested_tools if t not in self._capabilities]
            if unregistered:
                raise ValueError(
                    f"[ClaudeAgentSDKOrchestratorAdapter] Subagent '{sub_name}' "
                    f"requests tool(s) this adapter never registered: {unregistered}. "
                    f"Registered capabilities: {sorted(self._capabilities)}. "
                    "A subagent may only be granted a subset of the adapter's own "
                    "capabilities -- never additional authority."
                )
            definitions[sub_name] = AgentDefinition(
                description=spec.get("description", ""),
                prompt=spec.get("prompt", ""),
                tools=requested_tools or None,
                model=spec.get("model"),
                maxTurns=spec.get("maxTurns"),
            )
            self.logger.info(
                "[ClaudeAgentSDKOrchestratorAdapter] subagent '%s' confined to tools=%s",
                sub_name, requested_tools,
            )
        return definitions

    def _build_mcp_server(self):
        wrapped = []
        for cap in self._capabilities.values():
            wrapped.append(
                sdk_tool(cap.name, cap.description, cap.input_schema)(cap.handler)
            )
        return create_sdk_mcp_server(name=_MCP_SERVER_NAME, tools=wrapped)

    # ── the egress gate ───────────────────────────────────────────────────

    async def _can_use_tool(
        self,
        tool_name: str,
        tool_input: Dict[str, Any],
        context: ToolPermissionContext,
    ) -> "PermissionResultAllow | PermissionResultDeny":
        """
        Every tool call the SDK attempts arrives here before it executes.
        Routed through BaseOrchestrator.apply_post_governance() -- the
        same egress-gate contract every other K9-AIF component uses
        (k9x_Shield's ShieldGovernance, when configured, runs
        ToolArgumentCheck / ExecutionGuardCheck / ... here). A
        PermissionError from governance becomes a structural deny, not an
        exception the SDK has to interpret.
        """
        payload = {"tool_name": tool_name, "tool_input": tool_input}
        try:
            await self.apply_post_governance(payload)
        except PermissionError as exc:
            self.logger.warning(
                "[ClaudeAgentSDKOrchestratorAdapter] egress DENIED tool=%s: %s",
                tool_name, exc,
            )
            return PermissionResultDeny(behavior="deny", message=str(exc), interrupt=False)

        return PermissionResultAllow(behavior="allow", updated_input=None, updated_permissions=None)

    # ── options construction (never accepts a pre-built options object) ─

    def _build_options(self) -> ClaudeAgentOptions:
        # NOTE: allowed_tools deliberately does NOT list these tool names.
        # A bare "mcp__server__tool" entry (no "(...)" specifier) is a
        # *whole-tool* allow rule -- the SDK auto-approves it before
        # can_use_tool is ever consulted (CanUseToolShadowedWarning, verified
        # live: the callback silently never fired). mcp_servers alone is what
        # makes the tool exist/callable; leaving allowed_tools empty is what
        # makes every call actually fall through to can_use_tool instead of
        # being pre-approved. Do not "fix" the missing-looking allowed_tools
        # entry without re-reading this note.
        return ClaudeAgentOptions(
            mcp_servers={_MCP_SERVER_NAME: self._mcp_server},
            can_use_tool=self._can_use_tool,
            agents=self._agent_definitions or None,
            system_prompt=self._system_prompt,
            model=self._model,
            max_turns=self._max_turns,
            permission_mode=self._permission_mode,
        )

    # ── BaseAdapter contract ──────────────────────────────────────────────

    def adapt_input(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        payload = payload or {}
        prompt = (
            payload.get("prompt")
            or payload.get("message")
            or payload.get("input")
            or payload.get("query")
            or ""
        )
        return {"prompt": prompt, "raw_payload": payload}

    def adapt_output(self, result: Any) -> Dict[str, Any]:
        """
        Deliberately a thin pass-through -- ``result`` is the raw SDK
        message list. Full normalization into the {"status", "result",
        "output_text"} envelope is ClaudeAgentSDKPayloadMapper's job,
        called exactly once at the facade layer (K9ClaudeAgentSDKAdapter).
        Duplicating that normalization here too, the way
        CrewAIOrchestratorAdapter.adapt_output() duplicates
        CrewAIPayloadMapper.from_crewai_output(), double-wraps the result
        on the second pass and loses output_text -- not repeated here.
        """
        return {"messages": result}

    # ── BaseOrchestrator contract ─────────────────────────────────────────

    def execute_flow(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.validate_payload(payload)

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            messages = asyncio.run(self._execute_flow_governed(payload))
        else:
            raise RuntimeError(
                "[ClaudeAgentSDKOrchestratorAdapter] execute_flow() was called from "
                "inside a running event loop. Use 'await adapter.execute_flow_async(payload)' "
                "instead of the synchronous entrypoint in async contexts."
            )

        return self.adapt_output(messages)

    async def execute_flow_async(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Async twin of execute_flow(), for callers already inside an event
        loop (e.g. a FastAPI handler) -- avoids the asyncio.run() footgun
        documented across this framework's other async/sync bridges."""
        self.validate_payload(payload)
        messages = await self._execute_flow_governed(payload)
        return self.adapt_output(messages)

    async def _execute_flow_governed(self, payload: Dict[str, Any]) -> List[Any]:
        """
        The full governed path: zero-trust -> ingress -> query() -> final
        egress -> audit. Both execute_flow() and execute_flow_async() call
        this so the two entrypoints can't drift into different governance
        behavior.
        """
        sdk_input = self.adapt_input(payload)

        zt_result = self.apply_zero_trust(sdk_input)
        if not zt_result["allowed"]:
            raise PermissionError(
                f"[ClaudeAgentSDKOrchestratorAdapter] Zero Trust denied session: "
                f"{zt_result.get('reason')}"
            )

        governed_input = await self.apply_pre_governance(sdk_input)

        self.publish_status("ClaudeAgentSDKSessionStarted", {"adapter": self.adapter_name})

        messages = await self._run_query(governed_input["prompt"])

        output_text = self._extract_final_text(messages)
        await self.apply_post_governance({"output_text": output_text})

        self.publish_status(
            "ClaudeAgentSDKSessionCompleted",
            {"adapter": self.adapter_name, "message_count": len(messages)},
        )

        return messages

    @staticmethod
    def _extract_final_text(messages: List[Any]) -> str:
        """Last assistant TextBlock text across the session -- used only for
        the final-output egress pass, not returned to the caller directly
        (ClaudeAgentSDKPayloadMapper.from_sdk_output() does that, once)."""
        output_text = ""
        for msg in messages:
            if type(msg).__name__ == "AssistantMessage":
                for block in getattr(msg, "content", []) or []:
                    text = getattr(block, "text", None)
                    if text:
                        output_text = text
        return output_text

    async def _run_query(self, prompt: str) -> List[Any]:
        """
        query() requires prompt as an AsyncIterable[dict] whenever
        can_use_tool is set (_internal/client.py raises ValueError on a
        plain str otherwise) -- and this adapter always sets can_use_tool,
        so this is not optional here. The single-message shape below is
        exactly what the SDK's own string-prompt path builds internally
        (_internal/client.py's isinstance(prompt, str) branch) -- verified
        by reading that code, not guessed.
        """
        options = self._build_options()

        async def _single_turn(p: str):
            yield {
                "type": "user",
                "session_id": "",
                "message": {"role": "user", "content": p},
                "parent_tool_use_id": None,
            }

        messages: List[Any] = []
        async for message in query(prompt=_single_turn(prompt), options=options):
            messages.append(message)
        return messages
