# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

"""
Prompt embedders for the learned router.

The router predicts a model's quality on a new prompt from the scores it has
seen on *similar* prompts, so it needs a vector per prompt:

  - ``HashingPromptEmbedder`` (default): word unigrams + bigrams hashed into a
    sparse vector. No model, no GPU, no new dependency, deterministic across
    processes. Good enough to separate "write a function…" from "summarise
    this claim…" and to find near-duplicate prompts.
  - ``ServicePromptEmbedder``: wraps any ``BaseEmbeddingService`` (e.g. the
    OOB Ollama embedder via ``EmbeddingServiceFactory``) for semantic vectors.

Vectors are either a sparse ``{index: weight}`` dict or a dense list; both are
L2-normalised so similarity is a plain dot product.
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Dict, List, Optional, Union

Vector = Union[Dict[int, float], List[float]]

_TOKEN = re.compile(r"[a-z0-9_]+")


def _normalise_sparse(vec: Dict[int, float]) -> Dict[int, float]:
    norm = math.sqrt(sum(v * v for v in vec.values()))
    return {k: v / norm for k, v in vec.items()} if norm else {}


def _normalise_dense(vec: List[float]) -> List[float]:
    norm = math.sqrt(sum(v * v for v in vec))
    return [v / norm for v in vec] if norm else list(vec)


def similarity(a: Vector, b: Vector) -> float:
    """Cosine similarity of two normalised vectors (sparse or dense)."""
    if not a or not b:
        return 0.0
    if isinstance(a, dict) and isinstance(b, dict):
        if len(a) > len(b):
            a, b = b, a
        return sum(v * b.get(k, 0.0) for k, v in a.items())
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        return sum(x * y for x, y in zip(a, b))
    return 0.0


class HashingPromptEmbedder:
    """Signed feature hashing of word unigrams and bigrams.

    The task type, when known, is added as its own token (as heavy as the whole
    text) so prompts of the same type sit closer together than prompts that merely
    share vocabulary.
    """

    def __init__(self, dims: int = 2048, task_weight: float = 1.0):
        self.dims = int(dims)
        self.task_weight = float(task_weight)
        self.name = f"hashing-v1-{self.dims}"

    def _slot(self, token: str) -> tuple[int, float]:
        digest = hashlib.md5(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "little") % self.dims
        sign = 1.0 if digest[4] & 1 else -1.0
        return index, sign

    def embed(self, text: str, task_type: Optional[str] = None) -> Dict[int, float]:
        words = _TOKEN.findall((text or "").lower())
        features: List[str] = list(words) + [f"{a} {b}" for a, b in zip(words, words[1:])]
        vec: Dict[int, float] = {}
        for token in features:
            index, sign = self._slot(token)
            vec[index] = vec.get(index, 0.0) + sign
        # Sub-linear term frequency so one repeated word doesn't dominate.
        vec = {k: math.copysign(1.0 + math.log(abs(v)), v) for k, v in vec.items() if v}
        if task_type:
            norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
            index, sign = self._slot(f"__task__:{task_type}")
            vec[index] = vec.get(index, 0.0) + sign * self.task_weight * norm
        return _normalise_sparse(vec)


class ServicePromptEmbedder:
    """Adapter over a ``BaseEmbeddingService`` (dense semantic vectors)."""

    def __init__(self, service, name: str):
        self.service = service
        self.name = name

    def embed(self, text: str, task_type: Optional[str] = None) -> List[float]:
        prefix = f"[{task_type}] " if task_type else ""
        return _normalise_dense([float(x) for x in self.service.embed(prefix + (text or ""))])


def build_embedder(learning_cfg: Dict, full_config: Optional[Dict] = None):
    """``inference.router.learning.embedder``: ``hashing`` (default) or
    ``service`` (uses EmbeddingServiceFactory with the app's ``vectordb``
    settings, e.g. Ollama ``nomic-embed-text``)."""
    kind = str(learning_cfg.get("embedder", "hashing")).lower()
    if kind in ("service", "ollama"):
        from k9_aif_abb.k9_factories.embedding_factory import EmbeddingServiceFactory

        cfg = full_config or {}
        svc = EmbeddingServiceFactory.create(cfg)
        model = cfg.get("vectordb", {}).get("embedding_model", "nomic-embed-text")
        return ServicePromptEmbedder(svc, name=f"service:{model}")
    return HashingPromptEmbedder(dims=int(learning_cfg.get("dims", 2048)),
                                 task_weight=float(learning_cfg.get("task_weight", 1.0)))
