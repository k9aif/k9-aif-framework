# CLAUDE.md

Guidance for Claude Code in this repository. Full prior version (extended
config/persistence/MCP/adapter-table reference material) preserved in
`old-CLAUDE.md`. Step-by-step recipes live in `SKILLS.md` — **read it
directly when doing one of those tasks; it is no longer auto-imported here**,
so don't assume its contents are already in context.

## What this is

K9-AIF: architecture-first framework for governed, observable, multi-agent
systems, built on OOA/OOD/TOGAF discipline. ABB (Architecture Building Block)
= abstract contract in `k9_core/`. SBB (Solution Building Block) = concrete
implementation extending an ABB, in `examples/<App>/` or `k9_projects/<App>/`.
Liskov Substitution and Open/Closed are non-negotiable — new capability
extends a `Base<Concern>` contract, never edits one.

Diagrams default to PlantUML. BPMN swim lanes: horizontal bands top-to-bottom,
labels left, activities left-to-right within a lane.

`BaseComponent` does **not** extend `ABC`. An ABB needing both infra
(logging/monitoring/message bus) and enforced abstract methods extends
`(BaseComponent, ABC)` — correct multiple inheritance, not redundant. Never
assume a parent already extends `ABC` without checking.

## Execution hierarchy

```
Event → K9EventRouter → known event_type → domain topic
                       → unknown → intent.in → IntentOrchestrator → domain topic
domain topic → Orchestrator → 1+ Squads → 1+ Agents → LLM
```

**Three-layer decoupling — never violate:** each layer knows only the layer
directly below it. Router imports/references Orchestrators only, never
Squads or Agents. Orchestrator imports Squads only, never Agents. Squad YAML
has no `orchestrator:` field; Agent YAML has no `squad:`/`routing:` fields.
Agent registration happens in the app entry point, not inside the
orchestrator.

Cardinality: Router 1→N Orchestrators, Orchestrator 1→N Squads
(`execute_squads(..., parallel=True/False)`), Squad 1→N Agents (sequential
`flow`).

## LLM calls — one path only

Agents never call `OllamaLLM`/`LLMFactory` directly. Always:

```python
from k9_aif_abb.k9_utils.llm_invoke import llm_invoke
resp = llm_invoke(self.config, InferenceRequest(prompt=..., task_type=...))
```

`llm_invoke` raises `RuntimeError` on failure — it never silently returns
empty output; catch and handle explicitly. Full chain + adding a new
provider: `SKILLS.md` Skills 2 and 13.

**BaseAgent vs K9ValidationLoopAgent vs K9PlanningLoopAgent** — the
generator/scaffold defaults every agent to one-shot `BaseAgent`. Ask per
agent: one-pass answer → `BaseAgent`; iterative convergence on a confidence
score → `K9ValidationLoopAgent`; agent must plan and revise its own steps →
`K9PlanningLoopAgent`. Full recipe: `SKILLS.md` Skill 10.

## Governance

Every agent gets a governance pipeline via `require_governance()` at init.
`K9_ENV=development|test` → `NoopGovernance` permitted (WARNING logged).
`K9_ENV=production|staging` → `enforce_governance()` **raises**
`PermissionError` if governance isn't configured. An agent that never calls
`self.enforce_governance()` in `execute()` silently runs `NoopGovernance`
even in production — the most common real bug in new agent code.

**`enforce_governance()` does not run any checks.** It only asserts that
governance isn't `NoopGovernance` — a "did anyone configure real governance
at all" guard. The methods that actually run checks are
`apply_pre_governance(payload)` / `apply_post_governance(result)`
(`BaseAgent`, and identically on `BaseOrchestrator`/`BaseRouter` — separate,
duplicated methods, not inherited from one place), which call
`self.governance.pre_process`/`post_process`. **Neither is called
automatically by any base class** — every concern (agent, orchestrator,
router) must call them itself, same as `enforce_governance()`. Calling only
`enforce_governance()` gives zero content-level protection even though it
looks like "governance is on."

## Security / Vulnerability (k9x_Shield) and Zero Trust

