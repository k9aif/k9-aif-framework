# K9-AIF Security Gap Analysis

Consolidates every gap referenced in the OWASP crosswalks
(`02-owasp-llm-crosswalk.md`, `03-owasp-agentic-crosswalk.md`) into a
single list, with the architecturally correct implementation location for
each, per this review's instruction to implement security "in the layer
where it naturally belongs" rather than forcing every finding into a
vulnerability check.

---

## G1 — `ShieldGovernance` does not thread per-check config from `config.yaml`

**OWASP impact**: cross-cutting — affects the configurability of every
Shield-based control in both crosswalks.

**Root cause**: `ShieldGovernance._build_chain()` instantiates each check
with `cls()` (no arguments). Every check's `__init__` already accepts a
`config` dict with real override points (`extra_patterns`,
`block_on_match`, thresholds) — the capability exists in each check, the
governance wrapper simply does not use it.

**Architecturally correct location**: `ShieldGovernance` itself
(`k9_security/vulnerability/shield_governance.py`) — this is a wiring
defect in the assembler, not a missing capability in any check.

**Disposition**: Fix. Low risk, high value, no new classes required.

---

## G2 — `IdentityContext.roles` captured but never evaluated (no ABAC/RBAC)

**OWASP impact**: ASI03 (Identity and Privilege Abuse) — the most
significant single gap identified in this review.

**Root cause**: the Zero Trust data model already carries `roles`, but
neither `ContextualRiskEvaluator` nor any guard reads it. No
authorization decision anywhere in the framework is keyed on
role/attribute.

**Architecturally correct location**: the Zero Trust evaluator layer
(`k9_security/zero_trust/evaluators.py`), **not** a vulnerability check —
this is a privilege/identity evaluation concern, structurally distinct
from payload-content pattern matching, and Zero Trust already owns
identity/context evaluation for the framework. A new
`BaseAuthorizationEvaluator` ABB + OOB `RoleBasedAuthorizationEvaluator`
SBB, composed into `DefaultZeroTrustGuard` alongside the existing
compromise/data-loss/contextual-risk evaluators, is the natural
extension point — consistent with the framework's existing pattern of
composing multiple evaluators/guards into one guard.

**Disposition**: Fix. This is the highest-priority gap in the entire
review.

**Implemented.** Added `BaseAuthorizationGuard` (ABB, `zero_trust/guards.py`)
alongside the existing `BaseCompromiseGuard`/`BaseDataLossGuard` — a
decision-shaped (`inspect() -> TrustDecision`) contract rather than a
risk-score contract, since authorization is a binary privilege decision, not
a continuous score. `RoleBasedAuthorizationGuard` (OOB SBB) denies an
action_type unless `IdentityContext.roles` intersects a configured
`role_policy[action_type]` allowlist. Wired into `DefaultZeroTrustGuard` as
a new `authorization_guard` constructor parameter (default:
`RoleBasedAuthorizationGuard()`), evaluated in `evaluate()` right after the
compromise guard and before the data-loss guard/risk scoring — identity and
privilege are checked before content-level risk, matching Zero Trust's
Verify-before-Control ordering.

Default behavior with no `role_policy` configured is **ALLOW** for every
action_type, not deny-all. This was a deliberate choice, following the same
principle established for G6: `DefaultZeroTrustGuard` composes this guard
unconditionally now, and Zero Trust itself is already opt-in
(`enable_zero_trust: true`) — silently denying every unconfigured
action_type the moment this guard existed would break every deployment
currently relying on `enable_zero_trust: true` with no role policy defined,
not just close a gap. Authorization is enforced only for action_types a
solution has deliberately restricted via `role_policy`.

---

## G3 — Zero Trust layer has zero automated test coverage

**OWASP impact**: not an OWASP category by itself, but undermines
confidence in every OWASP category the Zero Trust layer is credited with
partially covering (LLM01, LLM02, LLM06, ASI01, ASI09, ASI10).

