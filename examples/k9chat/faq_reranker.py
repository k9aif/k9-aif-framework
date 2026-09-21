# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework — k9chat FAQ match reranker
#
# Cross-encoder reranker for the FAQ/glossary shortcut: given the user's
# question and the top candidate chunk the vector retriever already found,
# scores how directly that candidate actually answers the question.
#
# Why a cross-encoder rather than the chat LLM: this is a purpose-built,
# small, CPU-only model for exactly this (query, passage) -> relevance
# task -- not the mechanical yes/no classification an LLM call would be
# repurposed for. Real retrieve-then-rerank architecture, not a Ollama
# LLM-as-judge call spending GPU cycles on a job a dedicated model already
# does better and faster. See requirements.txt for the dependency notes.
#
# Deliberately pinned to CPU (device="cpu") -- this model is small enough
# to be fast there, and staying off the GPU avoids contending with
# Ollama's own VRAM allocation for the real chat model.

from __future__ import annotations

import logging
from typing import Optional

log = logging.getLogger("k9chat.faq_reranker")

_MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"
_MODEL = None
_MODEL_LOAD_FAILED = False


def _get_model():
    global _MODEL, _MODEL_LOAD_FAILED
    if _MODEL is not None or _MODEL_LOAD_FAILED:
        return _MODEL
    try:
        from sentence_transformers import CrossEncoder
        _MODEL = CrossEncoder(_MODEL_NAME, device="cpu")
        log.info("[FAQReranker] Loaded %s on CPU", _MODEL_NAME)
    except Exception as exc:
        _MODEL_LOAD_FAILED = True
        log.warning("[FAQReranker] Could not load %s: %s", _MODEL_NAME, exc)
    return _MODEL


def warm_up() -> None:
    """Loads the model eagerly (call once at app startup) -- otherwise the
    first real user request pays the ~10s HuggingFace download/torch-init
    cost, confirmed live (10s cold vs 64ms warm on the very next call)."""
    _get_model()


def relevance_score(query: str, candidate_text: str) -> Optional[float]:
    """Raw cross-encoder logit for how well candidate_text answers query --
    higher is more relevant, no fixed bound (calibrated empirically per
    faq_shortcut.py's threshold, not assumed to be a [0,1] probability).
    Returns None if the model isn't available (never raises -- a reranker
    outage should fall through to normal LLM synthesis, not break chat)."""
    model = _get_model()
    if model is None:
        return None
    try:
        score = model.predict([(query, candidate_text)])
        return float(score[0])
    except Exception as exc:
        log.warning("[FAQReranker] scoring failed: %s", exc)
        return None
