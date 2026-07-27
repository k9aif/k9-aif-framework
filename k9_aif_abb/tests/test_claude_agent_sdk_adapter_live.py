"""
Live smoke test for ClaudeAgentSDKOrchestratorAdapter -- unlike
test_crewai_adapter.py (mocked DummyCrew), this one makes a real call
against the Claude Agent SDK. Requires either a signed-in `claude` CLI
session or ANTHROPIC_API_KEY set in the environment.

Run directly, not via pytest (same convention as test_crewai_adapter.py):
    python k9_aif_abb/tests/test_claude_agent_sdk_adapter_live.py

What this proves, that construction-time tests alone couldn't -- and did
not, the first two times this was actually run (see CLAUDE.md "Verified
facts" for the publish_status and streaming-mode bugs this caught):
- The adapter actually authenticates and reaches a live Claude session.
- Claude genuinely decides to call the one tool it's given.
- That tool call is real, observable, egress-governed traffic --
  _can_use_tool fires, governance runs, PermissionResultAllow is
  returned, and only then does the tool's own handler execute. This is
  checked programmatically below (governance.post_calls), not just by
  eyeballing the console log -- a third real bug (allowed_tools shadowing
  can_use_tool, silently skipping the gate) was caught exactly because a
  human was reading the raw output, not because a prior version of this
  test asserted anything about it.
- The qualified tool name (mcp__<server>__<tool>) the adapter builds is
  accepted by the real CLI transport, not just well-formed on paper.
"""

from __future__ import annotations

from k9_aif_abb.k9_adapters.claude_agent_sdk import (
    ClaudeAgentSDKOrchestratorAdapter,
    ToolCapability,
)

_STEPS = """
This test exercises the full governed path against a REAL Claude Agent SDK
session (not mocked). Flow:

  1. Construct the adapter with one tool ("echo") and an observable
     governance stub that records every ingress/egress call it receives.
  2. Zero Trust check runs (disabled here; adapter constructed without
     enable_zero_trust=True).
  3. Ingress governance runs on the prompt (apply_pre_governance).
  4. A real query() session starts against the live Claude API/CLI.
  5. Claude decides whether to call the "echo" tool.
  6. If it does, can_use_tool fires -> egress governance runs
     (apply_post_governance) -> only if allowed does the tool's own
     handler actually execute.
  7. Claude's final answer passes a second, final-output egress check.
  8. Assertions below check message count, that a tool call was actually
     attempted, and -- the important one -- that governance recorded a
     real per-tool-call egress event, not just the final-output one.
"""


class _ObservableGovernance:
    """Minimal concrete governance -- defined inline, not imported, same
    pattern SKILLS.md Skill 6 uses for agent tests. Allows everything, but
    records every call so what actually fired can be asserted on, not just
    printed and eyeballed."""

    def __init__(self) -> None:
        self.pre_calls: list[dict] = []
        self.post_calls: list[dict] = []

    def pre_process(self, payload: dict, ctx: dict | None = None) -> dict:
        print(f"[governance] INGRESS  ctx={ctx.get('component') if ctx else None} payload={payload}")
        self.pre_calls.append(payload)
        return payload

    def post_process(self, payload: dict, ctx: dict | None = None) -> dict:
        print(f"[governance] EGRESS   ctx={ctx.get('component') if ctx else None} payload={payload}")
        self.post_calls.append(payload)
        return payload


async def echo_handler(args: dict) -> dict:
    text = args.get("text", "")
    print(f"[tool] echo handler actually executed with: {text!r}")
    return {"content": [{"type": "text", "text": f"Echo: {text}"}]}


def main() -> None:
    print(_STEPS)

    governance = _ObservableGovernance()
    adapter = ClaudeAgentSDKOrchestratorAdapter(
        capabilities=[
            ToolCapability(
                name="echo",
                description="Echoes back whatever text is provided.",
                input_schema={"text": str},
                handler=echo_handler,
            ),
        ],
        governance=governance,
        max_turns=3,
    )

    result = adapter.execute_flow({
        "prompt": (
            "Call the echo tool with the text 'hello k9-aif', then tell me "
            "exactly what it returned."
        )
    })

    print("\n=== raw result ===")
    print(result)

    messages = result.get("messages", [])
    tool_use_seen = any(
        type(msg).__name__ == "AssistantMessage"
        and any(type(block).__name__ == "ToolUseBlock" for block in getattr(msg, "content", []) or [])
        for msg in messages
    )
    # The regression check for the allowed_tools-shadowing bug: a per-tool-call
    # egress event must actually be in post_calls, distinct from the one
    # final-output post_process call every run also produces.
    tool_call_egress_seen = any("tool_name" in call for call in governance.post_calls)

    print("\n=== PASS/FAIL checks ===")
    print(f"Got {len(messages)} messages: {'PASS' if messages else 'FAIL'}")
    print(f"Claude attempted a tool call (ToolUseBlock present): {'PASS' if tool_use_seen else 'FAIL'}")
    print(f"Tool call actually passed through egress governance (not shadowed): "
          f"{'PASS' if tool_call_egress_seen else 'FAIL'}")


if __name__ == "__main__":
    main()
