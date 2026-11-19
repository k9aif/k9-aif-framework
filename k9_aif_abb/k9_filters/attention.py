# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
K9AttentionFilter (in): give the agent the parts of its payload that matter, within a budget, with
each part's trust stated, before the agent's own code runs.

Agents commonly cut their context blind (``context = source[:8000]``): whatever came first stays,
the rest is gone, and nothing records it. This filter works from the parts the agent declares in its
YAML and does the cut deliberately:

```yaml
attention:
  pinned:     [policy, task]       # never pruned
  retrieved:  [policy_chunks]      # a list of chunks: scored, de-duplicated, pruned to the budget
  untrusted:  [vendor_email]       # labelled untrusted; never pruned like a chunk
  query_key:  query                # what relevance is scored against
  budget_tokens: 6000              # pinned + untrusted + retrieved (estimate: 4 characters per token)
  untrusted_budget_tokens: 2000    # optional: untrusted parts get their own cap instead of sharing
  untrusted_overflow: fail         # fail (default) | truncate: an untrusted part that doesn't fit
  order: score                     # kept chunks by score (default) or original
  min_score: 0.0                   # drop chunks scoring below this (default: keep while they fit)
  dedupe_threshold: 0.9            # word-set similarity at which a chunk counts as a copy
```

1. **Quarantine.** A declared part (or a retrieved chunk) that is a k9x Origin answer flagged
   ``quarantined`` is removed. A quarantined *pinned* part fails the agent: it can't run on a
   required fact it may not use. Parts flagged in_review / conflict / verification_failed are
   labelled ``unverified``.
2. **Score** each retrieved chunk against the query: the share of the query's words it contains.
3. **De-duplicate** near-identical chunks (the higher-scoring copy stays).
4. **Prune to the budget**, highest score first, across all retrieved parts. Pinned parts are never
   pruned; if they alone exceed the budget the agent fails (``FilterError``) instead of running on a
   cut-down policy. Untrusted parts share ``budget_tokens`` with the pinned parts (so a huge email
   can't silently crowd out the retrieved chunks or overrun the model's context), unless
   ``untrusted_budget_tokens`` gives them their own cap. One that doesn't fit fails the agent, or with
   ``untrusted_overflow: truncate`` is cut to fit, labelled ``truncated`` and recorded with its sizes.
5. **Label.** Sets ``payload["_attention"]``: per declared part, its role, trust, source and what was
   kept. Values are not rewritten, so the agent's parsing still works. A ``_attention`` the caller sent
   is replaced (and recorded): labels come from the agent's declaration, never from the request.
6. **Record** what was removed and why, with token estimates before and after.