Two independent, non-overlapping security layers ship in the framework —
know which one a question is actually about before answering it:

**k9x_Shield** (`k9_security/vulnerability/`) — 13 concrete
`BaseVulnerabilityCheck` subclasses (`checks/`: `InputSizeCheck`,
`PromptInjectionCheck`, `PIIBoundaryCheck`, `PIIRequestCheck`,
`SemanticDriftCheck`, `ToolArgumentCheck`, `ToolAuthorizationCheck`,
`ExecutionGuardCheck`, `HardcodedCredentialCheck`, `MemoryPoisoningCheck`,
`SystemPromptLeakageCheck`, `OutputSanitizationCheck`,
`RequestFrequencyCheck`), run in order by `VulnerabilityChain`
(`vulnerability_chain.py`), wrapped by `ShieldGovernance`
(`shield_governance.py`) — a concrete `pre_process`/`post_process`
implementation, i.e. a drop-in `governance=` value for any `BaseAgent`/
`BaseOrchestrator`/`BaseRouter`. A `BLOCK`-status check (or a `FLAG` when
`strict=True`) makes `ShieldGovernance` **raise `PermissionError`** — that
raise is the only block signal; there is no return-value sentinel. A `FLAG`
under `strict=False` (the common config) just logs and lets the payload
through unmodified — `ShieldGovernance` never mutates a passing payload.
`fail_open` (default `True`) controls what happens if a check itself
raises: `True` → treated as FLAG, `False` → treated as BLOCK.

**The checks are correct and well-tested** (`tests/test_shield_governance.py`).
**What is not automatic: nothing calls `apply_pre_governance`/
`apply_post_governance` for you.** `BaseValidationLoopAgent.execute()` and
`BaseCriticActorAgent.execute()` — the two most commonly generated agent
patterns — do not call them anywhere in their loop. A generated agent that
constructs `ShieldGovernance(config=config)` in `__init__` and passes it as
`governance=` gets **zero enforcement** unless its own `execute()` (or an
override) explicitly calls the hooks. Don't assume "this agent has
`ShieldGovernance` wired" means anything is actually being checked — verify
the hooks are called, not just that the object was constructed.

**Zero Trust** (`k9_security/zero_trust/`) — a separate mechanism,
identity/risk/authorization-based rather than pattern-matching-based:
`ExecutionContext` → `BaseZeroTrustGuard.evaluate()` (default
`DefaultZeroTrustGuard`: compromise check → role-based authorization →
data-loss/masking → risk scoring) → `TrustDecision`. Lives on
`BaseOrchestrator` only (`apply_zero_trust()`, not on `BaseAgent`/
`BaseRouter`), gated by `enable_zero_trust` (config key, **defaults
`False`** — `apply_zero_trust()` returns an unconditional
`{"allowed": True, "decision": "BYPASSED", ...}` bypass when off, so
calling it costs nothing when disabled but also protects nothing).
`DefaultZeroTrustGuard`'s built-in `PromptInjectionGuard` is a **plain
substring match** against 6 fixed phrases (`k9_security/zero_trust/guards.py`)
— materially weaker than Shield's regex-based `PromptInjectionCheck`
(handles `ignore (all|any) previous instructions`, `PromptInjectionGuard`
only matches the literal phrase `"ignore previous instructions"` — inserting
one word defeats it). Treat Zero Trust and Shield as additive, not
redundant: Zero Trust's real value is its authorization/risk-scoring/
data-masking machinery (`RoleBasedAuthorizationGuard`,
`SensitiveDataLossGuard`), not its compromise check.

**k9x_satan** (`k9x-ecosystem/k9x_satan`) is the reference implementation
proving these layers actually contain a real attack end-to-end — read its
own `CLAUDE.md` for the full Router-ingress/Orchestrator-egress containment
contract before assuming a generated app gets that containment "for free."
It doesn't, without explicit wiring — satan builds its own.

## Everything is provisioned through factories

Never instantiate directly in application code: `LLMFactory`,
`ModelRouterFactory`, `AgentRegistry`, `OrchestratorRegistry`,
`SecretManagerFactory`, `CacheFactory`, `ObjectStorageFactory`. Every factory
`create(config)` has a zero-config default (env secrets, in-memory cache,
local storage) — no config key required for the common case. Adding a new
provider to any of these: `SKILLS.md` Skill 11.

