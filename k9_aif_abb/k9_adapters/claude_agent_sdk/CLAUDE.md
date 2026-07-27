# CLAUDE.md — Claude Agent SDK Adapter (Package Level)

Framework-level conventions live in the K9-AIF root `CLAUDE.md`. This file covers only what is specific to this adapter package. Where both apply, framework conventions govern unless contradicted here explicitly.

Diagrams: `docs/block_diagram.puml` (simple view), `docs/context_diagram.puml` (full governance flow), `docs/class_diagram.puml` (class relationships).

---

## What this package is

An OOB adapter that lets a K9-AIF solution use the Claude Agent SDK's autonomous multi-turn tool-use loop, following the same `k9_adapters/<framework>/` shape as `k9_adapters/crewai/`. It is **not** a drop-in replacement for a native K9-AIF agent, and it does not claim to be one — see the conformance tier below before using it.

---

## The one decision that governs everything else in this package

**Conformance tier: action-governed, not fully-governed. This was a deliberate decision, not an oversight, made after exhausting every alternative.**

- **Action governance — full.** Ingress (`apply_pre_governance`), every tool call including subagent-originated ones (`can_use_tool` → `apply_post_governance`), final-output egress, Zero Trust, and audit trail (`publish_event`) all genuinely apply. Verified from the SDK's own source, not assumed — see "Verified facts" below.
- **Inference governance — structurally impossible, not merely unimplemented.** The Claude Agent SDK's own model calls cannot be routed through `llm_invoke`/`K9ModelRouter`. There is no seam: no injectable client field on `ClaudeAgentOptions`, no base-URL override, `Transport` is raw process I/O, and Anthropic's own docs state this kind of redirection isn't permitted for third-party integrations. **Do not attempt to build a `k9x_litellm_bridge_adapter` equivalent for this package.** It would fabricate a hook that doesn't actually intercept anything.
- **Provider-agnosticism — does not apply to this adapter, permanently.** Unlike `llm_invoke`-routed agents (native, or CrewAI via `K9XLiteLLMBridgeAdapter`), this adapter's wrapped runtime is Claude-only by construction. Bedrock/Vertex/Azure Foundry are still Claude, just different hosting.

If a solution needs Claude access with full governance on both axes (inference included), the correct answer is **not** this package — it's a direct-API `BaseLLM` adapter calling the Messages API through `llm_invoke`, the same relationship Pet Store Agentic's `DirectApiDiagnosisAgent` has to `SdkDiagnosisAgent`. That path costs you Claude's autonomous tool-use loop (you write the loop yourself) in exchange for full governance. This package exists for the opposite tradeoff: Claude's own loop, with its actions safely contained even though its thinking isn't.

Do not blur this distinction in docs, comments, or future extensions of this package. State it, don't hide it.

---

## Verified facts (claude-agent-sdk 0.2.128 — re-verify if the pinned version changes)

- `can_use_tool` is the deny mechanism this adapter uses. `PreToolUseHookSpecificOutput.permissionDecision: Literal['allow','deny','ask','defer']` proves `hooks["PreToolUse"]` can *also* block — both are real, valid mechanisms — but `can_use_tool` remains the better choice: cleaner dataclass-typed I/O (`PermissionResultAllow`/`PermissionResultDeny`) versus raw `TypedDict` manipulation, and it's a single unambiguous chokepoint per call rather than a list of matched hooks whose precedence would need reasoning about.
- **Subagent tool calls are not a separate, bypassable path.** `_internal/query.py`'s `_handle_control_request()` routes every `subtype == "can_use_tool"` control request — top-level agent or any subagent — through the identical `self.can_use_tool` callback. `ToolPermissionContext.agent_id` (populated from the control request) identifies which one issued it; nothing about the routing itself differs. This is what makes the ASI10 rogue-subagent containment claim real rather than declarative-only.
- **No inference-interception seam exists**, confirmed four independent ways: (1) no callable/client field among `ClaudeAgentOptions`'s ~40 fields — `model`/`fallback_model` are plain strings; (2) `Transport` (`_internal/transport.py`) is an internal, unstable API for raw process/network I/O with the CLI, not model invocation — confirmed by reading its actual abstract methods (`connect`, `write`, `read_messages`, `close`); (3) no `BASE_URL`/`ANTHROPIC_`-prefixed override logic anywhere in the installed package's own source; (4) Anthropic's official docs (`code.claude.com/docs/en/agent-sdk/overview`) list only Anthropic-sanctioned hosts (Bedrock, Vertex, Azure Foundry) as alternatives, all still Claude, and state third-party redirection of this kind isn't permitted.
- `AgentDefinition.tools: list[str] | None` — a subagent's tool list is independent of the top-level `ClaudeAgentOptions.allowed_tools`. This is exactly why construction-time validation (every subagent tool name must already be in `_capabilities`) is necessary — nothing in the SDK itself prevents a caller from handing a subagent a tool name the adapter never registered.
- Qualified tool name for `allowed_tools` is `mcp__<server_name>__<tool_name>` — confirmed working (not just assumed) via `ClaudeAgentSDKOrchestratorAdapter._build_options()` construction test.

---

## Package invariants

Do not violate these without asking first.

1. **The adapter never accepts a pre-built `ClaudeAgentOptions`.** It constructs one, every call, from its own `_capabilities` registry. Accepting a pre-built options object (the way `CrewAIOrchestratorAdapter` accepts a pre-built `crew`) would mean trusting whatever tools/agents were already wired into it — exactly the encapsulation gap this package exists to close. This is the one place this package's design is deliberately *stricter* than the CrewAI adapter's, not just structurally different.
2. **Every subagent's `tools` list is validated against `_capabilities` at construction, and raises `ValueError` on any name outside it.** Never silently filter or narrow — a silent drop hides a caller's mistaken assumption about what authority they were granting.
3. **No subagent is enabled by default.** `subagents=` must be passed explicitly.
4. **`can_use_tool` is the only deny mechanism this package implements.** If a future capability needs to also *observe* (not just allow/deny) tool calls, use `hooks["PreToolUse"]` additively — don't replace `can_use_tool`.
5. **`ClaudeAgentSDKOrchestratorAdapter.adapt_output()` stays a thin pass-through** (`{"messages": result}`). Full envelope normalization belongs in `ClaudeAgentSDKPayloadMapper.from_sdk_output()`, called exactly once, at the facade layer. `CrewAIOrchestratorAdapter.adapt_output()` duplicates its own mapper's normalization logic and — because the facade then normalizes a second time — silently produces a stringified-dict `output_text` on the second pass. Don't repeat that bug here.

---

## When the installed SDK differs from what this file assumes

The installed package wins. Re-verify the four "no inference seam" checks above and the subagent-routing claim (`grep -n "can_use_tool" .../claude_agent_sdk/_internal/query.py`) before trusting this file after any version bump. If a future SDK version *does* expose a genuine model-client injection point, that changes the conformance-tier decision itself — treat it as a reason to revisit this file's core claim, not a minor update.

## Documentation standards for this package

Same as Pet Store Agentic's: every capability claim here must correspond to either a passing test or a directly-verified source-level fact (cite the file/mechanism, as above). Do not claim this package achieves full governance parity with native K9-AIF agents — it doesn't, on the inference axis, permanently.
