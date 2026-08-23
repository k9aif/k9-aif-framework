# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

"""Data models for the BaseValidationLoopAgent iterative reasoning pattern."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class ValidationDisposition(str, Enum):
    """Decision returned by should_continue() after each validation step."""

    CONTINUE  = "continue"   # confidence insufficient — run another iteration
    FINALIZE  = "finalize"   # confidence sufficient — produce final output
    ESCALATE  = "escalate"   # uncertainty unresolvable — route to HIL
    FAIL      = "fail"       # definitive negative — validation cannot pass


@dataclass
class ValidationLoopStep:
    """Immutable record of one iteration inside the validation loop."""

    iteration:   int
    hypothesis:  Any
    tool_result: Any
    observation: Any
    disposition: ValidationDisposition
    confidence:  float = 0.0
    metadata:    Dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationLoopContext:
    """
    Mutable state carried across iterations — the agent's working memory.

    ``metadata`` is the generic extension point for subclass-specific state
    (e.g. K9PlanningLoopAgent's ``remaining_steps``/``notes`` plan-tracking
    fields). It is not a fixed schema — the base loop never reads or writes
    it; only subclasses that need extra carried state do.
    """

    payload:         Dict[str, Any]
    steps:           List[ValidationLoopStep] = field(default_factory=list)
    iteration:       int = 0
    metadata:        Dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationLoopResult:
    """
    Final output produced by finalize(), escalate(), or fail().

    ``output`` is the generic per-subclass payload — subclasses that carry
    extra finalized state (e.g. K9PlanningLoopAgent's final plan/notes)
    include it there rather than as dedicated fields on this shared
    dataclass, so the base ABB's result contract doesn't grow fields that
    only one subclass populates.
    """

    disposition:      ValidationDisposition
    output:           Dict[str, Any]
    steps:            List[ValidationLoopStep]
    iterations:       int
    final_confidence: float
    evidence:         List[str] = field(default_factory=list)
