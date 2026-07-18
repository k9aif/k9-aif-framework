# K9-AIF Security Architecture

This document describes how the framework's security subsystems fit
together as of this review, including the fixes and additions made during
it (G1–G8, see `04-gap-analysis.md`). It is written for someone extending or
integrating with K9-AIF's security layer, not re-deriving it from source.

**Framework capability, not application logic.** Every component described
here is an ABB (abstract contract) or an OOB SBB (concrete, ready-to-use
implementation) shipped by the framework itself. Application developers
configure policy — which checks run, what thresholds apply, which roles are
authorized for which actions — they do not implement security engines. This
principle is why every fix in this review targeted `k9_aif_abb/`, never a
Satan-specific mechanism (see `08-security-design-rationale.md` for why that
boundary is load-bearing).

---

## Two independent, composable layers

K9-AIF ships two security subsystems that solve different problems and can
be used independently or together:

```
┌─────────────────────────────────────────────────────────────────────┐
│                         K9-AIF Security Model                       │
│                                                                       │
│   k9x_Shield                          Zero Trust Execution Layer    │
│   (payload content inspection)        (identity/privilege/risk)     │
│                                                                       │
│   BaseVulnerabilityCheck              BaseCompromiseGuard            │
│     └─ 12 OOB checks                  BaseAuthorizationGuard  (G2)  │
│   VulnerabilityChain                  BaseDataLossGuard              │
│     (Chain of Responsibility)         BaseRiskEvaluator              │
│   ShieldGovernance                    DefaultZeroTrustGuard          │
│     (dual-gate: ingress/egress)         (Verify → Control → Enforce) │
│                                        RuntimePolicyEnforcer          │
│                                                                       │
│   Wired at: BaseAgent pre/post hooks  Wired at: BaseRouter,          │
│   (via governance= parameter)         BaseOrchestrator               │
│                                        (enable_zero_trust: true)      │
└─────────────────────────────────────────────────────────────────────┘
```

**k9x_Shield** answers: *"does this payload's content contain a known
attack pattern?"* — regex/heuristic checks over the actual message content,
composed via GoF Chain of Responsibility, wired at the agent boundary.

**Zero Trust** answers: *"given who is asking, what they're asking for, and
where it's going, should this action proceed?"* — identity, destination,
and risk-attribute evaluation, wired at the Router/Orchestrator boundary
(the layers that make dispatch decisions, per CLAUDE.md's three-level
decoupling).

They are complementary, not redundant: a payload can pass every Shield
check (no attack pattern present) and still be denied by Zero Trust (wrong
principal, restricted destination), and vice versa. Composing both gives
defense-in-depth across two different signal types — content vs. context —
exactly the way the framework's Provider Adapter Pattern composes multiple
independent layers elsewhere (see CLAUDE.md).

---

## k9x_Shield — Chain of Vulnerability Tests

```
BaseVulnerabilityCheck (ABB)
  check(payload) -> CheckResult(PASS | FLAG | BLOCK)
        │
        ▼
VulnerabilityChain
  .add(check).add(check)...
  .run(payload) -> ChainResult
  - BLOCK halts the chain immediately
  - FLAG is non-blocking (unless strict=True promotes it)
  - fail_open=True (default): a raising check → FLAG, not BLOCK  (G6)
        │
        ▼
ShieldGovernance                          <-- reads security.shield from config
  _pre_chain  (ingress — before the LLM)
  _post_chain (egress  — after the LLM, before tool execution)
  check_config: threads config.yaml overrides into each check's           (G1)
  constructor (cls(config=check_config.get(name)))
  raises PermissionError on BLOCK from either gate
```

**12 OOB checks** (`k9_security/vulnerability/checks/`), each independently
config-driven and independently wireable to ingress, egress, both, or
neither:

| Check | Threat class | Default polarity |
|---|---|---|
| `InputSizeCheck` | Oversized payload — token-flood DoS | BLOCK |
| `PromptInjectionCheck` | Injection/jailbreak phrasing | BLOCK |
| `PIIBoundaryCheck` | Email/SSN/credit-card/phone/ZIP patterns | FLAG |
| `HardcodedCredentialCheck` | API keys/secrets/PEM in payload | BLOCK |
| `ToolArgumentCheck` | SQLi/command-injection/path-traversal/SSRF in tool args | BLOCK |
| `SemanticDriftCheck` | Goal-hijacking phrases, loop-trap repetition | BLOCK |
| `ExecutionGuardCheck` | Destructive/reverse-shell/persistence commands | BLOCK |
| `ToolAuthorizationCheck` *(new, G8)* | Unapproved tool identity/backend | BLOCK (default-deny if unconfigured) |
| `MemoryPoisoningCheck` *(new, G8)* | Fabricated/contradicted session memory | BLOCK |
| `SystemPromptLeakageCheck` *(new, G8)* | Agent echoing its own system prompt | BLOCK (no-op if unconfigured) |
| `OutputSanitizationCheck` *(new, G8)* | HTML/JS/template injection in output | BLOCK |
| `RequestFrequencyCheck` *(new, G8)* | Per-session request-rate abuse | BLOCK |

