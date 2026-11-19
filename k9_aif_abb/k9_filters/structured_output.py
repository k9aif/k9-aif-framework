# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
K9StructuredOutputFilter (out): the agent's output as validated JSON, or a recorded failure.

Models wrap JSON in code fences, put prose around it, or return something close to JSON. Every
application ends up writing its own extractor, each handling a different subset, and the next step
crashes on what it missed. For an agent that declares ``structured_output:`` this filter:

1. takes the output as is when it is already a dict or list;
2. otherwise finds the JSON in the text: the whole text, then a fenced block (```json ... ```), then
   the first complete object or array inside prose;
3. validates it: ``type`` (object | array), ``required`` keys (for an object), and, when given, a full
   JSON Schema under ``schema:`` (needs the ``jsonschema`` package; missing, it raises rather than
   skip the check);
4. returns the parsed value as the agent's output.

No JSON, or JSON that fails validation, raises ``FilterError`` with the reason: the step fails as a
recorded failure, never with the raw text passed on as if it were the result.

```yaml
# agent YAML
structured_output:
  type: object
  required: [decision, reason]
  schema: {...}          # optional JSON Schema
```

An agent without a ``structured_output:`` section passes its output through unchanged.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional, Tuple

from k9_aif_abb.k9_core.filters.base_filter import BaseFilter, FilterContext, FilterError, FilterResult

_FENCE = re.compile(r"```(?:json|JSON)?\s*\n(.*?)```", re.DOTALL)


def extract_json(text: str) -> Tuple[Optional[Any], str]:
    """The first JSON value in ``text`` and how it was found ("whole", "fence", "embedded"), or
    ``(None, reason)``."""
    stripped = text.strip()
    try:
        return json.loads(stripped), "whole"
    except ValueError:
        pass
    for block in _FENCE.findall(text):
        try:
            return json.loads(block.strip()), "fence"
        except ValueError:
            continue
    decoder = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch in "{[":
            try:
                value, _ = decoder.raw_decode(text, i)
                return value, "embedded"
            except ValueError:
                continue
    return None, "no JSON object or array found"


class K9StructuredOutputFilter(BaseFilter):
    name = "structured_output"
    filter_type = "structured_output"
    applies_to = ("out",)

    def filter_out(self, output: Any, ctx: FilterContext) -> FilterResult:
        cfg = ctx.section("structured_output")
        if not cfg:
            return FilterResult(output)

        if isinstance(output, (dict, list)):
            value, how = output, "already structured"
        elif isinstance(output, str):
            value, how = extract_json(output)
            if value is None:
                raise FilterError(f"structured_output ({ctx.agent}): {how} in the output "
                                  f"({len(output)} characters)")
        else:
            raise FilterError(f"structured_output ({ctx.agent}): output is {type(output).__name__}, not text or JSON")

        kind = cfg.get("type")
        if kind == "object" and not isinstance(value, dict):
            raise FilterError(f"structured_output ({ctx.agent}): expected an object, got {type(value).__name__}")
        if kind == "array" and not isinstance(value, list):
            raise FilterError(f"structured_output ({ctx.agent}): expected an array, got {type(value).__name__}")
        required = cfg.get("required") or []
        if required:
            if not isinstance(value, dict):
                raise FilterError(f"structured_output ({ctx.agent}): required keys {required} need an object")
            missing = [k for k in required if k not in value]
            if missing:
                raise FilterError(f"structured_output ({ctx.agent}): missing required keys {missing}")
        schema = cfg.get("schema")
        if schema:
            try:
                import jsonschema
            except ImportError as exc:
                raise FilterError("structured_output: schema: needs the jsonschema package "
                                  "(pip install jsonschema)") from exc
            try:
                jsonschema.validate(value, schema)
            except jsonschema.ValidationError as exc:
                raise FilterError(f"structured_output ({ctx.agent}): {exc.message}") from exc

        record: Dict[str, Any] = {"found": how}
        return FilterResult(value, record=record if how != "whole" else {})
