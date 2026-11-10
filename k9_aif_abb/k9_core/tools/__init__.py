# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
k9_core.tools: the tool gate (1.25.0, opt-in with ``security.tool_gate.enabled``).

Every tool call made inside a governed agent call passes one gate, the
``BaseToolDispatcher``. It checks the call's values against records the model
didn't write, applies the solution's own rules, and runs the call, refuses it,
or holds it for a person. See ``base_tool_dispatcher.py``.
"""

from k9_aif_abb.k9_core.tools.base_tool_dispatcher import (
    BaseToolDispatcher,
    ToolCallDenied,
    ToolCallPendingReview,
    gate_enabled,
)
from k9_aif_abb.k9_core.tools.tool_call import ToolCall
from k9_aif_abb.k9_core.tools.tool_call_audit_log import (
    BaseToolCallAuditLog,
    InMemoryToolCallAuditLog,
    SQLiteToolCallAuditLog,
)
from k9_aif_abb.k9_core.tools.tool_call_decision import ToolCallDecision
from k9_aif_abb.k9_core.tools.tool_registry import RecordCheck, ToolRegistry, ToolSpec

__all__ = [
    "BaseToolDispatcher", "ToolCallDenied", "ToolCallPendingReview", "gate_enabled",
    "ToolCall", "BaseToolCallAuditLog", "InMemoryToolCallAuditLog", "SQLiteToolCallAuditLog",
    "ToolCallDecision", "RecordCheck", "ToolRegistry", "ToolSpec",
]
