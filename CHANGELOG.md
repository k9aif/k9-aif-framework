# Changelog

All notable changes to K9-AIF are documented here.

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
