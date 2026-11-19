# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""Recognising a k9x Origin answer in a payload (``K9Origin.get_current()`` shape), for the filters."""

from typing import Any, Dict, List

_UNVERIFIED_FLAGS = ("in_review", "conflict", "verification_failed")


def is_origin_answer(value: Any) -> bool:
    """True for a k9x Origin answer: a dict with ``entity``, ``id``, ``found`` and a ``flags`` dict."""
    return (isinstance(value, dict) and isinstance(value.get("flags"), dict)
            and "entity" in value and "id" in value and "found" in value)


def quarantined(answer: Dict[str, Any]) -> bool:
    return bool((answer.get("flags") or {}).get("quarantined"))


def unverified_flags(answer: Dict[str, Any]) -> List[str]:
    flags = answer.get("flags") or {}
    return [f for f in _UNVERIFIED_FLAGS if flags.get(f)]
