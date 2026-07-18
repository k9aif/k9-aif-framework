# K9-AIF Security Capability Inventory

This document is a complete, verified inventory of every security-relevant
capability currently implemented in the K9-AIF framework, as of this
review. It is the factual baseline the OWASP crosswalks
(`02-owasp-llm-crosswalk.md`, `03-owasp-agentic-crosswalk.md`) are built
against. Every entry below was confirmed against the actual source, not
assumed from documentation or naming.

---

## 1. k9x_Shield — Vulnerability Check Chain

**Location**: `k9_aif_abb/k9_security/vulnerability/`

A GoF Chain-of-Responsibility subsystem. `BaseVulnerabilityCheck` (abstract,
one method: `check(payload) -> CheckResult`) → `VulnerabilityChain`
(assembles checks in insertion order, runs them in sequence) → `CheckResult`
(`PASS` / `FLAG` / `BLOCK`, with `severity` and `metadata`).

**Chain semantics** (verified in `vulnerability_chain.py`):
- `BLOCK` halts the chain immediately; remaining checks do not run.
- `FLAG` is non-blocking by default; the chain continues.
- `strict=True` promotes the first `FLAG` to a `BLOCK`.
- A check that raises an exception is caught and converted to a `FLAG`
  (severity `high`), never a `BLOCK` — **a crashing check fails open**, not
  closed. This is a design property with direct OWASP relevance (see
  Agentic crosswalk, ASI08 Cascading Failures).

**Seven OOB checks**, all under `checks/`:

| Check | Threat detected | Default polarity |
|---|---|---|
| `PromptInjectionCheck` | Prompt-injection / jailbreak phrases (regex) | BLOCK (not configurable) |
| `HardcodedCredentialCheck` | Hardcoded API keys / secrets / PEM keys in payload | BLOCK |
| `PIIBoundaryCheck` | Email, SSN, credit-card, phone, ZIP patterns | FLAG (default) |
| `InputSizeCheck` | Oversized payload (char/key count) — token-flood DoS | BLOCK |
| `ToolArgumentCheck` | SQLi, command injection, path traversal, SSRF in tool-call arguments | BLOCK |
| `SemanticDriftCheck` | Goal-hijacking phrases; high-repetition "loop trap" content | BLOCK |
| `ExecutionGuardCheck` | Destructive commands, reverse shells, persistence, exfiltration, dangerous interpreter calls | BLOCK |

**`ShieldGovernance`** (`shield_governance.py`) wires the chain as a dual-gate
governance backend (ingress + egress), raising `PermissionError` on block —
this is the mechanism CLAUDE.md and Satan's own documentation describe as
"the same VulnerabilityChain ABB, reused at the agent pre/post hook."

**Known gap** (confirmed, not assumed): `ShieldGovernance._build_chain()`
instantiates each check with `cls()` — no arguments. Per-check config
options that exist in every check's `__init__` (`extra_patterns`,
`block_on_match`, `max_chars`, thresholds, etc.) are **not threaded through
from `config.yaml`**. They are reachable only via direct Python
instantiation, not through the framework's declarative config path. See
Gap Analysis (`04-gap-analysis.md`), Gap G1.

---

## 2. Zero Trust Execution Layer

**Location**: `k9_aif_abb/k9_security/zero_trust/`

Implements Verify → Control → Enforce as a single `evaluate()` call:

1. **Verify/Control (compromise)** — `PromptInjectionGuard` matches a small
   hardcoded suspicious-terms list against `str(payload)`. Any match →
   immediate `DENY` (risk_score 1.0), short-circuiting further evaluation.
2. **Control (data loss)** — `SensitiveDataLossGuard`: if data sensitivity
   is `restricted`/`confidential` and the destination is external →
   `ALLOW_WITH_OBLIGATIONS` (`mask_sensitive_data`, `audit_log`).
3. **Control (contextual risk)** — `ContextualRiskEvaluator` scores 0.0–1.0
   additively: external destination (+0.35), high/restricted/confidential
   sensitivity (+0.35), unknown/external/public destination type (+0.20),
   anonymous/unknown principal (+0.30).
4. **Enforce (thresholds)** — `deny_threshold=0.85`,
   `approval_threshold=0.75`, `obligation_threshold=0.60`, else `ALLOW`.

