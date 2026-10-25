# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

"""k9x Origin — one call for an agent: what is true right now, and where did it come from."""

from __future__ import annotations

import inspect
import json
import logging
import string
import threading
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from k9_aif_abb.k9_core.streams.base_context_state import BaseContextState, ContextUpdate, FieldChange
from k9_aif_abb.k9_core.streams.event_envelope import EventEnvelope
from k9_aif_abb.k9_origin.config import OriginConfig
from k9_aif_abb.k9_origin.conflicts import BaseConflictRule, Conflict, LateEventRule, TransitionRule
from k9_aif_abb.k9_origin.sources import OriginSources
from k9_aif_abb.k9_utils.trace_events import emit_trace_event

log = logging.getLogger("k9x.origin")

Answer = Dict[str, Any]
Key = Tuple[str, str]


class BaseOrigin(ABC):
    """
    ABB contract for k9x Origin. Agents get three read operations and nothing else; every
    answer carries ``as_of``, ``source``, ``version`` and flags. Origin states facts and makes
    no business decisions (rules do). See ``docs/roadmap/k9x-origin-design.md``.
    """

    @abstractmethod
    def get_current(self, entity: str, entity_id: str, agent: Optional[str] = None) -> Answer:
        raise NotImplementedError

    @abstractmethod
    def recent_changes(self, entity: str, entity_id: str, window_seconds: float = 600,
                       agent: Optional[str] = None) -> Answer:
        raise NotImplementedError

    @abstractmethod
    def query(self, entity: str, filters: Optional[Dict[str, Any]] = None,
              minimum: Optional[Dict[str, float]] = None, agent: Optional[str] = None) -> Answer:
        raise NotImplementedError

    @abstractmethod
    def resolve_for_squad(self, squad_id: str, payload: Dict[str, Any]) -> Dict[str, Answer]:
        """The ``live_context`` a squad declared in origin.yaml, resolved for this payload."""
        raise NotImplementedError


class _Fill(dict):
    def __missing__(self, key):
        raise KeyError(key)


def _ref(ref: Any) -> Optional[Tuple[str, str]]:
    if isinstance(ref, dict):
        e, i = ref.get("entity"), ref.get("id")
    else:
        e, _, i = str(ref).partition(":")
    return (str(e), str(i)) if e and i else None


