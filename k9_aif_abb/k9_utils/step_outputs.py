# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

"""
Reading inside a squad step's structured output (1.35.0).

An agent with structured output (``K9OpenAIAgent`` with ``structured_output:``) returns its typed
result as JSON text: ``{"output": "{\\"is_churn_risk\\": true, ...}"}``. The text is what the next
agent's prompt reads, so the stored result stays as it is. A condition, though, has to reach the
fields: a squad's ``when: {key: churn.output.is_churn_risk, eq: true}`` and a rule's
``when: "churn.output.is_churn_risk == true"``. Before 1.35.0 both stopped at the text and found
nothing, so a rule on structured output never matched and a ``when:`` on it never held.

These helpers parse only where a condition reads, never in the stored results:

- ``parse_json_text(value)``: JSON text holding an object or a list becomes that object or list;
  anything else (plain text, a number written as text, invalid JSON) is returned unchanged.
- ``resolve_path(ctx, key)``: dotted traversal that parses JSON text when the path continues into it.
- ``with_parsed_outputs(payload)``: a shallow copy in which each step result's ``output`` that is
  JSON text holding an object or list is parsed; what a rules engine receives as its facts.
"""

from __future__ import annotations

import json
from typing import Any, Dict


def parse_json_text(value: Any) -> Any:
    """JSON text holding an object or a list, parsed; any other value unchanged."""
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text or text[0] not in "{[":
        return value
    try:
        parsed = json.loads(text)
    except ValueError:
        return value
    return parsed if isinstance(parsed, (dict, list)) else value


def resolve_path(ctx: Any, key: str) -> Any:
    """The value at a dotted path, or None if any segment is missing. JSON text met on the way is
    parsed so the path can continue inside it (``churn.output.is_churn_risk``); a list segment is an
    index (``items.0.amount``)."""
    val = ctx
    for part in key.split("."):
        val = parse_json_text(val)
        if isinstance(val, dict):
            if part not in val:
                return None
            val = val[part]
        elif isinstance(val, list) and part.isdigit() and int(part) < len(val):
            val = val[int(part)]
        else:
            return None
    return val


def with_parsed_outputs(payload: Dict[str, Any]) -> Dict[str, Any]:
    """A shallow copy of ``payload`` in which every step result's ``output`` that is JSON text holding
    an object or list is parsed. The payload itself is not changed."""
    out: Dict[str, Any] = {}
    for key, value in payload.items():
        if isinstance(value, dict) and isinstance(value.get("output"), str):
            parsed = parse_json_text(value["output"])
            if parsed is not value["output"]:
                value = {**value, "output": parsed}
        out[key] = value
    return out
