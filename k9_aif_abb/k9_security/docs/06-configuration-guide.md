# K9-AIF Security Configuration Guide

Everything in this guide is configuration — no code required. If you find
yourself writing a new `BaseVulnerabilityCheck` or `BaseZeroTrustGuard`
subclass to get the behavior you need, see `07-extension-guide.md` instead.

All security capability in K9-AIF ships **disabled or unrestricted by
default** — enabling it, and deciding how strict it is, is entirely a
solution-config decision. This section covers `k9_aif_abb/config/config.yaml`
under the `security:` key.

---

## k9x_Shield

```yaml
security:
  shield:
    enabled: false          # nothing runs until this is true
    strict: false           # true: promotes every FLAG to a BLOCK
    fail_open: true         # false: a crashing check becomes BLOCK, not FLAG
    ingress:                # runs before the LLM
      checks:
        - InputSizeCheck
        - PromptInjectionCheck
        - PIIBoundaryCheck
    egress:                 # runs after the LLM, before tool execution
      checks:
        - SemanticDriftCheck
        - ToolArgumentCheck
        - ExecutionGuardCheck
        - PIIBoundaryCheck
    check_config:            # per-check constructor overrides, keyed by class name
      InputSizeCheck:
        max_chars: 50000
      PIIBoundaryCheck:
        block_on_match: true
```

Wire it into an agent as a governance backend:

```python
from k9_aif_abb.k9_security.vulnerability import ShieldGovernance

agent = MyAgent(config=config, governance=ShieldGovernance(config))
```

### `strict` vs `fail_open` — two independent dials

These control different failure modes and are easy to conflate:

- **`strict`** changes what happens on a *normal* `FLAG` result (a check ran
  successfully and found something worth flagging but not blocking) — with
  `strict: true`, that FLAG is promoted to a BLOCK.
- **`fail_open`** changes what happens when a check *raises an exception*
  (a bug in the check itself, or malformed input the check didn't
  anticipate). `fail_open: true` (default) converts the exception to a
  FLAG — the payload proceeds, but you find out via logs/audit that a check
  didn't run cleanly. `fail_open: false` converts it to a BLOCK instead —
  the payload is rejected outright rather than silently passing whatever
  the crashing check would have inspected.

If you're running Shield in a compliance-sensitive deployment where "a
check silently stopped protecting" is unacceptable, set `fail_open: false`.
If availability matters more than that specific edge case, leave the
default. There is no universally correct answer — this is why it's a
config option, not a changed default (see `04-gap-analysis.md`, G6).

### Enabling the five newly-ported checks

These are registered but **not** in the default `ingress`/`egress` lists —
each needs solution-specific configuration to be meaningful, and adding
them to the shipped defaults would silently change behavior for every SBB
that copies this config file.

**`ToolAuthorizationCheck`** — approve specific tools/backends. With no
config, both allowlists default to empty, which means **any** `tool_name`
or `*_backend`/`*_url`/`*_endpoint` field present in the payload is
blocked (default-deny). Configure your actual allowlist before enabling:

```yaml
security:
  shield:
    egress:
      checks: [ToolArgumentCheck, ToolAuthorizationCheck]
    check_config:
      ToolAuthorizationCheck:
        approved_tools: ["search", "lookup_claim"]
        approved_backends: ["internal-api.example.com", "localhost"]
```

**`SystemPromptLeakageCheck`** — list your agents' actual role/goal text so
leaked fragments can be detected. With no config it's a safe no-op (empty
fragment list, nothing to match):

```yaml
security:
  shield:
    egress:
      checks: [SystemPromptLeakageCheck]
    check_config:
      SystemPromptLeakageCheck:
        system_prompt_fragments:
          - "You are a claims adjudication agent."
        leakage_min_chars: 20   # ignore fragments shorter than this
```

**`OutputSanitizationCheck`** — no config required, safe to enable directly
(pattern set is already framework-generic, not solution-specific):

```yaml
security:
  shield:
    egress:
      checks: [OutputSanitizationCheck]
    check_config:
      OutputSanitizationCheck:
        block_on_output_markup: true   # false: FLAG instead of BLOCK
```