**Architecturally correct location**: `k9_aif_abb/tests/` (matching the
existing flat test-file-per-subsystem convention: `test_zero_trust.py`).

**Disposition**: Fix. Required regardless of any other gap closure, since
new evaluator work (G2) needs test coverage from day one, not bolted on
after.

**Implemented.** `tests/test_zero_trust.py` — 34 tests covering
`TrustDecision` constructors, `ContextualRiskEvaluator` scoring (each
component and the 1.0 cap), `PromptInjectionGuard`, `SensitiveDataLossGuard`,
the new `RoleBasedAuthorizationGuard` (G2), `DefaultZeroTrustGuard`'s full
composition and guard-ordering (compromise → authorization → data-loss →
risk thresholds), and `RuntimePolicyEnforcer` (masking, nested masking,
audit logging, DENY passthrough).

---

## G4 — `ProfanityGovernance` returns a different contract shape than every other governance implementation

**OWASP impact**: not an OWASP category directly; a correctness/contract
defect that risks silent data loss for any caller expecting the payload
back.

**Root cause**: `pre_process()` returns `{"status": "BLOCKED"|"SAFE", ...}`
instead of the payload dict (mutated or not) every other `BaseGovernance`
implementation returns.

**Architecturally correct location**: `k9_governance/profanity_governance.py`
itself — a contract-conformance fix local to this one class.

**Disposition**: Fix. Small, contained, unambiguous correctness bug.

**Additional defects found and fixed while closing this gap** (both would
have made the class fail at first real use, independent of the contract-shape
bug above):
- `self.llm = LLMFactory().create("granite-guardian")` — `LLMFactory` exposes
  no `create` method (only classmethods, `get()` among them); this raised
  `AttributeError` on every `ProfanityGovernance()` construction. Fixed to
  `LLMFactory.get("granite-guardian")`.
- `result = self.llm.generate(prompt=...)` — `OllamaLLM.generate()` is
  `async def`; the call was missing `await`, so `result` was an unawaited
  coroutine object and `result.upper()` would have raised `AttributeError`
  the first time this code path actually ran. Fixed to
  `await self.llm.generate(...)`.

Tests added in `tests/test_profanity_governance.py` (3 tests, mocking
`LLMFactory.get`) cover the SAFE passthrough, BLOCKED→`PermissionError`, and
`post_process` passthrough paths.

---

## G5 — Production Kafka event bus (`K9EventBus`) has no authentication or transport encryption

**OWASP impact**: ASI07 (Insecure Inter-Agent Communication) — partial,
since the standard K9-AIF pattern minimizes true agent-to-agent messaging
by design, but Router→Orchestrator messaging over this same bus is
unprotected.

**Root cause**: `K9EventBus` constructs `KafkaProducer`/`KafkaConsumer`
with only `bootstrap_servers`; `security_protocol`/SASL support exists
only in the separate, less-central `KafkaEventFabric` abstraction.

**Architecturally correct location**: `k9_core/messaging/k9_event_bus.py`
itself — extend it to accept the same `security_protocol`/SASL
configuration `KafkaEventFabric` already supports, sourced from
environment variables per the framework's existing credential-handling
convention, defaulting to today's `PLAINTEXT` behavior for backward
compatibility.

**Disposition**: Fix, backward-compatible (opt-in via config, default
unchanged).

