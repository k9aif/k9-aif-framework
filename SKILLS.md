# SKILLS.md

Step-by-step recipes for the most common development tasks in K9-AIF.
Read alongside `CLAUDE.md` (architecture) — this file covers *how to build*, not *how it works*.

---

## Skill 1 — Add a new Agent

### Step 1: Create the agent YAML

```
examples/<App>/agents/yaml/my_agent.yaml
```

```yaml
name: MyAgent
class: MyAgent                         # must match the Python class name exactly

description: >
  What this agent does in one paragraph.

pattern: reasoning                     # reasoning | extraction | chat | guardrails
model: reasoning                       # must match a key in inference.model_catalog

role: >
  You are a ... (LLM system prompt — who the agent is)

goal: >
  Your goal is to ... (what the agent must achieve)

instructions:
  - Instruction one
  - Instruction two
  - Always include confidence score in output

output_schema:
  field_one: string
  field_two: float
  confidence: float (0.0–1.0)

tools: []

governance:
  pre_process: true
  post_process: false
```

### Step 2: Create the Python class

```
examples/<App>/agents/src/my_agent.py
```

```python
from typing import Any, Dict, Optional
from k9_aif_abb.k9_core.agent.base_agent import BaseAgent
from k9_aif_abb.k9_inference.models.inference_request import InferenceRequest
from k9_aif_abb.k9_utils.llm_invoke import llm_invoke


class MyAgent(BaseAgent):

    layer = "<App> MyAgent SBB"

    def __init__(self, config: Optional[Dict[str, Any]] = None, monitor=None, **kwargs):
        super().__init__(config or {}, monitor=monitor, **kwargs)

    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        # 1. Build prompt from payload + agent YAML config
        prompt = (
            f"Role: {self.config.get('role', '')}\n"
            f"Goal: {self.config.get('goal', '')}\n\n"
            f"Input: {payload}"
        )

        # 2. Build InferenceRequest — task_type drives model scoring
        req = InferenceRequest(
            prompt=prompt,
            task_type=self.config.get("model", "general"),
            metadata={"agent": "MyAgent"},
        )

        # 3. Invoke LLM via router
        resp = llm_invoke(self.config, req)

        # 4. Return structured result
        result = {
            "agent": "MyAgent",
            "output": resp.output.strip(),
            "model_used": resp.model_alias,
        }

        # 5. Publish event for audit trail
        self.publish_event({"type": "MyAgentCompleted", "agent": "MyAgent"})

        return result
```

### Step 3: Register in `_load_squad()`

Agents are not registered with the orchestrator — they are registered into `AgentRegistry` inside `_load_squad()` so `SquadLoader` can wire them into the Squad. The orchestrator only holds the assembled Squad.

```python
from examples.<App>.agents.src.my_agent import MyAgent

for name, cls in [
    ...
    ("MyAgent", MyAgent),          # add here
]:
    agent_registry.register(
        name,
        lambda c=cls, n=name: c(config=agent_loader.merge_with_global(n, self.config)),
    )
```

### Step 4: Add to the squad YAML flow

Each `flow:` step must be a dict with an `agent:` key — plain strings will raise `ValueError` at runtime.

```yaml
# config/squads.yaml  (note the squads: wrapper and squad ID key)
squads:
  MySquad:
    description: "What this squad does."
    orchestrator: MyOrchestrator
    agents:
      - ...
      - MyAgent
    flow:
      - ...
      - agent: MyAgent
        result_key: my_agent        # key under which result is stored in context
```

Optional flow step fields: `result_key` (defaults to agent name), `context` (static overrides merged into step input), `when` (condition — step skipped if false).

---

## Skill 2 — How an Agent invokes the LLM

This is the complete chain every agent must follow. Never call `OllamaLLM` or `LLMFactory` directly from agent code.

```python
from k9_aif_abb.k9_inference.models.inference_request import InferenceRequest
from k9_aif_abb.k9_utils.llm_invoke import llm_invoke   # ABB — use this by default

# 1. Build the request
req = InferenceRequest(
    prompt="Your prompt here",
    task_type="reasoning",           # drives K9ModelRouter scoring (+3 for capability match)
    sensitivity="confidential",      # optional — routes to guardian model (+2)
    latency_budget="realtime",       # optional — boosts realtime-tier models (+2)
    cost_profile="minimal",          # optional — boosts minimal-cost models (+2)
    metadata={"agent": "MyAgent", "correlation_id": correlation_id},
)

# 2. Invoke — ModelRouterFactory selects the right model, persists the decision
resp = llm_invoke(self.config, req)

# 3. Check the response
resp.output        # the LLM text output
resp.model_alias   # which model was selected (e.g. "reasoning")
resp.provider      # e.g. "ollama"
resp.latency_ms    # round-trip time
```

