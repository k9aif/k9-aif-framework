# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

"""RedisContextState — shared, memory-bounded live state for clustered deployments."""

from __future__ import annotations

import json
import logging
import os
import random
import time
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from k9_aif_abb.k9_core.streams.base_context_state import (
    BaseContextState,
    ContextUpdate,
    ContextValue,
    EntityKey,
    FieldChange,
    merge_update,
)
from k9_aif_abb.k9_core.streams.event_envelope import EventEnvelope

log = logging.getLogger("RedisContextState")


def _dt(text: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(text) if text else None


class RedisContextState(BaseContextState):
    """
    Live state in Redis, shared by every ingest worker, MCP server and orchestrator.

    Bounded memory with least-recently-used eviction is Redis's own job: run Redis with
    ``maxmemory <size>`` and ``maxmemory-policy volatile-lru``. Entity values and their history
    carry an expiry (``ttl_seconds``, default 30 days), which makes them evictable; quarantine
    markers carry none, so they are never evicted: a refused event can't be forgotten and then
    "cleaned" by a read-through. An evicted entity comes back through read-through, marked
    ``history_available: false``.

    YAML config::

        streams:
          state:
            provider: redis
            url: "${REDIS_URL:-redis://localhost:6379/0}"
            prefix: k9o
            ttl_seconds: 2592000
            changes_per_entity: 50

    Writes use an optimistic transaction per entity (WATCH / MULTI), so concurrent workers never
    lose an update. Requires ``pip install "k9-aif[redis]"``.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None, projections: Optional[Iterable[Any]] = None,
                 client: Any = None):
        super().__init__(config, projections)
        cfg = (self.config.get("streams") or {}).get("state") or {}
        self.prefix = cfg.get("prefix", "k9o")
        self.ttl = int(cfg.get("ttl_seconds", 30 * 24 * 3600))
        if client is None:
            try:
                import redis
            except ImportError as exc:   # pragma: no cover - depends on the extra
                raise RuntimeError('pip install "k9-aif[redis]" required for RedisContextState') from exc
            client = redis.Redis.from_url(cfg.get("url") or os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
                                          decode_responses=True)
        self.r = client
        self._check_policy()

    # ── keys ───────────────────────────────────────────────────────────
    def _k(self, kind: str, key: EntityKey) -> str:
        return f"{self.prefix}:{kind}:{key[0]}:{key[1]}"

    def _check_policy(self) -> None:
        try:
            policy = self.r.config_get("maxmemory-policy").get("maxmemory-policy")
            if policy and policy != "volatile-lru":
                log.warning("[RedisContextState] maxmemory-policy is %s; use volatile-lru so entity values "
                            "are evicted least-recently-used and quarantine markers are never evicted", policy)
        except Exception:   # managed Redis often disallows CONFIG
            pass

    # ── (de)serialisation ──────────────────────────────────────────────
    def _dump(self, cv: ContextValue) -> str:
        return json.dumps({"entity": cv.entity, "id": cv.entity_id, "value": cv.value,
                           "as_of": cv.as_of.isoformat(), "source": cv.source, "version": cv.version,
                           "field_times": {k: v.isoformat() for k, v in cv.field_times.items()},
                           "history_available": cv.history_available}, default=str)

    def _load(self, key: EntityKey, raw: Optional[str], quarantine: Optional[str]) -> Optional[ContextValue]:
        markers = json.loads(quarantine) if quarantine else []
        if raw is None:
            if not markers:
                return None
            # value evicted, quarantine pinned: the entity still answers, flagged
            return ContextValue(key[0], key[1], {}, _dt(markers[-1]["at"]), {}, markers, None, {}, False)
        d = json.loads(raw)
        return ContextValue(d["entity"], d["id"], d["value"], _dt(d["as_of"]), d.get("source") or {}, markers,
                            d.get("version"), {k: _dt(v) for k, v in (d.get("field_times") or {}).items()},
                            d.get("history_available", True))

    # ── writes ─────────────────────────────────────────────────────────
    def _write(self, update: ContextUpdate, envelope: EventEnvelope, source: Dict[str, Any]) -> List[FieldChange]:
        import redis
        key = update.key
        vkey, qkey, hkey = self._k("v", key), self._k("q", key), self._k("h", key)
        for attempt in range(200):
            if attempt:   # contention on this entity: back off with jitter, then merge again
                time.sleep(random.uniform(0, min(0.05, 0.002 * attempt)))
            with self.r.pipeline() as pipe:
                try:
                    pipe.watch(vkey)
                    current = self._load(key, pipe.get(vkey), pipe.get(qkey))
                    result = merge_update(current, update, envelope, source)
                    pipe.multi()
                    pipe.set(vkey, self._dump(result.value), ex=self.ttl)
                    for kind, fields in (("", result.applied), ("late:", result.late)):
                        if fields:
                            pipe.rpush(hkey, json.dumps({"at": result.at.isoformat(), "type": kind + envelope.event_type,
                                                         "fields": fields, "source": source}, default=str))
                    pipe.ltrim(hkey, -self.changes_per_entity, -1)
                    pipe.expire(hkey, self.ttl)
                    pipe.execute()
                    return result.changes
                except redis.WatchError:
                    continue   # another worker changed this entity first; merge again
        raise RuntimeError(f"RedisContextState: could not write {key} after 200 attempts")

    def _mark_quarantined(self, key: EntityKey, marker: Dict[str, Any], source: Dict[str, Any]) -> None:
        qkey = self._k("q", key)
        markers = json.loads(self.r.get(qkey) or "[]")
        self.r.set(qkey, json.dumps((markers + [marker])[-10:]))     # no expiry: pinned
        self.r.rpush(self._k("h", key), json.dumps({"at": marker["at"], "type": "quarantined",
                                                     "fields": {"blocked_by": marker["blocked_by"]}, "source": source}))
        self.r.expire(self._k("h", key), self.ttl)

    def mark_history_unavailable(self, key: EntityKey) -> None:
        vkey = self._k("v", key)
        raw = self.r.get(vkey)
        if raw:
            d = json.loads(raw)
            d["history_available"] = False
            self.r.set(vkey, json.dumps(d), ex=self.ttl)
        self.r.delete(self._k("h", key))

    # ── reads ──────────────────────────────────────────────────────────
    def _read(self, key: EntityKey) -> Optional[ContextValue]:
        raw, q = self.r.mget(self._k("v", key), self._k("q", key))
        return self._load(key, raw, q)

    def _scan(self, entity: str) -> List[ContextValue]:
        out = []
        for vkey in self.r.scan_iter(match=f"{self.prefix}:v:{entity}:*", count=500):
            entity_id = vkey.split(":", 3)[3]
            cv = self._read((entity, entity_id))
            if cv:
                out.append(cv)
        return out

    def _changes(self, key: EntityKey) -> List[Dict[str, Any]]:
        items = [json.loads(x) for x in self.r.lrange(self._k("h", key), 0, -1)]
        for item in items:
            item["at"] = _dt(item["at"])
        return sorted(items, key=lambda c: c["at"])

    def _entity_counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for vkey in self.r.scan_iter(match=f"{self.prefix}:v:*", count=500):
            entity = vkey.split(":", 3)[2]
            counts[entity] = counts.get(entity, 0) + 1
        return counts

    def clear(self) -> None:
        for k in self.r.scan_iter(match=f"{self.prefix}:*", count=500):
            self.r.delete(k)
