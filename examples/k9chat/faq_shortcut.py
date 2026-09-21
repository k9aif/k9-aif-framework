# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework — k9chat FAQ shortcut
#
# Real retrieve-then-rerank pattern: the vector retriever (bi-encoder,
# nomic-embed-text) finds candidates fast but loosely -- its own #1 hit
# isn't always the best one (confirmed live: for "What does ABB stand
# for?" the bi-encoder's top hit was an FAQ entry about the ABB-vs-SBB
# *difference*, not the glossary's actual ABB definition, which ranked
# lower in vector-search order but is the correct answer). Reranking only
# that single top hit would have shortcut-answered with the wrong FAQ
# entry -- confirmed, this actually happened before this comment was
# written. Fixed: rerank every curated candidate among knowledge_context
# and take the highest scorer, not just gate the bi-encoder's own #1.
# Only when BOTH the source is curated
# (k9chat/faq or k9chat/glossary -- written to stand alone as a direct
# answer, unlike blog/README prose) AND the reranker is confident does
# this return the stored text verbatim, bypassing the chat LLM entirely --
# deterministic, zero hallucination risk, for exactly the class of
# question a glossary/FAQ entry already answers correctly.
#
# Falls through to None (normal LLM synthesis) on anything uncertain --
# see config.yaml's faq_shortcut section for the empirically-calibrated
# threshold and why erring toward "ask the LLM" is the safe default here.

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional

from examples.k9chat import faq_reranker

log = logging.getLogger("k9chat.faq_shortcut")

_PREFIX_RE = re.compile(r"^\[[^\]]+\]\s*")


def _clean_answer(text: str) -> str:
    """Strips the internal "[source] " retrieval tag -- everything after
    that is the real stored text, shown verbatim (this is the whole point:
    standard, deterministic wording, not reworded by an LLM)."""
    return _PREFIX_RE.sub("", text).strip()


def try_shortcut(
    config: Dict[str, Any], knowledge_context: list, query: str
) -> Optional[Dict[str, Any]]:
    """Returns {"answer": str, "score": float, "source": str} if a
    confident FAQ/glossary match exists, else None. Takes the knowledge
    hits chat.py already retrieved for this turn (knowledge_context) rather
    than querying the vector store again -- same retrieve() call the
    normal synthesis path would use if this shortcut doesn't fire.

    Never raises -- any failure here (reranker unavailable, empty
    knowledge_context) falls through to normal chat, same fail-open
    convention as every other guard in k9chat.

    Does NOT check faq_shortcut.enabled itself -- the caller (chat.py's
    check_faq_shortcut(), gated by the runtime-toggleable
    is_faq_shortcut_enabled()) is the single source of truth for that,
    same split as correction_learner.detect_correction()."""
    if not knowledge_context:
        return None

    cfg = config.get("faq_shortcut", {})
    allowed_sources = set(cfg.get("sources", ["k9chat/faq", "k9chat/glossary"]))
    threshold = float(cfg.get("score_threshold", 3.5))

    try:
        candidates = [
            hit for hit in knowledge_context
            if hit.get("metadata", {}).get("source", "") in allowed_sources
        ]
        if not candidates:
            return None

        best = None
        best_score = threshold  # strictly must clear the threshold to win
        for hit in candidates:
            score = faq_reranker.relevance_score(query, hit.get("text", ""))
            if score is not None and score >= best_score:
                best = hit
                best_score = score

        if best is None:
            return None

        answer = _clean_answer(best.get("text", ""))
        if not answer:
            return None

        source = best.get("metadata", {}).get("source", "")
        log.info(
            "[FAQShortcut] matched source=%s score=%.2f (threshold=%.2f, %d candidate(s) considered)",
            source, best_score, threshold, len(candidates),
        )
        return {"answer": answer, "score": best_score, "source": source}
    except Exception as exc:
        log.warning("[FAQShortcut] failed, falling through to normal chat: %s", exc)
        return None
