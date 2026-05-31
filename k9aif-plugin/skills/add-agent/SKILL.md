---
description: Scaffold a new K9-AIF agent — creates the agent YAML, Python class, squad registration stub, and test stub. Pass the agent name and app name as arguments.
---
**Before doing anything else, check that `/k9aif:configure` has been run.**
If `K9AIF_PROJECT_ROOT` and `K9AIF_APP_NAME` are not set, refuse and say:
> "Please run `/k9aif:configure` first to set your project root and app name."
Do not proceed until init has been run.



# K9-AIF: Add Agent

Scaffold a complete new agent for the K9-AIF framework. The user provides: `<AgentName> <AppName>` (e.g. `ClaimsTriageAgent MyApp`).

**Before creating any files:**
1. Check whether `examples/<AppName>/` already exists.
2. If it does NOT exist, ask the user to confirm before proceeding:
   > "The app folder `examples/<AppName>/` does not exist yet. Do you want to create a new app structure, or did you mean a different app name? Existing apps: (list folders under examples/)"
3. Only proceed once the user confirms the app name.

## What to create

### 1. Agent YAML — `examples/<AppName>/agents/yaml/<agent_name_lower>.yaml`

```yaml
name: <AgentName>
class: <AgentName>

description: >
  <one paragraph — what this agent does>

pattern: reasoning
model: reasoning

role: >
  You are a ...

goal: >
  Your goal is to ...

instructions:
  - Instruction one
  - Instruction two

output_schema:
  result: string
  confidence: float

governance:
  pre_process: true
  post_process: false
```

### 2. Python class — `examples/<AppName>/agents/src/<agent_name_lower>.py`

```python
from typing import Any, Dict, Optional
from k9_aif_abb.k9_core.agent.base_agent import BaseAgent
from k9_aif_abb.k9_inference.models.inference_request import InferenceRequest
from k9_aif_abb.k9_utils.llm_invoke import llm_invoke


class <AgentName>(BaseAgent):

    layer = "<AppName> <AgentName> SBB"

    def __init__(self, config: Optional[Dict[str, Any]] = None, monitor=None, **kwargs):
        super().__init__(config or {}, monitor=monitor, **kwargs)

    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        prompt = (
            f"Role: {self.config.get('role', '')}\n"
            f"Goal: {self.config.get('goal', '')}\n\n"
            f"Input: {payload}"
        )
        req = InferenceRequest(
            prompt=prompt,
            task_type=self.config.get("model", "general"),
            metadata={"agent": "<AgentName>"},
        )
        try:
            resp = llm_invoke(self.config, req)
        except RuntimeError as exc:
            self.logger.error("[%s] LLM unavailable: %s", self.layer, exc)
            return {"agent": "<AgentName>", "output": "[WARN] LLM unavailable", "confidence": 0.0}

        self.publish_event({"type": "<AgentName>Completed", "agent": "<AgentName>"})
        return {
            "agent": "<AgentName>",
            "output": resp.output.strip(),
            "model_used": resp.model_alias,
        }
```

### 3. Squad registration stub (show the user where to add it in `_load_squad()`)

```python
from examples.<AppName>.agents.src.<agent_name_lower> import <AgentName>

# Inside _load_squad(), add to the registration list:
("<AgentName>", <AgentName>),
```

### 4. Test stub — `examples/<AppName>/tests/test_<agent_name_lower>.py`

```python
from unittest.mock import patch, MagicMock
from examples.<AppName>.agents.src.<agent_name_lower> import <AgentName>
from k9_aif_abb.k9_inference.models.inference_response import InferenceResponse


class _TestGovernance:
    def pre_process(self, payload, ctx=None): return payload
    def post_process(self, payload, ctx=None): return payload


def test_execute_returns_output():
    mock_resp = MagicMock(spec=InferenceResponse)
    mock_resp.output = "Result."
    mock_resp.model_alias = "reasoning"
    mock_resp.provider = "ollama"

    with patch("examples.<AppName>.agents.src.<agent_name_lower>.llm_invoke", return_value=mock_resp):
        agent = <AgentName>(config={}, governance=_TestGovernance())
        result = agent.execute({"input": "test"})

    assert result["agent"] == "<AgentName>"
    assert "output" in result
```

## Rules to follow
- Agent YAML never contains `squad:`, `routing:`, or `orchestrator:` fields — agents are squad-agnostic.
- `flow:` steps must be dicts with an `agent:` key — never plain strings.
- Always use `llm_invoke` — never call `OllamaLLM` or `LLMFactory` directly from agent code.
- Wrap `llm_invoke` in a try/except RuntimeError and return a `[WARN]` dict on failure.
- After generating files, remind the user to add the agent to the squad YAML flow and register it in `_load_squad()`.
