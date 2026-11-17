# CLAUDE.md — OpenAI Agents SDK Adapter (Package Level)

Framework conventions live in the root `CLAUDE.md`; this file covers what is specific to this
package. Diagrams: `docs/block_diagram.puml` (where the adapter sits), `docs/class_diagram.puml`.

## What this package is

An OOB orchestrator adapter (1.27.0) that runs OpenAI Agents SDK agents under K9-AIF governance.
Same three-part shape as `crewai/`, `langgraph/`, `claude_agent_sdk/`: facade
(`K9OpenAIAgentsAdapter`), orchestrator adapter (`OpenAIAgentsOrchestratorAdapter`), payload
mapper. The adapter is an orchestrator: the Router sends it an `event_type`; the SDK's Runner and
its agents take the place of Squad -> Agent on that path.

## Two ways to run several agents (1.28.0)

| | `K9OpenAIAgent` in a squad (recommended) | `OpenAIAgentsOrchestratorAdapter` handoffs |
|---|---|---|
| Who picks the next agent | The squad's `flow:` (the architecture) | The model, from `transfer_to_<agent>` tools |
| Same input, same path | Yes | Not guaranteed |
| Synthesis | The squad's `synthesis:` (`K9ContextSynthesizerAgent`) | None |
| Zero Trust | On the orchestrator that runs the squad | Also per agent turn (`openai_agent:<name>`) |
| Tools, model | Same `build_function_tool` guardrails, same `K9ModelProvider` | Same |

`K9OpenAIAgent` (`k9_openai_agent.py`): one OpenAI agent, built from its agent YAML, run as one governed
squad step through `Runner.run` with no handoffs (`handoffs:` in its YAML is refused). The application
adds one small subclass per agent (`class WeatherAgent(K9OpenAIAgent): pass`) so `AgentLoader` and
`BaseSquad` find it by class name; tools come in as `SquadLoader` `agent_kwargs={"capabilities": [...]}`.
The step prompt is the request (`prompt`/`query`/`question`/`text`/`input`) plus `squad_digest`, or each
earlier step's `output`. Tests: `tests/test_openai_agent_squad.py` (no handoff offered to the model, flow
order, earlier results read, digest used, governance at each step, `RequiresHIL` keeps its type).

## Conformance tier: action and inference governed

Stronger than the Claude adapter (action only), because the OpenAI SDK has a model seam
(`RunConfig.model_provider`). With `model_routing: k9` (default) `K9ModelProvider` asks the router
through `llm_route()` for every model the SDK needs; eligibility applies (`tool_calling` is
required for agents with tools or handoffs, since a handoff is a function call; `confidential` for a
confidential request) and fails closed. The
SDK makes the call through `OpenAIChatCompletionsModel`, so only OpenAI-compatible backends
(`ollama`, `openai`) are served; any other backend raises `ValueError`.

## Where each check runs (all verified by `tests/test_openai_agents_adapter.py`)

| Point | Mechanism | Test |
|---|---|---|
| Before the run | `apply_zero_trust`, then `apply_pre_governance` | `test_injected_request_never_reaches_the_model` |
| Each agent's turn | `RunHooks.on_agent_start` -> Zero Trust, action `openai_agent:<name>` | `test_zero_trust_is_applied_to_each_agent` |
| Each tool call | tool input guardrail -> `screen_tool_call`; refusal = `reject_content` | `test_refused_tool_call_does_not_run_the_tool` |
| Each tool result | tool output guardrail -> `screen_tool_result`; refusal = withheld notice | `test_poisoned_tool_result_is_withheld_from_the_model` |
| Each model reply | `RunHooks.on_llm_end` -> `apply_post_governance`; a block ends the run | `test_blocked_model_reply_ends_the_run` |
| Final output | `apply_post_governance` | `test_clean_run_checks_every_step` |

No separate per-agent input check: everything entering an agent's context was checked where it
entered (request, tool result, previous agent's reply). Re-screening the history would repeat
text, which `SemanticDriftCheck` flags (see `k9_security/CLAUDE.md`).

## Verified facts (openai-agents 0.24.0; re-verify after a bump)

- Tool guardrails run only for `FunctionTool`; hosted tools and handoffs never pass them (SDK docs,
  guardrails page). The adapter builds every tool from `ToolCapability`, so hosted tools can't be given.
- Agent-level SDK guardrails run only on the first agent's input and the last agent's output. The
  adapter does not use them; the hooks cover every agent.
- An exception raised in a `RunHooks` method propagates out of `Runner.run()` (reply-block test).
- The SDK re-raises a tool handler's exception wrapped in `UserError`. The adapter records the original
  in `_TOOL_ERRORS` and raises it, so `RequiresHIL` / `PermissionError` keep their type
  (`test_review_raised_inside_a_tool_keeps_its_type`). Without
  `set_function_tool_failure_error_function(tool, None)` the SDK would instead turn the error into text
  for the model.
- Tracing exports to OpenAI by default; the adapter sets `tracing_disabled=True` unless
  `openai_agents.export_traces: true`.
- `openai-agents` needs `openai>=3`; `crewai` (through `instructor`) needs `openai<3`. Separate
  environments; `openai-agents` is not in the `all` extra.

## Shield notes for solutions using this adapter

- `ToolArgumentCheck` reads tool arguments, not reply text: it belongs in **ingress** for tool calls
  (tool calls go through `pre_process`). On egress it sees nothing to check in a plain reply.
- `PIIBoundaryCheck` matches US ZIP codes and flags (doesn't block) by default. Leave
  `block_on_match` off for any solution whose input is a ZIP code.

## Invariants

1. Never accept a pre-built `Agent`, tool or `RunConfig` from a caller.
2. Every tool and handoff name in a spec is validated at construction (`ValueError`), never filtered.
3. The handoff group stays capped (`max_handoffs`); a known multi-step process is a K9 squad of `K9OpenAIAgent` steps (1.28.0).
4. `adapt_input` / `adapt_output` stay thin; the mapper normalizes once, at the facade.
5. Router access only through `llm_route()`; this package never imports `ModelRouterFactory`.

## Open

- Tool gate: the run executes in a gate session, so connector calls inside a handler are proposed
  to the dispatcher, and a review is raised with its type. Resuming the OpenAI run after approval
  is not built: the orchestrator's `resume_tool_call()` runs the stored call, the agent loop does not
  continue from where it stopped.
- `K9TraceProcessor` (SDK spans -> K9 trace events) is not built; the hooks emit K9 events for agent
  turns, handoffs, model replies and calls, and the tool guardrails for tool calls and results.
- Streaming (`Runner.run_streamed`) is not wrapped.
