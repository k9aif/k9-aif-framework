# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

"""
RequiresHIL -- the signal an Agent or Squad raises to trigger human review.

Deliberately an exception, not a return-value flag. A Squad's ``execute()``
drives a sequential agent flow it doesn't fully control the top of; if
"needs HIL" were just a dict key, it only reaches the Orchestrator when
every layer in between remembers to check for it. An exception unwinds the
call stack automatically -- it reaches the Orchestrator whether or not the
Squad author ever thought about HIL.

Only the Orchestrator may catch it (see BaseOrchestrator.handle_requires_hil()).
Agents and Squads never touch Kafka directly, even for HIL -- see CLAUDE.md's
Kafka ownership section for why that's a consistency requirement, not a
style rule.
"""

from typing import Any, Dict, Optional


class RequiresHIL(Exception):
    """
    Raised by an Agent or Squad to signal that a human decision is needed
    before this workflow can continue.

    Args:
        reason:   human-readable explanation (e.g. "fraud_probability 0.82
                  exceeds auto-approve threshold").
        context:  the review payload a human reviewer needs to see -- not
                  necessarily the full execution payload.
        priority: "low" | "medium" | "high" | "critical". Default "medium".
        queue:    optional HIL queue/domain name. When omitted, the
                  catching Orchestrator's own ``layer`` is used, so a
                  fraud-detection orchestrator's HIL requests land in a
                  fraud-shaped queue without every raise site having to
                  know the queue name.
    """

    def __init__(
        self,
        reason: str,
        context: Optional[Dict[str, Any]] = None,
        priority: str = "medium",
        queue: Optional[str] = None,
    ):
        self.reason = reason
        self.context = context or {}
        self.priority = priority
        self.queue = queue
        super().__init__(reason)
