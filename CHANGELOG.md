# Changelog

All notable changes to K9-AIF are documented here.

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
