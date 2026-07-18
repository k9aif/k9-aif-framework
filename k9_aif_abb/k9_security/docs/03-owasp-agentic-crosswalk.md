# OWASP Top 10 for Agentic Applications (2026) — K9-AIF Crosswalk

Source verified cross-referentially against two independent third-party
summaries of the OWASP GenAI Security Project's Agentic Security
Initiative (ASI) document (the primary PDF is gated behind an email-capture
form and could not be retrieved directly; the category IDs and names below
were confirmed consistent across both sources before use). If the
official document differs from this list in wording, the mapping logic
below should transfer directly — only the labels would need updating.

Coverage classification: **Full**, **Partial**, **Not Covered**.

---

### ASI01 — Agent Goal Hijack

**Coverage: Partial**

- `SemanticDriftCheck` (Shield, egress) — detects goal-hijacking phrases
  attempting to override agent identity/purpose mid-session.
- `PromptInjectionCheck` (Shield, ingress+egress) and `PromptInjectionGuard`
  (Zero Trust) — the injection vector most commonly used to attempt a
  hijack.

**Justification**: same structural limitation as LLM01 in the LLM
crosswalk — pattern-based detection, evadable by paraphrase, with the
semantic backstop (`GovernanceAgent`) not integrated into the Shield
chain itself.

---

### ASI02 — Tool Misuse and Exploitation

**Coverage: Partial**

- `ToolArgumentCheck` (Shield) validates arguments the LLM generates for
  a tool call (SQLi, command injection, path traversal, SSRF) before
  execution.

**Justification**: argument-level validation is present and solid; tool
*identity* authorization (is this a tool the agent is permitted to call
at all) is not — see LLM03/LLM06 discussion. `ToolArgumentCheck` protects
against a legitimate tool being called with malicious arguments; nothing
in the framework prevents an illegitimate tool from being called with
well-formed arguments. See Gap Analysis G1/G8.

---

### ASI03 — Identity and Privilege Abuse

**Coverage: Not Covered**

`IdentityContext.roles` (Zero Trust) is captured as data but is never
read by `ContextualRiskEvaluator`, `DefaultZeroTrustGuard`, or any guard —
role/attribute information flows into the context and is then ignored.
No ABAC or RBAC implementation exists anywhere in `k9_aif_abb` (confirmed
by repository-wide search). `MockAuth` is an explicit demo/placeholder.
`AuthAgent` performs a static shared-secret check, not identity- or
role-based authorization.

**This is the most significant gap identified in this review.** The
framework captures the data needed for privilege-based authorization
(`IdentityContext.roles`) but has no evaluation logic that consumes it —
the gap is a missing evaluator, not a missing data model. See Gap
Analysis G2, which proposes closing this at the Zero Trust evaluator
layer, not as a vulnerability check.

---

### ASI04 — Agentic Supply Chain Vulnerabilities

**Coverage: Not Covered**

Identical finding to LLM03 in the LLM crosswalk: no runtime verification
of tool/plugin/data-source provenance; `ToolAuthorizationCheck` (an
approved-tool allowlist) exists only in K9x Satan, not in the framework.
See Gap Analysis G1/G8.

---

### ASI05 — Unexpected Code Execution (RCE)

**Coverage: Full**

- `ExecutionGuardCheck` (Shield, egress) — literal-string match for
  filesystem destruction, privilege escalation, reverse shells,
  persistence mechanisms, exfiltration commands, and dangerous
  interpreter invocations (`eval(base64`, `os.system(`).
- `ToolArgumentCheck` (Shield, ingress+egress) — command injection,
  subshell injection, and command-chaining patterns in tool arguments,
  independently of `ExecutionGuardCheck`.

**Justification for Full**: this is the one category where two
independent checks, at two different chain positions, both target
overlapping but non-identical patterns for the same underlying threat
class, with no structural gap comparable to the other categories (no
missing allowlist, no opt-in-only wiring, no untested layer). The
general fail-open-on-exception property of `VulnerabilityChain` (see
Cross-Cutting Findings below) applies here as it does everywhere else in
Shield, but is a systemic chain property, not a defect specific to these
two checks' design or coverage.

---

### ASI06 — Memory & Context Poisoning

**Coverage: Not Covered**

No control in `k9_aif_abb/k9_security/` detects fabricated or
contradicted persistent-memory/session-fact claims injected across
turns. `MemoryPoisoningCheck` (session-fact fingerprinting via
`CacheFactory`) exists and is proven in K9x Satan, not in the framework.
Directly closeable by porting the proven pattern — see Gap Analysis
G1/G8.

---

### ASI07 — Insecure Inter-Agent Communication

**Coverage: Partial**

**Justification**: the threat surface this category targets
(interception, spoofing, or replay of messages between agents) is
architecturally narrower in K9-AIF than in frameworks with a native
agent-to-agent (A2A) messaging pattern, because K9-AIF agents do not
message each other directly by convention — CLAUDE.md documents that
agents share data through progressive Squad-level context enrichment,
not inter-agent Kafka messages, and that Agent-to-Agent messaging via a
`message_bus` is "architecturally possible... but not used in standard
K9-AIF solutions." This is a genuine, real mitigating architectural
property, not an oversight. Where Kafka messaging *does* occur (Router
publishing to Orchestrators), the production event bus (`K9EventBus`)
has no authentication or transport encryption at all; only the separate,
less-integrated `KafkaEventFabric` abstraction supports SASL_SSL. See Gap
Analysis G5.

