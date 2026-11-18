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

from typing import Any, Dict, Iterable, List, Optional

from k9_aif_abb.k9_core.orchestration.hil_task import check_task_fields, coerce_artifacts


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
        resume_state: (1.29.0) what the flow needs to continue where it stopped
                  after the decision (e.g. a paused OpenAI run, the squad steps
                  already done). Never shown to the reviewer: the orchestrator
                  stores it in the resume payload under ``_k9_resume``.

    K9X HIL task fields (1.30.0, the contract ``k9x.hil.task/v1``, owned by K9X HIL; checked here so a value
    HIL would refuse fails at the raise site, not after the flow paused):
        title:    the task's title (default: ``reason``); ``reason`` becomes its description.
        task_type: what kind of task, e.g. ``invoice-approval``.
        artifacts: documents and links for the reviewer, any number: ``HILArtifact``, a dict
                  ``{uri, title, media_type, role, pii}`` or a URI string; ``s3://bucket/key`` or ``https://``.
        required_role, decision_authority: the lowest HIL role allowed to decide, and who decides.
        require_comment: approval needs a written justification.
        ttl_hours, ttl_action: the deadline and what happens after it (reject | expire | escalate).
        pii, pii_fields: personal data in the task.
    """

    def __init__(
        self,
        reason: str,
        context: Optional[Dict[str, Any]] = None,
        priority: str = "medium",
        queue: Optional[str] = None,
        correlation_id: Optional[str] = None,
        resume_state: Optional[Dict[str, Any]] = None,
        *,
        title: Optional[str] = None,
        task_type: Optional[str] = None,
        artifacts: Optional[Iterable[Any]] = None,
        required_role: Optional[str] = None,
        decision_authority: Optional[str] = None,
        require_comment: bool = False,
        ttl_hours: Optional[int] = None,
        ttl_action: Optional[str] = None,
        pii: bool = False,
        pii_fields: Optional[List[str]] = None,
    ):
        check_task_fields(priority=priority, task_type=task_type, required_role=required_role,
                          ttl_hours=ttl_hours, ttl_action=ttl_action)
        self.reason = reason
        self.context = context or {}
        self.priority = priority
        self.queue = queue
        # 1.25.0: set when the review must be published under a known id (the tool
        # gate's pending call); None lets BaseHILOrchestrator generate one, as before.
        self.correlation_id = correlation_id
        self.resume_state = resume_state or {}
        self.title = title
        self.task_type = task_type
        self.artifacts = coerce_artifacts(artifacts)
        self.required_role = required_role
        self.decision_authority = decision_authority
        self.require_comment = bool(require_comment)
        self.ttl_hours = ttl_hours
        self.ttl_action = ttl_action
        self.pii = bool(pii)
        self.pii_fields = list(pii_fields or [])
        super().__init__(reason)

    def set_task_fields(self, **fields: Any) -> "RequiresHIL":
        """Fill in K9X HIL task fields after the signal was raised: e.g. the orchestrator that caught a framework's
        own pause (an OpenAI agent's needs_approval) adds the task type, the role the rules named, and the document
        under review. Checked like the constructor's; unknown names raise. Returns self."""
        allowed = {"title", "task_type", "artifacts", "required_role", "decision_authority", "require_comment",
                   "ttl_hours", "ttl_action", "pii", "pii_fields", "priority"}
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"unknown HIL task fields {sorted(unknown)}")
        check_task_fields(priority=fields.get("priority", self.priority),
                          task_type=fields.get("task_type", self.task_type),
                          required_role=fields.get("required_role", self.required_role),
                          ttl_hours=fields.get("ttl_hours", self.ttl_hours),
                          ttl_action=fields.get("ttl_action", self.ttl_action))
        for name, value in fields.items():
            if name == "artifacts":
                value = coerce_artifacts(value)
            elif name in ("require_comment", "pii"):
                value = bool(value)
            elif name == "pii_fields":
                value = list(value or [])
            setattr(self, name, value)
        return self

    def task_fields(self) -> Dict[str, Any]:
        """The K9X HIL task fields this signal sets (for BaseHILOrchestrator)."""
        return {"title": self.title, "task_type": self.task_type,
                "artifacts": [a.to_dict() for a in self.artifacts], "required_role": self.required_role,
                "decision_authority": self.decision_authority, "require_comment": self.require_comment,
                "ttl_hours": self.ttl_hours, "ttl_action": self.ttl_action, "pii": self.pii,
                "pii_fields": self.pii_fields}
