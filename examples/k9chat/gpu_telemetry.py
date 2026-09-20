# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

"""
GPU/CPU telemetry -- proxies the real nvidia-smi-backed server at
K9CHAT_GPU_TELEMETRY_URL (see /Users/ravinatarajan/ai/RTX-5090/opt/
gpu-telemetry/gpu-server.js), not a fake/simulated readout. Cached
briefly so k9chat's own polling (queue admission checks + the UI's
telemetry panel, both independently on ~2s intervals) doesn't hammer
nvidia-smi harder than the standalone dashboard already does.

Two consumers:
1. app.py's /telemetry endpoint -- the UI panel polls this.
2. queue_control.py's QueueSlot -- checks is_over_temp_limit() before
   admitting a NEW job. Does not touch an already-running generation;
   killing an in-flight request safely is a harder, riskier problem than
   just not starting new ones while hot.
"""

from __future__ import annotations

import os
import time
from typing import Optional

import requests

_URL = os.environ.get("K9CHAT_GPU_TELEMETRY_URL", "http://localhost:5000/gpu")
_TEMP_LIMIT_C = float(os.environ.get("K9CHAT_GPU_TEMP_LIMIT_C", "85"))
_CACHE_TTL_SECONDS = 1.5

_cache: Optional[dict] = None
_cache_at: float = 0.0


def get_telemetry(force: bool = False) -> dict:
    """Returns the real telemetry dict, or {"error": "..."} if the
    telemetry server isn't reachable -- never fabricates numbers. Cached
    for _CACHE_TTL_SECONDS to keep repeated callers cheap."""
    global _cache, _cache_at
    now = time.monotonic()
    if not force and _cache is not None and (now - _cache_at) < _CACHE_TTL_SECONDS:
        return _cache

    try:
        resp = requests.get(_URL, timeout=3)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        data = {"error": str(exc)}

    _cache = data
    _cache_at = now
    return data


def is_over_temp_limit() -> bool:
    """True only on a real, successfully-read temperature at or above the
    configured limit. A telemetry-fetch failure does NOT count as
    over-limit -- fail open on the guard, same fail-open convention as
    every other retrieval/guard check in k9chat tonight (a monitoring
    outage shouldn't itself take the whole chat down)."""
    data = get_telemetry()
    temp = data.get("temperatureC")
    if temp is None:
        return False
    return float(temp) >= _TEMP_LIMIT_C


def temp_limit_c() -> float:
    return _TEMP_LIMIT_C
