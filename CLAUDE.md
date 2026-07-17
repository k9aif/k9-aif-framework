# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

@SKILLS.md

---

## Architecture & Design Discipline

> "The entire history of software engineering is one of rising levels of abstraction. This is as it was, is now, and always shall be." — Grady Booch

K9-AIF is built on OOA, OOD, TOGAF, and Design Pattern principles. When working on this codebase, apply these disciplines:

- **OOA / OOD** — every new concern follows the ABB/SBB separation: abstract contract first, concrete implementation second. Liskov Substitution and Open-Closed Principle are non-negotiable.
- **Design Patterns** — Factory, Adapter, Registry are the core patterns. New infrastructure concerns must follow the existing `Base<Concern>` → `<Provider>Adapter` → `<Concern>Factory` structure.
- **TOGAF** — ABB (Architecture Building Block) = abstract contract in `k9_core/`. SBB (Solution Building Block) = concrete implementation. This is not a suggestion — it is the architecture.
- **UML / PlantUML** — default to PlantUML for all diagrams. Class diagrams for ABB/SBB relationships, component diagrams for infrastructure, activity diagrams for flows.
- **BPMN** — swim lane diagrams use BPMN conventions: horizontal bands stacked top-to-bottom, lane labels on the left, activities flowing left-to-right within each lane, vertical arrows for cross-lane interactions.
- **ABC inheritance** — `BaseComponent` does NOT extend `ABC`. ABBs that need both infrastructure (logging, monitoring, message bus) and abstract method enforcement must extend `(BaseComponent, ABC)` — this is correct multiple inheritance, not redundant. Never assume a parent class already extends `ABC` without checking the source.

---

## Pre-Push Checklist

Before committing or pushing any file, verify:

- **No hardcoded IP addresses** — never commit `192.168.x.x` or any private IP. Use env vars with defaults: `"${POSTGRES_HOST:-localhost}"`, `"${OLLAMA_BASE_URL:-http://localhost:11434}"` etc.
- **No credentials in config files** — passwords, API keys, tokens must be in `.env` (gitignored), never in `config.yaml`
- **`.env` is never staged** — it is in `.gitignore`; use `env-example` for the template
- **No `__pycache__` or `.pyc` files** — ensure `.gitignore` is present before first commit
- **Three-layer decoupling preserved** — Router knows only Orchestrators, Orchestrator knows only Squads, Squad knows only Agents

---

## Hooks

Five PostToolUse hooks fire automatically after every Write or Edit (configured in `.claude/settings.json`):

| Hook | Triggers on | What it checks |
|---|---|---|
| `check-python.sh` | Any `*.py` file | Python syntax (`py_compile`) — exits 2 (blocks) on error |
| `check-yaml.sh` | Any `*.yaml` / `*.yml` | YAML parse validity — exits 2 (blocks) on error |
| `run-abb-tests.sh` | Files under `k9_aif_abb/` | Runs `test_framework.py` + `test_intelligent_model_router.py` |
| `check-governance.sh` | `*.py` under `examples/` | Warns if `NoopGovernance` appears in example code |
| `check-init-docstring.sh` | Any `__init__.py` | Warns if module docstring is missing (required for pydoc generation) |

Hook scripts live in `.claude/hooks/`. Exit code 2 = block the action; exit 0 = continue.

---

## Commands

### Setup

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Run tests

All framework stability tests (no external services needed):
```bash
cd k9_aif_abb
pytest tests/test_framework.py -v
pytest tests/test_intelligent_model_router.py -v
```

Single test file:
```bash
pytest k9_aif_abb/tests/test_agent_registry.py -v
```

All tests:
```bash
pytest k9_aif_abb/tests/ -v
```

### Run example apps (local, Mac)

```bash
./run_k9chat.sh
./run_acme_support_center.sh
```

### EOC — build and run (RHEL / Podman)

```bash
bash build.sh                    # build container image only
bash run_eoc_pod.sh              # build + create pod + start 3 containers
sudo podman pod ps               # check pod status
sudo podman logs eoc-app-backend # tail a container
```

After a `git pull` on RHEL, always rebuild (`run_eoc_pod.sh`) — restarting containers alone does not pick up code changes.

### Smoke tests

```bash
bash test_model_router.sh        # router + LLM end-to-end
bash test_squads.sh              # squad execution flow
```

