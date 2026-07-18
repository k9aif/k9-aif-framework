# K9-AIF Security Extension Guide

How to add new security capability to the framework itself, following the
same ABB/SBB discipline as every other K9-AIF subsystem (see CLAUDE.md's
Architecture & Design Discipline section). This guide is for framework
contributors and solutions that need a genuinely new capability — if the
behavior you want is already possible by configuring an existing check or
guard, use `06-configuration-guide.md` instead.

**The one rule that matters most**: new checks are `BaseVulnerabilityCheck`
subclasses added to `k9_security/vulnerability/checks/`. New guards are
`Base*Guard` subclasses added to `k9_security/zero_trust/guards.py`. Never
add inline conditionals to `VulnerabilityChain`, `ShieldGovernance`,
`DefaultZeroTrustGuard`, `BaseRouter`, or `BaseOrchestrator` themselves —
those are the assemblers, not the place threat-specific logic lives. This
is the exact discipline K9x Satan followed when it built its 5 checks
locally (see `08-security-design-rationale.md`), which is precisely why
they ported into the framework cleanly (G8) — no rewiring of the assembler
was needed, only registration.

---

## Adding a new vulnerability check

### Step 1: Implement `BaseVulnerabilityCheck`

```python
# k9_aif_abb/k9_security/vulnerability/checks/my_new_check.py

from __future__ import annotations
from typing import Any, Dict

from ..base_vulnerability_check import BaseVulnerabilityCheck
from ..models.check_result import CheckResult


class MyNewCheck(BaseVulnerabilityCheck):
    """One sentence: what threat class this detects."""

    def __init__(self, config: Dict[str, Any] | None = None) -> None:
        super().__init__(config)
        # Read check-scoped config directly off self.config — NOT nested
        # under a "security" sub-key. ShieldGovernance passes each check a
        # flat, check-scoped dict (config["security"]["shield"]["check_config"]
        # ["MyNewCheck"]), matching every existing OOB check's convention.
        self._threshold = self.config.get("threshold", 10)
        self._block = self.config.get("block_on_match", True)

    def check(self, payload: Dict[str, Any]) -> CheckResult:
        if self._detects_something(payload):
            msg = "Describe what was found and why it matters"
            if self._block:
                return CheckResult.block(self.check_name, msg, severity="high")
            return CheckResult.flag(self.check_name, msg, severity="medium")
        return CheckResult.pass_check(self.check_name)

    def _detects_something(self, payload: Dict[str, Any]) -> bool:
        ...
```

**Config-shape rule** (this was a real defect found and fixed while porting
Satan's checks in G8 — Satan's originals assumed the *global* app config
was passed to the check, via `self.config.get("security", {}).get(...)`,
which broke the moment they were wired through `ShieldGovernance`'s
`check_config` threading, which passes a flat per-check dict): always read
your check's own settings directly off `self.config`, never off a nested
`"security"` key.

**If your check needs state across separate payloads** (session tracking,
rate limiting, anything that must survive `ShieldGovernance` being rebuilt
fresh per request): use the shared cache helper, not `CacheFactory.create()`
directly in your `__init__` — `CacheFactory.create()` constructs a brand
new adapter on every call and never memoizes, so per-instance state would
never survive across requests with the in-memory default.

```python
from ._shared_cache import get_shared_cache

class MyStatefulCheck(BaseVulnerabilityCheck):
    def __init__(self, config=None):
        super().__init__(config)
        self._cache = get_shared_cache(self.config.get("cache"))
```

### Step 2: Register in the check registry

```python
# k9_aif_abb/k9_security/vulnerability/checks/__init__.py
from .my_new_check import MyNewCheck
__all__ = [..., "MyNewCheck"]

# k9_aif_abb/k9_security/vulnerability/__init__.py
from .checks import ..., MyNewCheck
__all__ = [..., "MyNewCheck"]

# k9_aif_abb/k9_security/vulnerability/shield_governance.py
from .checks import ..., MyNewCheck
_CHECK_REGISTRY = {..., "MyNewCheck": MyNewCheck}
```

Registering makes it wireable by name from `config.yaml` (`checks:
[MyNewCheck]`) — do not add it to the *default* `ingress`/`egress` lists in
`config/config.yaml` unless it's genuinely safe with zero configuration
(most new checks aren't — see how `ToolAuthorizationCheck` and
`SystemPromptLeakageCheck` were deliberately left out of the defaults in
G8, each documented with why).

