from __future__ import annotations

from typing import Any, Dict, Optional


def make_governance(config: Dict[str, Any]) -> Optional[Any]:
    """
    Return the configured governance instance, or None for NoopGovernance
    default (require_governance() resolves None to NoopGovernance, gated
    only by K9_ENV).

    "shield" wires in ShieldGovernance (k9_aif_abb.k9_security.vulnerability)
    — a framework OOB class — using the security.shield block in config.yaml.
    Same pattern as k9x_satan's target/squad.py:_make_governance(), the
    other place this exact wiring is proven in a real, running pipeline.
    """
    provider = (config or {}).get("governance", {}).get("provider", "noop")
    if provider == "shield":
        from k9_aif_abb.k9_security.vulnerability.shield_governance import ShieldGovernance
        return ShieldGovernance(config=config)
    return None