### Generate stub app

```bash
./k9_generator.sh preview <AppName>
./k9_generator.sh run <AppName>
./k9_generator.sh recycle <AppName>
```

---

## Architecture

### Core concept: ABB vs SBB

**Architecture Building Blocks (ABB)** — abstract contracts in `k9_aif_abb/`. Define interfaces, lifecycle, governance hooks. Never contain domain logic.

**Solution Building Blocks (SBB)** — concrete implementations that extend ABBs with domain-specific behavior without modifying the core. Two locations:
- `examples/<AppName>/` — hand-crafted reference SBBs (EOC is the canonical example)
- `k9_projects/<AppName>/` — stub SBBs scaffolded by `k9_generator.sh`; flesh out from the reference examples

### Execution hierarchy

```
Event → K9EventRouter (single entry point)
    ├── event_type in routing.table ─────────────────► domain topic
    └── event_type unknown ──────────► intent.in
                                            │
                              IntentOrchestrator (consumes intent.in)
                                  → IntentSquad → K9IntentAgent
                                      ├── intent resolved ──► domain topic
                                      └── intent unclear  ──► responses.out

domain topic → Orchestrator → 1+ Squads → 1+ Agents → LLM
```

- **Router** (`k9_core/router/base_router.py`) — **single entry point** for all events. Routes by `event_type` deterministically; publishes to `intent.in` when intent cannot be determined. Never contains classification logic. Owns the **object store** — when a document arrives, the Router stores it in the bucket and publishes a JSON event with the `document_uri` to the domain topic. Downstream agents receive only the URI.
- **IntentOrchestrator** (`k9_orchestrators/intent_orchestrator.py`) — OOB Kafka consumer on `intent.in`. Self-bootstraps `IntentSquad` + `K9IntentAgent`. Runs IntentSquad to classify intent, then re-publishes to the correct domain topic. If intent remains unclear or confidence is below threshold, publishes a "please clarify" response.
- **IntentSquad** (`k9_squad/intent_squad.py`) — squad used by IntentOrchestrator; wraps one or more `BaseIntentAgent` implementations; handles confidence gating
- **Orchestrator** (`k9_core/orchestration/base_orchestrator.py`) — coordinates 1 or more squads for a domain workflow. Use `execute_squads(squads, payload, parallel=True)` for multi-squad parallel execution; results namespaced by `squad_id`
- **Squad** (`k9_squad/base_squad.py`) — executes a defined `flow` of 1 or more agents in sequence
- **Agent** (`k9_core/agent/base_agent.py`) — implements `execute(payload) -> dict`; must extend `BaseAgent`

### Intent classification ABBs

Used inside `IntentOrchestrator` when the Router cannot determine intent deterministically. The Router publishes to `intent.in`; `IntentOrchestrator` consumes it, runs `IntentSquad`, and re-publishes to the correct domain topic — or generates a "please clarify" response.

**The SA never wires anything in front of the Router.** IntentOrchestrator is a separate Kafka-decoupled process, not a pre-step.

| Class | Kind | Path |
|---|---|---|
| `K9EventRouter` | OOB Router | `k9_core/router/k9_event_router.py` |
| `BaseIntentAgent` | ABB abstract | `k9_agents/intent/base_intent_agent.py` |
| `K9IntentAgent` | OOB LLM-driven | `k9_agents/intent/k9_intent_agent.py` |
| `IntentSquad` | ABB squad for intent classification | `k9_squad/intent_squad.py` |
| `IntentOrchestrator` | OOB — self-bootstrapped with K9IntentAgent | `k9_orchestrators/intent_orchestrator.py` |

`K9IntentAgent` classification order: (1) `intent_map` dict rule lookup — zero latency; (2) LLM via `llm_invoke`; (3) `fallback_intent()` — `event_type` verbatim or `"unknown"`.

`IntentSquad` override surface: `select_agent(payload)`, `merge_intent(payload, result)`, `on_low_confidence(payload, intent, confidence)`. The `confidence_threshold` config key (default 0.5) triggers `on_low_confidence` when below.

**Three routing outcomes from the Router's perspective:**
1. `event_type` known → publish directly to domain topic (zero latency)
2. `event_type` unknown → publish to `intent.in` → IntentOrchestrator resolves → domain topic
3. Intent unresolvable → IntentOrchestrator publishes "please clarify" response