### Step 3: Decide the default-safety posture, deliberately

Every check needs an explicit answer to: *"what happens if a solution
enables this with zero configuration?"* There are two legitimate answers,
and you must pick consciously, not by accident:

- **Safe no-op until configured** — appropriate when the check needs
  solution-specific knowledge to mean anything (e.g.
  `SystemPromptLeakageCheck` needs *your* system prompt text; with none
  configured, it correctly never fires).
- **Default-deny** — appropriate when the check is an allowlist and an
  empty allowlist is the only defensible default under Zero Trust's
  "deny unless explicitly permitted" posture (e.g. `ToolAuthorizationCheck`
  with no `approved_tools` blocks every tool call, rather than silently
  allowing everything).

Document whichever you choose in the check's own docstring — this decision
is exactly the kind of thing a future reader cannot infer from the code
alone.

### Step 4: Add tests

Follow `tests/test_ported_vulnerability_checks.py` as the template — one
test file per related group of checks, covering: clean-payload PASS,
the threat-triggering BLOCK/FLAG path, config override behavior, and (if
your check flattens nested payloads, like `PIIBoundaryCheck` and the G8
output-facing checks do) a nested-payload test.

---

## Adding a new Zero Trust guard or evaluator

Zero Trust has two distinct extension shapes — pick the one that matches
what you're actually deciding:

- **A guard** (`inspect(context) -> TrustDecision`) — for a binary
  allow/deny/require-approval decision. `BaseCompromiseGuard`,
  `BaseDataLossGuard`, and `BaseAuthorizationGuard` (added in G2) are all
  this shape.
- **An evaluator** (`score(context) -> float`) — for a continuous risk
  contribution that gets thresholded later. `BaseRiskEvaluator` is this
  shape; `ContextualRiskEvaluator` is its only current implementation.

Authorization was added as a *guard* (G2), not folded into
`ContextualRiskEvaluator`'s scoring, because "is this principal allowed to
do this at all" is a yes/no privilege question, not a risk contribution
that should be averaged in with everything else and possibly outweighed by
a low score elsewhere.

### Example: a new guard

```python
# k9_aif_abb/k9_security/zero_trust/guards.py

class BaseComplianceGuard(ABC):
    @abstractmethod
    def inspect(self, context: ExecutionContext) -> TrustDecision:
        raise NotImplementedError


class RegionComplianceGuard(BaseComplianceGuard):
    """Denies actions whose destination falls outside an allowed region set."""

    def __init__(self, allowed_regions: list[str] | None = None) -> None:
        self._allowed_regions = allowed_regions or []

    def inspect(self, context: ExecutionContext) -> TrustDecision:
        region = context.attributes.labels.get("region")
        if self._allowed_regions and region not in self._allowed_regions:
            return TrustDecision.deny(
                reason=f"Destination region '{region}' not in allowed set",
                risk_score=1.0,
            )
        return TrustDecision.allow(reason="Region check passed")
```

Wire it into `DefaultZeroTrustGuard` the same way `authorization_guard` was
added in G2 — a new constructor parameter, defaulted to the OOB
implementation, called in `evaluate()` at the point in the Verify → Control
sequence where it logically belongs (identity/privilege guards before
content-risk scoring; new guards should generally go wherever they most
resemble an existing one).

### Example: a new evaluator

```python
class VelocityRiskEvaluator(BaseRiskEvaluator):
    """Adds risk for a principal making unusually frequent requests."""

    def score(self, context: ExecutionContext) -> float:
        ...  # return 0.0-1.0
```

Pass it to `DefaultZeroTrustGuard(risk_evaluator=VelocityRiskEvaluator())`
to replace `ContextualRiskEvaluator` entirely, or compose both by writing a
small evaluator that calls each and combines their scores — there is no
built-in multi-evaluator composition today because exactly one evaluator
has ever been needed; add one if you need two.

---

## What never changes when extending

Per CLAUDE.md's Provider Adapter Pattern constraints, applied here:

- All new checks/guards are purely additive — no modification to existing
  classes' behavior or defaults.
- Credentials/secrets never in `config.yaml` — environment variables only.
- A zero-config default must exist and must be safe (see Step 3 above) —
  or, where an empty allowlist is the only honest default, that must be
  documented as deliberate default-deny, not left ambiguous.
- New `BaseVulnerabilityCheck`/`Base*Guard` subclasses accept `config=None`
  in `__init__` with sane defaults, exactly like every existing OOB
  implementation.