**Implemented.** Added `security_protocol`/`sasl_mechanism` constructor
parameters to `K9EventBus`, defaulting to `PLAINTEXT`/`PLAIN` — identical
connection behavior to before this option existed. A new `_security_kwargs()`
method (mirroring `KafkaEventFabric`'s existing pattern exactly) is reused
across the producer, the sync consumer (`subscribe()`), and the async
consumer (`subscribe_async()`), so all three connection paths honor the same
setting rather than only the producer. `MessageFactory.create()` reads
`messaging.security_protocol`/`messaging.sasl_mechanism` from config and
threads them through; SASL credentials come from `KAFKA_SASL_USERNAME`/
`KAFKA_SASL_PASSWORD` environment variables only, never `config.yaml`,
consistent with the framework's existing credential-handling convention. 9
new tests in `tests/test_k9_event_bus_security.py` (KafkaProducer mocked, no
real broker needed) cover the PLAINTEXT default, SASL_SSL kwargs assembly,
env-var credential sourcing, graceful degradation on connection failure, and
`MessageFactory` config threading.

---

## G6 — `VulnerabilityChain` fails open (to `FLAG`) when a check raises an exception

**OWASP impact**: ASI08 (Cascading Agent Failures) — a genuine policy
tension between availability (one buggy check should not halt the whole
chain) and security (a crashing check silently stops protecting, with no
distinct signal that it failed rather than passed).

**Architecturally correct location**: `VulnerabilityChain` itself
(`k9_security/vulnerability/vulnerability_chain.py`) — add a
constructor-level policy option (default preserves current behavior, for
backward compatibility) rather than unilaterally flipping the default,
since this is a deliberate, deployment-specific risk-tolerance decision,
not a bug with one correct answer.

**Disposition**: Fix — make it configurable, do not silently change
existing behavior for deployments that rely on the current default.

---

## G7 — Supply-chain / dependency provenance verification

**OWASP impact**: LLM03, ASI04 (the "verify the supply chain artifacts
themselves are trustworthy" half of this category, distinct from G8's
"restrict which already-known tools an agent may call" half).

**Disposition**: **Not implemented; scoped out deliberately.** Verifying
model weight provenance, package/dependency integrity, or third-party
data-source trustworthiness is a repository/CI/supply-chain-tooling
concern (dependency pinning, SBOM generation, artifact signing) that does
not belong inside a runtime `k9_security/` component evaluating an
in-flight payload — there is no payload-shaped signal a
`BaseVulnerabilityCheck` could inspect that would verify, for example,
that a loaded model's weights were not tampered with. Forcing this into a
vulnerability check would not meaningfully address the risk and would
misrepresent what the control actually does. Recorded here as an honest
scope boundary, consistent with the instruction not to force every OWASP
requirement into a check.

---

## G8 — Five proven Satan-local checks not promoted into the framework

**OWASP impact**: LLM03/ASI02/ASI04 (tool authorization), LLM04/ASI06
(memory poisoning), LLM05 (output sanitization), LLM07 (system prompt
leakage), LLM10 (request-rate limiting).

**Root cause**: K9x Satan — an adversarial test tool built using the
framework's ABB classes to attack and validate the framework itself, not
a governed application solution built on it — implemented five
`BaseVulnerabilityCheck` subclasses locally, because the framework itself
did not provide OOB equivalents:
`ToolAuthorizationCheck`, `MemoryPoisoningCheck`,
`SystemPromptLeakageCheck`, `OutputSanitizationCheck`,
`RequestFrequencyCheck`. All five are tested and proven in production use
against a real K9-AIF pipeline (satan.k9x.ai).

**Architecturally correct location**: `k9_security/vulnerability/checks/`
in the framework itself — this is precisely the Enterprise Continuum's
own harvesting pattern (a proven SBB, generalized and elevated to an OOB
ABB-level capability) applied to the security subsystem rather than to a
domain agent. Each check is already framework-generic in its actual
logic (none of the five reference anything insurance/defense/domain-
specific) — they were Satan-local only because no promotion had happened
yet, not because they need Satan-specific behavior.

**Disposition**: Fix — port all five into the framework, generalizing
class/variable names away from any Satan-specific framing, re-verify
against this framework's own `BaseVulnerabilityCheck`/`CheckResult`
contract (already identical to Satan's, both extend the same ABB), and
add fresh tests in this repository (do not assume Satan's tests transfer
automatically).

**Implemented.** All five checks ported to
`k9_security/vulnerability/checks/` and registered in `ShieldGovernance`'s
`_CHECK_REGISTRY`. One config-shape change was required during the port:
Satan's originals read `self.config.get("security", {}).get(...)` (assuming
the *global* app config is passed to the check), but the framework's own
checks — and `ShieldGovernance`'s `check_config` threading added for G1 —
pass each check a **flat, check-scoped** config dict
(`InputSizeCheck.__init__` reads `self.config.get("max_chars")` directly, no
"security" nesting). All five ported checks were flattened to match:
`ToolAuthorizationCheck.approved_tools`/`approved_backends`,
`SystemPromptLeakageCheck.system_prompt_fragments`/`leakage_min_chars`,
`OutputSanitizationCheck.block_on_output_markup`,
`MemoryPoisoningCheck.memory_ttl`/`tracked_fact_keys`,
`RequestFrequencyCheck.max_requests_per_window`/`rate_limit_window_seconds`
are all now read directly off the check's own config, not a "security"
sub-key.

Two checks (`MemoryPoisoningCheck`, `RequestFrequencyCheck`) need
cross-request state via `CacheFactory`, which does not memoize — a new
internal helper, `checks/_shared_cache.py`, holds one process-level
singleton cache instance so counts/facts survive `ShieldGovernance` being
rebuilt fresh per request (same problem Satan solved locally with its own
`_shared_cache.py`, now generalized into the framework rather than
duplicated by every solution that needs it).

Two checks' defaults were deliberately changed from Satan's, since a
framework default must not encode one solution's specifics:
`ToolAuthorizationCheck` now defaults both allowlists to empty (default-deny
consistent with Zero Trust — Satan defaulted to `["fake_search"]`/
`["localhost", "127.0.0.1"]`, its own test fixtures) and
`SystemPromptLeakageCheck` now defaults `system_prompt_fragments` to empty
(no-op until configured — Satan defaulted to its own four hardcoded
agent-prompt strings). `OutputSanitizationCheck` needed no config changes —
its pattern set was already framework-generic.

35 new tests added in `tests/test_ported_vulnerability_checks.py`, covering
all five checks plus the `_host_matches`/`_extract_host` regression coverage
inherited from Satan's own test suite.

**Not ported**: Satan's `FieldAnomalyCheck` (authority-override social
engineering) was reviewed and excluded — its pattern set
(`EXEC-OVERRIDE`, `Priority: CRITICAL`, `COO auth`) is tuned specifically
to Satan's insurance-claim test corpus, and promoting it as-is would
misrepresent it as a general-purpose framework capability when it is
closer to a worked example. `PromptInjectionCheck` already covers the
general authority-override-phrasing threat class this check specializes.

---

## Summary — Disposition Table

| Gap | OWASP categories closed/improved | Disposition |
|---|---|---|
| G1 | All Shield-based categories (configurability) | Fix |
| G2 | ASI03 | Fix (highest priority) |
| G3 | Confidence in LLM01/02/06, ASI01/09/10 | Fix |
| G4 | Contract correctness | Fix |
| G5 | ASI07 | Fix |
| G6 | ASI08 | Fix (configurable, not a default change) |
| G7 | LLM03, ASI04 (provenance half) | Scoped out — not a runtime-check problem |
| G8 | LLM03/04/05/07/10, ASI02/04/06 | Fix — port 5 checks |

Not ported: Satan's `FieldAnomalyCheck` (too domain-specific to promote
as-is; general threat class already covered by `PromptInjectionCheck`).

Not addressed in this pass (recorded as future work rather than a
resolvable gap): OWASP Agentic ASI09 (human-reviewer manipulation
defense) and the longitudinal/behavioral-drift half of ASI10 (Rogue
Agents) — both require capabilities (session-level behavioral baselines,
UX-level reviewer-manipulation defenses) that are reasonably out of scope
for a single review pass and are noted honestly rather than claimed as
covered.
