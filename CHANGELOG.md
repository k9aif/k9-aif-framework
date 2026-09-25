# Changelog

All notable changes to K9-AIF are documented here.

---

## [1.12.5] — 2026-09-25

Documentation and project-context release: no runtime behaviour changes to
any framework component.

### Changed

- **`k9aif --context-init` now writes an accurate `k9aif_context.md`** (the file a new project's `CLAUDE.md` imports). The previous template's governance example called only `enforce_governance()`, which runs no checks, so an agent written from it got no Shield protection. The template now covers:
  - the real hook pattern (`_run_coro_sync(self.apply_pre_governance(...))`, and `apply_shield()` in orchestrators);
  - Shield config with explicit ingress/egress check lists — `enabled: true` alone blocks nothing;
  - Zero Trust;
  - the Kafka-ownership and HIL rules;
  - MCP usage (`streamable_http` for hosted servers);
  - the absolute paths of the installed `CLAUDE.md` / `SKILLS.md`.
- **Packaged `CLAUDE.md` and `SKILLS.md` refreshed** (`k9_aif_abb/CLAUDE.md`, `k9_aif_abb/SKILLS.md` in the wheel):
  - async governance hooks silently check nothing if called un-awaited from sync code;
  - the Shield default-off config, and the empty-check-list trap;
  - the HIL compare-and-swap resume order (G-16) and the open G-18 window;
  - HIL request fields not yet passed (TTL, PII, role, `artifacts`);
  - new MCP-transport and model-router sections;
  - a Reference section replacing the deleted `old-CLAUDE.md`.
- `SKILLS.md`'s governance recipe used `run_until_complete`, which raises inside a running event loop (FastAPI); it now uses `_run_coro_sync`.

603/603 full suite passing, zero regressions.

---

## [1.12.4] — 2026-09-25

### Fixed

- **1.12.3's `MCPStreamableHttpConnector` failed on a clean install with the current MCP SDK (2.x).** Caught by installing `k9-aif[mcp]==1.12.3` from PyPI into a fresh virtualenv: `mcp>=1.10` resolves to `mcp 2.2.0`, a new major line, while 1.12.3 was developed and tested against `mcp 1.26`. Three breaks, all fixed:
  - `MCPClientConnectionFactory.bootstrap()` imported every built-in connector eagerly, including `MCPHttpConnector`, which needs `httpx` — not a k9-aif dependency, and no longer pulled in by the MCP SDK (2.x moved to `httpx2`). So `get("streamable_http")` raised `ModuleNotFoundError: httpx`. Built-ins are now registered by import path and imported only when that transport is requested.
  - The connector built its timeout with `httpx.Timeout`; it now uses whichever HTTP library the installed SDK's own client factory uses (`httpx` on 1.x, `httpx2` on 2.x).
  - SDK 2.x renamed result fields to snake_case (`is_error`, `structured_content`); the connector read only the 1.x camelCase names, so on 2.x a failed tool call was returned as data and structured results were missed. Both spellings are now read.
- Tests now run on both SDK lines (the in-process server uses 2.x `MCPServer` or 1.x `FastMCP`, whichever is installed) and no longer import `httpx` at module level. Verified: 20/20 on `mcp 1.26`; 19 passed + 1 skipped (the `MCPHttpConnector` comparison, which needs `httpx`) on `mcp 2.2` in a clean venv; the live test passes against a deployed MCP server on both. 603/603 full suite passing.

**Note:** use `1.12.4`, not `1.12.3`, with the `mcp` extra.

---

## [1.12.3] — 2026-09-25

### Added

- **G-24: `MCPStreamableHttpConnector` — the framework can now call hosted, standards-compliant MCP servers.** Until now the only HTTP connector, `MCPHttpConnector`, spoke a REST convention (`GET /tools`, `POST /tools/call` with `{name, arguments}`) and never performed the MCP `initialize` handshake, so it got a 404 from any server speaking the standard MCP streamable-HTTP transport (e.g. one built with the official SDK's `FastMCP`, served at `/mcp`). The framework's other MCP connectors speak the real protocol but only over stdio. Solutions reaching a deployed MCP server had to call the official SDK directly, outside the framework. The new connector (`k9_core/integration/mcp_streamable_http_connector.py`) wraps the official SDK's streamable-HTTP client behind the same `connect` / `list_tools` / `call_tool` / `close` shape as the existing connectors:
  - config: `url` (or `base_url`), optional `api_key` (Bearer), `headers`, `timeout`, `sse_read_timeout`;
  - `call_tool` returns the tool's structured content, falling back to JSON parsed from its text content; FastMCP's `{"result": ...}` wrapper around generic return types is removed only when the text content confirms it is a wrapper;
  - a tool call the server marks `isError` raises `MCPToolError` instead of returning an error payload as if it were data;
  - one MCP session per call, because the SDK's transport uses task-bound anyio cancel scopes — a session opened in `connect()` and closed in `close()` fails once those run in different asyncio tasks;
  - uses the SDK's current `streamable_http_client` when present, falling back to `streamablehttp_client` on older SDKs.
- **New optional extra `mcp`** (`pip install "k9-aif[mcp]"`, `mcp>=1.10`), also included in `all`. The SDK is imported lazily, so the framework imports without it.

### Fixed

- **`MCPClientConnectionFactory` had an empty registry** — `bootstrap()` registered nothing, so `get()` could only return connectors a solution registered itself. `bootstrap()` now registers the built-in transports `streamable_http`, `http` and `stdio` (never overriding a name a solution already registered), and `get()` bootstraps on first use. `get()` also no longer reports a `KeyError` raised inside a connector's constructor as "Unknown MCP client".
- **`k9_mcp` package docstring** showed `MCPClientConnectionFactory.from_config()` / `get_connection()`, neither of which exists; replaced with the real `get()` API.

18 new tests (`test_mcp_streamable_http_connector.py`): result unwrapping and config against a fake session; the real protocol against a FastMCP server started in-process on a free port (list, call, generic-return unwrapping, tool error, repeated calls across event loops, and `MCPHttpConnector` failing against the same server); plus an optional live test run when `MCP_SERVER_URL` is set, which passes against a deployed containerized MCP server. 602/602 full suite passing, zero regressions.

---

## [1.12.2] — 2026-09-24

### Fixed

- **G-19 (critical): `K9EventBus.subscribe_async(pattern=…)` raised `TypeError` against a real broker.** The prior implementation called `AIOKafkaConsumer(pattern=re.compile(pattern), ...)` — aiokafka's constructor has no `pattern` parameter on any version; pattern subscription is `consumer.subscribe(pattern=...)`, called after construction. Impact: `K9EventRouter.listen_for_hil_replies()` failed on real Kafka, so no HIL reply was ever consumed and paused flows never resumed. Missed by this framework's own `test_hil_roundtrip.py`, which fakes the message bus and never exercises this method's real aiokafka call — caught only by a live-integration test against real Redpanda. Fixed: construct the consumer without `topics`/`pattern`, then call `consumer.subscribe(pattern=...)` or `consumer.subscribe(topics=...)` before `start()`. Also added a configurable `metadata_max_age_ms` (default 3000ms, was implicitly aiokafka's 5-minute default), since the long default delays discovering a topic created after the consumer started — e.g. the first `hil.replies.<queue>` for a queue nobody's escalated to yet.
- **G-20 (high): `PostgresDatabaseStorage` failed on a clean install** with `ModuleNotFoundError: psycopg`. `sqlalchemy>=2.0` (no upper bound) resolves 2.1 on a fresh install, and SQLAlchemy 2.1 changed the default driver for a bare `postgresql://` URL from psycopg2 to psycopg (v3) — but the framework's own `postgres` extra ships only `psycopg2-binary`. Fixed by naming the driver explicitly (`postgresql+psycopg2://`, matching what the extra actually installs) rather than switching the extra to psycopg v3 — smallest fix that closes the gap between what's installed and what the URL asks SQLAlchemy to load. Configurable via `postgres.driver` in config for anyone with psycopg v3 installed by other means.

### Documentation

- **G-17: `SKILLS.md` Skill 13 described an older provider-adapter pattern than the code.** It said `LLMFactory.register("name", SomeBaseLLMSubclass)` was the whole mechanism — `BaseProviderAdapter`/`ProviderAdapterRegistry` is a real layer that already sat between `LLMFactory` and every OOB adapter (ollama, openai, openai-compatible, azure-openai, watsonx, mock) before this release, undocumented. Refreshed from the actual current code.

### Deferred

- **G-18** (make `_on_hil_reply()`'s resolve→route sequence crash-safe via a `pending → resuming → resolved` state plus a stale-row recovery sweep) — real scope, not small: needs new Router-side sweep infrastructure this framework doesn't have yet. Left for 1.13 rather than rushed into this release.

18 new tests (`test_k9_event_bus_subscribe_async.py`, `test_postgres_database_storage.py`), 584/584 full suite passing, zero regressions.

**Note:** `1.12.0` was yanked from PyPI — it shipped before G-16 (a separate reply-idempotency bug, fixed in `1.12.1`) was known. Anything pinning this framework should use `1.12.2`, not `1.12.0` or `1.12.1`.

---

## [1.12.1] — 2026-09-24

### Fixed

- **G-16: HIL reply resolution wasn't actually idempotent.** `get_hil_pending()` had no status filter — it returned a `hil_pending` row whether it was `"pending"` or `"resolved"`. `_on_hil_reply()` only checked whether a row existed at all, never whether it was still pending, before re-routing. A duplicate reply — Kafka's own at-least-once redelivery on a consumer-group rebalance, or a race between the outbox's immediate publish attempt and its retry sweep both landing a message on the topic (k9x-hil) — re-routed an already-resumed flow a second time. Fixed: `resolve_hil_pending()` is now an atomic compare-and-swap (`UPDATE ... WHERE correlation_id=? AND status='pending'`, returns whether exactly one row changed) instead of an unconditional update with no return value; `_on_hil_reply()` calls it *before* building the resumed payload and only re-routes if it returns `True`. Also closes a second latent bug for free: two Router instances racing on the same reply now correctly have only one of them win.

New test proves a duplicate reply resumes a flow exactly once. 570/570 full suite passing.

---

## [1.12.0] — 2026-09-24 — YANKED, see 1.12.2

### Added

- **`AzureOpenAIProviderAdapter` + `AzureOpenAILLM` (G-4)** — registered OOB as backend `azure-openai` in `ProviderAdapterRegistry`. Motivated by direct evidence, not speculative provider coverage: a live IBM Process Studio blueprint resolved its actual tech stack to "Azure OpenAI GPT-4o, Azure tenant." Routes by deployment name (Azure's real routing model — passed as `model=` per-request, not baked into the client at construction); credential resolution mirrors `OpenAIProviderAdapter`'s exact order for consistency. 38 new tests (invocation, timeout, 429, malformed/empty responses, `system_prompt=None` acceptance).

569/569 full suite passing at release time.

**Yanked 2026-09-24:** shipped before G-16 (see `1.12.1`) was discovered — a duplicate HIL reply could re-route an already-resumed flow. Use `1.12.2`.

---

## [1.11.0] — 2026-09-24

### Added

- **HIL (Human-in-the-Loop) round trip** — `RequiresHIL` (`k9_core/orchestration/hil_signal.py`), a first-class exception an Agent or Squad raises to trigger a human decision mid-flow, rather than a return-value flag a Squad author has to remember to check. Propagates by exception through the existing Agent → Squad → Orchestrator call chain; only the catching Orchestrator ever touches Kafka (a deliberate, documented carve-out of the Kafka-ownership rule — see `CLAUDE.md`'s HIL section for why that's a consistency requirement, not layering purity).
- **`BaseHILOrchestrator`** — a real, invocable Orchestrator (`BaseOrchestrator.handle_requires_hil()` delegates to it — a second deliberate carve-out, "Orchestrators don't call other Orchestrators," chosen so Studio's own "HIL Orchestrator" canvas component maps onto something actually invocable). Publishes `hil.requests.<queue>`, persists a new `hil_pending` table via `RoutingStateStore` (correlation_id, which orchestrator/module to resume, the resume payload — not just a topic name), returns `pending_hil` immediately. Never blocks — a HIL review can take hours or days.
- **`K9EventRouter.listen_for_hil_replies()`** — one consumer, pattern-subscribed across every `hil.replies.*` topic (`K9EventBus.subscribe_async()` gained `pattern=` support), not one process per orchestrator type — job-id belongs in the message (`correlation_id`), never the topic name. Resolves by `correlation_id` against `hil_pending` and re-routes the resumed payload through the Router's own `route()` — resuming is just re-routing with new information now available, not a second mechanism.

### Fixed

- `execute_squads()`'s parallel-execution path wrapped squad execution in a bare `except Exception`, which would have silently converted a `RequiresHIL` signal into a generic `"failed"` result — now special-cased to propagate instead.

New: `test_hil_roundtrip.py`. 552/552 full suite passing.

---

## [1.10.8] — 2026-09-19

### Added

- **`k9_utils/trace_events.py`** — a shared observability event bus
  (`register_trace_callback`/`emit_trace_event`). Generalizes what was
  previously a private, LLM-call-only callback inside `llm_invoke.py`
  (kept as a backward-compatible re-export) so `ShieldGovernance` (full
  per-check pass/flag/block/not-reached breakdown, previously computed
  then discarded after logging), `GuardianGovernance` (pre/post LLM
  calls, with verdict), and `BaseOrchestrator.apply_zero_trust()` all
  emit through it too. Built for an application to get a real, structured
  trace of a run — no log-scraping required.
- `VulnerabilityChain.check_names` — names of every check configured in
  a chain, in run order, including ones that never ran because an earlier
  check blocked. Lets a trace consumer distinguish "ran and passed" from
  "never reached."

### Fixed

- **`ToolArgumentCheck`'s "Subshell injection" pattern matched any pair of
  backticks, including a markdown code fence** — LLM output wrapping
  JSON/code in ` ```json ... ``` ` was flagged as a subshell injection
  attempt, blocking completely benign runs. Fenced blocks are now
  stripped before matching; real backtick/`$(...)` command injection
  still blocks. Confirmed live against a real generated scaffold's
  Anomaly Detection flow, not just a unit test.
- `llm_invoke`'s `LLMCall` trace event now resolves the actual model name
  from config (e.g. `granite3-dense:8b`) instead of the router's catalog
  alias (`"reasoning"`), handling both the dict-shaped and flat-string
  model-catalog config formats.

546 → 549 framework tests pass (2 new since 1.10.7: `test_tool_argument_check.py`,
plus 3 new `ShieldGovernance` trace-event tests).

---

## [1.10.7] — 2026-09-19

### Fixed

- **k9x_Shield was configured but never invoked on the two most commonly
  generated agent patterns.** `BaseValidationLoopAgent.execute()` and
  `BaseCriticActorAgent.execute()` never called `apply_pre_governance()`/
  `apply_post_governance()` — every generated agent constructs
  `ShieldGovernance` in `__init__` and it simply sat there, configured and
  inert, regardless of `security.shield.enabled`. `execute()` on both
  classes renamed to `_execute_loop()` (logic unchanged) and wrapped with
  real governance calls; a blocked payload never enters the loop (zero LLM
  cost); egress scans only the agent's actual output, never the full
  result dict — `steps[]`/`evidence[]` legitimately duplicate content
  across iterations by design (audit trail) and made
  `SemanticDriftCheck`'s loop-trap heuristic false-positive on completely
  benign multi-iteration runs, confirmed against a real generated
  scaffold, not a hypothetical.
- **`ProfanityGovernance` replaced outright, not patched again.** Already
  had three rounds of fixes in 1.9.0 (await bug, wrong `LLMFactory`
  method, contract shape) that didn't catch the deeper problem: it read
  `payload.get("text", "")` (generated agents use `"query"`, so it always
  saw an empty string) and checked for a `"SAFE"`/`"BLOCKED"` free-text
  response format that `granite4.1-guardian:8b` never actually produces —
  confirmed the real model always answers `<score>yes|no</score>`
  regardless of prompt wording. Its own test suite mocked exactly those
  wrong assumptions, so it kept passing while remaining non-functional
  against the real model. Now an alias for the new `GuardianGovernance`
  (see Added below) — every existing call site (both generator templates,
  every already-generated scaffold) keeps working unchanged and starts
  actually working.
- **PyPI package shipped zero `.md` files, ever, including the entire
  `k9_security/docs/` set and the Claude Agent SDK adapter's own
  `CLAUDE.md`.** `package-data` only listed `**/*.yaml`/`**/*.json`/
  `**/*.sql`. Confirmed by inspecting the already-published 1.10.6 wheel
  directly — 0 `.md` files present. Added `**/*.md`. Root-level
  `CLAUDE.md`/`SKILLS.md` are outside the `k9_aif_abb` package tree
  entirely (so no `package-data` glob could ever reach them) — added as
  symlinks (`k9_aif_abb/CLAUDE.md` → `../CLAUDE.md`,
  `k9_aif_abb/SKILLS.md` → `../SKILLS.md`), verified the build correctly
  dereferences them to real content, not broken links. A `pip install
  k9-aif` now carries the same context a git checkout does — the point
  being a Solutions Architect opening a generated scaffold in an IDE with
  a coding assistant gets the framework's own governance/security
  documentation automatically, not just the source.

### Added

- **`GuardianGovernance`** (`k9_governance/guardian_governance.py`) — real
  semantic governance via Granite Guardian (`granite4.1-guardian:8b`),
  promoted from `k9x-ecosystem/k9x_satan` where it was built and proven
  first against a real attack suite (same one-way harvesting process
  already used for 5 vulnerability checks in 1.9.0). Correctly parses the
  model's actual `<score>yes|no</score>` output format. Proper
  `on_unavailable` policy (`fail_closed` default | `fail_open` |
  `inconclusive`) — a timeout/HTTP-error/unreachable Ollama never silently
  becomes "SAFE." Verified live against a real endpoint: a fully
  paraphrased social-engineering attempt with zero Shield regex keywords
  was correctly blocked — the paraphrase-evasion coverage pattern-matching
  structurally cannot provide.
- **`BaseOrchestrator.apply_shield()`** — mirrors `apply_zero_trust()`'s
  shape. Most generated scaffolds have no Router layer at all (confirmed
  absent in a real generated AP scaffold); the Orchestrator is the actual
  outermost boundary, and previously had no Shield gate of its own, only
  Zero Trust's.
- **`k9_utils/guardian_check.py`** — startup-time check: is the
  configured Guardian model actually pulled on the configured Ollama
  endpoint? Doesn't raise on its own (callers decide what "not available"
  means for them) but is meant to be the first thing a solution's entry
  point checks, before anything else runs.
- **`test_framework.sh`** (renamed from `test_squads.sh`, which already
  ran the full suite despite its name) — `pytest k9_aif_abb/tests -v`.

---

## [1.10.0] — 2026-07-27

### Added

- **Claude Agent SDK adapter** (`k9_adapters/claude_agent_sdk/`) — OOB adapter parallel to `k9_adapters/crewai/`, built against the installed SDK's own source rather than assumed behavior. Conformance tier is action-governed, not fully-governed (deliberate — documented in the package's own `CLAUDE.md`). The adapter owns tool registration: the SDK receives only adapter-wrapped tools via one `create_sdk_mcp_server()` call — it never accepts a pre-built `ClaudeAgentOptions` the way `CrewAIOrchestratorAdapter` accepts a pre-built crew. Every tool call routes through `can_use_tool` into `apply_post_governance()` (k9x_Shield's egress chain when configured), confirmed live with a real per-tool-call egress event firing before the tool handler executes. New `claude-agent-sdk` optional-dependency extra (`pip install k9-aif[claude-agent-sdk]`), following the same lazy-import pattern as the `crewai` extra.

### Fixed

- **`CrewAIOrchestratorAdapter`-parallel `ClaudeAgentSdkOrchestratorAdapter` publish call** — used `publish_event(event)`, a `BaseAgent`-only method; `BaseOrchestrator` only has `publish_status(status, context)`. Raised `AttributeError` on the first live call.
- **`query()` string-prompt path was never actually reachable** — the SDK requires `prompt` as an `AsyncIterable[dict]`, not `str`, whenever `can_use_tool` is set, and this adapter always sets it. Fixed by building the same single-message streaming shape the SDK's own string-prompt branch constructs internally.
- **Per-tool-call governance gate was silently bypassed** — `allowed_tools` containing a tool's bare qualified name (`mcp__<server>__<tool>`, no `(...)` specifier) is a whole-tool allow rule that the SDK auto-approves before `can_use_tool` is ever consulted. The adapter's core claim — "every tool call is gated" — was false in the shipped code; the first live run showed no per-tool-call egress event, only the final-output one. Fixed by dropping `allowed_tools` from `_build_options()` entirely: `mcp_servers` alone makes a tool exist/callable, and with no whole-tool rule present every call correctly falls through to `can_use_tool`.

---

## [1.9.0] — 2026-07-18

### Added

- **Five new OOB vulnerability checks** (`k9_security/vulnerability/checks/`) — `ToolAuthorizationCheck` (approved-tool/backend allowlist), `MemoryPoisoningCheck` (fabricated/contradicted session memory, cache-backed), `SystemPromptLeakageCheck` (agent echoing its own system prompt), `OutputSanitizationCheck` (HTML/JS/template injection in output), `RequestFrequencyCheck` (per-session rate limiting, cache-backed). All five were proven first as local checks in the K9x Satan adversarial test project, then generalized and promoted into the framework once verified — closing OWASP LLM03/04/05/07/10 and ASI02/04/06 coverage gaps. Registered in `ShieldGovernance`'s check registry; not enabled by default (each needs solution-specific config — see `k9_security/docs/06-configuration-guide.md`).
- **`RoleBasedAuthorizationGuard`** + **`BaseAuthorizationGuard`** (`k9_security/zero_trust/guards.py`) — the Zero Trust layer's first identity/privilege evaluator. Reads `IdentityContext.roles` (previously captured but never evaluated) against a configurable `role_policy` mapping of `action_type -> [allowed roles]`. Wired into `DefaultZeroTrustGuard` via a new `authorization_guard` constructor parameter, evaluated right after the compromise guard. No policy configured for an `action_type` means allowed (opt-in restriction, not a new default-deny).
- **`ShieldGovernance` per-check config threading** — `security.shield.check_config` in `config.yaml` now threads constructor overrides (`max_chars`, `block_on_match`, `extra_patterns`, etc.) into each OOB check, previously reachable only via direct Python instantiation.
- **`VulnerabilityChain(fail_open=...)`** — a check that raises an exception now has a configurable policy: `fail_open=True` (default, unchanged behavior) converts it to a FLAG; `fail_open=False` converts it to a BLOCK instead, for deployments that consider a crashing security check a fail-closed event rather than a fail-open one.
- **`K9EventBus` SASL/TLS support** — new `security_protocol`/`sasl_mechanism` constructor parameters (default `PLAINTEXT`/`PLAIN`, byte-identical to prior behavior). `MessageFactory` threads `messaging.security_protocol`/`messaging.sasl_mechanism` from config; credentials come from `KAFKA_SASL_USERNAME`/`KAFKA_SASL_PASSWORD` environment variables only.
- **Security documentation set** (`k9_security/docs/`) — capability inventory, OWASP LLM Top 10 crosswalk, OWASP Agentic Top 10 crosswalk, gap analysis, architecture overview, configuration guide, extension guide, and design rationale for the full `k9_security` subsystem.
- **`PIIRequestCheck`** (`k9_security/vulnerability/checks/`) — detects a request/instruction soliciting disclosure of sensitive fields (SSN, DOB, bank account + routing number, credit card, driver's license, passport), as distinct from `PIIBoundaryCheck`, which only catches literal PII values already present. Found via a live attack: a "compliance audit" document asking that full SSN/DOB/account numbers be included in the response contains no PII itself, so no existing pattern-based check caught it. Requires both a solicitation phrase and a sensitive-field mention to co-occur, reducing false positives on legitimate text that merely references a field name. Registered in `ShieldGovernance`.

### Fixed

- **`ProfanityGovernance` contract shape** — `pre_process()`/`post_process()` returned `{"status": "BLOCKED"|"SAFE", ...}` instead of the payload dict every other `BaseGovernance` implementation returns; a BLOCKED verdict now raises `PermissionError` instead of silently replacing the payload.
- **`ProfanityGovernance.__init__` crashed on construction** — `LLMFactory().create(...)` called a method that doesn't exist (`LLMFactory` has no `create`, only classmethods); fixed to `LLMFactory.get(...)`.
- **`ProfanityGovernance.pre_process` never awaited its LLM call** — `self.llm.generate(...)` is `async def`; the missing `await` meant `result` was an unawaited coroutine, and `result.upper()` would have raised `AttributeError` the first time this path actually ran.
- **`GovernanceAgent.__init__` crashed on construction** — same class of bug as `ProfanityGovernance`: called `LLMFactory.from_config(...)`, a method that doesn't exist. Every construction silently caught the `AttributeError` and fell back to a `StubLLM` that always returned `"safe"`, so the "LLM-based reasoning guard" never actually called an LLM. Now constructs `OllamaLLM` directly.
- **`GovernanceAgent.pre_process`/`post_process` never awaited the LLM call**, and `post_process` always collapsed the payload into `{"answer": text}` regardless of safe/unsafe, never matching the payload-dict contract every other `BaseGovernance` implementation follows. Redaction now applies recursively to the payload dict in place instead of stringifying the whole payload.
- **`PromptInjectionCheck`'s default patterns missed multi-qualifier phrasing** — e.g. `ignore\s+(previous|all|prior)\s+instructions?` only permitted one qualifier word between the trigger and target word, so "ignore all previous instructions" (two qualifiers) — arguably the single most common phrasing of this attack — was never matched. Confirmed via a live attack document that reached the agent layer as an uncontained Finding despite containing this exact phrase, plus "You are now in administrative override mode" and "[SYSTEM OVERRIDE]", neither of which matched any of the 10 existing patterns either, for the same single-word-gap reason. Broadened the affected patterns and added system/administrative-override and without-validation-checks patterns the exhibited document also used.

---

## [1.8.2] — 2026-07-17

### Added

- **`WatsonxLLM` + `WatsonxProviderAdapter`** (`k9_core/inference/watsonx_llm.py`, `watsonx_provider_adapter.py`) — OOB IBM watsonx.ai backend. IAM token exchange (cached per instance), `project_id`, region-specific base URL, real REST calls via `aiohttp`. Registered as a `ProviderAdapterRegistry` default alongside `ollama`/`openai`/`openai-compatible`.
- **`openai` optional dependency extra** — `pip install k9-aif[openai]` for the `openai` SDK the `OpenAIProviderAdapter` lazily imports.

### Fixed

- **`OpenAILLM.generate()` missing `system_prompt` parameter** — `K9ModelRouter.invoke()`/`ainvoke()` always call `generate(prompt, system_prompt=...)`; `OpenAILLM` lacked the parameter and raised `TypeError` on every real call. Now accepts it and forwards it as a `system` role message.
- **`K9ModelRouter.invoke()` crashed inside a running event loop** — `asyncio.run()` cannot nest inside an already-active loop, which is exactly the situation for any solution embedding K9-AIF inside an async web framework (FastAPI, etc.). Added `_run_coro_sync()`, which detects a running loop and falls back to a worker thread with its own loop. Silent failure mode previously: agent code's broad `except Exception` swallowed the `RuntimeError` and returned stub output with no visible error.
- **`ModelRouterFactory._build_router_state_store()` incompatible with `MemoryPersistence`** — `persistence.enabled: false` and `persistence.provider: memory` both constructed `RoutingStateStore(MemoryPersistence())`, but `RoutingStateStore._init_tables()` unconditionally requires `.metadata`/`.engine` (SQLAlchemy), which `MemoryPersistence` doesn't provide — every call raised `AttributeError`. Both now resolve to an in-memory SQLite engine (`SQLiteDatabaseStorage(db_path=":memory:")`) instead, preserving the "no disk I/O" intent of disabled persistence.

---

## [1.7.0] — 2026-07-05

### Added

- **`BasePromptEvaluator`** (`k9_core/evaluation/base_prompt_evaluator.py`) — ABB contract for development-time prompt evaluation. Defines `evaluate()`, `compare()`, and `run_suite()` as the standard interface for grading authored prompts before they enter a workflow.
- **`K9PromptEvaluator`** (`k9_agents/evaluation/k9_prompt_evaluator.py`) — OOB LLM-as-judge SBB. Scores five weighted dimensions: correctness (35%), completeness (25%), format compliance (15%), clarity (15%), relevance (10%). Grade scale A–F; configurable PASS threshold (default 70). Judge calls tagged with `metadata["operation"] = "evaluate"` for separate telemetry tracking.
- **`EvaluationFactory`** — config-driven factory following the standard K9-AIF provider adapter pattern. `provider: k9` selects `K9PromptEvaluator`; custom SBBs register via the same factory.
- **`EvaluationResult`, `DimensionScore`, `ComparisonResult`, `SuiteResult`, `PromptTestCase`** — typed models for all evaluation operations.
- **K9Chat evaluation toggle** — topbar toggle in the K9Chat reference application. When enabled, every response is graded in real time; grade pill (A–F), score, verdict, and per-dimension rationale appear beneath each message.

---

## [1.6.0] — 2026-06-23

### Added

- **`BaseLLM.generate()` system prompt support** — `InferenceRequest.system_prompt` flows through the full inference chain: `llm_invoke` → `K9ModelRouter` → `LLMFactory` → `OllamaLLM.invoke()`. All existing call sites are unaffected (backwards compatible).
- **Streaming LLM responses** — `BaseLLM.generate_stream()` ABB (optional override, degrades gracefully), `K9ModelRouter.ainvoke_stream()`, and `llm_invoke_stream()` async generator utility. Config-driven (`chat.stream: true`), additive — no changes to batch inference path.
- **K9Chat redesign** — conversation memory (Redis/in-memory session), runtime provider settings UI, guardrails toggle, streaming token-by-token output, dark/light theme.

---

## [1.5.0] — 2026-06-17

### Added

- **`BaseOrchestrator.execute_squads()`** — run 1 or more squads sequentially or in parallel (`parallel=True`). Results are namespaced by `squad_id`. Single-squad workflows continue to use `execute_flow()` unchanged.

---

## [1.4.0] — 2026-06-13

### Added

- **`BaseObjectStorage` ABB** (`k9_core/storage/base_object_storage.py`) — provider-agnostic contract: `upload()`, `download()`, `get_uri()`.
- **`S3ObjectStorageAdapter`** — OOB adapter for S3 and MinIO. Credentials from `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` env vars.
- **`LocalObjectStorageAdapter`** — default zero-dependency adapter for development.
- **`ObjectStorageFactory`** — `provider: local | s3 | ibm` in config; lazy imports for optional `boto3` / `ibm-cos-sdk` dependencies.
- **`BaseRouter` object store integration** — Router stores incoming documents in the object store and publishes a `document_uri` in the domain event. Downstream agents download by URI via `ObjectStorageFactory`.

---

## [1.3.0] — 2026-06-12

### Added

- **`K9PlanningLoopAgent`** (`k9_agents/planning/k9_planning_loop_agent.py`) — OOB sibling of `K9ValidationLoopAgent` extending `BaseValidationLoopAgent` for dynamic, multi-step planning. Drives an LLM-generated plan with a scratchpad until the task is complete, rather than converging on a confidence score.
- **`ValidationLoopContext` / `Result`** (`k9_agents/validation/models/validation_loop.py`) — additive `remaining_steps` and `notes` fields to support planning-style loops; surfaced via `BaseValidationLoopAgent._to_dict()`.
- **`k9_core/streams`** — K9 Enterprise Context Fabric ABB (Phase 1). Provider-agnostic, governed transport contracts for streaming enterprise context (SAP/CRM/CDC/IoT). Exports `EventEnvelope`, `BaseEventFabric`, `BaseContextStream`, `BaseContextWindow`, `BaseContextProjection`, `EventGovernanceGate`, `NoopGovernanceGate`, `GateDecision`, and `GateResult`. Concrete transports (Kafka, Confluent, IBM Event Streams) remain SBBs; this module defines contracts only.

---

## [1.2.1] — 2026-05-31

### Fixed
- Corrected GitHub repository URLs in `pyproject.toml` (was `k9x-ai`, now `k9aif`).

---

## [1.2.0] — 2026-05-31

### Added

- **`K9EventRouter`** (`k9_core/router/k9_event_router.py`) — OOB Kafka-aware router. Single entry point for all events. Routes deterministically via `routing.table` config; falls back to `intent.in` topic when `event_type` is unknown.
- **`IntentOrchestrator`** (`k9_orchestrators/intent_orchestrator.py`) — OOB Kafka-decoupled intent resolution orchestrator. Consumes `intent.in`, runs `IntentSquad` + `K9IntentAgent` to classify intent, then re-publishes to the correct domain topic or sends a "please clarify" response to `responses.out`.
- **`K9EventBus.publish_to(topic, event)`** — multi-topic publish support for Router and IntentOrchestrator.
- **`routing:` config section** in `k9_aif_abb/config/config.yaml` — defines `intent_topic`, `response_topic`, `confidence_threshold`, and routing `table`.
- **`examples/k9routing/`** — working example demonstrating all three routing outcomes (deterministic, LLM-resolved, clarification) and two SBB override patterns (`ConfigListIntentAgent`, `AcmeIntentOrchestrator`). Runs without Kafka or LLM.

### Changed

- **`config.yaml`** — all hardcoded IPs, credentials, and endpoints replaced with `${ENV_VAR:-default}` placeholders (`POSTGRES_HOST`, `POSTGRES_PASSWORD`, `KAFKA_BROKER`, `OLLAMA_BASE_URL`, `DOCLING_ENDPOINT`).
- **`config_loader.py`** — added `load_dotenv()` so `.env` is automatically applied before config expansion. No code changes required in calling code.
- **`BaseIntentAgent`** and **`IntentSquad`** docstrings corrected — removed "pre-router" terminology; both components are internal to `IntentOrchestrator`, not wired in front of the Router.
- **`orchestrators.yaml`** — replaced obsolete demo stubs with `IntentOrchestrator` entry.
- **`CLAUDE.md`** and **`README.md`** — execution hierarchy updated to reflect Router as the single entry point and `IntentOrchestrator` as a Kafka-decoupled consumer.

### Removed

- **`FrameworkOrchestrator`** — demo stub that never invoked a squad; removed to avoid misleading SBB implementors.
- **`GovernanceOrchestrator`** — demo stub with the same issue; removed.

---

## [1.1.8] — prior release

See [GitHub releases](https://github.com/k9aif/k9-aif-framework/releases) for earlier history.
