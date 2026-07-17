"""k9_security.attacks — ABB contracts for red-team attack implementations."""

from .base_attack import (
    BaseAttack,
    AttackResult,
    AttackOutcome,
    AttackSurface,
    PenetrationDepth,
)

__all__ = [
    "BaseAttack",
    "AttackResult",
    "AttackOutcome",
    "AttackSurface",
    "PenetrationDepth",
]
