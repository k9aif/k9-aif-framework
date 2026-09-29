# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
import logging
import threading
import time
import uuid
from typing import Any, Coroutine, Dict, List, Optional

from ..models.inference_request import InferenceRequest
from ..models.inference_response import InferenceResponse
from ..models.route_decision import RouteDecision
from ..catalog.model_catalog import ModelCatalog
from .base_model_router import BaseModelRouter


def _run_coro_sync(coro: "Coroutine[Any, Any, Any]") -> Any:
    """
    Execute an async coroutine from synchronous code — safe whether or not
    an event loop is already running on the calling thread.

    BaseAgent.execute() (and therefore invoke()) is a synchronous contract,
    but K9-AIF is commonly embedded inside async web frameworks (FastAPI,
    etc.) whose request handlers run on an already-active event loop.
    asyncio.run() refuses to nest inside a running loop — calling it from
    such a request handler raises "asyncio.run() cannot be called from a
    running event loop", which agents.py-style broad excepts turn into a
    silent stub fallback with no indication the LLM was never actually
    called.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # No loop on this thread (plain script/CLI/test) — the common case.
        return asyncio.run(coro)

    # A loop is already running here — run the coroutine on a fresh loop in
    # a separate thread instead, and block this thread until it completes.
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()

from k9_aif_abb.k9_factories.llm_factory import LLMFactory
from k9_aif_abb.k9_storage.routing_state_store import RoutingStateStore
from ..learning import Example, KNNQualityPredictor, build_embedder, utility

log = logging.getLogger("K9ModelRouter")

# inference.router.learning -- every key optional.
_LEARNING_DEFAULTS: Dict[str, Any] = {
    "enabled": True,
    "embedder": "hashing",       # or "service" (EmbeddingServiceFactory / vectordb.*)
    "k": 15,                     # neighbours per model
    "power": 2.0,                # similarity weighting exponent
    "min_similarity": 0.15,      # prompts less similar than this are not evidence
    "min_neighbors": 3,          # graded neighbours a model needs to be predicted
    "min_models": 2,             # models with predictions before evidence can decide
    "margin": 3.0,               # quality points needed to overrule the rules' pick
    "window": 2000,              # graded examples kept in memory
    "refresh_seconds": 30,       # reload evidence written by other processes
    "breaker": {"window": 20, "min_calls": 5, "failure_rate": 0.5},
}


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in ("", "0", "false", "no", "off")
    return bool(value)


_COMPLEXITY_SCORE: dict[str, float] = {
    "reasoning": 0.8,
    "extraction": 0.6,
    "analysis": 0.7,
    "general": 0.3,
    "chat": 0.2,
    "summarization": 0.4,
}

_LATENCY_TIERS = ("realtime", "interactive", "batch")
_COST_TIERS = ("minimal", "standard", "premium")


class K9ModelRouter(BaseModelRouter):
    """
    OOB K9 Model Router
    -------------------
    Rules first, then evidence -- a learned router in the style of
    Not Diamond / RouteLLM, trained on graded outcomes.

    1. Rules (cold start, always computed). Weighted scoring, higher wins:
         +3  capability match on task_type
         +2  sensitivity=="confidential" and "confidential" in capabilities
         +2  latency_budget matches model's latency_tier
         +2  cost_profile matches model's cost_tier
       Falls back to default_model when no candidate scores > 0. On a tie,
       the session's current model (affinity) wins, then catalog order.

    2. Evidence (inference.router.learning, on by default). Graded outcomes
       -- record_feedback(), K9X Arena, evaluators -- are kept as
       (prompt vector, model, quality). For a new prompt each model's
       quality is predicted from its scores on the k most similar prompts,
       minus a latency/cost penalty set by the request's hints. When at
       least ``min_models`` models have predictions, the best one replaces
       the rules' pick if it is ahead by ``margin`` points (or the rules'
       pick has no evidence at all).

    Guard rails the evidence can't cross: a confidential request only goes
    to confidential-capable models (when the catalog has any), and a model
    whose recent calls mostly failed is skipped (circuit breaker).

    Every routed call records its outcome (success, latency); every
    decision records why. With no graded evidence the router behaves
    exactly like the rules above.
    """

    def __init__(
        self,
        catalog: ModelCatalog,
        config: Optional[dict] = None,
        monitor=None,
        state_store: Optional[RoutingStateStore] = None,
    ):
        self.catalog = catalog
        self.config = config or {}
        self.monitor = monitor

        if state_store is None:
            raise ValueError(
                "K9ModelRouter requires a state_store provided by ModelRouterFactory"
            )

        self.state_store = state_store

        router_cfg = (self.config.get("inference", {}).get("router")
                      or self.config.get("router") or {})
        user_learning = router_cfg.get("learning") or {}
        self.learning = {**_LEARNING_DEFAULTS, **user_learning,
                         "breaker": {**_LEARNING_DEFAULTS["breaker"], **(user_learning.get("breaker") or {})}}
        self.learning_enabled = _truthy(self.learning.get("enabled", True))
        self._embedder = None
        self._predictor = KNNQualityPredictor(k=self.learning["k"], power=self.learning["power"],
                                              min_similarity=self.learning["min_similarity"])
        self._examples: List[Example] = []
        self._recent: Dict[str, List[bool]] = {}
        self._loaded_at = 0.0
        self._vectors: Dict[str, Any] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------
    def _resolve_session_id(self, request: InferenceRequest) -> str:
        session_id = getattr(request, "session_id", None)
        if not session_id:
            return str(uuid.uuid4())
        try:
            return str(uuid.UUID(str(session_id)))
        except ValueError:
            # Postgres stores session_id as uuid; map any caller string to a
            # stable uuid so the same conversation id always lands together.
            return str(uuid.uuid5(uuid.NAMESPACE_URL, f"k9aif:session:{session_id}"))

    def _resolve_user_id(self, request: InferenceRequest) -> str:
        user_id = getattr(request, "user_id", None)
        return str(user_id) if user_id else "anonymous"

    def _persist_request_context(
        self,
        request: InferenceRequest,
    ) -> tuple[str, str, int]:
        session_id = self._resolve_session_id(request)
        user_id = self._resolve_user_id(request)

        self.state_store.ensure_session(session_id=session_id, user_id=user_id)

        turn_id = self.state_store.append_turn(
            session_id=session_id,
            role="USER",
            content=request.prompt,
            token_count=None,
            compressed_flag=False,
        )

        return session_id, user_id, turn_id

    def _persist_route_decision(
        self,
        session_id: str,
        turn_id: int,
        decision: RouteDecision,
        request: InferenceRequest,
    ) -> None:
        complexity = _COMPLEXITY_SCORE.get(request.task_type or "general", 0.5)
        governance = 1.0 if getattr(request, "sensitivity", None) == "confidential" else 0.0

        self.state_store.record_routing_decision(
            session_id=session_id,
            turn_id=turn_id,
            selected_model=decision.model_alias,
            routing_reason=decision.rationale,
            complexity_score=complexity,
            governance_score=governance,
            prompt_hash=None,
            metadata={
                "provider": decision.provider,
                "router": "K9ModelRouter",
                "score": decision.score,
            },
        )

        self.state_store.update_model_affinity(
            session_id=session_id,
            model_name=decision.model_alias,
        )

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------
    def _score_candidate(self, alias: str, meta: dict, request: InferenceRequest) -> float:
        score = 0.0
        caps = meta.get("capabilities", [])

        if request.task_type and request.task_type in caps:
            score += 3.0

        if getattr(request, "sensitivity", None) == "confidential" and "confidential" in caps:
            score += 2.0

        if request.latency_budget and request.latency_budget == meta.get("latency_tier"):
            score += 2.0

        if request.cost_profile and request.cost_profile == meta.get("cost_tier"):
            score += 2.0

        return score

    def _allowed(self, request: InferenceRequest) -> List[str]:
        """Aliases this request may use at all. A confidential request goes
        only to confidential-capable models when the catalog has any --
        before 1.13 this was just +2, so a +3 capability match elsewhere
        could send confidential data to a model not cleared for it."""
        aliases = list(self.catalog.models)
        if getattr(request, "sensitivity", None) == "confidential":
            secure = [a for a in aliases
                      if "confidential" in (self.catalog.models[a].get("capabilities") or [])]
            if secure:
                return secure
        return aliases

    def _rule_order(self, request: InferenceRequest) -> tuple[List[tuple], Dict[str, float]]:
        """Allowed aliases ordered by rule score (stable: catalog order on ties)."""
        scores = {alias: self._score_candidate(alias, self.catalog.models[alias], request)
                  for alias in self._allowed(request)}
        order = sorted(enumerate(scores.items()), key=lambda x: (-x[1][1], x[0]))
        return [pair for _, pair in order], scores

    def _affinity(self, request: InferenceRequest) -> Optional[str]:
        if not getattr(request, "session_id", None):
            return None
        try:
            row = self.state_store.get_session(self._resolve_session_id(request))
            alias = row.get("model_affinity") if isinstance(row, dict) else None
            return alias if alias in self.catalog.models else None
        except Exception:
            return None

    def route(self, request: InferenceRequest) -> RouteDecision:
        ordered, scores = self._rule_order(request)
        tripped = self._tripped() if self.learning_enabled else set()

        # --- 1. rules --------------------------------------------------
        best_alias: Optional[str] = None
        best_score = 0.0
        for alias, score in ordered:
            if score > 0 and alias not in tripped:
                best_alias, best_score = alias, score
                break
        if best_alias is not None:
            affinity = self._affinity(request)
            if affinity and affinity != best_alias and scores.get(affinity) == best_score \
                    and affinity not in tripped:
                best_alias = affinity

        # Fall back to default when nothing matched (best_score == 0 means
        # no capability/sensitivity/latency/cost signals fired at all)
        if best_alias is None:
            best_alias = self.catalog.get_default_model()
            best_score = 0.0
            allowed = self._allowed(request)
            if best_alias not in allowed and allowed:
                best_alias = allowed[0]

        if not best_alias:
            raise RuntimeError("ModelRouter: no model alias resolved")

        rationale_parts = ["K9 weighted-score routing"]
        if best_score > 0:
            rationale_parts.append(f"score={best_score:.1f}")
        if request.latency_budget:
            rationale_parts.append(f"latency={request.latency_budget}")
        if request.cost_profile:
            rationale_parts.append(f"cost={request.cost_profile}")
        if tripped:
            rationale_parts.append("skipped (failing): " + ", ".join(sorted(tripped)))

        chosen, strategy = best_alias, "rules"
        predicted: Optional[float] = None
        predictions: Optional[Dict[str, float]] = None
        predicted_latency: Optional[int] = None

        # --- 2. evidence -----------------------------------------------
        if self.learning_enabled:
            learned = self._learned_pick(request, best_alias, tripped)
            if learned:
                preds, pick, note = learned
                predictions = {a: p.utility for a, p in preds.items()}
                if pick != best_alias:
                    chosen, strategy = pick, "learned"
                    rationale_parts = ["K9 learned routing"]
                rationale_parts.append(note)
                if chosen in preds:
                    predicted = preds[chosen].quality
                    if preds[chosen].latency_ms is not None:
                        predicted_latency = int(round(preds[chosen].latency_ms))

        model_info = self.catalog.get_model(chosen)
        return RouteDecision(
            model_alias=chosen,
            provider=model_info.get("provider"),
            score=(scores.get(chosen) or None) if strategy == "learned"
            else (best_score if best_score > 0 else None),
            predicted_latency_ms=predicted_latency,
            rationale="; ".join(rationale_parts),
            strategy=strategy,
            predicted_quality=predicted,
            predictions=predictions,
        )

    # ------------------------------------------------------------------
    # Learning: evidence, prediction, feedback
    # ------------------------------------------------------------------
    def _get_embedder(self):
        if self._embedder is None:
            self._embedder = build_embedder(self.learning, self.config)
        return self._embedder

    def _vector(self, prompt: str, task_type: Optional[str]):
        key = hashlib.sha256(f"{task_type}\x00{prompt}".encode("utf-8")).hexdigest()
        vec = self._vectors.get(key)
        if vec is None:
            vec = self._get_embedder().embed(prompt, task_type)
            if len(self._vectors) > 512:
                self._vectors.clear()
            self._vectors[key] = vec
        return key, vec

    def _refresh(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and self._loaded_at and now - self._loaded_at < float(self.learning["refresh_seconds"]):
            return
        with self._lock:
            try:
                name = self._get_embedder().name
                graded = self.state_store.load_outcomes(graded_only=True, embedder=name,
                                                        limit=int(self.learning["window"]))
                recent = self.state_store.load_outcomes(limit=int(self.learning["breaker"]["window"]) * 20)
            except Exception as exc:  # evidence is an optimisation, never a failure
                log.warning("K9ModelRouter: could not load routing outcomes (%s)", exc)
                graded, recent = [], []
            graded = graded if isinstance(graded, list) else []
            recent = recent if isinstance(recent, list) else []
            self._examples = [Example(vector=r["prompt_vector"], model_alias=r["model_alias"],
                                      quality=float(r["quality"]), latency_ms=r.get("latency_ms"),
                                      task_type=r.get("task_type"))
                              for r in graded if r.get("prompt_vector") and r.get("quality") is not None]
            per_model: Dict[str, List[bool]] = {}
            window = int(self.learning["breaker"]["window"])
            for r in recent:  # newest first
                if r.get("source") != "runtime":
                    continue
                flags = per_model.setdefault(r["model_alias"], [])
                if len(flags) < window:
                    flags.append(bool(r.get("success", True)))
            self._recent = per_model
            self._loaded_at = now

    def _tripped(self) -> set:
        self._refresh()
        b = self.learning["breaker"]
        out = set()
        for alias, flags in self._recent.items():
            if len(flags) >= int(b["min_calls"]):
                if flags.count(False) / len(flags) >= float(b["failure_rate"]):
                    out.add(alias)
        # Never trip every model -- a router with no candidates is worse.
        return out if len(out) < len(self.catalog.models) else set()

    def _learned_pick(self, request: InferenceRequest, rule_alias: str, tripped: set):
        self._refresh()
        if not self._examples:
            return None
        candidates = [a for a in self._allowed(request) if a not in tripped]
        _, vec = self._vector(request.prompt, request.task_type)
        preds = self._predictor.predict(vec, self._examples, candidates, task_type=request.task_type)
        preds = {a: p for a, p in preds.items() if p.neighbors >= int(self.learning["min_neighbors"])}
        if len(preds) < int(self.learning["min_models"]):
            return None
        for alias, p in preds.items():
            p.utility = utility(p, self.catalog.models[alias], request.latency_budget,
                                request.cost_profile, self.learning)
        order = list(self.catalog.models)
        best = max(preds.values(), key=lambda p: (p.utility, -order.index(p.model_alias)))
        margin = float(self.learning["margin"])
        summary = ", ".join(f"{a}={p.utility:.1f}" for a, p in
                            sorted(preds.items(), key=lambda kv: -kv[1].utility))
        rule = preds.get(rule_alias)
        if best.model_alias == rule_alias:
            return preds, rule_alias, f"evidence agrees ({summary})"
        if rule is None and rule_alias in candidates:
            return preds, best.model_alias, f"predicted {summary}; rules' pick {rule_alias} has no evidence"
        if rule is None:
            return preds, best.model_alias, f"predicted {summary}; rules' pick {rule_alias} not allowed"
        if best.utility - rule.utility >= margin:
            return preds, best.model_alias, (f"predicted {summary}; beats rules' pick {rule_alias} "
                                             f"by {best.utility - rule.utility:.1f} (margin {margin:g})")
        return preds, rule_alias, f"evidence within margin {margin:g} ({summary})"

    def record_feedback(
        self,
        prompt: str,
        model_alias: str,
        quality: float,
        task_type: Optional[str] = None,
        latency_ms: Optional[float] = None,
        session_id: Optional[str] = None,
        source: str = "feedback",
    ) -> None:
        """Teach the router: ``model_alias`` scored ``quality`` (0-100) on
        ``prompt``. Graders, evaluators, HIL reviewers and K9X Arena call
        this; future prompts similar to this one use it."""
        if model_alias not in self.catalog.models:
            raise ValueError(f"record_feedback: '{model_alias}' is not in the model catalog")
        quality = float(quality)
        if not 0.0 <= quality <= 100.0:
            raise ValueError("record_feedback: quality must be between 0 and 100")
        key, vec = self._vector(prompt, task_type)
        self.state_store.record_outcome(
            model_alias=model_alias, task_type=task_type, success=True, quality=quality,
            latency_ms=latency_ms, session_id=session_id, prompt_hash=key,
            embedder=self._get_embedder().name, prompt_vector=vec, source=source,
        )
        self._refresh()
        with self._lock:
            self._examples.insert(0, Example(vector=vec, model_alias=model_alias, quality=quality,
                                             latency_ms=latency_ms, task_type=task_type))
            del self._examples[int(self.learning["window"]):]

    def _record_runtime(self, session_id: str, request: InferenceRequest, alias: str,
                        ok: bool, started: float) -> int:
        latency = int((time.perf_counter() - started) * 1000)
        try:
            self.state_store.record_outcome(
                model_alias=alias, task_type=request.task_type, success=ok,
                latency_ms=latency, session_id=session_id, source="runtime",
            )
            flags = self._recent.setdefault(alias, [])
            flags.insert(0, ok)
            del flags[int(self.learning["breaker"]["window"]):]
        except Exception as exc:
            log.warning("K9ModelRouter: could not record outcome (%s)", exc)
        return latency

    # ------------------------------------------------------------------
    # Sync Invoke
    # ------------------------------------------------------------------
    def invoke(self, request: InferenceRequest) -> InferenceResponse:
        session_id, user_id, turn_id = self._persist_request_context(request)

        decision = self.route(request)
        self._persist_route_decision(session_id, turn_id, decision, request)

        model_info = self.catalog.get_model(decision.model_alias)
        llm_ref = model_info.get("llm_ref")

        llm = LLMFactory.get(llm_ref)

        sys_prompt = getattr(request, "system_prompt", None)

        started = time.perf_counter()
        try:
            if hasattr(llm, "invoke"):
                result = llm.invoke(request.prompt, system_prompt=sys_prompt)
            elif hasattr(llm, "generate"):
                result = _run_coro_sync(llm.generate(request.prompt, system_prompt=sys_prompt))
            elif hasattr(llm, "chat"):
                result = llm.chat(request.prompt)
            elif callable(llm):
                result = llm(request.prompt)
            else:
                raise AttributeError(
                    f"{llm.__class__.__name__} has no supported inference method "
                    "(expected invoke, generate, chat, or __call__)"
                )
        except Exception:
            self._record_runtime(session_id, request, decision.model_alias, False, started)
            raise
        latency = self._record_runtime(session_id, request, decision.model_alias, True, started)

        return InferenceResponse(
            output=result,
            model_alias=decision.model_alias,
            provider=model_info.get("provider"),
            latency_ms=latency,
        )

    # ------------------------------------------------------------------
    # Async Invoke
    # ------------------------------------------------------------------
    async def ainvoke(self, request: InferenceRequest) -> InferenceResponse:
        session_id, user_id, turn_id = self._persist_request_context(request)

        decision = self.route(request)
        self._persist_route_decision(session_id, turn_id, decision, request)

        model_info = self.catalog.get_model(decision.model_alias)
        llm_ref = model_info.get("llm_ref")

        llm = LLMFactory.get(llm_ref)

        sys_prompt = getattr(request, "system_prompt", None)

        started = time.perf_counter()
        try:
            if hasattr(llm, "ainvoke") and callable(llm.ainvoke):
                result = await llm.ainvoke(request.prompt, system_prompt=sys_prompt)

            elif hasattr(llm, "agenerate") and callable(llm.agenerate):
                result = await llm.agenerate(request.prompt, system_prompt=sys_prompt)

            elif hasattr(llm, "generate") and callable(llm.generate):
                result = await llm.generate(request.prompt, system_prompt=sys_prompt)

            elif hasattr(llm, "invoke") and callable(llm.invoke):
                result = llm.invoke(request.prompt, system_prompt=sys_prompt)

            elif callable(llm):
                result = llm(request.prompt)

            else:
                raise AttributeError(
                    f"{llm.__class__.__name__} has no supported inference method"
                )
        except Exception:
            self._record_runtime(session_id, request, decision.model_alias, False, started)
            raise
        latency = self._record_runtime(session_id, request, decision.model_alias, True, started)

        return InferenceResponse(
            output=str(result),
            model_alias=decision.model_alias,
            provider=model_info.get("provider"),
            latency_ms=latency,
        )

    # ------------------------------------------------------------------
    # Async Streaming Invoke
    # ------------------------------------------------------------------
    async def ainvoke_stream(self, request: InferenceRequest):
        """
        Route the request and stream the inference response incrementally.

        Uses the same routing/scoring logic as ``ainvoke()``. If the selected
        LLM adapter implements ``generate_stream()``, chunks are yielded as
        they arrive. Otherwise falls back to the base class behavior — a
        single chunk containing the complete ``ainvoke()`` output — so the
        streaming interface works uniformly regardless of adapter support.
        """
        session_id, user_id, turn_id = self._persist_request_context(request)

        decision = self.route(request)
        self._persist_route_decision(session_id, turn_id, decision, request)

        model_info = self.catalog.get_model(decision.model_alias)
        llm_ref = model_info.get("llm_ref")

        llm = LLMFactory.get(llm_ref)
        sys_prompt = getattr(request, "system_prompt", None)

        if hasattr(llm, "generate_stream") and callable(llm.generate_stream):
            started = time.perf_counter()
            try:
                async for chunk in llm.generate_stream(request.prompt, system_prompt=sys_prompt):
                    yield chunk
                self._record_runtime(session_id, request, decision.model_alias, True, started)
                return
            except NotImplementedError:
                pass  # adapter declared but didn't override — fall through
            except Exception:
                self._record_runtime(session_id, request, decision.model_alias, False, started)
                raise

        # Fallback: no streaming support — yield the complete response once
        response = await self.ainvoke(request)
        yield response.output