class K9Origin(BaseOrigin):
    """
    The built-in k9x Origin.

    Answering ``get_current(entity, id)`` runs, in order: scope → request screening → live state
    → read-through to the system of record when the entity is missing → verify against the
    system of record when the asking agent is a ``verify_before`` step → flags (quarantine,
    in review, conflict; never hidden) → answer screening → trace.

    Ingest is the context fabric's (``ContextIngest``); Origin listens to field changes on the
    same state and flags conflicts (reversal, late event; disagreement from verify). Conflicts
    are facts: ``conflict_listeners`` receive them (an application's Router turns them into the
    ``origin.conflict`` domain event), and business rules decide what follows.
    """

    def __init__(self, state: BaseContextState, config: Optional[OriginConfig] = None,
                 request_governance: Any = None, answer_governance: Any = None,
                 sources: Optional[OriginSources] = None):
        self.state = state
        self.config = config or OriginConfig()
        self.request_governance = request_governance
        self.answer_governance = answer_governance
        self.sources = sources or OriginSources(self.config.sources)
        self.conflict_listeners: List[Callable[[Conflict], None]] = []
        self.call_listeners: List[Callable[[Dict[str, Any]], None]] = []
        self._conflicts: Dict[Key, Conflict] = {}
        self._reviews: Dict[Key, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self.rules: List[BaseConflictRule] = []
        for name, policy in self.config.entities.items():
            for watch in policy.conflicts:
                self.rules.append(TransitionRule(name, watch))
            if policy.conflicts:
                self.rules.append(LateEventRule(name, [w.field for w in policy.conflicts]))
        state.change_listeners.append(self._on_change)

    # ── agent operations ───────────────────────────────────────────────
    def get_current(self, entity: str, entity_id: str, agent: Optional[str] = None) -> Answer:
        t0 = time.time()
        entity, entity_id = str(entity), str(entity_id)
        refused = self._refusal("get_current", {"entity": entity, "id": entity_id}, agent)
        if refused:
            return self._done("get_current", entity, entity_id, agent, t0, refused)

        view = self.state.get_current(entity, entity_id)
        kind = "stream"
        policy = self.config.entities.get(entity)
        sor = policy.system_of_record if policy else None
        unavailable = None
        if not view.get("found") and sor:
            got = self._read_through(entity, entity_id, sor)
            if got is True:
                view, kind = self.state.get_current(entity, entity_id), "system_of_record"
            elif isinstance(got, str):              # the source failed: not the same as "no such record"
                unavailable = {"system": sor, "error": got}

        verified = None
        if view.get("found") and sor and self.config.verifies(agent):
            verified = self._verify(entity, entity_id, view, policy)
            kind = "both"

        answer = self._answer(entity, entity_id, view, kind, verified)
        if unavailable:
            answer["source_unavailable"] = unavailable
        return self._done("get_current", entity, entity_id, agent, t0, self._screen_answer("get_current", answer))

    def recent_changes(self, entity: str, entity_id: str, window_seconds: float = 600,
                       agent: Optional[str] = None) -> Answer:
        t0 = time.time()
        args = {"entity": entity, "id": entity_id, "window_seconds": window_seconds}
        refused = self._refusal("recent_changes", args, agent)
        if refused:
            return self._done("recent_changes", entity, entity_id, agent, t0, refused)
        out = self.state.recent_changes(entity, entity_id, window_seconds)
        view = self.state.get_current(entity, entity_id)
        if view.get("history_available") is False:
            out["history_available"] = False
        return self._done("recent_changes", entity, entity_id, agent, t0, self._screen_answer("recent_changes", out))

    def query(self, entity: str, filters: Optional[Dict[str, Any]] = None,
              minimum: Optional[Dict[str, float]] = None, agent: Optional[str] = None) -> Answer:
        t0 = time.time()
        args = {"entity": entity, "filters": filters or {}, "minimum": minimum or {}}
        refused = self._refusal("query", args, agent)
        if refused:
            return self._done("query", entity, None, agent, t0, refused)
        out = self.state.query(entity, filters=filters, minimum=minimum)
        out["rows"] = [self._answer(entity, r["id"], r, "stream", None) for r in out["rows"]]
        return self._done("query", entity, None, agent, t0, self._screen_answer("query", out))

    def resolve_for_squad(self, squad_id: str, payload: Dict[str, Any]) -> Dict[str, Answer]:
        refs = self.config.squad_refs(squad_id) + list(payload.get("live_context_refs") or [])
        fill = _Fill({k: v for k, v in payload.items() if isinstance(v, (str, int, float))})
        live: Dict[str, Answer] = {}
        for ref in refs:
            if isinstance(ref, str) and "{" in ref:
                try:
                    ref = string.Formatter().vformat(ref, (), fill)
                except (KeyError, IndexError, ValueError):
                    continue   # this payload does not name that entity
            parsed = _ref(ref)
            if parsed:
                live[f"{parsed[0]}:{parsed[1]}"] = self.get_current(*parsed, agent=None)
        return live

    # ── human review (driven by the K9X HIL round trip) ─────────────────
    def mark_in_review(self, entity: str, entity_id: str, case: Optional[Dict[str, Any]] = None) -> None:
        with self._lock:
            self._reviews[(entity, str(entity_id))] = {"since": _now_iso(), **(case or {})}

    def clear_review(self, entity: str, entity_id: str) -> None:
        with self._lock:
            self._reviews.pop((entity, str(entity_id)), None)
            self._conflicts.pop((entity, str(entity_id)), None)

    def open_conflicts(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [c.to_dict() for c in self._conflicts.values()]

    # ── internals ──────────────────────────────────────────────────────
    def _refusal(self, tool: str, args: Dict[str, Any], agent: Optional[str]) -> Optional[Answer]:
        entity = str(args.get("entity", "")).lower()
        scope = self.config.allowed_entities(agent)
        if scope is not None and entity not in scope:
            who = f"agent {agent}" if agent else "this solution"
            return {"refused_by_governance": True, "tool": tool,
                    "reason": f"entity '{entity}' is outside the scope of {who} ({', '.join(sorted(scope))})"}
        if self.request_governance is not None:
            payload = {"query": json.dumps(args, default=str), "source": "origin_request", "source_tool": tool}
            try:
                _call(self.request_governance.pre_process, payload, {"component": f"origin:{tool}"})
            except PermissionError as exc:
                return {"refused_by_governance": True, "tool": tool, "reason": str(exc)}
        return None

    def _screen_answer(self, tool: str, answer: Answer) -> Answer:
        if self.answer_governance is None:
            return answer
        from k9_aif_abb.k9_security.tool_result_guard import _run_coro_sync, screen_tool_result, withheld_value
        try:
            _run_coro_sync(screen_tool_result(self.answer_governance, tool, answer, {"component": "k9x-origin"}))
        except PermissionError as exc:
            return withheld_value(answer, str(exc))
        return answer

    def _read_through(self, entity: str, entity_id: str, source_name: str):
        """True: found and applied. False: the source has no such record. A string: the source failed (its
        error), reported to the agent as ``source_unavailable`` (1.19.0; before, it read as "not found")."""
        try:
            record = self.sources.fetch(source_name, entity, entity_id)
        except Exception as exc:
            log.warning("[Origin] read-through %s %s:%s failed: %s", source_name, entity, entity_id, exc)
            return str(exc)[:200] or type(exc).__name__
        if not record:
            return False
        version = record.get("version") if isinstance(record, dict) else None
        env = EventEnvelope(event_type=f"{entity}.read_through", source_system=source_name, payload=record,
                            metadata={"version": f"{source_name}:{version}"} if version is not None else {})
        source = {"kind": "system_of_record", "system": source_name}
        self.state._write(ContextUpdate(entity, entity_id, fields=dict(record)), env, source)
        self.state.mark_history_unavailable((entity, entity_id))
        return True

    def _verify(self, entity: str, entity_id: str, view: Answer, policy) -> Dict[str, Any]:
        sor = policy.system_of_record
        try:
            record = self.sources.fetch(sor, entity, entity_id) or {}
        except Exception as exc:
            return {"against": sor, "agrees": None, "error": str(exc)[:200]}
        owned = policy.owned_fields or list(record)
        live = view.get("value") or {}
        differences = [{"field": f, "live": live.get(f), "system_of_record": record.get(f)}
                       for f in owned if f in record and live.get(f) != record.get(f)]
        if differences:
            self._raise(Conflict(entity, entity_id, "disagreement", differences[0]["field"],
                                 f"live state and {sor} disagree on {', '.join(d['field'] for d in differences)}",
                                 differences))
        return {"against": sor, "agrees": not differences, "differences": differences}

    def _answer(self, entity: str, entity_id: str, view: Answer, kind: str, verified) -> Answer:
        key = (entity, str(entity_id))
        with self._lock:
            conflict = self._conflicts.get(key)
            review = self._reviews.get(key)
        if not view.get("found"):
            return {"entity": entity, "id": str(entity_id), "found": False, "as_of": None,
                    "flags": {"quarantined": None, "in_review": bool(review), "conflict": None,
                              "verification_failed": None}}
        source = dict(view.get("source") or {})
        source["kind"] = "both" if kind == "both" else source.get("kind") or kind
        quarantined = view.get("quarantined") or []
        out = {"entity": entity, "id": str(entity_id), "found": True, "value": view.get("value") or {},
               "as_of": view.get("as_of"), "age_seconds": view.get("age_seconds"),
               "version": view.get("version"), "source": source,
               "flags": {"quarantined": quarantined[-1] if quarantined else None,
                         "in_review": bool(review), "review": review,
                         "conflict": conflict.to_dict() if conflict else None,
                         # a verify_before step whose system of record couldn't be reached (1.19.0): the
                         # live value is unverified, so it must not be acted on as if checked
                         "verification_failed": ({"against": verified.get("against"), "error": verified.get("error")}
                                                 if verified and verified.get("agrees") is None else None)},
               "verified": verified,
               "history_available": view.get("history_available", True)}
        return out

    def _on_change(self, change: FieldChange) -> None:
        for rule in self.rules:
            conflict = rule.check(change)
            if conflict:
                self._raise(conflict)

    def _raise(self, conflict: Conflict) -> None:
        with self._lock:
            self._conflicts[(conflict.entity, conflict.entity_id)] = conflict
        emit_trace_event({"type": "OriginConflict", "entity": conflict.entity, "id": conflict.entity_id,
                          "kind": conflict.kind, "field": conflict.field})
        for listener in self.conflict_listeners:
            try:
                listener(conflict)
            except Exception:
                log.exception("[Origin] conflict listener failed")

    def _done(self, tool: str, entity: str, entity_id: Optional[str], agent: Optional[str], t0: float,
              out: Answer) -> Answer:
        outcome = ("refused" if out.get("refused_by_governance") else
                   "withheld" if out.get("withheld_by_governance") else "answered")
        record = {"tool": tool, "entity": entity, "id": entity_id, "agent": agent,
                  "ms": round((time.time() - t0) * 1000, 1), "outcome": outcome,
                  "source": (out.get("source") or {}).get("kind"), "as_of": out.get("as_of"),
                  "age_seconds": out.get("age_seconds"), "found": out.get("found", True),
                  "reason": out.get("reason")}
        emit_trace_event({"type": "Origin", **{k: v for k, v in record.items() if v is not None}})
        for listener in self.call_listeners:
            try:
                listener(record)
            except Exception:
                log.exception("[Origin] call listener failed")
        return out


def _call(fn, *args):
    out = fn(*args)
    if inspect.isawaitable(out):
        from k9_aif_abb.k9_security.tool_result_guard import _run_coro_sync
        return _run_coro_sync(out)
    return out


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
