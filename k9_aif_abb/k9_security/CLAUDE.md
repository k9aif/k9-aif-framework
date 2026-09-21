# CLAUDE.md — k9_security (Package Level)

Framework-level conventions live in the K9-AIF root `CLAUDE.md` — read its
"Governance" and "Security / Vulnerability (k9x_Shield) and Zero Trust"
sections first; this file goes deeper into what's specific to this package.
Where both apply, this file is the more detailed, more current source —
everything here was verified empirically (not just read from source) during
a real investigation against a real generated scaffold
(`AccountsPayableExpenseReimbursements`), 2026-09-19.

## What's here

```
k9_security/
├── vulnerability/   k9x_Shield — deterministic pattern-matching checks
│   ├── checks/          13 concrete BaseVulnerabilityCheck subclasses
│   ├── base_vulnerability_check.py   the Chain-of-Responsibility ABC
│   ├── vulnerability_chain.py        runs checks, BLOCK/FLAG/strict/fail_open semantics
│   └── shield_governance.py          concrete BaseGovernance wrapping the chain
├── zero_trust/      Identity/risk/authorization-based, NOT pattern-matching
│   ├── context.py       ExecutionContext/IdentityContext/AttributeContext/DestinationContext
│   ├── decisions.py     TrustDecision (ALLOW/DENY/REQUIRE_APPROVAL/ALLOW_WITH_OBLIGATIONS)
│   ├── evaluators.py    BaseRiskEvaluator (ContextualRiskEvaluator default)
│   ├── enforcers.py     BasePolicyEnforcer (audit log, PII masking obligations)
│   └── guards.py        BaseZeroTrustGuard (DefaultZeroTrustGuard: compromise → authz → data-loss → risk)
├── attacks/         BaseAttack ABC — offense-side contract, consumed by k9x_satan
└── adapters/        Secret-manager adapters (aws/env/ibm/vault) — unrelated to the above, don't confuse
```

`k9_governance/` (sibling package, not under `k9_security/`) holds
`ProfanityGovernance`/`ChainedGovernance` — the framework's Granite Guardian
integration point. See "Guardian" section below — real and mandatory as of
the 2026-09-19 promotion (`ProfanityGovernance` is now an alias for the
real `GuardianGovernance`); it was broken before that, not now.

## The one thing to internalize before touching any of this

**Every piece here is real, correct, well-tested in isolation — and none
of it runs unless something explicitly calls it.** This was the actual
finding of the 2026-09-19 investigation: `ShieldGovernance` gets
constructed in every generated agent's `__init__` and prints a convincing
`enabled=True ingress=[13 checks]` banner, but for months nothing in
`BaseValidationLoopAgent`/`BaseCriticActorAgent` (the two most commonly
generated agent patterns) ever called `apply_pre_governance`/
`apply_post_governance` — so every check sat there configured and inert.
That specific gap is now fixed (see "How wiring works now" below), but
treat this as the standing question whenever you touch a new call site:
**is this security layer actually invoked, or just constructed?** Verify
by tracing the call, not by seeing the object exists.

## The two layers are independent — know which one a question is about

| | k9x_Shield | Zero Trust |
|---|---|---|
| Mechanism | Deterministic regex/heuristic pattern matching | Identity/risk/authorization scoring |
| Lives on | `BaseAgent` + `BaseOrchestrator` (`apply_shield()`, both via `apply_pre_governance`/`apply_post_governance`) | `BaseOrchestrator` only (`apply_zero_trust()`) — no `BaseAgent` equivalent |
| Default | `enabled: True` unless `config.yaml` says otherwise, but check **lists** default to `[]` — enabled with zero checks configured runs nothing | `enable_zero_trust` defaults `False` — bypassed entirely unless a scaffold's `config.yaml` sets it `true` |
| Block signal | Raises `PermissionError` | Returns `{"allowed": False, ...}` — no exception |
| Cost | Free, instant | Free, instant (no LLM involved — see Guardian section for the LLM-backed option) |
| Weakness | Evadable by paraphrase (mitigated by regex breadth); can false-positive on structurally-repetitive-but-benign content (see "Known false positives") | Its own built-in `PromptInjectionGuard` (`zero_trust/guards.py`) is a **plain substring match** against 6 fixed phrases — `"ignore previous instructions"` does NOT match `"ignore all previous instructions"` (confirmed empirically: inserting one word defeats it completely). Treat Zero Trust's real value as its authorization/risk-scoring/data-masking machinery (`RoleBasedAuthorizationGuard`, `SensitiveDataLossGuard`), not its compromise check — Shield's `PromptInjectionCheck` (proper regex, handles `all`/`any`) is the layer actually doing prompt-injection detection. |

