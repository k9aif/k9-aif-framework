# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework — k9x_Shield
"""
BaseAttack — ABB contract for red-team attack implementations.

GoF Template Method: craft_payload() + run() define the attack skeleton.
Concrete SBBs implement both methods and declare their name and surface.

Mirrors the VulnerabilityChain / BaseVulnerabilityCheck pattern on the
offense side — one check = one handler; one attack = one SBB.

SBBs live in k9x_satan (or any red-team tool in the ecosystem) and import
from here, the same way target SBBs import BaseRouter / BaseOrchestrator.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional


class AttackSurface(str, Enum):
    DOCUMENT = "document"   # inbound document / form content
    SEARCH   = "search"     # web search tool response poisoning
    CONFIG   = "config"     # SBB config override attempt
    PAYLOAD  = "payload"    # raw inbound payload manipulation
    TOOL     = "tool"       # tool call argument injection


class PenetrationDepth(str, Enum):
    """How far the attack penetrated before being stopped."""
    ROUTER       = "router"        # stopped at ingress gate  — Shield held
    ORCHESTRATOR = "orchestrator"  # stopped at egress gate   — Shield held
    SQUAD        = "squad"         # reached squad layer      — FINDING
    AGENT        = "agent"         # reached agent layer      — FINDING
    UNKNOWN      = "unknown"


class AttackOutcome(str, Enum):
    BLOCKED = "BLOCKED"   # stopped at router or orchestrator — Shield held
    FLAGGED = "FLAGGED"   # soft-blocked, flagged for review  — Shield held
    PASSED  = "PASSED"    # not stopped — vulnerability found


@dataclass
class AttackResult:
    """
    Structured result returned by every BaseAttack.run() implementation.

    shield_held is derived — True when outcome is BLOCKED or FLAGGED.
    """
    attack_name:       str
    surface:           AttackSurface
    outcome:           AttackOutcome
    penetration_depth: PenetrationDepth
    payload_sent:      Dict[str, Any]
    response_received: Optional[Dict[str, Any]] = None
    finding:           Optional[str] = None
    notes:             str = ""

    @property
    def shield_held(self) -> bool:
        return self.outcome in (AttackOutcome.BLOCKED, AttackOutcome.FLAGGED)


class BaseAttack(ABC):
    """
    ABB contract for all k9x_Shield red-team attack implementations.

    Each subclass targets one attack surface and one (or more) Shield checks.
    Implement craft_payload() to build the malicious payload and run() to
    fire it through the target pipeline and return an AttackResult.

    Helper methods _classify_depth() and _classify_outcome() interpret the
    standard pipeline response format — override if the target deviates.
    """

    name:    str           = "BaseAttack"
    surface: AttackSurface = AttackSurface.PAYLOAD

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}

    @abstractmethod
    def craft_payload(self) -> Dict[str, Any]:
        """Build and return the malicious payload dict."""
        raise NotImplementedError

    @abstractmethod
    def run(self, target_url: str) -> AttackResult:
        """Fire the attack at target_url and return an AttackResult."""
        raise NotImplementedError

    # ── helpers (override if the target pipeline uses different field names) ──

    def _classify_depth(self, response: Dict[str, Any]) -> PenetrationDepth:
        blocked_at = response.get("blocked_at", "")
        if "router"       in blocked_at: return PenetrationDepth.ROUTER
        if "orchestrator" in blocked_at: return PenetrationDepth.ORCHESTRATOR
        if "squad"        in blocked_at or response.get("squad_id"):
            return PenetrationDepth.SQUAD
        if "agent"        in blocked_at or response.get("agent"):
            return PenetrationDepth.AGENT
        return PenetrationDepth.UNKNOWN

    def _classify_outcome(
        self, response: Dict[str, Any], depth: PenetrationDepth
    ) -> AttackOutcome:
        status = response.get("status", "")
        if status in ("blocked", "rejected"): return AttackOutcome.BLOCKED
        if status == "flagged":               return AttackOutcome.FLAGGED
        if depth in (PenetrationDepth.SQUAD, PenetrationDepth.AGENT):
            return AttackOutcome.PASSED
        return AttackOutcome.BLOCKED
