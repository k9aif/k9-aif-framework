# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

"""
k9x Origin — what is true right now, and where it came from.

Built into the framework like k9x Shield. An agent makes one call (``get_current``); Origin
answers from live state (streams), reads through to the system of record when needed, verifies
before irreversible steps, flags quarantine and conflicts, and screens requests and answers
with k9x Shield. It states facts; business rules (``K9RulesAgent``) decide.

Design: docs/roadmap/k9x-origin-design.md. Configure in config/config.yaml (``origin:``) and
config/origin.yaml. Build with ``OriginFactory.create(config)``.
"""

from k9_aif_abb.k9_origin.config import ConflictWatch, EntityPolicy, OriginConfig
from k9_aif_abb.k9_origin.conflicts import BaseConflictRule, Conflict, LateEventRule, TransitionRule
from k9_aif_abb.k9_origin.origin import BaseOrigin, K9Origin
from k9_aif_abb.k9_origin.sources import OriginSources

__all__ = [
    "BaseOrigin", "K9Origin", "OriginConfig", "EntityPolicy", "ConflictWatch",
    "Conflict", "BaseConflictRule", "TransitionRule", "LateEventRule", "OriginSources",
]