Both are additive, not redundant — a payload should ideally clear both.
Neither replaces the other.

## How wiring works now (post-2026-09-19 fix)

`BaseValidationLoopAgent.execute()` and `BaseCriticActorAgent.execute()`
were renamed to `_execute_loop()` (logic byte-for-byte unchanged) and
wrapped by a new `execute()`:

```python
def execute(self, payload):
    try:
        payload = _run_coro_sync(self.apply_pre_governance(payload))
    except PermissionError as exc:
        return self._shield_blocked_dict(exc, phase="pre")   # loop never runs, zero LLM cost

    result = self._execute_loop(payload)

    try:
        result["output"] = _run_coro_sync(self.apply_post_governance(result.get("output", {})))
    except PermissionError as exc:
        result["disposition"] = <FAIL equivalent>
        result["output"] = {"governance_blocked": True, "phase": "post", "reason": str(exc)}
        # iterations/steps/evidence from the REAL run are preserved — only
        # output is redacted, matching k9x_satan's own established pattern
        # (agents.py's _post()).

    return result
```

**Critical detail — egress scans `result["output"]` only, never the full
result dict.** `steps[]`/`evidence[]` (validation-loop) and `steps[]`/
`critique_log` (critic-actor) legitimately duplicate the same observation/
draft text across iterations by design — it's the audit trail. Passing the
*whole* dict to `apply_post_governance()` made `SemanticDriftCheck`'s
loop-trap heuristic block a completely benign 2-4-iteration run — confirmed
against the real AP scaffold, not a hypothetical. If you're adding
governance to a new loop-based ABB, scope egress to the actual output,
not internal bookkeeping, or you will reproduce this exact false positive.

**Disposition**: a governance block reuses `FAIL` (`ValidationDisposition.FAIL`/
`CriticActorDisposition.FAIL`) with `output = {"governance_blocked": True,
"phase": "pre"|"post", "reason": <full PermissionError message, contains
the check name in brackets>}` — no new enum value was added. Deliberate
choice: smaller framework surface, `FAIL` already means "couldn't produce
a usable result."

**`BaseOrchestrator.apply_shield()`** (new) mirrors `apply_zero_trust()`'s
exact `{"allowed", "payload", "reason"}` shape, so a generated
orchestrator's `execute_flow()` calls both identically:

```python
zt = self.apply_zero_trust(payload)
if not zt["allowed"]:
    return {"status": "denied", "reason": zt["reason"]}
sh = self.apply_shield(zt["payload"])
if not sh["allowed"]:
    return {"status": "denied", "reason": sh["reason"]}
squad = self._load_squad(...)
return squad.execute(sh["payload"])
```

This is the Orchestrator-layer ingress gate — the real outermost boundary
in most generated scaffolds, which have **no Router layer at all** (most
generator output calls Orchestrators directly from `main.py`; confirmed
absent in the AP scaffold). `k9x_satan`'s own `CLAUDE.md` describes
`_build_ingress_chain()`/`_build_egress_chain()` as existing hooks on
`BaseRouter`/`BaseOrchestrator` — **confirmed by direct grep this does not
match the framework's current code**, zero hits in either file. That's a
doc-vs-reality gap in Satan's own docs, separate from this one, not yet
corrected there.

