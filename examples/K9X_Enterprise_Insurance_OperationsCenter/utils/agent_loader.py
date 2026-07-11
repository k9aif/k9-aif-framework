# SPDX-License-Identifier: Apache-2.0
# K9-AIF EOC — utils/agent_loader.py
#
# AgentLoader has been promoted to the ABB layer.
# Import from there so all solutions share the same implementation,
# including enterprise policy enforcement via _policy.locked.

from k9_aif_abb.k9_agents.agent_loader import AgentLoader  # noqa: F401

__all__ = ["AgentLoader"]
