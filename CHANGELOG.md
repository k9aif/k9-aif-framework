# Changelog

All notable changes to K9-AIF are documented here.

---

## [Unreleased] (planned 1.20.0)

### Large events travel as a link

- **An event over 512 KB is stored in object storage and sent as a link.** `K9EventBus.publish()` /
  `publish_to()` upload it to the application's `object_storage` (S3, MinIO, IBM COS, local or your own)
  and publish a small event with `k9_large_event` (uri, bucket, key, size, sha256) plus its routing fields
  (`event_type`, `correlation_id`, `job_id`, `task_id`, `meta`, `topic`). `subscribe()` and
  `subscribe_async()` fetch it back, check the hash and pass the original event to the callback, so
  producers and consumers don't change. Before, the event was replaced by `{"truncated": true}` and sent
  with only a warning: the consumer got an event whose data was gone.
- **Framework default bucket `k9aif-large-events`, objects expire after 30 days.** On first use the bus
  creates the bucket if it's missing and sets a lifecycle rule on the `large-events/` prefix only, merged
  with the bucket's other rules. Override with `messaging.large_events.bucket` / `ttl_days` (`0` leaves
  lifecycle to you). A store that can't set expiry is reported at error level.
- **New optional storage hooks:** `BaseObjectStorage.ensure_bucket()` and `set_expiry()` (defaults: nothing,
  and "not supported"). The S3 and IBM COS adapters implement both (`k9_storage/adapters/s3_lifecycle.py`);
  the local adapter deletes files older than the TTL.