`RuntimePolicyEnforcer` executes obligations: `audit_log` currently
`print()`s a line (not a structured logger); `mask_sensitive_data`
recursively replaces values under `ssn`/`customer_ssn`/`dob`/
`credit_card`/`account_number` keys with `"***MASKED***"`.

**Wiring**: opt-in, identical pattern duplicated on `BaseOrchestrator` and
`BaseRouter` (constructor flag `enable_zero_trust`, method
`apply_zero_trust(payload, ctx)`). **Not wired on `BaseSquad` or
`BaseAgent`** — Zero Trust exists only at the Router and Orchestrator
layers.

**Known gap**: `IdentityContext.roles` is captured but never evaluated by
any guard or evaluator — role/attribute-based authorization is captured as
data but functionally inert. See Gap Analysis, Gap G2.

**Known gap**: zero automated test coverage — no test file references
`zero_trust` anywhere in `tests/`. See Gap Analysis, Gap G3.

---

## 3. Governance Pipeline

**Location**: `k9_aif_abb/k9_core/governance/` (ABB contract),
`k9_aif_abb/k9_governance/` and `k9_aif_abb/k9_agents/governance/` (SBBs)

`BaseGovernance` (abstract `pre_process`/`post_process`, both async).
`NoopGovernance` is the passthrough default. `require_governance()`
resolves a real governance object or falls back to `NoopGovernance`,
logging at WARNING in `development`/`test` and ERROR otherwise —  but does
not itself raise.