**SBB classification strategies** — all plug in via `BaseIntentAgent.classify()`:
- Config list / `intent_map` in YAML (zero-code, zero-latency)
- LLM prompt (`K9IntentAgent` OOB)
- NLP / regex pipeline
- Docling document extraction + classification
- Rules engine (e.g. Drools via an adapter)

The topology (Router → `intent.in` → IntentOrchestrator → domain topic) is the same regardless of which strategy is used inside the agent.

### Inference pipeline

Agents call LLMs exclusively through:

```python
from k9_aif_abb.k9_utils.llm_invoke import llm_invoke
resp = llm_invoke(self.config, InferenceRequest(prompt=..., task_type=...))
```

`llm_invoke` → `ModelRouterFactory.get_router()` → `BaseModelRouter.route()` → `LLMFactory.get(llm_ref)` → `OllamaLLM.invoke()`

`K9ModelRouter` is the OOB default implementation of `BaseModelRouter`. `DefaultModelRouter` (`k9_inference/routers/default_model_router.py`) is a second OOB router, selectable via `router.type: default`. Solutions can substitute their own router by implementing `BaseModelRouter` (`k9_inference/routers/base_model_router.py`) — which has three abstract methods: `route()`, `invoke()`, and `ainvoke()` (async) — and registering it via `ModelRouterFactory`.

`K9ModelRouter` selects the model via weighted scoring:
- `+3` task_type matches a model's `capabilities[]`
- `+2` sensitivity == "confidential" and model has "confidential" capability
- `+2` `latency_budget` matches model's `latency_tier`
- `+2` `cost_profile` matches model's `cost_tier`

Falls back to `default_model` when nothing scores > 0. Selected model, `complexity_score`, and `governance_score` are persisted to the routing state store after every call.

### Governance

Every agent receives a governance pipeline via `require_governance()` at init time.
- In `development`/`test` (`K9_ENV`): NoopGovernance with WARNING log — permitted
- In `production`/`staging`: NoopGovernance with ERROR log — `enforce_governance()` will raise `PermissionError`

Agents that must enforce governance call `self.enforce_governance()` at the top of `execute()`. Agents that skip this call will silently use NoopGovernance even in production.

### Cardinality

```
Router 1 → N Orchestrators
Orchestrator 1 → N Squads (sequential or parallel via execute_squads)
Squad 1 → N Agents (sequential via flow)
```

### Three-level decoupling

Each layer knows only what is **below** it in the hierarchy:

| Layer | Knows about | Does NOT know about |
|---|---|---|
| **Orchestrator** | Its squads — loaded via `_load_squad()` | Routers, agents, other orchestrators |
| **Squad** | Its agents and their execution flow | Orchestrators |
| **Agent** | Its own behavior (role, goal, model) | Squads, routing, next agent |

**The single rule: each layer only knows the layer directly below it.**

- **Router** only knows Orchestrators — not Squads, not Agents
- **Orchestrator** only knows Squads — not Agents, not Routers
- **Squad** only knows Agents — not Orchestrators, not Routers
- **Agent** knows nothing above itself

**STRICT RULES — never violate:**
- Router must not import or reference Squad or Agent classes
- Orchestrator must not import or reference Agent classes
- Squad YAML has no `orchestrator:` field
- Agent YAML has no `squad:` or `routing:` fields

Agent registration belongs in the **application entry point** (`app.py`, `bootstrap.py`) — not inside the orchestrator. The orchestrator receives a pre-loaded squad and calls `execute_flow()` only.

### Squad definition (YAML)

Each squad lives in its own YAML file under `squads/yaml/`. Flow steps **must** be dicts with an `agent:` key — plain strings will raise `ValueError` at runtime.

```yaml
squads:
  ClaimsProcessingSquad:
    description: "Triage, adjudication and audit for claims."
    agents:
      - ClaimsTriageAgent
      - AdjudicationAgent
      - GuardAgent
      - AuditAgent
    flow:
      - agent: ClaimsTriageAgent
        result_key: triage
      - agent: AdjudicationAgent
        result_key: adjudication
      - agent: GuardAgent
        result_key: guard
      - agent: AuditAgent
        result_key: audit
```

