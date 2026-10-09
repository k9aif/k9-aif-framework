# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

from __future__ import annotations

from typing import Any, Dict, Optional

from k9_aif_abb.k9_core.governance.pipeline import governance_from_config


def make_governance(config: Dict[str, Any]) -> Optional[Any]:
    """
    The governance this app's agents run under, built by the framework from
    config.yaml (governance_from_config, k9-aif >= 1.15): security.shield ->
    ShieldGovernance, governance.guardian -> GuardianGovernance, both ->
    ChainedGovernance(Shield, Guardian). None means nothing is configured
    (require_governance() then decides by K9_ENV).
    """
    return governance_from_config(config)
