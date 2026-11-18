# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
The HIL task message, as K9X HIL's task contract defines it (1.30.0).

K9X HIL owns the structure of a task: ``k9x.hil.task/v1``, published by HIL as JSON Schema
(``GET /api/contract/task``; ``contract/k9x.hil.task.v1.schema.json`` in the k9x-hil repository). HIL dead-letters a
message that names the contract and doesn't conform, so the framework checks the fields where they are set (the
``RequiresHIL`` raise site), not after the flow has paused.

``BaseHILOrchestrator`` builds every HIL request with :func:`build_hil_task_message`;
``tests/test_hil_task_contract.py`` checks what it builds against HIL's published schema.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Union

HIL_TASK_CONTRACT = "k9x.hil.task/v1"
PRIORITIES = ("low", "medium", "high", "critical")
ROLES = ("worker", "manager", "admin")
TTL_ACTIONS = ("reject", "expire", "escalate")
ARTIFACT_ROLES = ("primary", "supporting")

_URI = re.compile(r"^(s3://[^/\s]+/\S+|https?://\S+)$")
_MEDIA = re.compile(r"^[a-z]+/[a-z0-9.+-]+$")
_TASK_TYPE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,99}$")


@dataclass(frozen=True)
class HILArtifact:
    """A document or link the reviewer needs. ``s3://bucket/key`` objects are fetched by K9X HIL itself from
    object storage (S3/MinIO; HIL needs read access to the bucket); ``https://`` links open in the browser."""

    uri: str
    title: Optional[str] = None
    media_type: Optional[str] = None     # e.g. application/pdf
    role: Optional[str] = None           # primary: the document the decision is about; supporting: context
    pii: Optional[bool] = None

    def __post_init__(self):
        if not isinstance(self.uri, str) or len(self.uri) > 2000 or not _URI.match(self.uri):
            raise ValueError(f"HIL artifact uri must be s3://bucket/key or http(s)://..., got {self.uri!r}")
        if self.title is not None and not (1 <= len(self.title) <= 300):
            raise ValueError("HIL artifact title must be 1..300 characters")
        if self.media_type is not None and not _MEDIA.match(self.media_type):
            raise ValueError(f"HIL artifact media_type must look like type/subtype, got {self.media_type!r}")
        if self.role is not None and self.role not in ARTIFACT_ROLES:
            raise ValueError(f"HIL artifact role must be one of {ARTIFACT_ROLES}, got {self.role!r}")

    @classmethod
    def coerce(cls, item: Union["HILArtifact", Dict[str, Any], str]) -> "HILArtifact":
        if isinstance(item, HILArtifact):
            return item
        if isinstance(item, str):
            return cls(uri=item)
        if isinstance(item, dict):
            unknown = set(item) - {"uri", "title", "media_type", "role", "pii"}
            if unknown:
                raise ValueError(f"HIL artifact has unknown fields {sorted(unknown)}")
            return cls(**item)
        raise ValueError(f"HIL artifact must be an HILArtifact, dict or URI string, got {type(item).__name__}")

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in (("uri", self.uri), ("title", self.title), ("media_type", self.media_type),
                                  ("role", self.role), ("pii", self.pii)) if v is not None}


def coerce_artifacts(items: Optional[Iterable[Any]]) -> List[HILArtifact]:
    out = [HILArtifact.coerce(i) for i in (items or [])]
    if len(out) > 50:
        raise ValueError("a HIL task carries at most 50 artifacts")
    return out


def check_task_fields(*, priority: str = "medium", task_type: Optional[str] = None,
                      required_role: Optional[str] = None, ttl_hours: Optional[int] = None,
                      ttl_action: Optional[str] = None) -> None:
    """Raise ValueError for a value HIL's contract would refuse (and dead-letter)."""
    if priority not in PRIORITIES:
        raise ValueError(f"HIL priority must be one of {PRIORITIES}, got {priority!r}")
    if task_type is not None and not _TASK_TYPE.match(task_type):
        raise ValueError(f"HIL task_type must be lowercase letters, digits, '.', '_' or '-', got {task_type!r}")
    if required_role is not None and required_role not in ROLES:
        raise ValueError(f"HIL required_role must be one of {ROLES}, got {required_role!r}")
    if ttl_hours is not None and (not isinstance(ttl_hours, int) or isinstance(ttl_hours, bool)
                                  or not 1 <= ttl_hours <= 8760):
        raise ValueError(f"HIL ttl_hours must be an integer 1..8760, got {ttl_hours!r}")
    if ttl_action is not None and ttl_action not in TTL_ACTIONS:
        raise ValueError(f"HIL ttl_action must be one of {TTL_ACTIONS}, got {ttl_action!r}")


def build_hil_task_message(*, correlation_id: str, reply_to: str, title: str, description: Optional[str] = None,
                           source_orchestrator: Optional[str] = None, source_topic: Optional[str] = None,
                           priority: str = "medium", task_type: Optional[str] = None,
                           required_role: Optional[str] = None, decision_authority: Optional[str] = None,
                           require_comment: bool = False, ttl_hours: Optional[int] = None,
                           ttl_action: Optional[str] = None, pii: bool = False,
                           pii_fields: Optional[List[str]] = None, payload: Optional[Dict[str, Any]] = None,
                           artifacts: Optional[Iterable[Any]] = None) -> Dict[str, Any]:
    """One ``k9x.hil.task/v1`` message. Optional fields left unset are omitted (HIL shows them as "none")."""
    check_task_fields(priority=priority, task_type=task_type, required_role=required_role,
                      ttl_hours=ttl_hours, ttl_action=ttl_action)
    title = (title or "Human review requested").strip()[:500] or "Human review requested"
    message: Dict[str, Any] = {
        "contract": HIL_TASK_CONTRACT,
        "title": title,
        "correlation_id": str(correlation_id),
        "reply_to": reply_to,
        "priority": priority,
        "require_comment": bool(require_comment),
        "pii": bool(pii),
        "payload": payload or {},
        "artifacts": [a.to_dict() for a in coerce_artifacts(artifacts)],
    }
    optional = {"task_type": task_type, "description": description, "source_orchestrator": source_orchestrator,
                "source_topic": source_topic, "required_role": required_role,
                "decision_authority": decision_authority, "ttl_hours": ttl_hours, "ttl_action": ttl_action}
    message.update({k: v for k, v in optional.items() if v is not None})
    if pii_fields:
        message["pii_fields"] = [str(f) for f in pii_fields]
    return message
