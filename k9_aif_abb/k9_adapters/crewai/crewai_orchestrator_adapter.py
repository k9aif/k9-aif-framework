# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

from __future__ import annotations

import asyncio
import concurrent.futures
from typing import Any, Coroutine, Dict, Optional

from k9_aif_abb.k9_core.base_adapter import BaseAdapter
from k9_aif_abb.k9_core.orchestration.base_orchestrator import BaseOrchestrator


def _run_coro_sync(coro: "Coroutine[Any, Any, Any]") -> Any:
    """
    Execute an async coroutine from synchronous code — safe whether or not
    an event loop is already running on the calling thread. Mirrors
    K9ModelRouter's helper of the same name (k9_inference/routers/
    k9_model_router.py) — same problem (a sync contract, apply_pre/post_
    governance() are async), same fix, kept local rather than shared
    since neither has grown a shared-utils home yet.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


class CrewAIOrchestratorAdapter(BaseOrchestrator, BaseAdapter):
    """
    Adapter that wraps a CrewAI Crew and exposes it through K9-AIF orchestration contracts.

    Governance is invoked unconditionally on every call, exactly like any
    native K9-AIF orchestrator — there is no config.yaml flag that gates
    this (an earlier ``governance.enabled`` key seen in some example
    config.yaml files is not read by any framework code; do not add a
    reference to it here). What varies is which governance object
    ``require_governance()`` resolved at construction time: pass a real
    one via ``governance=`` for actual enforcement, or leave it unset and
    get ``NoopGovernance`` (silent passthrough, gated only by ``K9_ENV``).
    """

    def __init__(
        self,
        crew: Any,
        name: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
        governance: Optional[Any] = None,
    ) -> None:
        BaseAdapter.__init__(self, adapter_name=name or "CrewAIOrchestratorAdapter")
        BaseOrchestrator.__init__(self, config=config, governance=governance)
        self.crew = crew

    def adapt_input(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Thin pass-through — the same double-normalization defect as
        adapt_output(), on the input side. CrewAIPayloadMapper.to_crewai_
        input() already normalizes the payload once, at the facade layer,
        before execute_flow() ever sees it; re-running the identical logic
        here re-wrapped an already-normalized payload, producing a doubly
        nested "raw_payload" on every call.
        """
        return payload or {}

    def adapt_output(self, result: Any) -> Any:
        """
        Thin pass-through. Full envelope normalization ({"status",
        "result", "output_text"}) is CrewAIPayloadMapper.from_crewai_
        output()'s job, called exactly once, at the facade layer
        (K9CrewAIAdapter.execute()). Applying the same normalization
        here too was a real, previously-shipped bug: it silently
        double-wrapped every response into a garbled, nested payload —
        see the Claude Agent SDK adapter's CLAUDE.md, which documents
        this exact defect in this exact file as the invariant its own
        adapt_output() must not repeat.
        """
        return result

    def execute_flow(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.validate_payload(payload)
        crew_input = self.adapt_input(payload)

        governed_input = _run_coro_sync(self.apply_pre_governance(crew_input))

        self.publish_status("CrewAISessionStarted", {"adapter": self.adapter_name})

        if hasattr(self.crew, "kickoff"):
            result = self.crew.kickoff(inputs=governed_input)
        elif hasattr(self.crew, "run"):
            result = self.crew.run(governed_input)
        else:
            raise AttributeError(
                "Provided CrewAI crew does not support kickoff() or run()."
            )

        adapted = self.adapt_output(result)
        governed_output = _run_coro_sync(self.apply_post_governance(adapted))

        self.publish_status("CrewAISessionCompleted", {"adapter": self.adapter_name})

        return governed_output