`SquadLoader` reads this YAML and wires agents from `AgentRegistry` at startup. The orchestrator that calls `_load_squad()` determines which squad runs — that association lives in orchestrator code, not in the squad YAML.

### Config structure (`config.yaml`)

Two levels:
- **Framework ABB config** (`k9_aif_abb/config/config.yaml`) — defaults for testing; Ollama at `${OLLAMA_BASE_URL:-http://localhost:11434}`, SQLite persistence
- **Example SBB config** (`examples/<App>/config/config.yaml`) — overrides for that app; EOC uses PostgreSQL (`eoc` schema), Kafka at `${KAFKA_BROKER:-localhost:9092}`

Key config sections: `inference.llm_factory.models` (maps alias → Ollama model name + params), `inference.model_catalog` (maps alias → capabilities/tiers), `inference.router.persistence` (sqlite | postgres | memory), `postgres`, `messaging` (Kafka/Redpanda).

### Persistence

- **Routing state store** (`k9_storage/routing_state_store.py`) — 4 tables: `sessions`, `session_turns`, `routing_decisions`, `context_artifacts`. SQLite OOB (auto-created); PostgreSQL via reflection. All tables live in the `k9aif` schema on the PostgreSQL instance at `${POSTGRES_HOST:-localhost}`.
- **PostgresDatabaseStorage** sets `search_path` and `MetaData(schema=...)` from `postgres.schema` in config — schema must match the PostgreSQL schema or reflection will miss the tables.

### EOC example structure

`examples/K9X_Enterprise_Insurance_OperationsCenter/` is the canonical reference example.

Three processes (one container each in the pod):
1. `start_eoc_app.sh` — FastAPI backend + Web UI (port 8000)
2. `start_eoc_orchestrator.sh` — Kafka consumer → squads/agents → publishes results to `eoc-results` topic
3. `start_eoc_router.sh` — Kafka router: consumes `eoc-events`, **publishes** to domain topics (`eoc-claims`, `eoc-fraud`, …) by `event_type`

**Kafka publish/subscribe ownership** — by convention, only the Router and Orchestrator process touch Kafka:
- **Router** is the only Kafka publisher for domain topics
- **Orchestrator process** consumes domain topics and publishes to `eoc-results`
- **Agents** are constructed without a `message_bus` in standard K9-AIF solutions — `publish_event()` reaches the monitor and logger only. A2A via Kafka is architecturally possible (wire an agent with a `message_bus`) but is not used in standard solutions — agents share data sequentially through the Squad flow instead

Static assets (`webui/`) use `?v=N` cache busting on own files. Bump the version number when changing `app.js` or `styles.css` and rebuild the container.

### Key ABB contracts

| File | Contract |
|---|---|
| `k9_core/agent/base_agent.py` | `execute(payload: dict) -> dict` — synchronous, must be implemented |
| `k9_core/orchestration/base_orchestrator.py` | `execute_flow(payload: dict) -> dict` — coordinates squad execution; `execute_squads(squads, payload, parallel=False) -> dict[str, dict]` — run 1+ squads (sequential or parallel) |
| `k9_core/router/base_router.py` | `route(payload: dict) -> dict` — dispatches event to the Orchestrator's topic (deterministic or via `intent.in`); returns routing metadata |
| `k9_squad/base_squad.py` | `execute(payload: dict) -> dict` — executes `flow` steps in order (`run()` exists as backwards-compat alias) |
| `k9_inference/routers/base_model_router.py` | `route(request)` → `RouteDecision`; `invoke(request)` → `InferenceResponse`; `ainvoke(request)` → `InferenceResponse` (async) |
| `k9_core/storage/base_object_storage.py` | `upload(bucket, key, data)` → URI; `download(bucket, key)` → bytes; `get_uri(bucket, key)` → str |
| `k9_core/governance/pipeline.py` | `require_governance()` factory; `NoopGovernance`; `GovernanceConfigError` |
| `k9_agents/validation/base_validation_loop_agent.py` | Iterative loop ABB — `generate_hypothesis` · `run_validation` · `evaluate_observation` · `should_continue` · `finalize` |
| `k9_agents/validation/k9_validation_loop_agent.py` | OOB LLM-driven loop — extend and override only what differs (analogous to `K9ModelRouter`) |
| `k9_agents/critic_actor/base_critic_actor_agent.py` | Actor-Critic refinement ABB — `generate` · `critique` · `refine` · `should_accept` · `finalize` |
| `k9_agents/critic_actor/k9_critic_actor_agent.py` | OOB LLM-driven Actor-Critic — override `critique()` to plug in a real external validator |

