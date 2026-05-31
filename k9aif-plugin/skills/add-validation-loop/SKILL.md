---
description: Convert a K9-AIF agent to use the iterative validation loop pattern (K9ValidationLoopAgent). Pass the agent name and app name.
---
**Before doing anything else, check that `/k9aif:configure` has been run.**
If `K9AIF_PROJECT_ROOT` and `K9AIF_APP_NAME` are not set, refuse and say:
> "Please run `/k9aif:configure` first to set your project root and app name."
Do not proceed until init has been run.



# K9-AIF: Add Validation Loop

Convert an existing agent — or scaffold a new one — that uses the iterative `K9ValidationLoopAgent` pattern instead of one-shot `BaseAgent`. Use this when an agent needs to test a hypothesis, observe the result, and decide whether to try again.

The user provides: `<AgentName> <AppName>` (e.g. `FraudDetectionAgent EOC`).

## Decision rule — ask this first

> "Does this agent need to test something, observe the result, and decide whether to try again — or does it produce its answer in one pass?"

| One-pass → keep `BaseAgent` | Iterative → use `K9ValidationLoopAgent` |
|---|---|
| Triage, routing, audit, guard, graph sync | Fraud signal correlation, claims evidence, compliance gap, document confidence |

## What to generate

### Python class — `examples/<AppName>/agents/src/<agent_name_lower>.py`

```python
from typing import Any, Dict, Optional
from k9_aif_abb.k9_agents.validation import (
    K9ValidationLoopAgent,
    ValidationDisposition,
    ValidationLoopContext,
    ValidationLoopResult,
)


class <AgentName>(K9ValidationLoopAgent):

    layer = "<AppName> <AgentName> SBB"

    def __init__(self, config: Optional[Dict[str, Any]] = None, monitor=None, **kwargs):
        super().__init__(config or {}, monitor=monitor, **kwargs)

    def generate_hypothesis(self, loop_ctx: ValidationLoopContext):
        return {"query": "<what to test>", **loop_ctx.payload}

    def run_validation(self, hypothesis, loop_ctx: ValidationLoopContext):
        # Call rule engine, database, LLM, or external tool here
        return {"result": "placeholder", "score": 0.5}

    def evaluate_observation(self, tool_result, loop_ctx: ValidationLoopContext):
        confidence = tool_result.get("score", 0.0)
        return {"confidence": confidence, "result": tool_result.get("result")}

    def should_continue(self, observation, loop_ctx: ValidationLoopContext):
        threshold = self.config.get("confidence_threshold", 0.8)
        if observation["confidence"] >= threshold:
            return ValidationDisposition.FINALIZE
        if loop_ctx.iteration >= 3 and observation["confidence"] < 0.3:
            return ValidationDisposition.ESCALATE
        return ValidationDisposition.CONTINUE

    def finalize(self, loop_ctx: ValidationLoopContext) -> ValidationLoopResult:
        last = loop_ctx.steps[-1]
        return ValidationLoopResult(
            disposition=ValidationDisposition.FINALIZE,
            output={"decision": "complete", "confidence": last.confidence},
            steps=loop_ctx.steps,
            iterations=loop_ctx.iteration,
            final_confidence=last.confidence,
            evidence=[str(s.observation) for s in loop_ctx.steps],
        )
```

### Agent YAML additions

Add these keys to the agent YAML (alongside `role`, `goal`, etc.):

```yaml
max_iterations: 5
confidence_threshold: 0.8
finalize_on_max_iterations: true
```

## Rules to follow
- Import from `k9_aif_abb.k9_agents.validation` — not from a sub-module path.
- `finalize()` **must** be overridden — it has no default implementation.
- `escalate()` and `fail()` can be optionally overridden for domain-specific HIL routing.
- The five loop methods replace `execute()` entirely — do not define `execute()`.
- Remind the user that squad registration and YAML flow steps are identical to a regular agent.
