# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

import logging
import os
from typing import Any

log = logging.getLogger(__name__)


class GovernanceConfigError(RuntimeError):
    """Raised when governance is required but not configured."""


class NoopGovernance:
    """
    Passthrough governance — valid only in development/test environments.

    Do NOT use in production. Pass an explicit governance instance or set
    K9_ENV=development to permit this fallback.
    """

    def pre_process(self, payload: dict, ctx: dict | None = None) -> dict:
        return payload

    def post_process(self, payload: dict, ctx: dict | None = None) -> dict:
        return payload


def require_governance(governance: Any, env: str | None = None) -> Any:
    """
    Resolve the governance object for a component at initialisation time.

    Rules:
    - If *governance* is provided → use it as-is.
    - If *governance* is None and the environment is ``development`` or
      ``test`` → log a WARNING and fall back to :class:`NoopGovernance`.
    - If *governance* is None in any other environment → log an ERROR
      (misconfiguration is clearly visible) and still return
      :class:`NoopGovernance` so the process can start.  Components that
      *require* governed execution must call
      :py:meth:`BaseAgent.enforce_governance` inside ``execute()``; that
      is where the hard fail occurs.

    The resolved environment is taken from the *env* argument first, then
    the ``K9_ENV`` environment variable, defaulting to ``"production"``.
    """
    if governance is not None:
        return governance

    resolved_env = (env or os.getenv("K9_ENV", "production")).lower()

    if resolved_env in ("development", "dev", "test"):
        log.warning(
            "[Governance] No governance pipeline provided — using NoopGovernance "
            "(K9_ENV=%s). This is NOT safe for production.",
            resolved_env,
        )
    else:
        log.error(
            "[Governance] No governance pipeline configured (K9_ENV=%s). "
            "NoopGovernance is active — governed agents will refuse to execute. "
            "Pass an explicit governance instance or set K9_ENV=development.",
            resolved_env,
        )

    return NoopGovernance()

def governance_from_config(config: dict | None) -> Any:
    """Governance a component gets when none is passed in: built from the
    application's own config, so configuring it once covers every agent.

    ``security.shield.enabled: true`` → :class:`ShieldGovernance` over the
    whole config (it reads ``security.shield.ingress/egress.checks``).
    Otherwise ``None`` (→ :func:`require_governance` decides).
    """
    shield = ((config or {}).get("security") or {}).get("shield") or {}
    if shield.get("enabled") is True:
        from k9_aif_abb.k9_security.vulnerability.shield_governance import ShieldGovernance
        return ShieldGovernance(config)
    return None


def is_permissive_env(env: str | None = None) -> bool:
    """development / dev / test tolerate NoopGovernance; everything else
    (including K9_ENV unset, which means production) does not."""
    return (env or os.getenv("K9_ENV", "production")).lower() in ("development", "dev", "test")


def assert_governed(governance: Any, layer: str, logger: logging.Logger | None = None) -> None:
    """Refuse ungoverned execution outside development/test.

    Raises :class:`PermissionError` if *governance* is :class:`NoopGovernance`
    in production/staging; logs a warning and returns in development/test.
    Shared by :class:`BaseAgent` (called automatically around every
    ``execute()``) and the framework adapters (around ``execute_flow()``).
    """
    if not isinstance(governance, NoopGovernance):
        return
    env = os.getenv("K9_ENV", "production").lower()
    if is_permissive_env(env):
        (logger or log).warning(
            "[%s] NoopGovernance active in %s environment — proceeding without enforcement.", layer, env)
        return
    raise PermissionError(
        f"[{layer}] enforce_governance() failed: ungoverned execution refused — NoopGovernance is active "
        f"in {env!r} environment. "
        "Configure governance (e.g. security.shield.enabled: true, or pass governance=...)."
    )