**What happens under the hood:**

```
llm_invoke(config, req)
  → ModelRouterFactory.get_router(config)      # cached router instance
  → K9ModelRouter.route(req)                   # scores all catalog models
  → catalog.get_model(best_alias)              # looks up llm_ref
  → LLMFactory.get(llm_ref)                   # cached OllamaLLM instance
  → OllamaLLM.invoke(prompt)                  # hits Ollama at 192.168.1.98:11434
  → RouteDecision + complexity/governance scores persisted to routing state store (SQLite or PostgreSQL)
```

**If the LLM is unreachable**, `llm_invoke` raises `RuntimeError` — it never silently returns empty output. Handle it:

```python
try:
    resp = llm_invoke(self.config, req)
except RuntimeError as exc:
    self.logger.error("[%s] LLM unavailable: %s", self.layer, exc)
    return {"agent": "MyAgent", "output": "[WARN] LLM unavailable", "confidence": 0.0}
```

---

## Skill 3 — Add a new model to the Router

`K9ModelRouter` is the OOB default router. A solution can substitute its own router by implementing `BaseModelRouter` (`k9_aif_abb/k9_inference/routers/base_model_router.py`) and registering it via `ModelRouterFactory`. The steps below apply to the default `K9ModelRouter`.

**Two places to update in `config.yaml`:**

```yaml
# 1. LLMFactory — the actual Ollama model name and parameters
inference:
  llm_factory:
    models:
      my_model:
        model: "granite3-dense:2b"    # Ollama model name
        temperature: 0.2
        max_tokens: 4096

# 2. Model catalog — capabilities and routing tiers
  model_catalog:
    models:
      my_model:
        provider: ollama
        llm_ref: my_model             # must match llm_factory.models key above
        capabilities: [reasoning, analysis]
        latency_tier: interactive     # realtime | interactive | batch
        cost_tier: standard           # minimal | standard | premium
```

The router scores this model automatically. No code changes needed.

---

## Skill 4 — Add a new Squad

### Squad YAML

```
examples/<App>/config/squads.yaml
```

`SquadLoader` reads `data["squads"]` — the squad ID is a key under `squads:`, not a `name:` field. Flow steps **must** be dicts with an `agent:` key.

```yaml
squads:
  MySquad:
    description: "What this squad does."
    orchestrator: MyOrchestrator
    agents:
      - AgentOne
      - AgentTwo
      - AuditAgent
    flow:
      - agent: AgentOne
        result_key: agent_one
      - agent: AgentTwo
        result_key: agent_two
      - agent: AuditAgent
        result_key: audit
```

### Wire it in `_load_squad()`

```python
loader = SquadLoader(agent_registry, orchestrator_registry)
squad = loader.load_one(squads_yaml_path, "MySquad")
```

---

## Skill 5 — Governance enforcement in an Agent

`K9_ENV` controls what happens when `enforce_governance()` is called:

| `K9_ENV` | `enforce_governance()` behaviour |
|---|---|
| `development` / `test` | Logs WARNING, continues |
| `production` / `staging` | Raises `PermissionError` — agent stops |

**To require governance before executing:**

```python
def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        self.enforce_governance()        # raises in production if NoopGovernance
    except PermissionError as exc:
        self.logger.error("[%s] %s", self.layer, exc)
        return {"agent": self.layer, "output": "[WARN] governance not configured"}

    # ... rest of execute
```

**To apply governance pipeline hooks:**

```python
import asyncio

# Pre-process (sanitize/validate input before LLM)
payload = asyncio.get_event_loop().run_until_complete(
    self.apply_pre_governance(payload)
)

# ... call llm_invoke ...

# Post-process (validate/redact output after LLM)
result = asyncio.get_event_loop().run_until_complete(
    self.apply_post_governance(result)
)
```

---

## Skill 6 — Write a test for an Agent

No LLM or database needed — mock `llm_invoke` and test `execute()` directly.