- **Send errors reach the caller.** `publish()` / `publish_to()` no longer catch and log every exception;
  a broker that refuses an event after `send()` is logged at error level. `MessageFactory.publish()` now
  uses the bus (it looked for a `producer` the bus doesn't have) and raises instead of printing.

**Upgrading.** Production applications that may publish events over 512 KB need an `object_storage` block;
without one such an event raises `LargeEventError` (development and test use local files). With S3/MinIO
the credentials need `s3:CreateBucket` and `s3:PutLifecycleConfiguration` on the bucket, or create the
bucket and its rule yourself and set `ttl_days: 0`. Code that relied on publish never raising should catch
the error where it can act on it (the orchestrator, per "failures propagate"). Consumers of the same topic
must run 1.20 or later to read link events.

### Configuration

- **The shipped config no longer opts out of fail-closed Shield.** `k9_aif_abb/config/config.yaml` set
  `fail_open: true`; applications told to copy its check lists carried that opt-out and missed 1.19.0's
  production default. The line is now a comment explaining the default.

---

## [1.19.0] — 2026-10-26

### Failures surface, everywhere

Five places where a failure could pass as success, found in the framework review of 2026-10-25/26. Each
now surfaces, and each has a test that proves it.

- **Parallel squads raise a squad's failure.** `execute_squads(..., parallel=True)` used to turn a failing
  squad into `{"status": "failed"}` in its results and return normally, so an orchestrator reported a
  completed run. Now the other squads finish, then the first failure is raised (as on the sequential path),
  with notes naming the failed and completed squads. `RequiresHIL` still cancels the rest at once.
- **Shield blocks on a crashing check in production.** `security.shield.fail_open` unset now follows
  `K9_ENV`: fail closed in production, fail open (FLAG) in development and test. Before, it was always open,
  so an input that made a check throw passed that check unscreened. An explicit `fail_open` still wins;
  `VulnerabilityChain`'s own default is unchanged.
- **k9x Origin flags a verification it couldn't make.** A `verify_before` step whose system of record
  can't be reached now gets `flags.verification_failed` (`against`, `error`) instead of an answer that
  looked verified. The orchestrator's live-context trace lists it with the other flags.
- **DoclingParser fails as an agent.** `execute()` raises `DocumentConversionError` (with `.result`) when a
  document can't be converted, so a squad never runs its next steps on an empty document. `convert()` and
  `parse()` still return results for callers that inspect them.
- **Inspector K9-LLM-002 checks the right property.** It used to warn on any `llm_invoke()` call outside
  `try/except` and suggest returning a failed result, which is the pattern "failures propagate" forbids. It
  now reports a handler around `llm_invoke()` that catches the failure and carries on (a stand-in result,
  a warning string, `pass`); unguarded and re-raising calls are fine. Title: "Model-call failures are not
  turned into results".

Tests: `test_execute_squads.py`, `test_shield_governance.py` (3), `test_k9x_origin.py`,
`test_docling_parser.py` (4), `test_k9_inspect.py` (2).

### Every configuration used, every outcome reported

The review's medium and low findings.

- **No message bus, no "routed".** `K9EventRouter.route()` and `IntentOrchestrator.execute_flow()` raise
  when there is no message bus, instead of reporting `routed` for an event that went nowhere.
- **One intent threshold.** `IntentSquad` and `IntentOrchestrator` share `DEFAULT_CONFIDENCE_THRESHOLD`
  (0.6) for `routing.confidence_threshold`; before, the squad defaulted to 0.5 and the orchestrator to 0.6.
- **IntentOrchestrator knows only squads.** Its zero-config squad comes from `default_intent_squad(config)`
  in the squad layer; the orchestrator no longer imports or builds `K9IntentAgent`.
- **MonitorFactory uses the configuration it's given.** `create(config)` reads `monitors` and
  `common_tags` from it (the framework default when absent, found by package path) and raises on a monitor
  it can't build. Before, it ignored the argument, read a path relative to the working directory, and on
  any error silently returned an empty monitor. Monitor arguments may be written `params:` or `kwargs:`.
- **PersistenceFactory raises** for an unknown provider or a failing backend instead of returning `None`.
- **Short waits when a model server is down.** `llm_invoke()` waits 5 s between attempts when the server
  can't be reached (connection refused, host not found), and keeps 60 s for an empty reply. Both, and the
  number of attempts, are configurable under `inference.retry` (`attempts`, `delay_seconds`,
  `unreachable_delay_seconds`); explicit arguments still win. Before, an outage cost about two minutes per
  call.
- **k9x Origin tells "down" from "not found".** A read-through whose system of record fails returns
  `source_unavailable` (`system`, `error`) with `found: false`.
- **Critic-actor failures propagate.** A `critique()` exception now re-raises by default
  (`on_critic_error: raise | escalate | fail`), as validation loops have since 1.18.2; before, the default
  was a FAIL result. `escalate_on_critic_error: true` still means escalate.
- **The LLMCall trace names the right model,** resolving the catalog entry's `llm_ref`.
- **Configured but broken is an error.** A router's `object_storage` block, or `session.enabled: true`, that
  fails to build now raises at start-up instead of silently meaning "not configured" (router and
  orchestrator).
- **The squad's digest writer keeps its own identity:** `K9ContextSynthesizerAgent` is built from the
  squad's config, or the first agent's without its role, goal and instructions.
- **Example:** `rfp_analyzer`'s agent YAML names its `module:` and its agent lets a model failure propagate.

Not changed, by design: `OllamaLLM` still reports a failed call as `"[WARN] ..."` text (the model router's
fallback reads it; `llm_invoke()` turns it into an exception).

Tests: `test_review_medium_low.py` (16), `test_k9x_origin.py`, `test_k9_critic_actor_agent.py` (2). Suite:
971 passed. DAS, Arena, Inspector, SATAN, Sentinel and Newswatch suites identical before and after.

### Upgrade notes

- An orchestrator that ran squads in parallel and checked each result's `status` for `failed` now gets the
  exception instead: catch it around `execute_squads()` and record it (DAS `TraceabilityOrchestrator` used
  to report such a run as completed).
- A production Shield config without `fail_open` now blocks when a check crashes. Set `fail_open: true` to
  keep the old behaviour deliberately.
- Code that calls `DoclingParser.execute()` and checks `status` should call `convert(filename, bytes)`
  instead, or catch `DocumentConversionError` (its `.result` is the old return value). DAS `normalize.py`
  does the former check today.
- Agents that wrap `llm_invoke()` and return a "[WARN]" result now get a K9-LLM-002 warning; let the error
  propagate. K9X Studio's agent template is fixed to match.
- A `K9EventRouter` or `IntentOrchestrator` built without a message bus now raises when it dispatches. For
  direct calls without Kafka, use `BaseRouter`.
- Code that compared `routing.confidence_threshold` behaviour against 0.5 (the squad's old default) now
  sees 0.6 unless it sets the value.
- `MonitorFactory.create(config)` now applies `config["monitors"]`; a monitor class that can't be imported
  raises instead of being skipped.
- `PersistenceFactory.create()` raises instead of returning `None`.
- A critic-actor agent whose `critique()` raises now propagates the error. Set `on_critic_error: fail` to
  keep the old result.
- A configured `object_storage` block or `session.enabled: true` that can't be built stops start-up.
- Code that compared an Origin answer's keys exactly sees `source_unavailable` when a read-through fails,
  and `flags.verification_failed` (always present, `None` when it didn't happen).

---

## [1.18.8] — 2026-10-25

### Enhancements

**Local and hosted models in one application.** Each model alias can now name its own backend and
connection settings, so an application can run a local Ollama model for everyday work and a hosted model
(watsonx.ai, OpenAI, Azure OpenAI) for the tasks that need it, from one configuration:

```yaml
inference:
  llm_factory:
    backend: ollama
    models:
      general: "llama3.2:1b"
      auditor:
        backend: watsonx
        model: ibm/granite-3-8b-instruct
        base_url: https://us-south.ml.cloud.ibm.com
```

The model router checks at start-up that each catalog entry's `provider` matches the backend that serves
it, so routing decisions (confidential-only models among them) always reflect where a prompt really goes.
`LLMFactory.get()` now returns the `BaseLLM` contract.

**Production-grade messaging.** A production process now starts only when its Kafka/Redpanda broker is
reachable, and says clearly why if it isn't (`MessagingUnavailableError`), so events are never published
into a bus that cannot deliver them. Development and test keep working without a broker, using an
in-process queue; `messaging.allow_local_fallback: true` makes that a deliberate choice in production too.
The framework also points out shared default topic and consumer-group names, so each application keeps
its messages to itself.

**One clear configuration per process.** The model factory and model router now confirm that a process
runs on exactly the configuration it was given: the same configuration again is reused, an agent's config
without an `inference` section uses the application's, and a conflicting one is reported at once
(`ConfigConflictError`) rather than resolved silently. This makes multi-process deployments (Router,
Orchestrator and API as separate processes) predictable by construction.

**Thread-safe model creation.** Models and routers are created once, even when many requests arrive at
the same moment.

**Cleaner operations and testing.** Structured logging throughout `LLMFactory`;
`k9_aif_abb.k9_factories.reset_all()` gives tests a clean slate between configurations (used
automatically by the framework's own suite); `OrchestrationFactory.reset()`.

New Developer Guide sections: 12.5 "Local and hosted models side by side" and 17.7 "One Application per
Process". 22 new tests (`test_factory_process_safety.py`); 950 passing.

### Upgrading

- Start the message broker before a production process that uses Kafka/Redpanda, or set
  `messaging.allow_local_fallback: true` if in-process messaging is what you want.
- Give each application its own `messaging.topic` and `group_id` (a log line now reminds you).
- Run one application per process, as K9X applications already do. Tests that switch configurations call
  `reset_all()` between them.
- If a model catalog names a `provider`, it should match the alias's backend; the router tells you at
  start-up if not. (All 240 configurations checked across the K9X repositories already match.)

---

## [1.18.7] — 2026-10-22

### Inspector (k9_inspect)

Found by running Inspector on a fresh K9X Studio scaffold and on the K9X applications.

- **K9-GOV-002 checks what the Shield lists hold, not only that they exist.** Before, any non-empty list
  passed, so a config with only `InputSizeCheck` was reported compliant. Now ingress must run
  `PromptInjectionCheck` and egress `PIIBoundaryCheck` (a check built in code counts) — violation.
- **K9-NET-001 (new, warning): API adapters keep agents off internal hosts.** Reports
  `allow_private_networks: true` in YAML or adapter config in code, which turns off 1.18.5's refusal of
  internal addresses for agent-chosen URLs.
- **K9-SUP-001 (new, recommendation): locally served models are pinned by digest.** Lists the Ollama model
  aliases without a `digest` (1.18.6).
- **K9-DEP-002 compares against the latest release on PyPI**, not the k9-aif installed where Inspector runs.
  A host with an old install (K9X Studio's generator was on 1.16.0) reported old pins as up to date.
  Offline, or with `K9_INSPECT_OFFLINE=1`, it falls back to the installed version.

31 rules (was 29). Tests: `test_k9_inspect.py`.

### Upgrade notes

- A solution whose Shield ingress lacks `PromptInjectionCheck` or egress lacks `PIIBoundaryCheck` now fails
  `k9aif inspect --fail-on violation`. `PIIBoundaryCheck` flags by default (it blocks only with
  `block_on_match: true` or `strict: true`).

---

## [1.18.6] — 2026-10-22

### Security

Two holes found by mapping the framework against a six-layer AI security model (supply chain, prompt,
retrieval, inference, output, monitoring).

- **Model digest pinning** (`k9_core/inference/model_integrity.py`, new; wired into `OllamaLLM` and
  `LLMFactory`). A local model server loads weights by tag, and a tag can point at different weights after
  a re-pull, a mirror or host access, with every agent still calling it. A model alias may now pin its
  content digest (`inference.llm_factory.models.<alias>.digest`, from `ollama list`); `OllamaLLM` checks the
  served digest before the first prompt and every `digest_recheck_seconds` (default 300). A different or
  missing digest raises `ModelIntegrityError` (a `PermissionError`) before any prompt is sent, and emits a
  `ModelIntegrity` trace event. Opt-in: a model without `digest` behaves as before. `digest` on a non-Ollama
  backend is a configuration error. `llm_invoke()` no longer retries a `PermissionError` from the router:
  a refusal is a decision, not an outage. Catalog: `model_integrity.digest_pin` (LLM03, LLM04 partial).
- **One trace id per run** (`k9_utils/trace_events.py`: `trace_scope()`, `current_trace_id()`,
  `trace_id_from()`). Trace events had no shared id, so one request's model calls, Shield/Guardian checks,
  tool-result screens, Zero Trust decisions and Origin answers could not be stitched into one execution
  path. `BaseOrchestrator.execute_squads()` and the CrewAI, LangGraph and Claude SDK adapters' `execute_flow()`
  now open a scope; every event inside it carries `trace_id`, taken from the payload's `trace_id`,
  `correlation_id` or `job_id` (so the path continues across processes) or generated. Parallel squads run
  in a copy of the caller's context and share the id. Existing sinks receive one extra key. Catalog:
  `observability.trace_correlation`.

Tests: `test_trace_and_model_integrity.py`.

### Upgrade notes

- Nothing to change. To pin a model: `ollama list`, copy the ID's full digest (`curl $OLLAMA_BASE_URL/api/tags`
  shows all 64 hex characters), add `digest: sha256:<digest>` under that model alias.
- A trace sink that rejects unknown keys must accept `trace_id`.

---

## [1.18.5] — 2026-10-21

### Security

From K9X Sentinel's open findings, each checked against the code before changing it.

- **aiohttp floor raised to 3.14.4** (`requirements.txt` pin 3.13.3 → 3.14.4). OSV lists eight advisories
  affecting 3.14.3, the previous floor (among them GHSA-2g87-pp6c-29x5, unbounded memory/CPU use, and
  GHSA-5wr8-gcqf-gqf3, no initial request/header timeout, both high), and none for 3.14.4. Sentinel #2409.
- **Outbound guard for API adapters** (`k9_adapters/integration/outbound_guard.py`, new; wired into the
  `BaseApiAdapter.execute()` template and `HttpApiAdapter`). Before, `HttpApiAdapter` filled URL placeholders
  from the agent's payload unescaped and requested any host, and `BaseApiAdapter` took the whole URL from the
  payload when none was configured: an agent, or text injected into it, could reach the cloud metadata
  endpoint (credentials), internal services, or another host via `../`, `@` or `?` in a placeholder. Now:
  placeholder values are URL-encoded; link-local and metadata addresses (169.254.0.0/16, fd00:ec2::254,
  100.100.100.200, fe80::/10) are always refused; an agent-chosen URL may reach internal addresses only when
  listed in `allowed_hosts` or `allow_private_networks: true`; a host written in the configured URL keeps
  working as before; `allowed_hosts`, when set, is the complete destination list; redirects are followed by
  the guard and every hop is checked. A refusal raises `OutboundRefused` (a `PermissionError`), never an
  error result. Catalog: `integration.outbound_guard`. Sentinel #1170. Tests: `test_outbound_guard.py`.
- **Squad digests proven screened** (Sentinel #49, self-generated injection in compaction summaries): a
  real squad test shows a digest carrying an injected instruction is refused by the next agent's governance
  and that agent never runs. No code change was needed (governance by construction screens every agent's
  input); the catalog now records it as `squad_digest_screening`.
- **Catalog guidance for agent-written SQL** (Sentinel #74, CVE-2026-65669): `shield.tool_argument` limits now
  state that read-only must be enforced at the database (read-only role or connection), never by prompt or
  regex.

### Upgrade notes

- An adapter used with **no configured `url`** whose agents legitimately call internal hosts must now list
  them in `allowed_hosts` (or set `allow_private_networks: true`). Adapters with a configured URL are
  unaffected, except that link-local and metadata addresses are refused.

---

## [1.18.4] — 2026-10-16

### Security

- **MCP SDK floor raised to 1.30.0** (`k9-aif[mcp]` and the base requirement; `requirements.txt` pin 1.26.0 → 1.30.0). `mcp` 1.28.1, the previous floor, is affected by CVE-2026-59951 / GHSA-84m7-p3x7-pcfv (unbounded session accumulation in the StreamableHTTP transport, resource exhaustion), fixed in 1.30.0. Found by K9X Sentinel's dependency audit (OSV), finding #1985.

Tests: the MCP connector tests and the full suite pass on mcp 1.30.0.

---

## [1.18.3] — 2026-10-16

### Changed

- **k9_inspect recognises the framework itself.** A folder that is K9-AIF (it defines `BaseAgent` in `k9_core/agent/base_agent.py` and carries `k9_inspect`, at the root or under `k9_aif_abb/`) is reported as `scope: framework`, verdict **K9-AIF FRAMEWORK**, with a note and no score; the solution rules are not applied. Inside the framework its base classes are local, not imported, so the rules misread them (13 false "does not extend an agent ABB" findings on `k9_aif_abb`). Solutions and the framework's examples are inspected as before.

Tests: `test_k9_inspect_framework_scope.py` (the package and the repository root are not graded; an example still is).

---

## [1.18.2] — 2026-10-15

### Changed

- **Validation and planning loops let a tool failure propagate.** A `run_validation()` exception in `BaseValidationLoopAgent` (and so `K9ValidationLoopAgent`, `K9PlanningLoopAgent`) is recorded as a step and re-raised by default, so it reaches the squad and orchestrator like any agent's failure (CLAUDE.md "Failures propagate"). Before, the loop returned a FAIL result with output `{"reason": "validation_failed"}`, and a squad carried on with it. New config key `on_tool_error`: `raise` (default) | `escalate` | `fail`; the older `escalate_on_tool_error: true` still means `escalate`. An unknown value raises `ValueError`.

  **Upgrade note:** a loop that relied on FAIL results for tool errors sets `on_tool_error: fail`. Apps that overrode `fail()` to re-raise (DAS `utils/loop_errors.py`) can drop the override.

Tests: `test_validation_loop_agent.py` (raise by default, fail/escalate when configured, older flag, bad value, and a `BaseSquad` flow that stops when the loop's tool fails).

---

## [1.18.1] — 2026-10-14

### Changed

- **Three-layer decoupling, stated by what each layer knows, and enforced.** An orchestrator loads a squad by YAML file and squad id and never names, imports, registers or builds an agent; the squad layer builds the agents each squad YAML names. Test: *if a squad's agents change, the orchestrator is unaffected.* (Registering agents by name, 1.15, already kept agent imports out of orchestrators; this release moves the agent names out as well.)

### Added

- **The squad layer builds a squad's agents.** `SquadLoader.from_agents(agents_dir, config, squad_cls=..., agent_kwargs=...)`, built once at the application entry point and passed to orchestrators as `squads=`, resolves every agent a squad YAML names through `AgentLoader` (`class:` + `module:`). `load_one(path, squad_id, config=..., agent_kwargs=...)` builds only that squad, with an optional per-run config (for example a governance override). A squad keeps the config it was built with (`squad.config`).
- **`BaseSquad.before_step(agent_name, context)`**: a hook before each step's agent runs, for squad-level behaviour in an application's one common `<App>Squad(BaseSquad)` (squads stay YAML).
- **`BaseOrchestrator(squads=...)`**.
- **`AgentLoader.refresh()`**; `resolve_class` re-reads the agent YAML directory once when it meets an unknown agent (a squad gained an agent since start-up).
- **k9_inspect K9-DEC-002 "Orchestrator knows only squads"** (violation): an orchestrator module that names agents or builds an `AgentRegistry` / `AgentLoader`. K9-DEC-001 checks imports only.
- Claude Code hook `check-orchestrator-squads.sh` (every orchestrator edit).

### Updated

- The EOC example follows the squad layer: its seven orchestrators load squads by id; `EOCOrchestrator` loads each squad directly from `config/squads.yaml`; class diagrams show orchestrators → `SquadLoader` → `AgentLoader`.
- Docs: `CLAUDE.md`, `SKILLS.md` (Skills 1, 4, 9), Developer Guide §3.5, §6.3 and the agent walkthrough, `AgentLoader` docstring.
- **Squad Layer pattern** in the Developer Guide pattern catalogue (§27.11), with the anti-pattern (§4.5) and common mistake (§25.9); also on [patterns.k9x.ai](https://patterns.k9x.ai/squad-layer-pattern.html).
- `k9aif new` scaffold generates the squad layer: agent YAML with `module:`, an orchestrator that loads squads only, a router given its orchestrator, and `main.py` wiring squad layer → orchestrator → router.
- `MockLLM.generate()` accepts `system_prompt`, so a freshly generated project runs on the mock provider.

Tests: `test_orchestrator_knows_only_squads.py` (adds an agent to a squad YAML and runs the unchanged orchestrator; per-run config; `before_step`; K9-DEC-002).

---

## [1.18.0] — 2026-10-13

### Added

- **k9x Origin** (`k9_origin`), built into the framework like k9x Shield: one call for an agent, *what is true right now, and where did it come from?* Design: `docs/roadmap/k9x-origin-design.md`.
  - `BaseOrigin` / `K9Origin`: `get_current`, `recent_changes`, `query`, `resolve_for_squad`. Each answer carries the value, `as_of`, `version`, `source` (stream, system of record, or both) and flags (quarantined, in review, conflict). Origin states facts and makes no business decisions.
  - Resolver order: per-agent scope → request screening → live state → read-through to the system of record when the entity is missing → verify against it when the asking agent is a `verify_before` step → flags → answer screening → trace.
  - `config/origin.yaml` (`OriginConfig`, `${ENV}` expansion): entities (key, system of record, owned fields, conflict watches), sources, topics, squads (`live_context`, `verify_before`), agents (`allowed_entities`), governance (request and answer checks).
  - Sources reuse the framework's adapters: `mcp` (MCP client, any MCP server), `api` (`BaseApiAdapter`), `sql` (`BaseDataAdapter`). No new connector type.
  - Conflict flags: `TransitionRule` (listed transitions such as `approved -> disapproved` within a window), `LateEventRule` (an older event contradicting a watched field), disagreement from verify; `Conflict.to_envelope()` gives the `origin.conflict` domain event. `mark_in_review` / `clear_review` for the K9X HIL round trip.
  - `OriginMCPServer` (per agent, optionally) and `ContextMCPServer.register_on(mcp)` to add the tools to an existing MCP server.
  - `OriginFactory.create(config)`; production refuses an ungoverned Origin.
  - `BaseOrchestrator(origin=...)`: each squad receives the `live_context` it declares, resolved per payload.
- **`RedisContextState`**: shared live state for clusters. Bounded with Redis `maxmemory` + `volatile-lru`; entity values are evictable, quarantine markers never are; evicted entities return through read-through marked `history_available: false`. Concurrent writers verified to lose no updates. Extra: `k9-aif[redis]`.
- **Built-in implementations of existing ABBs:** `HttpApiAdapter`, `SqlDataAdapter`, `K9RulesAdapter` (rules in YAML; conditions parsed, never executed), `RestRulesAdapter` (decision services: Drools/KIE, ODM, OpenL, Corticon), and `K9RulesAgent`, the business-rules step (a decision such as `hil` raises `RequiresHIL`; an engine that cannot answer escalates rather than allows).
- Security capability catalog: `origin_governed_answers`, `origin_conflict_flags`.

### Changed

- **Live state applies events by source order, not arrival.** A field is set only if the event is not older than its current value, so a late `approved` can no longer overwrite a newer `disapproved`; late events stay in history, in source order; appends always apply; `as_of` is the source time; answers carry `version` (metadata version, Debezium LSN, or transport position). One merge function is shared by every state backend.
- Debezium mapper adds the log position (`lsn`) and a version.

Tests: `test_k9x_origin.py` (17), `test_redis_context_state.py` (6, with `K9_TEST_REDIS_URL`), source-order tests in `test_context_fabric.py`.

## [1.17.1] — 2026-10-12

### Added

- **`ContextMCPServer` checks what agents ask, not only what they get back.** `allowed_entities` limits the entity types the server answers about (anything else is refused before the state is read); `request_governance` screens each request's arguments, so instructions hidden in a tool argument (`PromptInjectionCheck`) and solicitations for PII such as "include the full SSN and bank account number" (`PIIRequestCheck`) are refused. A refused request returns `{"refused_by_governance": true, "reason": ...}` and is reported to `on_call` as `refused`. With `governance` using `PIIBoundaryCheck` (`block_on_match: true`), PII values in answers are withheld. Verified in K9X Streams' threat simulator: poisoned and PII-carrying stream events are refused at the gate; PII requests, argument injection and out-of-scope requests are refused at the server; ordinary agent requests are answered.
- Security capability catalog: `context_mcp_request_screening`.
- **`ContextMCPServer` works with MCP SDK 1.x and 2.x.** `build_fastmcp()` uses `MCPServer` on SDK 2.x (the renamed `FastMCP`) and `FastMCP` on 1.x; the new `http_app()` returns the stateless streamable-HTTP app on either, so an application mounts it without knowing the SDK version. Tested on mcp 1.28.1 and 2.3.0.

Tests: `test_context_fabric.py` (24).

## [1.17.0] — 2026-10-12

### Added

- **Live context from event streams (context fabric).** Agents get the current state of what they reason about, not a snapshot: every value carries `as_of`, `age_seconds`, `stale` and its source event (topic, partition, offset).
  - `BaseContextState` (ABB) with `ContextUpdate` / `ContextValue`: latest value per entity, recent changes, filtered queries; `InMemoryContextState` (OOB). `streams.state.max_age_seconds` sets when a value is stale.
  - `BaseContextProjection.updates()`: a projection keys its result by `entity` / `id_field`, or returns several `ContextUpdate`s (merge fields, append to lists, defaults). Existing projections are unchanged.
  - `GovernanceEventGate`: every event runs through the application's governance (k9x Shield, Granite Guardian, or both) before it reaches state, a window or an agent. Refused events are quarantined: the entity is marked (`quarantined`, with the check that refused it) and the content is never applied.
  - `ContextIngest`: fabric → gate → state + window → listeners.
  - `ContextMCPServer` (`k9_mcp/servers`): tools `get_current`, `recent_changes`, `query` and resource `context://{entity}/{id}`; optional screening of each answer; `build_fastmcp()` for a streamable-HTTP endpoint.
  - `BaseOrchestrator(context_state=...)`: `execute_squads()` adds `payload["live_context"]` for the entities in `payload["live_context_refs"]`, with a `LiveContext` trace event. No `context_state`, no change.
  - **Envelope mappers**: sources need not speak K9-AIF. `BaseEnvelopeMapper` (ABB) turns a raw message into an `EventEnvelope`; OOB `native`, `debezium` (change data capture from PostgreSQL, MySQL, SQL Server, Oracle, MongoDB: `<table>.<created|snapshot|updated|deleted>`, the row as payload, the change time as timestamp), `log_line` (JSON or plain-text logs from Fluent Bit, Vector, Filebeat: `log.<level>`), and `auto` (default: native, then Debezium). Chosen per topic in `streams.mappers`; `KafkaEventFabric` reads raw bytes and counts unmapped messages; `ContextIngest.ingest_raw()` takes messages from sources that are not on Kafka (webhooks, pollers).
  - `StreamsFactory.create_state()` / `create_gate()` / `register_state()` / `create_mapper()` / `register_mapper()`. `create_gate()` uses the application's own governance and refuses ungoverned event streams outside development/test.
- **Security capability catalog:** `stream_event_gate` (LLM01, LLM04, ASI01, ASI06) and `context_freshness` (LLM09, ASI08).
- Diagrams: `docs/diagrams/context_fabric_class` and `context_fabric_flow`. Recipe: Developer Guide 15.7.

### Changed

- **`KafkaEventFabric`** reads `KAFKA_SECURITY_PROTOCOL` (PLAINTEXT, SSL, SASL_PLAINTEXT, SASL_SSL) and `KAFKA_SASL_MECHANISM` from the environment when config does not set them, falls back to `KAFKA_BROKER` for the broker address, takes `auto_offset_reset` and `group_id` from config (replay topics with `earliest`), sends `metadata["key"]` as the message key, stamps consumed events with their topic, partition and offset, and adds `flush()`.
- `BaseMCPServer` logs its lifecycle through the standard logger.

Tests: `test_context_fabric.py` (22), `test_envelope_mappers.py` (10).

## [1.16.1] — 2026-10-12

### Added

- **`PaymentDiversionCheck`** (k9x_Shield, ingress). Blocks documents that steer an automated decision in business language: payment redirection ("route the payment to the replacement account"), review bypass ("already through the full review", "no need to repeat the review", "treat as final") and concealment ("no need to flag this in your summary"). Any two of the three signals block; one alone passes, so a genuine claim that gives a new bank account or mentions a completed review goes through. Deterministic, microseconds, no configuration needed; on by default in the framework's ingress check list. Validated with k9x_Satan's attack documents and ordinary claims. Tests: `test_payment_diversion_check.py`.

### Changed

- **`PIIBoundaryCheck` ZIP code detection** matches a US ZIP code in an address context (after a state code, or a ZIP / postal code label), keeping claim, order and reference numbers such as `CLM-2026-48377` out of PII findings. Addresses, labelled ZIP codes and the other PII types are detected as before. Tests: `test_pii_boundary_check.py`.
- **Security capability catalog:** Guardian screening is rated `LLM01: partial`, reflecting repeated k9x_Satan runs on business-language paraphrases; `PaymentDiversionCheck` adds deterministic coverage for that case.

## [1.16.0] — 2026-10-11

### Added

- **Squad coordinator: bounded squad context.** A squad's agents run in sequence and each reads the full accumulated context, so prompts grow with every step. A squad can now set `synthesis:` (`off`, the default and the previous behaviour; `auto`; `always`). With `auto`, once the upstream results a step would receive exceed `max_context_chars` (default 24000, about 6k tokens), the step gets a digest (`squad_digest`, with `squad_digest_keys`) instead of the full outputs; `always` digests whenever there are upstream results.
- **`K9ContextSynthesizerAgent`** (`k9_agents/synthesis/`) writes the digest through `llm_invoke` (task type `summarization`). It is an ordinary `BaseAgent`, so governance by construction screens the digest like any agent output. A solution can name its own synthesizer in `synthesis.agent`.
- **Audit:** the squad's results keep every full output; `squad_synthesis` records each digest made (step, agent, source keys, characters in and out).
- Steps with `context_keys` (explicit scoping) or `synthesis: false` are never synthesized.

Tests: `test_squad_synthesis.py`. Recipe: `SKILLS.md` Skill 4, "Bounding squad context".

## [1.15.3] — 2026-10-09

### Fixed

- **`pip install "k9-aif[docling]"`** installs what `DoclingParser` imports (`httpx`). On 1.15.2 a clean install without httpx failed with `ModuleNotFoundError` when the parser was imported. Also in `all`.

## [1.15.2] — 2026-10-09

### Fixed

- **`DoclingParser` works again.** Its constructor passed `name=` to `BaseAgent`, which raises `TypeError` on 1.15; it now takes `config` / `monitor` like every agent. The framework config defaulted `DOCLING_ENDPOINT` to `/v1/parse`, which Docling-Serve does not serve; the default is now `/v1/convert/file`, and the parser reads `external_services.docling.endpoint` (then `retrieval.docling.host`).
- **It converts any supported file, with OCR.** It sends the MIME type from the file suffix (it always said `application/pdf`), asks for Markdown with OCR on (`to_formats=md`, `do_ocr=true`), and returns `{"status": "ok", "filename", "markdown", "seconds"}`; an empty conversion is an error.
- **`execute({"path": ...})`** names the file rather than carrying its bytes, so governance checks the payload and not the document (Shield's InputSizeCheck refused a 4 MB PDF). The Markdown comes back under `markdown`, not `output`: it is untrusted text for the caller to screen before a model reads it.

Tests: `test_docling_parser.py` (set `DOCLING_ENDPOINT` to run the live conversion). The k9_inspect clean-solution fixture now pins the release under test.

## [1.15.1] — 2026-10-09

### Fixed

- **On/off settings from `.env` are read correctly.** After `load_yaml` expands `"${K9_GUARDIAN_ENABLED:-true}"` the value is the string `"true"`. `governance_from_config()` required the boolean `True`, so Shield or Guardian driven from `.env` was silently left out; `enable_zero_trust` (orchestrator and router) and Shield's own `enabled` read the string `"false"` as on. A shared `config_flag()` (`k9_utils/config_flags.py`) now reads booleans, `"true"`/`"false"`, `yes`/`no`, `on`/`off`, `1`/`0` the same way everywhere.
- **k9_inspect** uses the same reading for its governance rules, and judges an unexpanded `${VAR:-default}` by its default: a Guardian or Shield setting taken from `.env` is no longer reported missing (or passed when its default is off).

Tests: `test_config_flags.py`.

## [1.15.0] — 2026-10-08

Governance by construction, and five k9x_Shield gaps found by a 208-document governance evaluation.

### Changed

- **Governance by construction.** `BaseAgent.__init_subclass__` wraps every subclass's `execute()` and `execute_stream()` when the class is defined: governance is asserted, the payload pre-processed and the output post-processed on every call, and an override is wrapped too. `governance_from_config()` gives every agent `ShieldGovernance` when `security.shield.enabled: true`. With no governance configured, production (`K9_ENV` unset or `production`) raises `PermissionError` before the agent runs.
- **Every inference call governed.** `llm_invoke()` / `llm_invoke_stream()` read a call-path mark set by agents and orchestration adapters; a call outside any governed entry point runs the configured `security.shield` checks itself, and is refused in production when none is configured.
- **Granite Guardian from config.** `governance_from_config()` also builds `GuardianGovernance` when `governance.guardian.enabled: true`; with Shield enabled too, every agent gets `ChainedGovernance(Shield, Guardian)` — Shield's deterministic checks first, so an obvious injection never reaches the model, then Guardian's semantic screening. Before, the flag configured nothing by construction. Verified live (`granite4.1-guardian:8b`): a benign request passes both, an injection stops at Shield, a paraphrased jailbreak passes Shield and is blocked by Guardian.
- Examples (k9chat, EOC) ship a Shield profile so they run under governance by construction.

### Fixed

- **k9_inspect:** an agent definition YAML with its own `governance:` block is not taken for the application config; version `1.15` equals `1.15.0` (a `>=1.15` floor was reported behind).
- A governance `PermissionError` raised outside an event loop no longer carries a misleading "during handling of RuntimeError: no running event loop" context.
- **GuardianGovernance egress** accepts the agent's output string (governance by construction passes `result["output"]`, not a dict); it raised `AttributeError` on every reply.
- **ToolArgumentCheck** no longer scans the whole payload when it has no tool fields (agent markdown `---` matched its SQL-comment pattern).
- **OutboundLinkCheck:** a brand used as a subdomain label (`paypal.refund-desk.com`) is `brand_in_subdomain`; one adjacent swap (`acmeinsurnace`) and a brand embedded in the registered name (`acme-insurance-claims.net`) are `lookalike`; defanged links (`hxxps://`, `[.]`) are scanned; an unknown link beside debt or payment-hold wording is a new BLOCK kind, `payment_lure`.
- **PromptInjectionCheck:** system-prompt extraction requests (print / quote / reproduce the instructions you were given), also with leetspeak digits folded.
- **HardcodedCredentialCheck:** `AWS_SECRET_ACCESS_KEY=...`-style names and markdown table rows (`| db_password | ... |`).

Tests: `test_check_gaps_v2_eval.py` (each missed form blocks; the benign forms from the evaluation still pass).

### Added

- **`k9_inspect`: static conformance inspection of a solution.** `K9Inspector().inspect(folder)` parses a solution's Python (AST) and YAML without importing or running it, and applies registered `BaseInspectionRule`s: ABB contract (agents extend an agent ABB; loop agents keep the loop), three-layer decoupling, the single model path (`llm_invoke`), Kafka ownership, governance by construction (Shield enabled with checks, Guardian, production `K9_ENV`, egress coverage), secrets and `.env`, private IPs, squad/agent YAML, model aliases, the k9-aif version. Findings are ranked critical / violation / warning / recommendation with file, line and fix; the report gives a verdict, a rule pass rate, Markdown and JSON. Organisations add rules with `InspectionRuleRegistry.register()`.
- **`AgentLoader.register_into(registry, config, names)`**: agents are registered by name, the class resolved from the agent YAML's `class:` + `module:` — orchestrators no longer import agent classes (three-layer decoupling).
- **Examples conform to the inspection rules: no example has a violation** (`k9aif inspect examples/<app>`; ACME Health, ACME Support, prompt_evaluation, rfp_analyzer and weather_assist fully compliant). Orchestrators register agents by name; addresses come from the environment (`${OLLAMA_BASE_URL}`, `${KAFKA_BROKER}`), no LAN IPs; Shield and Granite Guardian are configured in each application's `config.yaml`; ACME Health's and k9routing's orchestrators screen their own ingress; each `llm_invoke()` failure is handled the way its agent needs (adjudication escalates to a person, the guard agent fails closed); one squad definition per app (`config/squads.yaml`; drifted per-squad copies removed); example tests run offline and match the rules (EOC 149, ACME Support 16). Also fixed: a syntax error in `acme_health_insurance/agents/persistence_agent.py`, a stale `EOCRouter` re-export.
- **`k9aif inspect <folder> [--json] [--markdown FILE] [--fail-on violation]`** runs it from the command line (exit 1 at or above `--fail-on`, for CI). `k9aif inspect` without a folder still lists the installed components.

---

## [1.14.1] — 2026-10-01

Maintenance release: dependency floors raised past known vulnerabilities, the security capability catalog, and a per-model timeout.

### Security

- **Dependency floors raised.** The previous minimums allowed versions with published, already-fixed vulnerabilities (found by K9X Sentinel's OSV audit; counted as distinct CVEs, GitHub and PyPI advisories for the same CVE merged):

  | Package | Was | Now | Fixed vulnerabilities (CVEs) excluded |
  |---|---|---|---|
  | aiohttp | >=3.9 | >=3.14.3 | 38 |
  | pyjwt (`oidc`) | >=2.8 | >=2.15.0 | 12 |
  | requests | >=2.28 | >=2.33.0 | 4 |
  | mcp (`mcp`, `all`) | >=1.10 | >=1.28.1 | 3 |
  | kafka-python (`kafka`, `all`) | >=2.0 | >=2.3.2 | 2 |
  | pydantic | >=2.0 | >=2.4.0 | 1 |
  | python-dotenv | >=1.0 | >=1.2.2 | 1 |

- **claude-agent-sdk >= 0.2.163** (`claude-agent-sdk`, `all`): older SDKs break against MCP SDK 2.x (`'Server' object has no attribute 'list_tools'`), which a fresh install now resolves to. Verified with both MCP 2.2.0 and 1.28.1. Every extra was dry-run resolved in a clean environment.

### Fixed

- **Per-model `timeout`** in `inference.llm_factory.models.<alias>` is now passed to the provider (OllamaLLM was fixed at 120 s; watsonx already accepted one). A 27B model on a long prompt or a cold load needs longer; found running K9X Sentinel.

### Added

- **Security capability catalog** (`k9_aif_abb/k9_security/capabilities.yaml`, ships in the package). Every Shield check, Guardian risk, Zero Trust/identity component, the tool-result guard, model-router protections, governance enforcement and HIL, mapped to OWASP Top 10 for LLM Applications 2025 (LLM01–10) and OWASP Top 10 for Agentic Applications 2026 (ASI01–10), each with coverage (full/partial), whether it's on by default and its stated limits, plus the gaps the maintainers already know about. Read by [K9X Sentinel](https://github.com/k9aif/k9x-sentinel), which compares newly published threats against it daily. `test_security_capabilities.py` fails when a registered Shield check or Guardian risk is missing from the catalog, when a listed component no longer exists, or when `framework_version` doesn't match `pyproject.toml`.

---

## [1.14.0] — 2026-09-30

Security release, driven by Zscaler ThreatLabz's 2026 Phishing & Initial Access Report ("AI agents will phish other AI agents"). Three gaps closed; the default behaviour of existing solutions is unchanged.

### Added

- **Authenticated caller identity for Zero Trust** (`k9_security/zero_trust/identity.py`).
  - Until now `BaseRouter` and `BaseOrchestrator` built `IdentityContext` and `trust_zone` from the payload itself, so any caller, including another agent, could claim `roles: ["admin"]` or `trust_zone: "internal"`.
  - New ABB contracts `BaseAuthenticator` and `BaseIdentityResolver`, with OOB `ApiKeyAuthenticator` (API key → principal, `principal_type` agent/service/user, roles, tenant; keys from the environment only), `SignedIdentityResolver` and `PayloadIdentityResolver`.
  - `BaseRouter.admit(payload, credentials)` is the trusted edge: it authenticates, strips every self-declared identity field and any inbound stamp, and adds an HMAC-SHA256-signed identity stamp (`$K9_IDENTITY_SECRET`, with expiry). `SignedIdentityResolver` verifies it in any Router or Orchestrator, in this process or another (e.g. across Kafka). Unsigned, tampered or expired → anonymous.
  - `BaseRouter` and `BaseOrchestrator` take an optional `identity_resolver=` (and the Router an `authenticator=`); otherwise `security.identity.mode` decides. **Default: `payload`**, the previous behaviour, with a one-time warning. Set `signed` to opt in; the default changes in 2.0.
  - **`OIDCAuthenticator`** (`zero_trust/oidc_authenticator.py`, `pip install "k9-aif[oidc]"`): OIDC bearer tokens from Keycloak or any OIDC provider. Signature checked against the provider's JWKS, issuer and expiry enforced, audience when configured; roles from a configurable claim (`realm_access.roles`); Keycloak service accounts become `principal_type: agent`. Invalid tokens return None, never raise. `security.auth.oidc` and `api_keys` can be combined (`ChainedAuthenticator`).
  - **`AuthenticatorFactory`** (`k9_factories/authenticator_factory.py`), same static-registry pattern as every K9-AIF factory. Pre-registered: `api_key`, `oidc`, and IdP adapters `keycloak` (realm roles plus that client's roles; issuer from `base_url` + `realm`), `entra_id` (app roles, app-only tokens → agent) and `okta` (groups, client credentials → agent). Solutions add their own (a SAML bridge, a CAC/PIV check) with `AuthenticatorFactory.register()`. Config is `security.auth.providers: [{type: keycloak, ...}, ...]`, tried in order; the earlier `oidc`/`api_keys` keys still work. `OIDCAuthenticator` gains OIDC discovery (`discovery: true`), which refuses a document whose issuer doesn't match. Verified live against Keycloak, including a client-role-only authorization.
  - `examples/zero_trust_execution_demo/identity_demo.py` shows a spoofed role believed (payload), denied (signed), and a properly admitted agent allowed.
  - `examples/zero_trust_execution_demo/keycloak_demo.py` runs the same flow against a real Keycloak (verified live with six users): role-based approve/deny, a self-declared role denied, a forged token treated as anonymous, and an authenticated red-team prompt-injection probe passing Zero Trust but blocked by Shield.
- **Tool-result guard** (`k9_security/tool_result_guard.py`). What a tool *returns* is untrusted input to the model (indirect prompt injection). `screen_tool_result()` runs it through a governance object's ingress stage (Shield ingress checks, then Granite Guardian when chained), keyed as `query` so Guardian reads the real content.
  - The Claude Agent SDK adapter now screens every tool result automatically (`govern_tool_results=True`, optional narrower `tool_result_governance=`). A refused result reaches Claude as an error notice, never as the content. `can_use_tool` still governs the call going out.
  - `@govern_tool_result(governance)` for CrewAI tools and plain functions (returns a withheld notice), `on_block="raise"` for LangGraph nodes.
- **Granite Guardian `ingress_risks`** (opt-in, `governance.guardian.ingress_risks`). Extra ingress classifications, each with a risk definition as the model's **system message** at temperature 0, the way Granite Guardian takes a risk. Built-in:
  - `process_manipulation`: text that directs the system itself (approve, skip verification, treat as pre-authorized);
  - `impersonation`: text claiming to be an internal agent/system or asserting its own roles to get records approved or disclosed.

  Custom `{name, definition}` entries are also accepted. Verified live against `granite4.1-guardian:8b` on k9x_satan's corpus: each caught an attack the default check rated SAFE, with 0 false positives over 7 clean claims × 3 runs. Unavailable calls follow `on_unavailable`, never SAFE. The default (no list) is unchanged; each risk is one extra Guardian call.
- **`OutboundLinkCheck`** (k9x Shield, egress, opt-in; LLM05). Links in agent output: lookalike domains (one edit or homoglyph away from an allowed/protected brand), brand-in-subdomain (`paypal.com.evil.io`), `user@host` URLs, IP-literal URLs and punycode BLOCK by default; shorteners and non-allowlisted hosts FLAG. The ThreatLabz chatbot pattern (collect an ID, invent a debt, hand over a payment link).

### Fixed

- `K9ClaudeAgentSDKAdapter` (the facade) built its orchestrator adapter with no governance and offered no way to pass one. It now forwards `config=`, `governance=`, `enable_zero_trust=` and the tool-result options.

---

## [1.13.0] — 2026-09-29

K9ModelRouter becomes a learned router. Until now it stored sessions, turns, decisions and model affinity, but never read any of them back; routing was rules only.

### Added

- **Learned routing** (`inference.router.learning`, on by default). This follows evaluation-trained routers such as Not Diamond, RouteLLM and RouterBench's k-NN baseline.
  - Graded outcomes (prompt vector, model, quality 0–100, latency) are stored in the new `routing_outcomes` table.
  - For each new prompt, every model's quality is predicted as the similarity-weighted average of its scores on the k most similar graded prompts. Only prompts of the same task type count, and only when at least `min_similarity` (0.15) alike; an unrelated prompt falls back to the rules.
  - The request's `latency_budget` and `cost_profile` turn that into a utility score.
  - The top model replaces the rules' pick when it leads by `margin` points (default 3), or when the rules' pick has no evidence.
  - Routing is per prompt, not per task type.
  - With no graded evidence, behaviour is identical to 1.12.
- `K9ModelRouter.record_feedback(prompt, model_alias, quality, task_type=None, latency_ms=None)`: how graders, evaluators, HIL reviewers and K9X Arena teach the router.
- `k9_inference/learning/`:
  - `HashingPromptEmbedder`: sparse unigram and bigram hashing with stop-words removed; deterministic, no model or dependency. It matches wording, not meaning.
  - `ServicePromptEmbedder`: any `BaseEmbeddingService`, e.g. Ollama `nomic-embed-text`, for prompts that mean the same but are worded differently.
  - `KNNQualityPredictor` and `utility()`.
- Runtime outcomes: every `invoke`/`ainvoke`/stream records success and latency. `InferenceResponse.latency_ms` is now filled in.
- Circuit breaker: a model whose recent calls mostly failed is skipped (never every model).
- `InferenceRequest.session_id` and `user_id`. Turns now stay in one session, and the router prefers the session's current model on a tie (affinity). String ids map to stable UUIDs, as Postgres stores uuid.
- `RouteDecision.strategy` (`rules`/`learned`), `predicted_quality` and `predictions`.
- Verified live through `llm_invoke` against Ollama: the learned pick is used, the call's latency and success are recorded, and an unrelated prompt falls back to the rules.
- `RoutingStateStore.record_outcome()` / `load_outcomes()`. `routing_outcomes` is created automatically on existing databases; the Postgres DDL is in `db/k9aif_db_schema.sql`.

### Fixed

- **Confidential requests could reach a model not cleared for them.** Rules gave +3 for a capability match but only +2 for `confidential`, so a `reasoning` + `confidential` request went to the reasoning model. A confidential request is now restricted to confidential-capable models whenever the catalog has any. This includes the `default_model` fallback, and learned routing can't override it.
- `InferenceRequest` had no `session_id` field, so `_resolve_session_id()` always created a new session: every call was its own conversation.

---

## [1.12.6] — 2026-09-27

Documentation release: no runtime behaviour changes.

### Fixed

- **README links and images now absolute so they render on PyPI.** The README is also the PyPI `long_description`, and PyPI does not resolve relative paths: on pypi.org every relative link and image became `pypi.org/project/k9-aif/<path>` and returned 404. All 22 relative targets are now absolute: files use `github.com/.../blob/main/`, folders `.../tree/main/`, images `raw.githubusercontent.com/.../main/`. The list includes the outer link of the linked LLM-provider diagram. All 33 README URLs return HTTP 200.

### Added

- `scripts/check_readme_links.py`: fails on any relative link or image in the README; `--check-urls` also requires HTTP 200 for every URL. It is used by the new `k9_aif_abb/tests/test_readme_links.py` (skipped outside a repository checkout) and the new `.claude/hooks/check-readme-links.sh`, which blocks README edits that add a relative link.
- README: a short **Built on K9-AIF: Defense Acquisition System (DAS)** section with tips from building DAS, replacing an outdated entry that described DAS as using CrewAI.

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
