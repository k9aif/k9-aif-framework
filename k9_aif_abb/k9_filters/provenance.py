# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
K9ProvenanceFilter (in + out): the agent's result carries the evidence it was given.

In: notes every k9x Origin answer in the payload (top-level parts, and answers inside a list part),
after any earlier filter has run, so a part the attention filter removed is not cited.
Out: adds ``sources`` to the agent's result, next to ``output``: one entry per answer (entity, id,
version), with the ``parts`` it came in, ``source``, ``as_of``, ``version`` and every flag that is
set. The output itself is unchanged. Nothing to cite, nothing added.

``sources`` is screened by governance post like the output (``BaseAgent`` screens a filter's result
fields too), so a filter can't carry text past Shield beside the output. Checked against the
framework's egress checks (SemanticDriftCheck, ToolArgumentCheck, ExecutionGuardCheck,
PIIBoundaryCheck): distinct sources pass at any count; the loop-trap check fires only on three or
more identical entries, which the one-citation-per-answer rule prevents.
"""

from __future__ import annotations

from typing import Any, Dict, List

from k9_aif_abb.k9_core.filters.base_filter import BaseFilter, FilterContext, FilterResult
from k9_aif_abb.k9_filters._origin import is_origin_answer

_STATE = "provenance.sources"


def _cite(part: str, answer: Dict[str, Any]) -> Dict[str, Any]:
    flags = {k: v for k, v in (answer.get("flags") or {}).items() if v}
    entry = {"parts": [part], "entity": answer.get("entity"), "id": answer.get("id"),
             "found": answer.get("found"), "source": answer.get("source"),
             "as_of": answer.get("as_of"), "version": answer.get("version")}
    if flags:
        entry["flags"] = flags
    return {k: v for k, v in entry.items() if v is not None}


class K9ProvenanceFilter(BaseFilter):
    name = "provenance"
    filter_type = "provenance"
    applies_to = ("in", "out")

    def filter_in(self, payload: Any, ctx: FilterContext) -> FilterResult:
        found: List[tuple] = []
        if isinstance(payload, dict):
            for key, value in payload.items():
                if is_origin_answer(value):
                    found.append((key, value))
                elif isinstance(value, list):
                    found.extend((f"{key}[{i}]", v) for i, v in enumerate(value) if is_origin_answer(v))
        # One citation per answer (entity, id, version), listing every part it came in: repeated copies
        # add nothing, and three identical copies trip Shield's loop-trap check (SemanticDriftCheck).
        by_answer: Dict[tuple, Dict[str, Any]] = {}
        for part, answer in found:
            key = (answer.get("entity"), str(answer.get("id")), answer.get("version"))
            if key in by_answer:
                by_answer[key]["parts"].append(part)
            else:
                by_answer[key] = _cite(part, answer)
        ctx.state[_STATE] = list(by_answer.values())
        return FilterResult(payload)

    def filter_out(self, output: Any, ctx: FilterContext) -> FilterResult:
        sources = ctx.state.get(_STATE) or []
        if not sources:
            return FilterResult(output)
        return FilterResult(output, record={"sources": len(sources)}, result_fields={"sources": sources})