---

### ASI08 — Cascading Agent Failures

**Coverage: Partial**

- `BaseOrchestrator.execute_squads(parallel=True)` isolates per-squad
  exceptions into a `{"status": "failed", ...}` result rather than
  letting one squad's failure propagate and take down sibling squads —
  a direct, genuine mitigation for this category in the
  resource-availability sense.

**Justification for Partial, not Full**: `VulnerabilityChain`'s
exception handling has the inverse property from a security-outcome
perspective — a check that raises an exception is converted to a `FLAG`,
never a `BLOCK`, meaning **a crashing security check fails open**. This
is a defensible resilience choice (one buggy check does not halt the
entire chain) but it is also, from a security-outcome perspective, a
silent erosion of protection: if `ExecutionGuardCheck` throws on
malformed input, the payload proceeds as merely flagged rather than
blocked, with no distinct signal that the check itself failed rather
than passed. This is flagged as a genuine design tension, not simply a
bug — the correct resolution (fail-open vs. fail-closed on check
exception) is a policy decision this review surfaces rather than
resolves unilaterally. See Gap Analysis G6.

---

### ASI09 — Human-Agent Trust Exploitation

**Coverage: Not Covered**

Governance's `REQUIRE_APPROVAL` outcome and Zero Trust's
`approval_threshold` both provide a mechanism for escalating a decision
to a human reviewer, which is a necessary precondition for defending
against this category but not sufficient by itself. Nothing in the
framework addresses the manipulation of the human reviewer once an
approval request reaches them (e.g., an agent framing a request in a way
designed to exploit reviewer trust or authority bias). This is
appropriately difficult to address as a generic framework control — it is
substantially a human-factors/UX concern of whatever system renders the
approval request (e.g., K9X HIL, in downstream deployments), not
something `k9_security/` itself can detect from a payload. Flagged as an
honest limitation rather than forced into a check that could not
meaningfully address it.

---

### ASI10 — Rogue Agents

**Coverage: Partial**

- `enforce_governance()`'s fail-closed behavior in non-development
  environments, and Zero Trust's per-action `DENY`/`REQUIRE_APPROVAL`
  decisions, both bound what an individual agent action can do,
  regardless of the agent's own internal state or intent.

**Justification for Partial, not Full**: all existing controls evaluate a
single action/payload at a time. None perform longitudinal analysis of an
agent's behavior across a session or deployment lifetime to detect drift
from intended function — the literal "insider threat" framing of this
category (an agent that behaves acceptably per-action but has drifted in
aggregate pattern) is not addressed by any point-in-time check. This is a
harder capability to build (it requires session-level state and a
behavioral baseline) and is reasonably scoped as future work rather than
a gap to close in this pass — see Gap Analysis, Future Work note.

---

## Summary Table

| Category | Coverage | Primary gap if Partial/Not Covered |
|---|---|---|
| ASI01 Agent Goal Hijack | Partial | Same as LLM01 — semantic backstop not integrated, pattern-list duplication |
| ASI02 Tool Misuse & Exploitation | Partial | No tool-identity authorization, only argument validation |
| ASI03 Identity & Privilege Abuse | **Not Covered** | Roles captured but never evaluated — no ABAC/RBAC anywhere |
| ASI04 Agentic Supply Chain Vulnerabilities | Not Covered | No provenance check; allowlist exists only in Satan |
| ASI05 Unexpected Code Execution | Full | — |
| ASI06 Memory & Context Poisoning | Not Covered | No check in framework (Satan-only) |
| ASI07 Insecure Inter-Agent Communication | Partial | Architecturally narrowed threat surface; primary event bus has no auth/TLS |
| ASI08 Cascading Agent Failures | Partial | Squad-level isolation good; chain fail-open-on-exception is a real tension |
| ASI09 Human-Agent Trust Exploitation | Not Covered | Escalation mechanism exists; reviewer-manipulation defense is out of scope |
| ASI10 Rogue Agents | Partial | Per-action containment exists; no longitudinal drift detection |

---

## Cross-Cutting Findings (apply across multiple categories above)

1. **`VulnerabilityChain` fails open on a crashing check.** A check that
   raises an exception becomes a `FLAG`, never a `BLOCK`. This affects
   every category whose coverage depends on a Shield check surviving
   malformed or adversarial input designed to crash the check itself,
   not just evade its pattern. See Gap Analysis G6.

2. **`ShieldGovernance` does not thread per-check configuration from
   `config.yaml`.** Every check supports configuration overrides
   (`extra_patterns`, `block_on_match`, thresholds) in its constructor,
   but the governance wrapper that assembles the OOB chain calls
   `cls()` with no arguments — these overrides are reachable only via
   direct Python instantiation, not declaratively. This affects every
   category above that depends on operator-tunable thresholds or
   allowlists. See Gap Analysis G1.
