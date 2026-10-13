# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

"""Built-in business-rules agent: evaluates a rules adapter and raises RequiresHIL when a rule says so."""

from k9_aif_abb.k9_agents.rules.k9_rules_agent import K9RulesAgent

__all__ = ["K9RulesAgent"]