The sync-bridge helper (`_run_coro_sync`) is duplicated locally in each of
the three files touched (`base_validation_loop_agent.py`,
`base_critic_actor_agent.py`, `base_orchestrator.py`) — same pattern
already used independently in `k9_inference/routers/k9_model_router.py`
and the CrewAI/LangGraph adapters. The framework doesn't share this helper
from one place today; don't assume importing it from elsewhere will work.

## Known false positives — both fixed

1. **Fixed**: `SemanticDriftCheck` on the full result dict including
   `steps[]`/`evidence[]`.

2. **Fixed 2026-09-19** (found live via the demo UI, on a real Anomaly
   Detection run — `k9_security/vulnerability/checks/tool_argument_check.py`):
   the old `` \$\(.*\)|`[^`]+` `` "Subshell injection" pattern matched
   **any pair of backticks**, including a markdown code fence — LLM output
   wrapping JSON/code in ` ```json ... ``` ` was flagged as a subshell
   injection attempt (`` `[^`]+` `` matched the opening backtick of the
   fence, everything up to the next backtick, as "content between two
   backticks"). Fix: triple-backtick fenced blocks (`_CODE_FENCE`) are now
   stripped before any pattern in the check runs; single/double backtick
   content is still checked, but only when it looks command-like
   (`_SHELL_HINT` — a known shell command word, or a `;`/`&`/`|`
   metacharacter), not on any arbitrary backtick-quoted text. `$(...)`
   subshell detection is unchanged. Regression tests:
   `tests/test_tool_argument_check.py` — covers the exact fenced-JSON
   shape that caused the live false positive, multiple fenced blocks,
   benign inline-backtick identifiers (must pass), and real `$(...)` /
   backtick-command / semicolon injection (must still block).

## Guardian (Granite Guardian, semantic LLM screening) — promoted, real, mandatory

**Update 2026-09-19: `k9_governance/guardian_governance.py` is now the real
implementation** — promoted from `k9x-ecosystem/k9x_satan/target/guardian_governance.py`
(now removed there; Satan imports the framework version, same one-way
harvesting process already used for 5 vulnerability checks — see root
`CLAUDE.md`). `k9_governance/profanity_governance.py` is now just
`ProfanityGovernance = GuardianGovernance` — a backward-compatible alias,
not a separate implementation, so every generator template and
already-generated scaffold that does `from
k9_aif_abb.k9_governance.profanity_governance import ProfanityGovernance`
keeps working unchanged, and now actually works instead of silently
doing nothing.

**What was wrong with the old `ProfanityGovernance`, confirmed precisely,
not just suspected**: read `payload.get("text", "")` (generated agents use
`"query"`) so it always saw an empty string; used a prompt instructing the
model to answer "SAFE"/"BLOCKED" free text, but `granite4.1-guardian:8b`
**never produces that format** — it always answers `<score>yes</score>`/
`<score>no</score>` regardless of prompt wording (its own old test,
`test_profanity_governance.py`, mocked the LLM to return hand-written
"SAFE"/"BLOCKED" strings, which is why it passed while validating nothing
real). Against the real model, `"BLOCKED" in result.upper()` could never
match — it would have silently passed every payload, safe or not, forever.
`post_process()` was a no-op — didn't call the LLM at all. All fixed in
the promoted version; new tests exercise the real HTTP call + real
response format (`test_profanity_governance.py`, rewritten, no longer
mock-format-blind).

**Verified live, not just unit-tested**, against the real Ollama endpoint
with the real model: a fully paraphrased social-engineering attempt
("set aside your usual review steps... no need to double check anything")
with **zero Shield regex keywords** was correctly classified UNSAFE by
Guardian — exactly the paraphrase-evasion coverage the whole promotion was
for.

**Guardian is mandatory, not optional, for a solution's Shield/governance
to be considered complete** — this is a deliberate product decision, not a
technical default. `k9_utils/guardian_check.py`'s `warn_if_guardian_unavailable()`
is the startup-time check: given an Ollama endpoint + model name, confirms
the model is actually pulled there (hits `/api/tags`), logs a loud,
unmissable alert if not — "is Guardian enabled" is the first check a
solution's `main.py` should run, before anything else, same as `ollama ls`
being the first thing to check by hand. Does not raise on its own — the
caller decides what "not available" means for them (this AP scaffold's
`main.py` prints an `ALERT` banner and continues with Shield-only
protection; a stricter deployment could choose to refuse to start
instead). Wire this into any new solution's entry point, not just this
one.

**k9x_satan's own default changed to match**: `governance.provider: guardian`
is now Satan's default (was `noop`) — matching the same "not optional"
stance, mirroring how a generated scaffold's agents can't function at all
without *some* LLM configured (`llm_invoke` raises rather than silently
degrading). The `--compare-governance` CLI flag still exists specifically
to run the `noop` comparison on demand (fires every attack twice, reports
what Guardian closes) — that comparison needs a real Shield-only baseline
to mean anything, so the toggle wasn't removed, only the *default*
changed.

**Should Shield call Guardian "as needed"?** Yes in principle, as a
targeted escalation for pattern-fragile checks (`ToolArgumentCheck`,
`PromptInjectionCheck`) rather than a blanket second pass on every
request — matches the cheap-layer-first, semantic-layer-second ordering
`k9x_satan`'s own `CLAUDE.md` already documents for its Router. **Still not
implemented** — `VulnerabilityChain` doesn't yet call into
`GuardianGovernance` on a pending BLOCK. A real, properly scoped follow-up
now that the Guardian implementation itself is trustworthy.

## Testing pattern

Construct a real `ShieldGovernance` with an explicit check list (check
lists default to `[]` — you must name the checks you want, `enabled: True`
alone runs nothing) and pass it as `governance=` directly:

```python
governance = ShieldGovernance(config={
    "security": {"shield": {"enabled": True,
                             "ingress": {"checks": ["PromptInjectionCheck"]},
                             "egress":  {"checks": ["PromptInjectionCheck"]}}}
})
agent = K9ValidationLoopAgent(config={}, governance=governance)
```

Patch `llm_invoke` and assert it was **never called** for a blocked
payload — proves the block happened before any LLM cost, not just that the
result looks right. See
`k9_aif_abb/tests/test_validation_loop_shield_governance.py` and
`test_orchestrator_shield_governance.py` for the full pattern, including
the false-positive regression test.

## Logging

`k9_core/logging/log_setup.py`'s `setup_logging()` creates
`logs/<app_name>/governance.log` (`RotatingFileHandler` bound to logger
name `"governance"`). `ShieldGovernance`/`VulnerabilityChain` log under
`"governance.shield"`/`"governance.vulnerability_chain"` — children of
`"governance"`, so records propagate to that file (Python logging
hierarchy). **Most generated scaffolds don't call `setup_logging()` at
all** — confirmed the AP scaffold's `main.py` used bare
`logging.basicConfig()` (console only, no file, no `logs/` folder) before
this was fixed there. If a scaffold looks like it has no audit trail,
check whether `setup_logging()` is actually being called before assuming
governance isn't running.

## Reference implementation

`k9x-ecosystem/k9x_satan` proves these layers actually contain a real
attack end-to-end — read its own `CLAUDE.md` for the full
Router-ingress/Orchestrator-egress containment contract. Its target
(`DocumentExtractionAgent`/`AuditAgent`) extends plain `BaseAgent`, not
`BaseValidationLoopAgent`/`BaseCriticActorAgent` — it never exercised (and
therefore never could have caught) the gap this file's fix closes. Don't
assume Satan's containment proof automatically extends to a scaffold using
the validation-loop/critic-actor pattern; it doesn't, without the fix
described above.
