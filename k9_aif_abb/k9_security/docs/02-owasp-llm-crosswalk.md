# OWASP Top 10 for LLM Applications (2025) — K9-AIF Crosswalk

Source verified against `https://genai.owasp.org/llm-top-10/` at time of
review. Coverage classification: **Full**, **Partial**, **Not Covered**.
Every control cited below was confirmed present in the codebase during
this review (see `01-capability-inventory.md`); nothing in this crosswalk
is aspirational.

---

### LLM01:2025 — Prompt Injection

**Coverage: Partial**

- `PromptInjectionCheck` (Shield, ingress+egress) — regex match on
  known injection/jailbreak phrasing, always BLOCK.
- `SemanticDriftCheck` (Shield, egress) — goal-hijack phrase detection,
  a specific sub-case of prompt injection targeting mid-session identity
  override.
- `PromptInjectionGuard` (Zero Trust) — a second, independent, smaller
  hardcoded phrase list, evaluated separately from Shield.
- `GovernanceAgent` (opt-in SBB) — an LLM-based "is this request safe"
  classifier in `pre_process()`, which can catch paraphrased or encoded
  injection attempts a regex cannot enumerate.

**Justification for Partial, not Full**: coverage is strong against
literal, known-pattern injection, but two structural limitations remain.
First, regex-based detection is inherently evadable by paraphrase or
encoding — this is a known, general limitation of pattern matching, not
specific to K9-AIF, but the framework's only semantic backstop
(`GovernanceAgent`'s LLM check) is a separate, opt-in SBB, not integrated
into the `ShieldGovernance` chain itself — an operator who enables Shield
does not automatically get semantic screening. Second,
`PromptInjectionCheck` and `PromptInjectionGuard` maintain **independent,
divergent pattern lists** for the same threat class — a pattern added to
one is not automatically available to the other, a maintenance gap that
could produce inconsistent protection depending on which layer (Shield vs.
Zero Trust) is active for a given deployment.

---

### LLM02:2025 — Sensitive Information Disclosure

**Coverage: Partial**

- `PIIBoundaryCheck` (Shield) — email/SSN/credit-card/phone/ZIP pattern
  match, **FLAG by default**, not BLOCK.
- `HardcodedCredentialCheck` (Shield) — credential-pattern match, BLOCK.
- `SensitiveDataLossGuard` (Zero Trust) — triggers
  `ALLOW_WITH_OBLIGATIONS` (mask + audit) when `data_sensitivity` is
  `restricted`/`confidential` **and** the destination is external.

**Justification for Partial, not Full**: three real gaps. (1)
`PIIBoundaryCheck`'s pattern set is narrow (US-formatted identifiers only)
and defaults to non-blocking. (2) `SensitiveDataLossGuard` only fires if
the caller explicitly populates `data_sensitivity`/`destination` on the
`ExecutionContext` — nothing infers sensitivity from payload content, so
a caller that doesn't set these fields gets no data-loss protection from
Zero Trust at all. (3) The two mechanisms (Shield's pattern match, Zero
Trust's sensitivity-tag check) operate on different signals (content vs.
declared metadata) and are not composed — a deployment could enable one
without the other and have a materially different risk posture than
intended.

---

### LLM03:2025 — Supply Chain

**Coverage: Not Covered**

No control in `k9_security/` verifies the integrity or provenance of
models, plugins, tools, or third-party data sources an agent might load
or invoke at runtime. Secret management (`BaseSecretManager`/adapters)
provides safe *credential sourcing* for whatever supply chain is already
trusted — a related but distinct concern from verifying that the supply
chain itself is trustworthy.

**Notable finding**: an "approved tool allowlist" check
(`ToolAuthorizationCheck`) exists and is tested, but only in the
K9x Satan project (an adversarial test tool built using the framework's
ABB classes to test the framework, not a governed solution built on it), not in
`k9_aif_abb` itself. This is a genuine, closeable gap — see Gap Analysis
G1/G8.

---

### LLM04:2025 — Data and Model Poisoning

**Coverage: Not Covered**

No control in `k9_aif_abb/k9_security/` detects fabricated, contradicted,
or injected persistent-memory/session-fact claims. This threat class is
also OWASP Agentic ASI06 (Memory & Context Poisoning) — see that entry in
the Agentic crosswalk for the fuller discussion, since the relevant
existing prior art (`MemoryPoisoningCheck`) is again Satan-local only, not
framework-native. See Gap Analysis G1/G8.

---

### LLM05:2025 — Improper Output Handling

**Coverage: Partial**

- `ToolArgumentCheck` (Shield) validates LLM-generated tool-call
  arguments before execution — SQL injection, command injection, path
  traversal, SSRF patterns.

**Justification for Partial, not Full**: `ToolArgumentCheck` addresses
output handling specifically at the tool-dispatch boundary. There is no
general-purpose check for markup/script injection in an agent's raw text
output before it is rendered into a UI or downstream system (e.g., stored
XSS via an agent's generated HTML/markdown). An `OutputSanitizationCheck`
of this kind exists in K9x Satan, not in the framework. See Gap Analysis
G1/G8.

---

### LLM06:2025 — Excessive Agency

**Coverage: Partial**

- Zero Trust's `REQUIRE_APPROVAL`/`DENY`/`ALLOW_WITH_OBLIGATIONS`
  decisions, and governance's `REQUIRE_APPROVAL` outcome bridging to
  human review, both directly address bounding what an agent is
  permitted to do without oversight.

**Justification for Partial, not Full**: two structural gaps. (1) Zero
Trust is wired only at Router and Orchestrator — the layers that dispatch
work — not at Agent, which is where a tool is actually invoked; an agent
that bypasses its orchestrator's expected flow (or is invoked directly in
a test/alternate harness) receives no Zero Trust evaluation at all. (2)
There is no framework-native mechanism restricting *which* tools an agent
may invoke to an approved set (see LLM03 above — `ToolAuthorizationCheck`
exists only in Satan). Excessive Agency is fundamentally about bounding
scope of action; an allowlist of permitted tools is a direct, standard
mitigation for it that the framework does not yet provide natively.

---

### LLM07:2025 — System Prompt Leakage

**Coverage: Not Covered**

No control in `k9_aif_abb/k9_security/` detects an agent echoing its own
system prompt, role instructions, or internal configuration back in its
output. `SystemPromptLeakageCheck` exists in K9x Satan, not in the
framework. See Gap Analysis G1/G8.

---

### LLM08:2025 — Vector and Embedding Weaknesses

**Coverage: Not Covered**

Out of scope for this review as a `k9_security/` control: no
retrieval/embedding-specific security check exists in this subsystem, and
this review did not extend into `k9_aif_abb`'s retrieval components
(`K9Retriever` and related RAG infrastructure, if present, live outside
`k9_security/`). This is flagged as a legitimate scope boundary, not
treated as a gap to close in this pass — closing it correctly would
require reviewing the retrieval subsystem directly, which was not part of
this task's stated file set (`k9_aif_abb/k9_security/`). Recommended as a
follow-on review, not fabricated as covered here.

---

### LLM09:2025 — Misinformation

**Coverage: Not Covered**

Appropriately out of scope for a framework-level security control —
misinformation is substantially a model-quality/grounding concern, not
something a runtime security layer can reliably detect for arbitrary
content. No control is claimed here, consistent with the instruction not
to force every OWASP category into a vulnerability check where it does
not naturally belong.

---

### LLM10:2025 — Unbounded Consumption

**Coverage: Partial**

- `InputSizeCheck` (Shield) — payload character/key-count limits, BLOCK
  by default.
- `K9EventBus.max_event_bytes` (messaging layer) — truncates oversized
  serialized events with a warning, a distinct DoS control at the
  event-bus layer.

**Justification for Partial, not Full**: both existing controls bound
payload *size*, not request *rate* or cumulative *cost*. There is no
per-session or per-identity rate limiting anywhere in `k9_aif_abb`
itself — `RequestFrequencyCheck` (session request-count limiting via
`CacheFactory`) exists only in K9x Satan. There is also no token-budget or
cost-ceiling enforcement per request or session at the framework level.
See Gap Analysis G1/G8.

---

## Summary Table

| Category | Coverage | Primary gap if Partial/Not Covered |
|---|---|---|
| LLM01 Prompt Injection | Partial | Semantic backstop not integrated into Shield; duplicate pattern lists |
| LLM02 Sensitive Info Disclosure | Partial | PII patterns narrow + FLAG-default; Zero Trust needs caller-supplied sensitivity tags |
| LLM03 Supply Chain | Not Covered | No tool/model provenance check; allowlist exists only in Satan |
| LLM04 Data/Model Poisoning | Not Covered | No memory-poisoning check in framework (Satan-only) |
| LLM05 Improper Output Handling | Partial | No general output-sanitization check (Satan-only) |
| LLM06 Excessive Agency | Partial | Zero Trust not wired at Agent layer; no tool allowlist |
| LLM07 System Prompt Leakage | Not Covered | No check in framework (Satan-only) |
| LLM08 Vector/Embedding Weaknesses | Not Covered | Out of scope for this review (retrieval subsystem) |
| LLM09 Misinformation | Not Covered | Appropriately out of scope for a security control |
| LLM10 Unbounded Consumption | Partial | No rate limiting in framework (Satan-only); no cost/token ceiling |
