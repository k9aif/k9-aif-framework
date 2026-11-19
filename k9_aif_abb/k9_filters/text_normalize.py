# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
K9TextNormalizeFilter (in): make every string in the payload read the same to Shield as to the model.

Pattern checks compare characters; a model reads meaning. Text that a person (and a regex) sees as
harmless can carry instructions the model follows. Verified on k9-aif 1.31.1: Shield's
PromptInjectionCheck blocks "ignore all previous instructions" but passes it written

* with a zero-width space inside a word ("ig\\u200bnore"),
* in fullwidth letters ("ｉｇｎｏｒｅ"),
* in Unicode tag characters (U+E0000 to U+E007F: invisible, yet many models read them as ASCII).

For every string in the payload (nested dicts and lists included), this filter applies Unicode NFKC,
removes invisible format characters (zero-width space/joiner/non-joiner, word joiner, invisible
operators, byte-order mark, bidirectional embeddings, overrides and isolates) and, by default,
**reveals** tag characters as the ASCII they encode, so the hidden text is screened (and blocked) by
Shield and shows up in the log. ``tag_chars: strip`` removes them instead. Runs first in the chain.

Settings (chain entry)::

    - {name: text_normalize, nfkc: true, tag_chars: reveal, keep_joiners: false}   # reveal | strip

``keep_joiners: true`` keeps the zero-width non-joiner and joiner, which Persian, Indic scripts and
emoji sequences use legitimately.
"""

from __future__ import annotations

import unicodedata
from typing import Any, Dict, Tuple

from k9_aif_abb.k9_core.filters.base_filter import BaseFilter, FilterContext, FilterResult

# Invisible format characters with no place in text sent to a model.
_INVISIBLE = {
    0x00AD,                                          # soft hyphen
    0x180E,                                          # Mongolian vowel separator
    0x200B, 0x200C, 0x200D, 0x200E, 0x200F,          # zero-width space/non-joiner/joiner, LRM, RLM
    0x202A, 0x202B, 0x202C, 0x202D, 0x202E,          # bidi embeddings and overrides
    0x2060, 0x2061, 0x2062, 0x2063, 0x2064,          # word joiner, invisible operators
    0x2066, 0x2067, 0x2068, 0x2069,                  # bidi isolates
    0xFEFF,                                          # byte-order mark / zero-width no-break space
}
_TAG_FIRST, _TAG_LAST = 0xE0000, 0xE007F


class K9TextNormalizeFilter(BaseFilter):
    name = "text_normalize"
    filter_type = "normalize"
    applies_to = ("in",)

    def __init__(self, settings: Dict[str, Any] | None = None):
        super().__init__(settings)
        self.nfkc = bool(self.settings.get("nfkc", True))
        # ZWNJ/ZWJ belong to some scripts (Persian, Indic) and emoji sequences: keep them for such content.
        self.invisible = _INVISIBLE - ({0x200C, 0x200D} if self.settings.get("keep_joiners") else set())
        self.tag_chars = self.settings.get("tag_chars", "reveal")
        if self.tag_chars not in ("reveal", "strip"):
            raise ValueError("text_normalize: tag_chars must be 'reveal' or 'strip'")

    def _clean(self, text: str, counts: Dict[str, int]) -> str:
        out = []
        for ch in text:
            cp = ord(ch)
            if cp in self.invisible:
                counts["invisible_removed"] += 1
                continue
            if _TAG_FIRST <= cp <= _TAG_LAST:
                if self.tag_chars == "reveal" and 0x20 <= cp - _TAG_FIRST <= 0x7E:
                    counts["tag_chars_revealed"] += 1
                    out.append(chr(cp - _TAG_FIRST))
                else:
                    counts["tag_chars_removed"] += 1
                continue
            out.append(ch)
        cleaned = "".join(out)
        if self.nfkc:
            normalised = unicodedata.normalize("NFKC", cleaned)
            if normalised != cleaned:
                counts["nfkc_changed"] += 1
            cleaned = normalised
        return cleaned

    def _walk(self, value: Any, path: str, changed: Dict[str, Dict[str, int]]) -> Any:
        if isinstance(value, str):
            counts = {"invisible_removed": 0, "tag_chars_revealed": 0, "tag_chars_removed": 0, "nfkc_changed": 0}
            new = self._clean(value, counts)
            if new != value:
                changed[path or "$"] = {k: v for k, v in counts.items() if v}
            return new
        if isinstance(value, dict):
            return {k: self._walk(v, f"{path}.{k}" if path else str(k), changed) for k, v in value.items()}
        if isinstance(value, list):
            return [self._walk(v, f"{path}[{i}]", changed) for i, v in enumerate(value)]
        if isinstance(value, tuple):
            return tuple(self._walk(v, f"{path}[{i}]", changed) for i, v in enumerate(value))
        return value

    def filter_in(self, payload: Any, ctx: FilterContext) -> FilterResult:
        changed: Dict[str, Dict[str, int]] = {}
        new = self._walk(payload, "", changed)
        return FilterResult(new, record={"fields_changed": changed} if changed else {})
