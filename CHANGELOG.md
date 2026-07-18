# Changelog

All notable changes to K9-AIF are documented here.

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
