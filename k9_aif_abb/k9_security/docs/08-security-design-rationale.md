# K9-AIF Security Design Rationale

The *why* behind the decisions made in this review — not a repeat of
`04-gap-analysis.md`'s *what*. Read this when a choice here looks
surprising and you want to know if it was deliberate before changing it.

---

## Why K9X Shield is a framework capability, not an application concern

The task that drove this review states it plainly: *"K9X Shield is a
framework capability. Application developers should configure security
policies — not implement security engines."* Every decision below traces
back to this. A solution team building on K9-AIF should never need to
write a `BaseVulnerabilityCheck` subclass to get standard protection
against prompt injection, SQL injection, or PII leakage — that's the
framework's job, shipped OOB. What a solution team *should* write is
config: which checks run, at what thresholds, against which allowlists.
The extension guide (`07-extension-guide.md`) exists for the genuine
exception — a threat class specific enough to one solution's domain that
no framework default could reasonably cover it.

This is also why the fixes in this review universally targeted
`k9_aif_abb/` rather than adding solution-specific logic anywhere: G1
(config threading), G2 (authorization guard), G4 (contract fix), G5
(transport security), G6 (fail-open policy), and G8 (five ported checks)
all landed in the framework itself, available to every current and future
solution without any of them having to ask for it.

---

## Why K9x Satan is never folded into Shield

Satan is an adversarial test tool **built using** the framework's ABB
classes to attack and validate the framework itself — it is not a governed
application/solution built *on* the framework in the TOGAF sense, and it is
never described as an SBB anywhere in this review's documentation
(corrected during this review after an earlier draft mischaracterized it
that way). The distinction matters architecturally, not just
terminologically: Satan's job is to prove Shield holds under attack by
firing real attacks at a real pipeline and checking whether they're
blocked. If Satan's own attack logic lived inside `k9_security/`, the
framework would be testing itself with itself — a red team that shares
code with what it's attacking cannot produce an independent verdict.

This is precisely why G8's five ported checks are a one-way promotion, not
a permanent coupling: once `ToolAuthorizationCheck`,
`MemoryPoisoningCheck`, `SystemPromptLeakageCheck`,
`OutputSanitizationCheck`, and `RequestFrequencyCheck` were proven correct
in Satan's adversarial harness, they were generalized (Satan-specific
defaults and naming stripped, config shape flattened to match the
framework's own convention — see `04-gap-analysis.md` G8 for the specifics)
and re-verified against the framework's own test suite independently. Satan
still keeps its own copies for its own purposes; the framework's copies
share no code path with Satan going forward. The harvesting direction is
strictly one-way: proven adversarial finding → generalized framework
capability, never framework internals → Satan-specific behavior.

---

## Why several new defaults are default-allow, not default-deny

Two decisions in this review chose to leave existing behavior unrestricted
by default even though a stricter default was available:

- **G2**: `RoleBasedAuthorizationGuard` allows any `action_type` with no
  entry in `role_policy`, rather than denying anything unlisted.
- **G6**: `VulnerabilityChain`'s `fail_open` defaults to `True` (unchanged
  from before this review), even though `fail_open=False` is arguably the
  more secure posture for a crashing check.

Both decisions follow the same reasoning: **Zero Trust and Shield are
already opt-in** (`enable_zero_trust: true`, `security.shield.enabled:
true`). The moment a new guard is composed into `DefaultZeroTrustGuard` by
default, or a new failure-handling default is silently flipped, every
deployment currently relying on `enable_zero_trust: true` or Shield's
existing behavior would experience a behavior change they never asked for
and may not notice until something that used to work starts failing. A gap
fix's job is to make a missing capability *possible* — it is not licence to
also unilaterally decide every deployment's risk tolerance for them. Where
a stricter posture is genuinely warranted, it's exposed as a config option
(`role_policy`, `fail_open: false`) that a deployment opts into
deliberately, with a specific decision-maker taking responsibility for that
tradeoff.