Undeclared keys pass through untouched; an agent without an ``attention:`` section is skipped (logged
once). ``wrap_untrusted(text, source)`` gives agents one delimiter for untrusted text in a prompt.
"""

from __future__ import annotations

import json
import logging
import math
import re
from typing import Any, Dict, List, Optional, Set

from k9_aif_abb.k9_core.filters.base_filter import BaseFilter, FilterContext, FilterError, FilterResult
from k9_aif_abb.k9_filters._origin import is_origin_answer, quarantined, unverified_flags

log = logging.getLogger("k9.filters.attention")

_ROLES = ("pinned", "retrieved", "untrusted")
_TEXT_KEYS = ("text", "content", "page_content", "chunk", "body")
_WORD = re.compile(r"\w+", re.UNICODE)
_STOP = frozenset("a an and are as at be by can do does for from has have how i in is it its me my of on "
                  "or our please should so that the their them this to us was we were what when where "
                  "which who why will with would you your".split())
_SKIP_LOGGED: Set[str] = set()

TAG = "untrusted_content"


def wrap_untrusted(text: str, source: Optional[str] = None) -> str:
    """Wrap untrusted text in one standard delimiter for a prompt. A closing tag inside the text is
    escaped, so the content cannot end the wrapper early. Delimiters help a model keep data apart
    from instructions; they are not a security control (Shield and the tool-result guard are)."""
    body = str(text).replace(f"</{TAG}", f"&lt;/{TAG}")
    attr = f' source="{str(source).replace(chr(34), "&quot;")}"' if source else ""
    return f"<{TAG}{attr}>\n{body}\n</{TAG}>"


def _as_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if is_origin_answer(value):
        value = value.get("value")
    if isinstance(value, dict):
        for k in _TEXT_KEYS:
            if isinstance(value.get(k), str):
                return value[k]
    try:
        return json.dumps(value, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)


def _tokens(value: Any) -> int:
    return math.ceil(len(_as_text(value)) / 4)


def _words(text: str) -> Set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in _STOP}


def _source_of(value: Any) -> Optional[str]:
    if is_origin_answer(value):
        src = value.get("source") or {}
        return src.get("system") or src.get("name") or src.get("kind") or "k9x_origin"
    if isinstance(value, dict):
        for k in ("source", "uri", "url", "doc_id", "document"):
            if isinstance(value.get(k), str):
                return value[k]
    return None


class K9AttentionFilter(BaseFilter):
    name = "attention"
    filter_type = "attention"
    applies_to = ("in",)

    def filter_in(self, payload: Any, ctx: FilterContext) -> FilterResult:
        cfg = ctx.section("attention")
        if not cfg:
            if ctx.agent not in _SKIP_LOGGED:
                _SKIP_LOGGED.add(ctx.agent)
                log.info("[attention] %s declares no attention: section; its payload passes unchanged", ctx.agent)
            return FilterResult(payload)
        if not isinstance(payload, dict):
            raise FilterError(f"attention ({ctx.agent}): the payload is {type(payload).__name__}, "
                              "not a dict of named parts")

        roles: Dict[str, str] = {}
        for role in _ROLES:
            keys = cfg.get(role) or []
            if not isinstance(keys, (list, tuple)):
                raise ValueError(f"attention.{role}: give a list of payload keys")
            for k in keys:
                if k in roles:
                    raise ValueError(f"attention: {k!r} is both {roles[k]} and {role}")
                roles[k] = role

        budget = cfg.get("budget_tokens")
        budget = int(budget) if budget is not None else None
        order = cfg.get("order", "score")
        if order not in ("score", "original"):
            raise ValueError("attention.order must be 'score' or 'original'")
        min_score = float(cfg.get("min_score", 0.0))
        threshold = float(cfg.get("dedupe_threshold", 0.9))
        query = payload.get(cfg.get("query_key", "query"))
        query_words = _words(_as_text(query)) if query is not None else set()

        out = dict(payload)
        record: Dict[str, Any] = {"budget_tokens": budget, "dropped": [], "quarantined": [], "unverified": []}
        if "_attention" in payload:
            record["replaced_caller_labels"] = True
        labels: Dict[str, Dict[str, Any]] = {}
        record["tokens_before"] = sum(_tokens(payload[k]) for k in roles if k in payload)

        # 1. quarantine (whole parts)
        for key, role in roles.items():
            if key not in out:
                labels[key] = {"role": role, "present": False}
                continue
            value = out[key]
            if is_origin_answer(value) and quarantined(value):
                if role == "pinned":
                    raise FilterError(f"attention ({ctx.agent}): pinned part {key!r} is quarantined by k9x Origin "
                                      f"({value['flags']['quarantined']}); the agent can't run on it")
                del out[key]
                record["quarantined"].append(key)
                labels[key] = {"role": role, "present": False, "removed": "quarantined"}

        # 2-3. score and de-duplicate retrieved chunks, pooled across retrieved parts
        pool: List[Dict[str, Any]] = []
        for key, role in roles.items():
            if role != "retrieved" or key not in out:
                continue
            chunks = out[key]
            if not isinstance(chunks, list):
                raise FilterError(f"attention ({ctx.agent}): retrieved part {key!r} must be a list of chunks, "
                                  f"got {type(chunks).__name__}")
            for i, chunk in enumerate(chunks):
                if is_origin_answer(chunk) and quarantined(chunk):
                    record["quarantined"].append(f"{key}[{i}]")
                    continue
                words = _words(_as_text(chunk))
                score = (len(query_words & words) / len(query_words)) if query_words else 0.0
                pool.append({"key": key, "index": i, "chunk": chunk, "words": words,
                             "score": round(score, 3), "tokens": _tokens(chunk)})

        ranked = sorted(pool, key=lambda c: (-c["score"], c["key"], c["index"]))
        unique: List[Dict[str, Any]] = []
        for c in ranked:
            copy_of = next((u for u in unique if c["words"] and u["words"] and
                            len(c["words"] & u["words"]) / len(c["words"] | u["words"]) >= threshold), None)
            if copy_of is not None:
                record["dropped"].append({"part": f"{c['key']}[{c['index']}]", "score": c["score"],
                                          "reason": f"copy of {copy_of['key']}[{copy_of['index']}]"})
                continue
            unique.append(c)

        # 4. prune to the budget
        pinned_tokens = sum(_tokens(out[k]) for k, r in roles.items() if r == "pinned" and k in out)
        if budget is not None and pinned_tokens > budget:
            raise FilterError(f"attention ({ctx.agent}): pinned parts need ~{pinned_tokens} tokens, over the "
                              f"budget of {budget}; raise budget_tokens or pin less")
        untrusted_cap = cfg.get("untrusted_budget_tokens")
        untrusted_cap = int(untrusted_cap) if untrusted_cap is not None else None
        overflow = cfg.get("untrusted_overflow", "fail")
        if overflow not in ("fail", "truncate"):
            raise ValueError("attention.untrusted_overflow must be 'fail' or 'truncate'")
        shared = untrusted_cap is None
        u_room = untrusted_cap if not shared else (None if budget is None else budget - pinned_tokens)
        truncated: Dict[str, Dict[str, int]] = {}
        for key, role in roles.items():
            if role != "untrusted" or key not in out or u_room is None:
                continue
            need = _tokens(out[key])
            if need <= u_room:
                u_room -= need
                continue
            where = "untrusted_budget_tokens" if not shared else "budget_tokens (shared with pinned parts)"
            if overflow == "fail" or not isinstance(out[key], str) or u_room <= 0:
                raise FilterError(f"attention ({ctx.agent}): untrusted part {key!r} needs ~{need} tokens, "
                                  f"~{max(u_room, 0)} left in {where}; raise the budget, or set "
                                  "untrusted_overflow: truncate")
            out[key] = out[key][: u_room * 4]
            truncated[key] = {"tokens_before": need, "tokens_after": _tokens(out[key])}
            u_room = 0
        if truncated:
            record["untrusted_truncated"] = truncated
        untrusted_tokens = sum(_tokens(out[k]) for k, r in roles.items() if r == "untrusted" and k in out)
        room = None if budget is None else budget - pinned_tokens - (untrusted_tokens if shared else 0)
        kept: List[Dict[str, Any]] = []
        for c in unique:
            if c["score"] < min_score:
                record["dropped"].append({"part": f"{c['key']}[{c['index']}]", "score": c["score"],
                                          "reason": f"score below min_score {min_score}"})
                continue
            if room is not None and c["tokens"] > room:
                record["dropped"].append({"part": f"{c['key']}[{c['index']}]", "score": c["score"],
                                          "reason": "over budget"})
                continue
            kept.append(c)
            if room is not None:
                room -= c["tokens"]

        for key, role in roles.items():
            if role != "retrieved" or key not in out:
                continue
            mine = [c for c in kept if c["key"] == key]
            if order == "original":
                mine.sort(key=lambda c: c["index"])
            out[key] = [c["chunk"] for c in mine]
            labels[key] = {"role": "retrieved", "trust": "reference", "present": True,
                           "kept": [{"index": c["index"], "score": c["score"], "source": _source_of(c["chunk"])}
                                    for c in mine],
                           "dropped": len(payload[key]) - len(mine)}

        # 5. label pinned and untrusted parts
        for key, role in roles.items():
            if role == "retrieved" or key not in out:
                continue
            value = out[key]
            label = {"role": role, "present": True,
                     "trust": "untrusted" if role == "untrusted" else "trusted",
                     "source": _source_of(value)}
            if key in truncated:
                label["truncated"] = True
            if is_origin_answer(value):
                flags = unverified_flags(value)
                if flags:
                    label["trust"] = "unverified"
                    label["flags"] = flags
                    record["unverified"].append(key)
            labels[key] = label

        out["_attention"] = labels
        record["tokens_after"] = sum(_tokens(out[k]) for k in roles if k in out)
        record = {k: v for k, v in record.items() if v not in ([], None) or k in ("budget_tokens",)}
        return FilterResult(out, record=record)
