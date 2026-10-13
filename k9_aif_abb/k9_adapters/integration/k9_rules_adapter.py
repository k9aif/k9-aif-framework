# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

"""Built-in rules adapters: K9RulesAdapter (rules in YAML) and RestRulesAdapter (a decision service)."""

from __future__ import annotations

import ast
import re
from typing import Any, Dict, Iterable, List, Optional

from .base_rules_adapter import BaseRulesAdapter

_MISSING = object()
_COMPARE = re.compile(r"^\s*(?P<path>[^\s<>=!]+)\s*(?P<op>>=|<=|==|!=|>|<|not in|in)\s*(?P<value>.+?)\s*$")


def _literal(text: str) -> Any:
    """A rule value: number, quoted string, true/false/null, or a [list]. Never evaluated as code."""
    t = text.strip()
    low = t.lower()
    if low in ("true", "false"):
        return low == "true"
    if low in ("null", "none"):
        return None
    try:
        return ast.literal_eval(t)
    except (ValueError, SyntaxError):
        return t   # a bare word: treated as a string


def _resolve(facts: Any, path: str) -> List[Any]:
    """Values at a dotted path. ``*`` matches any key (``live_context.*.flags.conflict``); a key may
    contain ':' (``live_context.claim:C-1.value.amount``)."""
    nodes: List[Any] = [facts]
    for part in path.split("."):
        nxt: List[Any] = []
        for node in nodes:
            if isinstance(node, dict):
                if part == "*":
                    nxt.extend(node.values())
                elif part in node:
                    nxt.append(node[part])
            elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
                nxt.append(node[int(part)])
        nodes = nxt
    return nodes


def _compare(left: Any, op: str, right: Any) -> bool:
    try:
        if op == "==":
            return left == right
        if op == "!=":
            return left != right
        if op == "in":
            return left in right
        if op == "not in":
            return left not in right
        if left is None or right is None:
            return False
        return {">": left > right, ">=": left >= right, "<": left < right, "<=": left <= right}[op]
    except TypeError:
        return False


def evaluate_condition(cond: Any, facts: Dict[str, Any]) -> bool:
    """A condition: ``"claim.amount > 5000"``, ``"live_context.*.flags.conflict"`` (present and
    truthy), or ``{all: [...]}`` / ``{any: [...]}`` / ``{not: ...}``."""
    if isinstance(cond, dict):
        if "all" in cond:
            return all(evaluate_condition(c, facts) for c in cond["all"])
        if "any" in cond:
            return any(evaluate_condition(c, facts) for c in cond["any"])
        if "not" in cond:
            return not evaluate_condition(cond["not"], facts)
        raise ValueError(f"unknown rule condition: {cond}")
    if isinstance(cond, bool):
        return cond
    m = _COMPARE.match(str(cond))
    if not m:   # a bare path: present and truthy
        return any(bool(v) for v in _resolve(facts, str(cond).strip()))
    values = _resolve(facts, m.group("path"))
    right = _literal(m.group("value"))
    return any(_compare(v, m.group("op"), right) for v in values)


class K9RulesAdapter(BaseRulesAdapter):
    """
    Rules in configuration, for teams without a rules engine. Each rule has ``name``, ``when``
    (a condition) and ``then`` (a decision such as ``hil``, ``hold`` or ``allow``), plus an
    optional ``reason``. Rules are checked in order; the first match decides; none → ``allow``.

        rules:
          - name: large claim
            when: claim.amount > 5000
            then: hil
            reason: claims over $5,000 need a person
          - name: conflicting data
            when: live_context.*.flags.conflict
            then: hil

    No code is ever evaluated: conditions are parsed, values are literals. Registered as
    ``k9_rules`` in IntegrationAdapterFactory.
    """

    def evaluate(self, ruleset: str, facts: Dict[str, Any]) -> Dict[str, Any]:
        rules = self.config.get("rules") or []
        for rule in rules:
            if evaluate_condition(rule.get("when", False), facts):
                return {"decision": rule.get("then", "hil"), "rule": rule.get("name", ""),
                        "reason": rule.get("reason") or f"rule matched: {rule.get('name') or rule.get('when')}"}
        return {"decision": self.config.get("default", "allow"), "rule": None, "reason": "no rule matched"}


class RestRulesAdapter(BaseRulesAdapter):
    """
    A decision service over REST: Drools/KIE, IBM ODM, OpenL Tablets, Corticon, or your own.
    Posts ``{"ruleset": ..., "facts": ...}`` to ``engine_url`` (+ ``decision_service`` path) and
    returns the JSON decision; the service should answer with at least ``{"decision": ...}``.
    Registered as ``rest_rules`` in IntegrationAdapterFactory.
    """

    def evaluate(self, ruleset: str, facts: Dict[str, Any]) -> Any:
        import requests
        url = self.config["engine_url"].rstrip("/")
        if self.config.get("decision_service"):
            url += "/" + self.config["decision_service"].lstrip("/")
        resp = requests.post(url, json={"ruleset": ruleset, "facts": facts},
                             headers=self.config.get("headers") or {}, timeout=float(self.config.get("timeout", 30)))
        resp.raise_for_status()
        return resp.json()