## Kafka ownership

Only the **Router** (domain topics) and **Orchestrator** (results /
downstream topics) touch Kafka. Agents are constructed without a
`message_bus` — they share data sequentially through the Squad flow, not via
A2A messaging. `publish_event()` on an agent reaches the logger/monitor only.

## Pre-Push Checklist

- Every new `.py` file starts with the two-line header
  `# SPDX-License-Identifier: Apache-2.0` / `# K9-AIF Framework`, before any
  module docstring. Nearly universal in `k9_aif_abb/` but not enforced by
  any hook — check new files by hand; a whole adapter package (CrewAI) went
  missing it for a full release cycle before anyone noticed.
- No hardcoded IPs (`192.168.x.x` etc.) — env vars with localhost defaults:
  `"${POSTGRES_HOST:-localhost}"`, `"${OLLAMA_BASE_URL:-http://localhost:11434}"`
- No credentials in `config.yaml` — secrets in `.env` (gitignored) only
- `.env` never staged; `env-example` is the template
- No `__pycache__`/`.pyc` — `.gitignore` present before first commit
- Three-layer decoupling preserved (see above)
- After any `k9_aif_abb/` change: `./generate_pdoc.sh` (the `./` matters —
  without it, pdoc silently documents whatever `k9-aif` is pip-installed in
  `.venv` instead of the local tree) and commit `docs/pydocs/` in the same
  commit

## Hooks (`.claude/settings.json`, run automatically, exit 2 = blocked)

| Hook | Triggers on | Checks |
|---|---|---|
| `check-python.sh` | any `*.py` write/edit | Python syntax |
| `check-yaml.sh` | any `*.yaml`/`*.yml` write/edit | YAML validity |
| `run-abb-tests.sh` | files under `k9_aif_abb/` | `test_framework.py` + `test_intelligent_model_router.py` |
| `check-governance.sh` | `*.py` under `examples/` | warns if `NoopGovernance` appears |
| `check-init-docstring.sh` | any `__init__.py` | warns if module docstring missing |

## Commands

```bash
# Setup
python3.11 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt

# Tests
pytest k9_aif_abb/tests/ -v                      # all
pytest k9_aif_abb/tests/test_framework.py -v     # framework stability only, no external services

# Run example apps (local)
./run_k9chat.sh
./run_acme_support_center.sh

# EOC (RHEL/Podman) — after git pull, always rebuild; restart alone won't pick up code
bash build.sh && bash run_eoc_pod.sh
sudo podman pod ps
sudo podman logs eoc-app-backend

# Generate a stub app
./k9_generator.sh preview <AppName>
```

## Known gotchas (not obvious from the code alone)

- `K9ModelRouter.invoke()` bridges sync `BaseAgent.execute()` to async
  `BaseLLM.generate()` via `_run_coro_sync()` — never call `asyncio.run()`
  directly there. Inside an already-running event loop (FastAPI etc.),
  `asyncio.run()` raises, and a broad `except Exception` upstream will
  silently swallow it and fall back to stub output.
- Any new `BaseLLM.generate()` implementation must accept
  `system_prompt=None` — `K9ModelRouter` always passes it as a kwarg.
- `persistence.enabled: false` / `provider: memory` must still resolve to a
  SQLAlchemy-capable store — `RoutingStateStore` needs `.metadata`/`.engine`,
  which plain `MemoryPersistence` doesn't provide. Resolves to
  `SQLiteDatabaseStorage(db_path=":memory:")` instead.

## Where the rest lives

Config structure, persistence tables, MCP client stack, session management,
Zero Trust guard, the full Provider Adapter table, and detailed Squad/Agent
YAML examples were trimmed from this file per Anthropic's CLAUDE.md size
guidance (keep only what's needed nearly every session). They're either
self-evident from the source under `k9_aif_abb/`, covered step-by-step in
`SKILLS.md`, or preserved verbatim in `old-CLAUDE.md`.
