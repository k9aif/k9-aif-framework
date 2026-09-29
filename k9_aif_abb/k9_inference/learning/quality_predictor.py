# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

"""
Per-prompt quality prediction and the learned routing policy.

The approach follows the evaluation-trained routers (Not Diamond, RouteLLM's
similarity-weighted ranking, RouterBench's k-NN baseline): the router keeps
graded examples — (prompt vector, model, quality 0–100, latency) — and, for a
new prompt, predicts each model's quality as the similarity-weighted average
of that model's scores on the k most similar prompts it has seen. It then
picks the model with the best *utility*: predicted quality minus a latency and
cost penalty set by the request's ``latency_budget`` / ``cost_profile``.

Everything here is pure computation; persistence lives in RoutingStateStore
and the decision is made in K9ModelRouter.route().
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from .prompt_embedder import Vector, similarity


@dataclass
class Example:
    vector: Vector
    model_alias: str
    quality: float
    latency_ms: Optional[float] = None
    task_type: Optional[str] = None


@dataclass
class Prediction:
    model_alias: str
    quality: float
    neighbors: int
    weight: float
    latency_ms: Optional[float] = None
    utility: float = 0.0
    nearest: List[float] = field(default_factory=list)


class KNNQualityPredictor:
    """Similarity-weighted k-nearest-neighbour quality estimate per model."""

    def __init__(self, k: int = 15, power: float = 2.0, min_similarity: float = 0.05):
        self.k = int(k)
        self.power = float(power)
        self.min_similarity = float(min_similarity)

    def predict(self, vector: Vector, examples: Iterable[Example],
                candidates: Iterable[str], task_type: Optional[str] = None) -> Dict[str, Prediction]:
        """With ``task_type``, only examples graded on that task type count:
        how a model did on chat says nothing reliable about its code."""
        wanted = set(candidates)
        scored: Dict[str, List[tuple]] = {m: [] for m in wanted}
        for ex in examples:
            if ex.model_alias not in wanted:
                continue
            if task_type and ex.task_type and ex.task_type != task_type:
                continue
            sim = similarity(vector, ex.vector)
            if sim >= self.min_similarity:
                scored[ex.model_alias].append((sim, ex))

        out: Dict[str, Prediction] = {}
        for model, pairs in scored.items():
            if not pairs:
                continue
            pairs.sort(key=lambda p: p[0], reverse=True)
            top = pairs[: self.k]
            weights = [s ** self.power for s, _ in top]
            total = sum(weights)
            if total <= 0:
                continue
            quality = sum(w * ex.quality for w, (_, ex) in zip(weights, top)) / total
            lat = [(w, ex.latency_ms) for w, (_, ex) in zip(weights, top) if ex.latency_ms is not None]
            latency = (sum(w * l for w, l in lat) / sum(w for w, _ in lat)) if lat else None
            out[model] = Prediction(model_alias=model, quality=round(quality, 2), neighbors=len(top),
                                    weight=round(total, 4), latency_ms=latency,
                                    nearest=[round(s, 3) for s, _ in top[:3]])
        return out


# ----------------------------------------------------------------------
# Utility: quality minus the latency/cost the request says it can't afford
# ----------------------------------------------------------------------
DEFAULT_LATENCY_PENALTY = {"realtime": 4.0, "interactive": 1.0, "batch": 0.0}   # points per second
DEFAULT_COST_PENALTY = 10.0                                                     # points per tier above budget
_COST_RANK = {"minimal": 0, "standard": 1, "premium": 2}


def utility(pred: Prediction, meta: Dict[str, Any], latency_budget: Optional[str],
            cost_profile: Optional[str], learning_cfg: Dict[str, Any]) -> float:
    value = pred.quality
    per_second = dict(DEFAULT_LATENCY_PENALTY, **(learning_cfg.get("latency_penalty") or {}))
    if latency_budget and pred.latency_ms is not None:
        value -= float(per_second.get(latency_budget, 0.0)) * (pred.latency_ms / 1000.0)
    if cost_profile in _COST_RANK and meta.get("cost_tier") in _COST_RANK:
        over = _COST_RANK[meta["cost_tier"]] - _COST_RANK[cost_profile]
        if over > 0:
            value -= float(learning_cfg.get("cost_penalty", DEFAULT_COST_PENALTY)) * over
    return round(value, 2)
