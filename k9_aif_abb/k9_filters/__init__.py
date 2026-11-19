# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
k9_filters: the out-of-the-box K9X Filters (1.32.0). The contract is
``k9_aif_abb.k9_core.filters.BaseFilter``; FilterFactory builds these by name.

| Name | Class | Direction | What it does |
|---|---|---|---|
| ``text_normalize`` | K9TextNormalizeFilter | in | NFKC, invisible characters removed, tag characters revealed |
| ``attention`` | K9AttentionFilter | in | quarantine, score, de-duplicate, prune to a budget, label trust |
| ``structured_output`` | K9StructuredOutputFilter | out | JSON from the model's text, validated, or a failure |
| ``provenance`` | K9ProvenanceFilter | in + out | ``sources`` from the k9x Origin answers the agent was given |

Governance decides, filters transform. Design: ``docs/roadmap/k9x-filters-design.md``.
"""

from k9_aif_abb.k9_filters.attention import K9AttentionFilter, wrap_untrusted
from k9_aif_abb.k9_filters.provenance import K9ProvenanceFilter
from k9_aif_abb.k9_filters.structured_output import K9StructuredOutputFilter, extract_json
from k9_aif_abb.k9_filters.text_normalize import K9TextNormalizeFilter

__all__ = ["K9AttentionFilter", "K9ProvenanceFilter", "K9StructuredOutputFilter", "K9TextNormalizeFilter",
           "extract_json", "wrap_untrusted"]