```python
from unittest.mock import patch, MagicMock
from examples.<App>.agents.src.my_agent import MyAgent
from k9_aif_abb.k9_inference.models.inference_response import InferenceResponse


class _TestGovernance:
    """Minimal concrete governance for tests — define inline, not imported."""
    def pre_process(self, payload: dict, ctx=None) -> dict:
        return payload
    def post_process(self, payload: dict, ctx=None) -> dict:
        return payload

def _make_agent(config=None):
    return MyAgent(config=config or {}, governance=_TestGovernance())


def test_execute_returns_output():
    mock_resp = MagicMock(spec=InferenceResponse)
    mock_resp.output = "Assessment complete."
    mock_resp.model_alias = "reasoning"
    mock_resp.provider = "ollama"

    with patch("examples.<App>.agents.src.my_agent.llm_invoke", return_value=mock_resp):
        agent = _make_agent()
        result = agent.execute({"claim_id": "C001", "amount": 5000})

    assert result["agent"] == "MyAgent"
    assert "output" in result


def test_execute_handles_llm_unavailable():
    with patch("examples.<App>.agents.src.my_agent.llm_invoke",
               side_effect=RuntimeError("LLM backend unavailable")):
        agent = _make_agent()
        result = agent.execute({"claim_id": "C001"})

    assert "[WARN]" in result["output"]
```

---

## Skill 7 — Publish an event from an Agent

`publish_event()` sends to the **monitor and logger only** — agents are never wired with a `message_bus`, so nothing goes to Kafka. Use it for internal audit/observability signals.

```python
self.publish_event({
    "type": "MyAgentCompleted",       # event type — recorded by monitor/logger
    "agent": "MyAgent",
    "correlation_id": correlation_id,
    "result_summary": "...",          # lightweight summary only — no PII
})
```

**Kafka is not involved at the agent level.** The Kafka topology in EOC is:

```
app_backend → eoc-events → Router (publishes) → eoc-claims / eoc-fraud / …
                                                          ↓
                                        Orchestrator process (consumes, runs squads) → eoc-results
```

- **Router only**: publishes events to domain Kafka topics
- **Orchestrator only**: consumes from domain Kafka topics
- **Agents**: never touch Kafka — `publish_event()` reaches the monitor/logger, not the bus

---

## Skill 8 — Add a new scoring signal to the Router

This applies to `K9ModelRouter` (the OOB default). If a solution has implemented a custom `BaseModelRouter`, extend that instead.

The scoring logic lives in `k9_aif_abb/k9_inference/routers/k9_model_router.py` — `_score_candidate()`.

To add a new signal (e.g. `+2` for environment match):

```python
def _score_candidate(self, alias: str, meta: dict, request: InferenceRequest) -> float:
    score = 0.0
    caps = meta.get("capabilities", [])

    if request.task_type and request.task_type in caps:
        score += 3.0

    if getattr(request, "sensitivity", None) == "confidential" and "confidential" in caps:
        score += 2.0

    if request.latency_budget and request.latency_budget == meta.get("latency_tier"):
        score += 2.0

    if request.cost_profile and request.cost_profile == meta.get("cost_tier"):
        score += 2.0

    # New signal — environment match
    if request.environment and request.environment == meta.get("environment_tier"):
        score += 2.0

    return score
```

Then add the field to `InferenceRequest` (Optional, default None — backwards compatible):

```python
environment: Optional[str] = None   # "local" | "cloud" | "air-gapped"
```

And add `environment_tier` to catalog entries in `config.yaml`.

---

## Skill 9 — Agent config: what comes from YAML vs global config

When `_load_squad()` constructs an agent it calls:

```python
agent_loader.merge_with_global("MyAgent", self.config)
```

This produces one merged dict passed as `agent.config`. Merge rule: **agent YAML wins on key collision**.

| Source | What it provides |
|---|---|
| `config.yaml` (global) | `inference`, `messaging`, `postgres`, `neo4j`, `governance`, `eoc` — infrastructure |
| `agent.yaml` | `role`, `goal`, `instructions`, `model`, `pattern`, `routing`, `governance.pre_process` — behavior |

So in an agent:

```python
self.config.get("role")           # from agent YAML
self.config.get("model")          # from agent YAML — e.g. "reasoning"
self.config.get("inference")      # from global config.yaml — full inference block
self.config.get("postgres")       # from global config.yaml — DB connection
```

This is why agents never hardcode prompts or model names — all behavior is in YAML, all infrastructure is in the global config.