### Solutions Architect — BaseAgent vs K9ValidationLoopAgent

The generator, intake, and Claude Code scaffold all agents extending `BaseAgent` (one-shot) by default. The SA must decide at design time which agents need the validation loop.

**Decision rule — ask per agent:**
> *"Does this agent need to test something, observe the result, and decide whether to try again — or does it produce its answer in one pass?"*

| One-pass → `BaseAgent` | Iterative convergence → `K9ValidationLoopAgent` |
|---|---|
| Triage, routing, audit, guard, graph sync | Fraud signal correlation, claims evidence, compliance gap, document confidence |

When changing a generated agent to iterative: replace `class MyAgent(BaseAgent)` with `class MyAgent(K9ValidationLoopAgent)` and replace `execute()` with the five loop methods (`generate_hypothesis`, `run_validation`, `evaluate_observation`, `should_continue`, `finalize`). See Skill 10 in SKILLS.md.

### Factory pattern

All major components are provisioned through factories — never instantiated directly in application code:

- `LLMFactory.bootstrap(config)` then `LLMFactory.get(alias)` — returns a cached `BaseLLM` instance (`OllamaLLM`, `OpenAILLM`, `WatsonxLLM`, ...) resolved via `ProviderAdapterRegistry` from `inference.llm_factory.backend`
- `ModelRouterFactory.get_router(config)` — returns cached `K9ModelRouter`
- `AgentRegistry.register(name, cls)` / `create(name)` — instantiates agents by name
- `OrchestratorRegistry` — same pattern for orchestrators
- `SecretManagerFactory.create(config)` — provisions secret manager from `config["secrets"]["provider"]` (default: `"env"`)
- `CacheFactory.create(config)` — provisions cache from `config["cache"]["provider"]` (default: `"in_memory"`)
- `ObjectStorageFactory.create(config)` — provisions object store from `config["object_storage"]["provider"]` (default: `"local"`)

### Provider Adapter Pattern

The multi-provider LLM pattern is applied consistently across infrastructure concerns. Each area follows the same three-layer structure: `BaseXxx` ABB contract → provider `XxxAdapter` implementations → `XxxFactory` with config-driven default. All changes are additive — existing solutions using concrete classes directly are unaffected.

| Concern | Contract | Adapters | Factory | Config key |
|---|---|---|---|---|
| Secret Management | `BaseSecretManager` | `EnvSecretAdapter` (default), `VaultSecretAdapter`, `AwsSecretAdapter`, `IbmSecretAdapter` | `SecretManagerFactory` | `secrets.provider` |
| Cache | `BaseCache` | `InMemoryAdapter` (default), `RedisAdapter` | `CacheFactory` | `cache.provider` |
| Object Storage | `BaseObjectStorage` | `LocalObjectStorageAdapter` (default), `S3ObjectStorageAdapter` (OOB — S3/MinIO), `IbmCosObjectStorageAdapter` | `ObjectStorageFactory` | `object_storage.provider` |
| LLM Inference | `BaseProviderAdapter` (`k9_core/inference/base_provider_adapter.py`) | `OllamaProviderAdapter` (default), `OpenAIProviderAdapter` (`openai` + `openai-compatible` — also covers Grok/xAI, any OpenAI-shaped endpoint), `WatsonxProviderAdapter` (IBM watsonx.ai — IAM token exchange + `project_id`) | `LLMFactory` (resolves via `ProviderAdapterRegistry`) | `inference.llm_factory.backend` (or legacy `.provider`) |

**Design constraints (must be preserved in all adapter work):**
- API keys and secrets NEVER in `config.yaml` — credentials come from environment variables only
- Adapters that require optional packages use lazy imports and raise `RuntimeError` with install hint on first use
- Factory `create(config)` always has a zero-config default (env adapter, in_memory cache) — no config key required for the common case
- All new ABB code is purely additive — no modification to existing classes

