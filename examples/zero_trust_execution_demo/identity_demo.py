# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
Zero Trust identity demo (k9-aif 1.14): can an agent grant itself a role?

Zscaler ThreatLabz's 2026 report predicts attacker agents talking to
enterprise agents, "requesting data, escalating privileges, or triggering
actions" through spoofed interactions. This demo shows the same request
three ways:

  1. payload mode (the 1.x default): the agent writes roles into its own
     payload and Zero Trust believes it
  2. signed mode: the same self-declared roles are ignored; the caller is
     anonymous and denied
  3. signed mode, admitted: the Router authenticates the agent's API key,
     strips the claims and stamps a signed identity; the orchestrator
     verifies it and allows the action

Run:
    K9_ENV=development python examples/zero_trust_execution_demo/identity_demo.py

The API key and signing secret below are demo values set in-process; in a
real deployment both live in .env (K9_KEY_*, K9_IDENTITY_SECRET).
"""

from __future__ import annotations

import os

os.environ.setdefault("K9_IDENTITY_SECRET", "demo-only-secret")
os.environ.setdefault("K9_KEY_CLAIMS_BOT", "demo-key-claims-bot")

from k9_aif_abb.k9_core.orchestration.base_orchestrator import BaseOrchestrator  # noqa: E402
from k9_aif_abb.k9_core.router.base_router import BaseRouter  # noqa: E402
from k9_aif_abb.k9_security.zero_trust.guards import (  # noqa: E402
    DefaultZeroTrustGuard, RoleBasedAuthorizationGuard)

# Only principals holding claims_approver may approve a claim.
ROLE_POLICY = {"approve_claim": ["claims_approver"]}

# The one agent allowed to approve: its key lives in $K9_KEY_CLAIMS_BOT.
AUTH = {"api_keys": {"claims-bot": {"env": "K9_KEY_CLAIMS_BOT", "principal_type": "agent",
                                    "roles": ["claims_approver"]}}}

# What an attacker agent sends: it simply claims the role.
SPOOFED = {"action_type": "approve_claim", "claim_id": "CLM-7731",
           "principal_id": "claims-bot", "principal_type": "agent",
           "roles": ["claims_approver"], "trust_zone": "internal"}


class ClaimsOrchestrator(BaseOrchestrator):
    layer = "ClaimsOrchestrator"

    def execute_flow(self, payload):
        zt = self.apply_zero_trust(payload)
        if not zt["allowed"]:
            return {"status": "DENIED", "reason": zt["reason"]}
        return {"status": "APPROVED", "claim_id": payload["claim_id"]}


class EdgeRouter(BaseRouter):
    layer = "EdgeRouter"

    def route(self, payload):
        return payload


def orchestrator(mode: str) -> ClaimsOrchestrator:
    return ClaimsOrchestrator(
        config={"security": {"identity": {"mode": mode}}},
        enable_zero_trust=True,
        zero_trust_guard=DefaultZeroTrustGuard(
            authorization_guard=RoleBasedAuthorizationGuard(role_policy=ROLE_POLICY)),
    )


def show(title: str, result: dict) -> None:
    print(f"\n{title}\n  -> {result['status']}" + (f": {result['reason']}" if "reason" in result else ""))


if __name__ == "__main__":
    show("1. payload mode, agent claims claims_approver in its payload",
         orchestrator("payload").execute_flow(dict(SPOOFED)))

    show("2. signed mode, same self-declared claim",
         orchestrator("signed").execute_flow(dict(SPOOFED)))

    router = EdgeRouter(config={"security": {"auth": AUTH}})
    admitted = router.admit({"action_type": "approve_claim", "claim_id": "CLM-7731"},
                            credentials={"api_key": os.environ["K9_KEY_CLAIMS_BOT"]})
    show("3. signed mode, agent authenticated by the Router (admit)",
         orchestrator("signed").execute_flow(admitted))