The one case in this review where **default-deny** was chosen instead —
`ToolAuthorizationCheck`'s empty `approved_tools`/`approved_backends`
defaulting to block-everything — is different in kind: this is a *brand
new* check nobody currently depends on (it didn't exist in the framework
before G8), so there is no pre-existing deployment behavior to preserve.
For a genuinely new allowlist-shaped check, an empty allowlist meaning
"nothing is approved yet" is the only defensible reading — an empty
allowlist that meant "everything is approved" would make the check
actively misleading to any operator who enables it expecting it to do
something.

---

## Why fail-open is a policy option, not a resolved question

`VulnerabilityChain`'s handling of a crashing check — FLAG (default) vs.
BLOCK (opt-in via `fail_open=False`) — is a genuine, unresolved tension
between availability and security, not a bug with one correct answer. A
crashing check could mean the check itself has a bug (in which case
failing open keeps the pipeline running while the check gets fixed), or it
could mean the payload was crafted specifically to crash the check as an
evasion technique (in which case failing open is exactly the outcome the
attacker wanted). The framework cannot distinguish these cases from inside
`VulnerabilityChain.run()` — only the deployment knows which risk it's more
worried about. Making this configurable, with the pre-existing behavior
preserved as the default, was the only choice consistent with both "close
the gap" and "don't silently change behavior for existing deployments."

---

## Why authorization is a guard, not folded into risk scoring

`ContextualRiskEvaluator` produces a continuous 0.0–1.0 score from several
additive signals, thresholded afterward into ALLOW/ALLOW_WITH_OBLIGATIONS/
REQUIRE_APPROVAL/DENY. Authorization — "is this principal allowed to
perform this specific action at all" — doesn't fit that shape. It's a
binary privilege question, not a continuously-varying risk contribution;
folding it into the additive score would mean a critically unauthorized
action could still slip through as merely "elevated risk" if the rest of
the context happened to score low, which defeats the entire point of an
authorization check. This is why `BaseAuthorizationGuard` was added
alongside `BaseCompromiseGuard`/`BaseDataLossGuard` (both already
decision-shaped, both already able to short-circuit `evaluate()`) rather
than as a new term inside `ContextualRiskEvaluator.score()`.

---

## Future-proofing against OWASP's own evolution

The task framing this review explicitly asks that the framework "evolve
with future OWASP releases without being tied to a fixed version or count
of checks." Nothing in this review's design hardcodes "12 checks" or
"OWASP LLM Top 10 2025" as a ceiling:

- `_CHECK_REGISTRY` in `shield_governance.py` is a plain dict — adding a
  13th, 20th, or 50th check is a registration, not a schema change.
- `VulnerabilityChain` has no upper bound on chain length and no
  assumption about what threat classes exist — it only knows
  `BaseVulnerabilityCheck` instances produce `PASS`/`FLAG`/`BLOCK`.
- `DefaultZeroTrustGuard`'s guard/evaluator composition (compromise →
  authorization → data-loss → risk) is constructor-injected — a new guard
  slot (G2's `authorization_guard`) was added without touching any
  existing guard's code, and the same pattern extends to a sixth, seventh
  guard.
- The OWASP crosswalks (`02-owasp-llm-crosswalk.md`,
  `03-owasp-agentic-crosswalk.md`) are point-in-time snapshots by
  necessity — OWASP will revise both lists again — but the crosswalk
  *methodology* (Full/Partial/Not-Covered, justified against verified
  source, cross-cutting findings called out separately from
  per-category ones) is what should be re-run against the next revision,
  not re-invented.

The practical implication: closing a *future* OWASP gap should almost
always look like G8 (add a check, register it, document it) or G2 (add a
guard, wire it into the composition point), never like a change to
`VulnerabilityChain`'s or `DefaultZeroTrustGuard`'s own internals. If a
future gap *does* seem to require changing one of those, that's a strong
signal the new threat class doesn't fit the existing contract shape and
deserves its own design conversation before implementation — the same way
authorization-as-a-guard (rather than authorization-folded-into-risk-
scoring) got its own reasoning above instead of being forced into the
nearest existing mechanism.