**LLM adapter gotchas (both were real, silent bugs found and fixed in this table's rollout):**
- Every `BaseLLM.generate(prompt, system_prompt=None)` implementation **must** accept `system_prompt` — `K9ModelRouter.invoke()`/`ainvoke()` always pass it as a kwarg. `OpenAILLM.generate()` originally omitted it and would raise `TypeError` the instant a real call was attempted.
- `K9ModelRouter.invoke()` bridges the sync `BaseAgent.execute()` contract to an async `BaseLLM.generate()` via `_run_coro_sync()` (`k9_inference/routers/k9_model_router.py`) — **never** call `asyncio.run()` directly here. Any solution embedding K9-AIF inside an async web framework (FastAPI, etc.) calls `invoke()` from an already-running event loop; `asyncio.run()` raises `RuntimeError: asyncio.run() cannot be called from a running event loop` in that case, and a broad `except Exception` in agent code will silently swallow it and fall back to stub output with no visible error.
- `ModelRouterFactory._build_router_state_store()` must back `RoutingStateStore` with a SQLAlchemy-capable store (`SQLiteDatabaseStorage`, `PostgresDatabaseStorage`) — never `MemoryPersistence`. `RoutingStateStore._init_tables()` unconditionally reads `self.db.metadata`/`self.db.engine`, which `MemoryPersistence` (a plain key-value ABB) doesn't provide. `persistence.enabled: false` and `persistence.provider: memory` both now resolve to an in-memory SQLite engine (`SQLiteDatabaseStorage(db_path=":memory:")`) instead.

---

## Infrastructure (env-var driven — no hardcoded IPs)

| Service | Env var / Default |
|---|---|
| Ollama | `${OLLAMA_BASE_URL:-http://localhost:11434}` |
| PostgreSQL | `${POSTGRES_HOST:-localhost}:5432` (databases: `k9aif` schema `k9aif`, EOC uses `eoc` schema `eoc`) |
| Kafka / Redpanda | `${KAFKA_BROKER:-localhost:9092}` |
| Neo4j | `${NEO4J_URI:-bolt://localhost:7687}` |
| Docling OCR | `${DOCLING_ENDPOINT:-http://localhost:5001/v1/parse}` |
| Object Storage (S3/MinIO) | `${S3_ENDPOINT_URL:-http://localhost:9000}` (credentials via `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`) |

`K9_ENV` environment variable controls governance enforcement: `development` / `test` permit NoopGovernance; `production` / `staging` cause `enforce_governance()` to raise.

### Zero Trust execution layer

`BaseOrchestrator` includes an opt-in Zero Trust guard (`k9_security/zero_trust/`). Enable via `enable_zero_trust: true` in config or constructor. When enabled, `apply_zero_trust(payload, ctx)` evaluates a `DefaultZeroTrustGuard` before flow execution — denied payloads raise before any squad runs. The guard, context builder, and enforcers are pluggable.

### Session management

`BaseOrchestrator` auto-wires session management when `session.enabled: true` in config. `_bootstrap_session(config)` creates a session manager; `_enrich_with_session(payload)` and `_update_session(payload, result)` are called around flow execution. `SessionFactory` selects the backend. Sessions are optional — no config key means no session overhead.

### MCP (Model Context Protocol) layer

K9-AIF includes a full MCP client ABB stack for calling external tool servers:

| Component | Path | Role |
|---|---|---|
| `MCPHttpConnector` | `k9_core/integration/mcp_http_connector.py` | HTTP/HTTPS MCP client |
| `MCPStdioConnector` | `k9_core/integration/mcp_stdio_connector.py` | stdio MCP client |
| `BaseMCPAgent` | `k9_core/agent/base_mcp_agent.py` | Abstract base for MCP-aware agents |
| `MCPClientAgent` | `k9_agents/integration/mcp_client_agent.py` | Concrete MCP agent SBB |

The **Docling OCR MCP server** at `${DOCLING_ENDPOINT:-http://localhost:5001/v1/parse}` is the live tool server for document intelligence. It converts PDF, DOCX, and images to clean Markdown (tables, layout preserved), which agents consume as prompt context. `DocumentExtractorAgent` in the EOC connects to Docling via `MCPHttpConnector` — the connector type is config-driven, so any MCP-compatible tool server can be substituted without touching squad or orchestrator code.
