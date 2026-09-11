# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

# File: k9_aif_abb/k9_governance/chained_governance.py

"""
ChainedGovernance — composes multiple governance pipelines, run in order.

Additive, not substitutive: each stage stays fully active regardless of what
comes before or after it. This is the composing class for the pattern the
Developer Guide already describes for k9x_Shield + a semantic LLM layer like
Granite Guardian — "the two layers are additive, never substitutes for each
other ... k9x_Shield's deterministic checks stay in place regardless (cheap,
catching the obvious cases before any semantic call is even made), and a
semantic layer is opt-in on top" — but until now nothing actually implemented
the composition; every consumer had to pick exactly one governance object.

Typical use — Shield always, Guardian layered on top only when configured:

    governance = ShieldGovernance(config=config)
    if config.get("governance", {}).get("guardian", {}).get("enabled"):
        governance = ChainedGovernance(
            governance,
            ProfanityGovernance(config=config),
        )
    agent = MyAgent(config=config, governance=governance)
"""

from __future__ import annotations

import inspect
from typing import Any, Dict, Optional

from k9_aif_abb.k9_core.governance.base_governance import BaseGovernance


class ChainedGovernance(BaseGovernance):
    """
    Runs each stage's pre_process (then, separately, each stage's post_process)
    in the order given. A stage may be sync or async — resolved the same way
    BaseAgent.apply_pre_governance/apply_post_governance already resolve a
    single governance object's result (k9_core/agent/base_agent.py).

    Any stage raising PermissionError halts the chain immediately — that
    stage's block is the result, later stages never run. None entries are
    silently dropped so callers can build the stage list conditionally
    without an if/else around the constructor call itself.
    """

    layer = "ChainedGovernance"

    def __init__(
        self,
        *stages: BaseGovernance,
        config: Optional[Dict[str, Any]] = None,
        monitor=None,
    ) -> None:
        super().__init__(config=config, monitor=monitor)
        self._stages = [s for s in stages if s is not None]

    async def pre_process(
        self,
        payload: Dict[str, Any],
        ctx: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        for stage in self._stages:
            result = stage.pre_process(payload, ctx)
            if inspect.isawaitable(result):
                result = await result
            payload = result
        return payload

    async def post_process(
        self,
        payload: Dict[str, Any],
        ctx: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        for stage in self._stages:
            result = stage.post_process(payload, ctx)
            if inspect.isawaitable(result):
                result = await result
            payload = result
        return payload