**`MemoryPoisoningCheck`** — needs no required config; tune the tracked
fact keys if your domain's session-critical fields differ from the
defaults:

```yaml
security:
  shield:
    egress:
      checks: [MemoryPoisoningCheck]
    check_config:
      MemoryPoisoningCheck:
        memory_ttl: 3600
        tracked_fact_keys: [claim_amount, policy_number, approval_status]
```

**`RequestFrequencyCheck`** — set your session request budget:

```yaml
security:
  shield:
    ingress:
      checks: [RequestFrequencyCheck]
    check_config:
      RequestFrequencyCheck:
        max_requests_per_window: 20
        rate_limit_window_seconds: 60
```

`MemoryPoisoningCheck` and `RequestFrequencyCheck` both accept a `cache:`
sub-key to point at a real backend (Redis) instead of the in-memory default
— useful once you're running multiple agent processes that all need to see
the same session counters:

```yaml
check_config:
  RequestFrequencyCheck:
    max_requests_per_window: 20
    cache:
      provider: redis
```

---

## Zero Trust

```yaml
# On BaseRouter or BaseOrchestrator construction:
enable_zero_trust: true
```

Zero Trust doesn't currently have a single `config.yaml` block the way
Shield does — `DefaultZeroTrustGuard` is composed in code, with each guard
independently constructible. The most common customization is supplying a
`role_policy` for authorization:

```python
from k9_aif_abb.k9_security.zero_trust import (
    DefaultZeroTrustGuard,
    RoleBasedAuthorizationGuard,
)

guard = DefaultZeroTrustGuard(
    authorization_guard=RoleBasedAuthorizationGuard(role_policy={
        "approve_claim": ["adjudicator", "supervisor"],
        "delete_record": ["admin"],
    }),
)
```

Every `action_type` **not** listed in `role_policy` is allowed regardless of
the principal's roles — this guard restricts only what you've explicitly
listed. See `08-security-design-rationale.md` for why this default is
deliberate, not an oversight.

Threshold tuning (all three are keyword args to `DefaultZeroTrustGuard`):

```python
DefaultZeroTrustGuard(
    deny_threshold=0.85,
    approval_threshold=0.75,
    obligation_threshold=0.60,
)
```

Lower `deny_threshold` for a stricter posture (more requests denied
outright); raise `obligation_threshold` to reduce audit/masking overhead
for low-risk traffic.

---

## Messaging (K9EventBus)

```yaml
messaging:
  backend: kafka                    # kafka | redpanda
  brokers: ["${KAFKA_BROKER:-localhost:9092}"]
  topic: my-app-events
  group_id: my-app-core
  security_protocol: PLAINTEXT      # PLAINTEXT (default) | SASL_SSL
  sasl_mechanism: PLAIN             # PLAIN | SCRAM-SHA-256 | SCRAM-SHA-512
```

Credentials are **never** read from `config.yaml` — set them via
environment variables only:

```bash
# .env
KAFKA_SASL_USERNAME=svc-account
KAFKA_SASL_PASSWORD=your-secret-here
```

`security_protocol: PLAINTEXT` (the default) is byte-for-byte identical to
the connection behavior before this option existed — enabling SASL_SSL is
strictly opt-in and does not change any existing deployment's behavior
until the config key is explicitly set.

---

## Governance

```yaml
governance:
  enabled: true
  policy_path: "k9_aif_abb/policies/governance.yaml"
```

Per-agent enforcement is a code-level decision (`self.enforce_governance()`
inside `execute()`), not a config toggle — see Skill 5 in SKILLS.md.
`K9_ENV=development` or `test` permits `NoopGovernance`; any other value
raises `PermissionError` from `enforce_governance()` if no real governance
backend was supplied.

---

## Enterprise config lock

```yaml
_policy:
  locked: []   # e.g. [security.shield.enabled, enable_zero_trust, governance.enabled]
```

Keys listed here cannot be overridden by an SBB's own `config.yaml` or
agent YAML — `AgentLoader` restores the ABB-level value and logs a warning
on any attempted override at merge time. Ships empty by default; an
enterprise deployment that wants to guarantee Shield or Zero Trust cannot
be silently disabled by a downstream solution should populate this list.