The five G8 checks were ported from the K9x Satan adversarial test tool,
where they were proven against a real pipeline before being generalized
into the framework — see `08-security-design-rationale.md` for why this
promotion path (proven pattern → framework capability) is the correct one
and why Satan itself never becomes part of Shield.

Two of the ported checks (`MemoryPoisoningCheck`, `RequestFrequencyCheck`)
need state to persist across separate requests. Because `CacheFactory.
create()` never memoizes and `ShieldGovernance` may be rebuilt fresh per
request, both checks read from a process-level singleton
(`checks/_shared_cache.py`) rather than each constructing their own
throwaway in-memory store.

---

## Zero Trust Execution Layer

```
ExecutionContext                     <-- identity, attributes, destination, payload
      │
      ▼
DefaultZeroTrustGuard.evaluate()
  1. compromise_guard.inspect()        PromptInjectionGuard      — hard DENY short-circuits
  2. authorization_guard.inspect()     RoleBasedAuthorizationGuard  (G2) — hard DENY short-circuits
  3. data_loss_guard.inspect()         SensitiveDataLossGuard    — ALLOW_WITH_OBLIGATIONS short-circuits
  4. risk_evaluator.score()            ContextualRiskEvaluator   — 0.0-1.0 additive score
       score >= deny_threshold (0.85)        -> DENY
       score >= approval_threshold (0.75)    -> REQUIRE_APPROVAL
       score >= obligation_threshold (0.60)  -> ALLOW_WITH_OBLIGATIONS
       else                                   -> ALLOW
      │
      ▼
RuntimePolicyEnforcer.enforce()      <-- executes obligations: mask_sensitive_data, audit_log
```

Guard ordering matters and is deliberate: identity/privilege
(compromise, then authorization) is checked before content-level risk
scoring — you verify *who* and *whether they're allowed* before spending
effort deciding *how risky* the specific request looks. This is Zero
Trust's own Verify-before-Control principle, not an implementation
accident.

**`RoleBasedAuthorizationGuard` (G2)** is the framework's first
identity/privilege evaluator — it reads `IdentityContext.roles` (previously
captured but never consumed by anything) against a `role_policy` mapping of
`action_type -> [allowed roles]`. An `action_type` with no entry in the
policy is **allowed** — this guard enforces only what a solution has
deliberately restricted; see `08-security-design-rationale.md` for why
default-allow (not default-deny) is correct here specifically.

Zero Trust is wired at `BaseRouter` and `BaseOrchestrator` via
`enable_zero_trust: true` — **not** at `BaseSquad` or `BaseAgent`. An agent
invoked outside its normal Router/Orchestrator dispatch path (a direct call,
an alternate test harness) receives no Zero Trust evaluation. This is a
known, documented boundary (see `01-capability-inventory.md` §2), not
something this review closed — closing it would mean re-architecting where
Zero Trust attaches, a larger change than a gap fix.

---

## Governance Pipeline — the third integration point

`BaseGovernance` (`pre_process`/`post_process`, both async) is the contract
every agent's pre/post hooks call through `apply_pre_governance()`/
`apply_post_governance()`. Both `ShieldGovernance` and hand-written
governance SBBs (`ProfanityGovernance`, `GovernanceAgent`) implement this
same contract, which is why Shield can be wired into an agent as a drop-in
governance backend (`governance=ShieldGovernance(config)`) alongside, or
instead of, any other governance implementation.

`enforce_governance()` (on `BaseAgent`) is the actual enforcement point —
raises `PermissionError` if the resolved governance is `NoopGovernance` and
`K9_ENV` is not development/test. Governance is opt-in per agent: an agent
that never calls `self.enforce_governance()` runs ungoverned in production
silently. This is a known, documented framework behavior (CLAUDE.md), not
something this review changed.

---

## Where each new capability from this review attaches

| Gap | New capability | Attaches to |
|---|---|---|
| G1 | `check_config` threading | `ShieldGovernance.__init__` / `_build_chain` |
| G2 | `RoleBasedAuthorizationGuard` | `DefaultZeroTrustGuard` (new `authorization_guard` param) |
| G4 | Contract-shape + 2 bug fixes | `ProfanityGovernance` (standalone SBB, no wiring change) |
| G5 | SASL/TLS support | `K9EventBus` (`_security_kwargs()`, threaded via `MessageFactory`) |
| G6 | `fail_open` policy | `VulnerabilityChain` (constructor param, threaded through `ShieldGovernance`) |
| G8 | 5 ported checks | `_CHECK_REGISTRY` in `shield_governance.py` (opt-in, not default-enabled) |

None of these required a new architectural layer — every fix extended an
existing ABB/SBB/factory seam that was already there, which is itself a
signal the original architecture was sound; the gaps were incomplete
wiring and missing evaluators, not missing structure (see
`04-gap-analysis.md` for the full reasoning per gap).
