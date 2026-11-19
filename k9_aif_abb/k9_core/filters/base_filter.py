# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
BaseFilter: the ABB for K9X Filters (1.32.0, opt-in with ``filters.enabled``).

Governance asks "is this allowed?"; a filter asks "is this in the right shape?". Shield, Guardian
and Zero Trust decide and never change a payload that passes. A filter changes what flows (removes,
labels, normalises, attaches) and never blocks for policy: a filter that raises ``PermissionError``
is turned into a :class:`FilterError`, because blocking is a Shield check's job.

Where filters run (the ``BaseAgent`` wrapper, so every agent class gets them without code)::

    caller -> filters IN -> governance pre -> agent.execute() -> filters OUT -> governance post

* **in** sees the payload before the agent's own code runs, while it is still a dict of named parts;
* **out** sees ``result["output"]`` and may add fields to the result (``FilterResult.result_fields``);
* governance always screens the final form: what the agent receives, and what a filter added.

A filter that raises stops the agent like any other agent failure (it propagates). Each filter's
``record`` is logged and emitted as a ``FilterApplied`` trace event.

Configuration::

    filters:
      enabled: true
      chain: [text_normalize, attention, {name: mine, class: MyFilter, module: my_app.filters}]

    # agent YAML (merged into the agent's config):
    agent_filters: [attention]     # optional: narrow the chain for this agent; [] = none

Design: ``docs/roadmap/k9x-filters-design.md``. OOB filters: ``k9_aif_abb.k9_filters``.
"""

from __future__ import annotations

import logging
from abc import ABC
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("k9.filters")

DIRECTIONS = ("in", "out")


class FilterError(RuntimeError):
    """A filter could not do its job (a required part doesn't fit the budget, no valid JSON in the
    output, ...) or broke the contract. Propagates like any agent failure."""


@dataclass
class FilterResult:
    """What a filter returns: the new value, a record of what it changed (logged and traced), and,
    for an out filter, fields to add to the agent's result next to ``output``."""
    value: Any
    record: Dict[str, Any] = field(default_factory=dict)
    result_fields: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FilterContext:
    """Passed to every filter. ``state`` is shared by all filters of one agent call, in and out
    (an in filter can leave something for an out filter)."""
    agent: str
    layer: str
    config: Dict[str, Any]
    direction: str
    state: Dict[str, Any]

    def section(self, key: str) -> Dict[str, Any]:
        """The filter's own section of the agent's config (``attention:``, ...), or ``{}``."""
        value = (self.config or {}).get(key)
        return value if isinstance(value, dict) else {}


class BaseFilter(ABC):
    """A K9X filter. Override ``filter_in`` and/or ``filter_out`` and list the directions in
    ``applies_to``; the other direction passes the value through.

    Built by :class:`~k9_aif_abb.k9_factories.filter_factory.FilterFactory` from its config entry
    (``from_config``); one instance serves every call of the agent it was built for, so keep per-call
    data in ``ctx.state``, never on ``self``."""

    name: str = ""
    filter_type: str = ""
    applies_to: Tuple[str, ...] = DIRECTIONS

    def __init__(self, settings: Optional[Dict[str, Any]] = None):
        self.settings = dict(settings or {})

    @classmethod
    def from_config(cls, settings: Optional[Dict[str, Any]] = None) -> "BaseFilter":
        return cls(settings)

    def filter_in(self, payload: Any, ctx: FilterContext) -> FilterResult:
        return FilterResult(payload)

    def filter_out(self, output: Any, ctx: FilterContext) -> FilterResult:
        return FilterResult(output)


def filters_enabled(config: Optional[Dict[str, Any]]) -> bool:
    section = (config or {}).get("filters")
    return isinstance(section, dict) and section.get("enabled") is True


def _spec_name(spec: Any) -> str:
    if isinstance(spec, str):
        return spec
    if isinstance(spec, dict) and spec.get("name"):
        return str(spec["name"])
    raise ValueError(f"filters.chain entry {spec!r}: give a name, or a mapping with name: (and class:/module:)")