**`enforce_governance()`** (on `BaseAgent`) is the actual enforcement point:
raises `PermissionError` if governance is `NoopGovernance` **and** `K9_ENV`
is not `development`/`dev`/`test`. This is opt-in per agent — an agent that
never calls `self.enforce_governance()` runs ungoverned in production
silently. This exact behavior is already documented as a known risk in
CLAUDE.md ("agents that skip this call will silently use NoopGovernance
even in production").

**Concrete governance SBBs**:
- `ProfanityGovernance` (`k9_governance/`) — LLM-based profanity check via
  `LLMFactory`. **Contract deviation** (confirmed): returns `{"status":
  "BLOCKED"|"SAFE", ...}` instead of the payload dict every other
  governance implementation returns — a caller expecting the mutated
  payload back gets a different shape entirely. See Gap Analysis, Gap G4.
- `GovernanceAgent` (`k9_agents/governance/`) — YAML-policy-driven
  (`blocked_keywords`, `allowed_domains`, `response_redaction`) plus an
  LLM safety check in both `pre_process()` and `post_process()`.

**Enterprise config lock** (`k9_agents/agent_loader.py` +
`k9_utils/config_loader.py`): a `config["_policy"]["locked"]` dot-notation
key list that SBB/agent config cannot override — restores the ABB value
and logs a warning on attempted override. Tested (7/20 tests in
`test_agent_loader.py`). **Ships with an empty `locked: []` list by
default** — the enforcement mechanism exists but protects nothing out of
the box.

---

## 4. Messaging Security

**Location**: `k9_aif_abb/k9_streams/kafka_stream.py` (`KafkaEventFabric`),
`k9_aif_abb/k9_core/messaging/k9_event_bus.py` (`K9EventBus`)

- `KafkaEventFabric` supports `security_protocol: PLAINTEXT|SASL_SSL` and
  SASL mechanisms (`PLAIN`, `SCRAM-SHA-256`, `SCRAM-SHA-512`), credentials
  from environment variables only.
- `K9EventBus` — the core ABB event bus actually used by the Router/
  Orchestrator Kafka topology described in CLAUDE.md — has **no
  SASL/TLS support at all**. `KafkaProducer`/`KafkaConsumer` are
  constructed with only `bootstrap_servers`.
- `K9EventBus` does enforce `max_event_bytes` (default 512KB), truncating
  oversized events with a warning — a lightweight DoS/cost control at the
  event-bus layer, distinct from `InputSizeCheck`'s LLM-ingress-layer
  version of the same concern.

**Known gap**: the production messaging path (`K9EventBus`) has no
authentication or transport encryption; only the newer, less-integrated
`KafkaEventFabric` abstraction has it. No Kafka topic ACL enforcement, no
message-level encryption or signing anywhere. See Gap Analysis, Gap G5.

---

## 5. Identity, Secrets, and Authorization

**Secret management** — mature, consistent 3-layer pattern: `BaseSecretManager`
ABB → 4 adapters (`EnvSecretAdapter` default, `VaultSecretAdapter`,
`AwsSecretAdapter`, `IbmSecretAdapter`, all lazy-imported) →
`SecretManagerFactory`. Credentials always from environment, never
`config.yaml`. This capability is solid and required no changes.

**Authorization** — **no ABAC or RBAC implementation exists anywhere in
the codebase** (verified by repository-wide search). `IdentityContext.roles`
is captured but inert (see Zero Trust section above).

**Authentication** — `MockAuth` (`k9_core/security/mock_auth.py`) is
explicitly a demo/mock shared-secret check, not a real authentication
mechanism. `AuthAgent` (`k9_agents/security/auth_agent.py`) checks a
static `api_key` against config — a shared-secret check, not
identity/session-based auth, and has a latent bug (calls `self.log()`
synchronously where the base class defines it as `async`).

**`SecurityFactory`** (`k9_factories/security_factory.py`) — a static
factory intended for "encryption, IAM, and access control modules" with an
**empty registry**; nothing is registered into it anywhere in the
codebase. Aspirational contract, no OOB implementation.

**Non-functional stubs** (confirmed, not fixed as part of this review
unless flagged as a genuine gap): `EncryptionAgent`, `SecretManagerAgent`
under `k9_agents/security/` are `print()`-only stubs with constructor
signatures that don't match `BaseAgent.__init__`.

---

## 6. Orchestration-Level Security Properties

- **Three-level decoupling** (Router → Orchestrator → Squad → Agent, each
  layer knows only the layer directly below) constrains blast radius —
  enforced by convention/documentation (CLAUDE.md), not by any runtime
  guard. This is a structural security property, not a control.
- **`enforce_governance()` fail-fast** (see §3).
- **`BaseOrchestrator.execute_squads(parallel=True)`** isolates per-squad
  failures — one squad's exception becomes a `{"status": "failed", ...}`
  result rather than propagating and taking down sibling squads. A
  resilience property relevant to availability/DoS resistance.
- **`BaseSquad.execute()`** fail-fast validates flow-step structure and
  required-agent presence before executing anything — a correctness
  guard, not a security control per se, but it does prevent a
  partially-configured squad from silently skipping required steps.
- **Router's `store_document()`** has no access-control check — any caller
  with a Router instance can write to any bucket/key it names.

---

## 7. Monitoring

No dedicated security-monitoring subsystem exists (e.g., no SIEM
integration, no anomaly-detection-over-time component). The nearest
capability is the `publish_event()` audit trail (Router/Orchestrator only,
per CLAUDE.md's Kafka ownership convention) and `RuntimePolicyEnforcer`'s
`print()`-based audit logging (see Zero Trust section — not a structured
log sink). See Gap Analysis, Gap G6.

---

## 8. Supply-Chain Protections

No supply-chain-specific controls exist in the security subsystem
(dependency pinning/scanning is a repository/CI concern, out of scope for
`k9_security/` itself, and was not found wired into any runtime check).
See Gap Analysis, Gap G7 for the OWASP Supply Chain (LLM03 / ASI04)
crosswalk discussion of what is and is not applicable here.

---

## 9. Red-Team Boundary (k9x_SATAN)

`k9_aif_abb/k9_security/attacks/` contains **only** the `BaseAttack` ABB
contract (Template Method: `craft_payload()` + `run()`). No concrete
attack subclasses exist in this repository — they belong to the separate
K9x Satan project by design. This review does not add, modify, or
reference any Satan-specific logic in `k9_security/`, per the explicit
SATAN boundary instruction in this task.

---

## 10. Test Coverage Summary

| Area | Test file | Count | Coverage |
|---|---|---|---|
| Vulnerability chain + 7 checks | `test_vulnerability_chain.py` | 61 | Strong |
| ShieldGovernance | `test_shield_governance.py` | 16 | Strong |
| Secret management | `test_secret_manager.py` | 12 | Strong |
| Enterprise config lock | `test_agent_loader.py` (7 of 20) | 7 | Adequate |
| **Zero Trust** | — none — | **0** | **None** |
| **Governance SBBs** (`GovernanceAgent`, `ProfanityGovernance`) | — none — | **0** | **None** |
| **Security agents** (`AuthAgent`, etc.) | — none — | **0** | **None** |

Total pre-existing security-relevant tests: 96, concentrated entirely in
k9x_Shield and secret management.
