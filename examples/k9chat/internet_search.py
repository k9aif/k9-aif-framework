# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework — k9chat live web search
#
# Real internet access for K9Chat, off by default -- SCOPE_INSTRUCTION
# deliberately keeps this tool focused on K9-AIF/K9X, so general
# real-world questions ("what's the weather in X") get no live data and
# the model either declines or answers from stale training-data patterns
# unless this is explicitly turned on. When on, every message queries a
# self-hosted SearxNG instance (privacy-respecting metasearch, aggregates
# multiple engines -- no third-party API key, no per-query cost) and the
# top results are folded into the prompt as clearly-labeled live context
# (see chat_agent.py's _format_prompt() web_context handling).
#
# Verified live (2026-09-20) against the real instance: real results,
# real titles/urls/content, not a stub.

from __future__ import annotations

import logging
from typing import Any, Dict, List

import requests

log = logging.getLogger("k9chat.internet_search")


def search(base_url: str, query: str, top_k: int = 5, timeout: float = 6.0) -> List[Dict[str, Any]]:
    """Real SearxNG search. Returns [] (not an error) on any failure --
    unreachable search shouldn't break chat, same fail-open convention as
    every other retrieval path in k9chat."""
    if not query.strip():
        return []
    try:
        resp = requests.get(
            f"{base_url.rstrip('/')}/search",
            params={"q": query, "format": "json"},
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        log.warning("[InternetSearch] query failed: %s", exc)
        return []

    results = []
    for r in data.get("results", [])[:top_k]:
        title = (r.get("title") or "").strip()
        content = (r.get("content") or "").strip()
        url = (r.get("url") or "").strip()
        if title or content:
            results.append({"title": title, "content": content, "url": url})
    return results