class FilterChain:
    """The filters one agent runs, in chain order."""

    def __init__(self, filters: List[BaseFilter]):
        for f in filters:
            if not isinstance(f, BaseFilter):
                raise TypeError(f"{f!r} is not a BaseFilter")
            bad = [d for d in f.applies_to if d not in DIRECTIONS]
            if bad:
                raise ValueError(f"filter {f.name or type(f).__name__}: applies_to {bad} (use 'in' and/or 'out')")
        self.filters = list(filters)

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "FilterChain":
        """Build the chain from ``filters.chain``, narrowed by ``agent_filters`` when the agent's
        config has it. An unknown name or a filter that can't be built raises: never a silent skip."""
        from k9_aif_abb.k9_factories.filter_factory import FilterFactory

        specs = list(((config or {}).get("filters") or {}).get("chain") or [])
        names = [_spec_name(s) for s in specs]
        wanted = (config or {}).get("agent_filters")
        if wanted is not None:
            if not isinstance(wanted, (list, tuple)):
                raise ValueError("agent_filters: give a list of filter names ([] for none)")
            unknown = [w for w in wanted if w not in names]
            if unknown:
                raise ValueError(f"agent_filters names {unknown}, which are not in filters.chain {names}")
            specs = [s for s, n in zip(specs, names) if n in wanted]
        return cls([FilterFactory.create(s) for s in specs])

    @classmethod
    def for_agent(cls, agent: Any) -> Optional["FilterChain"]:
        """The agent's chain (built once and kept on the agent), or None when filters are off."""
        if not filters_enabled(getattr(agent, "config", None)):
            return None
        chain = agent.__dict__.get("_k9_filter_chain")
        if chain is None:
            chain = cls.from_config(agent.config)
            agent.__dict__["_k9_filter_chain"] = chain
        return chain

    def begin(self, agent: Any) -> "FilterCall":
        return FilterCall(self, agent)


class FilterCall:
    """The filters for one agent call: ``run_in`` before governance pre, ``run_out`` before
    governance post. Both share ``state``."""

    def __init__(self, chain: FilterChain, agent: Any):
        self.chain = chain
        self.agent = agent
        self.state: Dict[str, Any] = {}

    def _ctx(self, direction: str) -> FilterContext:
        return FilterContext(agent=type(self.agent).__name__, layer=getattr(self.agent, "layer", ""),
                             config=getattr(self.agent, "config", {}) or {}, direction=direction,
                             state=self.state)

    def _run(self, direction: str, value: Any) -> Tuple[Any, Dict[str, Any]]:
        from k9_aif_abb.k9_utils.trace_events import emit_trace_event

        fields: Dict[str, Any] = {}
        for f in self.chain.filters:
            if direction not in f.applies_to:
                continue
            label = f.name or type(f).__name__
            method = f.filter_in if direction == "in" else f.filter_out
            try:
                res = method(value, self._ctx(direction))
            except PermissionError as exc:
                raise FilterError(f"filter {label} raised PermissionError ({exc}): filters don't block; "
                                  "a block belongs in a Shield check") from exc
            if not isinstance(res, FilterResult):
                raise FilterError(f"filter {label}.filter_{direction}() returned {type(res).__name__}, "
                                  "not a FilterResult")
            value = res.value
            if res.result_fields:
                if direction != "out":
                    raise FilterError(f"filter {label}: result_fields are for out filters only")
                fields.update(res.result_fields)
            if res.record:
                event = {"type": "FilterApplied", "agent": type(self.agent).__name__, "filter": label,
                         "filter_type": f.filter_type, "direction": direction, "record": res.record}
                log.info("[filters] %s %s %s: %s", type(self.agent).__name__, direction, label, res.record)
                emit_trace_event(event)
        return value, fields

    def run_in(self, payload: Any) -> Any:
        value, _ = self._run("in", payload)
        return value

    def run_out(self, output: Any) -> Tuple[Any, Dict[str, Any]]:
        return self._run("out", output)

    def has_out(self) -> bool:
        return any("out" in f.applies_to for f in self.chain.filters)


def begin_filters(agent: Any) -> Optional[FilterCall]:
    """The filters for one call of ``agent``, or None when filters are off. Used by the ``BaseAgent``
    wrapper and by the loop ABBs, which run their own pre/post."""
    chain = FilterChain.for_agent(agent)
    return chain.begin(agent) if chain is not None else None


def apply_out(call: Optional[FilterCall], result: Any) -> Any:
    """Run the out filters on a dict result's ``output`` and merge their result fields."""
    if call is None or not isinstance(result, dict) or "output" not in result:
        return result
    out, fields = call.run_out(result["output"])
    return {**result, **fields, "output": out}
