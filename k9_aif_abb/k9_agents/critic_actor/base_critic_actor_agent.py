# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

"""
BaseCriticActorAgent — iterative Actor-Critic refinement ABB.

Also known in the literature as the Critic-Actor, Self-Correction, or
Refinement pattern.  Widely used in production for:

    - Code generation  : Actor writes code; Critic runs tests; Actor fixes
    - Data extraction  : Actor extracts JSON; Critic validates schema; Actor corrects
    - Contract drafting: Actor writes clause; Critic checks compliance checklist
    - RAG quality      : Actor drafts answer; Critic verifies against source docs

Loop skeleton
-------------
    Round 1:
        generate(ctx)          → draft
        critique(draft, ctx)   → feedback (accepted?, score, issues)
        should_accept(feedback) → ACCEPTED | REJECTED | ESCALATE | FAIL

    Round 2+:
        refine(draft, feedback, ctx)  → improved draft
        critique(draft, ctx)          → feedback
        should_accept(feedback)       → decision
        ...

    Termination:
        ACCEPTED  → finalize()
        ESCALATE  → escalate()
        FAIL      → fail()
        max_rounds reached → finalize() or escalate() per config

This ABB is distinct from BaseValidationLoopAgent:
    BaseValidationLoopAgent — one agent tests a hypothesis against an oracle
    BaseCriticActorAgent    — two roles: Actor produces output, Critic challenges it

Config keys (all optional)
--------------------------
max_rounds               : int   — default 3
acceptance_threshold     : float — default 0.8; used in should_accept()
finalize_on_max_rounds   : bool  — default True; if False, escalates on timeout
escalate_on_critic_error : bool  — default False; if True, ESCALATE on critique() exception
"""

import asyncio
import concurrent.futures
import logging
from abc import abstractmethod
from typing import Any, Coroutine, Dict

from k9_aif_abb.k9_core.agent.base_agent import BaseAgent
from k9_aif_abb.k9_agents.critic_actor.models.critic_actor import (
    CriticActorContext,
    CriticActorDisposition,
    CriticActorResult,
    CriticActorStep,
)

log = logging.getLogger(__name__)

_DEFAULT_MAX_ROUNDS          = 3
_DEFAULT_ACCEPTANCE_THRESHOLD = 0.8
_DEFAULT_FINALIZE_ON_MAX     = True


def _run_coro_sync(coro: "Coroutine[Any, Any, Any]") -> Any:
    """Run an async coroutine from sync code, safe whether or not a loop is
    already running on this thread. Same pattern as
    k9_inference/routers/k9_model_router.py's own _run_coro_sync — kept
    local rather than imported since the framework doesn't share it from
    one place today (three independent copies already exist)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


class BaseCriticActorAgent(BaseAgent):
    """
    ABB: Actor-Critic refinement loop.

    The Actor generates or refines a draft; the Critic evaluates it and
    returns structured feedback.  The loop continues until the Critic
    accepts the output, a terminal disposition is reached, or max_rounds
    is hit.

    Public interface is unchanged from BaseAgent — callers call
    ``execute(payload)`` and receive a ``dict``.  The loop is internal.

    Subclasses must implement:
        generate()
        critique()
        refine()
        should_accept()
        finalize()

    Subclasses may override:
        escalate()  — default returns disposition=ESCALATE
        fail()      — default returns disposition=FAIL
    """

    layer: str = "BaseCriticActorAgent"

    # ------------------------------------------------------------------
    # Public entry point — satisfies BaseAgent.execute() contract
    # ------------------------------------------------------------------

    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Governance-wrapped entry point. Applies Shield/governance
        pre_process() to the incoming payload and post_process() to the
        final result — the actual loop logic is unchanged, in
        _execute_loop() below. See k9-aif-framework/CLAUDE.md's Security /
        Vulnerability section.
        """
        try:
            payload = _run_coro_sync(self.apply_pre_governance(payload))
        except PermissionError as exc:
            self._emit("governance_blocked", {"phase": "pre", "reason": str(exc)})
            return self._shield_blocked_dict(exc, phase="pre")

        result = self._execute_loop(payload)

        # Egress scans only the actual output, never the full result dict —
        # steps[]/critique_log legitimately duplicate content across rounds
        # by design (audit trail); passing the whole dict to a naive
        # repetition-detecting check produces false positives on benign
        # multi-round runs, confirmed empirically on the validation-loop
        # sibling. See that file's identical comment for the full story.
        try:
            result["output"] = _run_coro_sync(self.apply_post_governance(result.get("output", {})))
        except PermissionError as exc:
            self._emit("governance_blocked", {"phase": "post", "reason": str(exc)})
            result["disposition"] = CriticActorDisposition.FAIL.value
            result["output"] = {"governance_blocked": True, "phase": "post", "reason": str(exc)}

        return result

    def _shield_blocked_dict(self, exc: PermissionError, phase: str) -> Dict[str, Any]:
        """Same shape _to_dict() produces, for a payload governance rejected
        before the loop ever ran (no rounds happened, so there's nothing
        real to preserve — unlike a post-phase block, see execute()).
        Reuses FAIL rather than adding a new disposition value. The check
        name that blocked it is already embedded in `str(exc)` (Shield's
        own PermissionError message), not re-parsed here."""
        return {
            "agent":        self.layer,
            "disposition":  CriticActorDisposition.FAIL.value,
            "output":       {"governance_blocked": True, "phase": phase, "reason": str(exc)},
            "rounds":       0,
            "final_score":  0.0,
            "critique_log": [],
            "steps":        [],
        }

    # ------------------------------------------------------------------
    # Internal — the loop itself, unchanged from before governance wrapping
    # was added. Only renamed from execute() to _execute_loop(); no logic
    # inside this method was touched.
    # ------------------------------------------------------------------

    def _execute_loop(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        max_rounds        = int(self.config.get("max_rounds", _DEFAULT_MAX_ROUNDS))
        finalize_on_max   = self._parse_bool(
            self.config.get("finalize_on_max_rounds"), _DEFAULT_FINALIZE_ON_MAX
        )
        escalate_on_error = self._parse_bool(
            self.config.get("escalate_on_critic_error"), False
        )

        ctx = CriticActorContext(payload=payload)
        self._emit("loop_started", {"max_rounds": max_rounds})

        draft = None

        while ctx.round < max_rounds:
            ctx.round += 1

            # Actor: generate on round 1, refine on subsequent rounds
            if ctx.round == 1:
                draft = self.generate(ctx)
                self._emit("draft_generated", {"round": ctx.round})
            else:
                prior = ctx.steps[-1]
                draft = self.refine(prior.draft, prior.feedback, ctx)
                self._emit("draft_refined", {"round": ctx.round})

            # Critic: evaluate the draft
            try:
                feedback = self.critique(draft, ctx)
                self._emit("critique_produced", {"round": ctx.round})
            except Exception as exc:
                self.logger.error(
                    "[%s] critique() raised at round %d: %s",
                    self.layer, ctx.round, exc,
                )
                error_disp = (
                    CriticActorDisposition.ESCALATE if escalate_on_error
                    else CriticActorDisposition.FAIL
                )
                ctx.steps.append(CriticActorStep(
                    round=ctx.round, draft=draft,
                    feedback={"error": str(exc)},
                    disposition=error_disp, score=0.0,
                ))
                event = "loop_escalated" if escalate_on_error else "loop_failed"
                self._emit(event, {"rounds": ctx.round, "error": str(exc)})
                handler = self.escalate if escalate_on_error else self.fail
                return self._to_dict(handler(ctx))

            disposition = self.should_accept(feedback, ctx)
            score = self._extract_score(feedback)

            ctx.steps.append(CriticActorStep(
                round=ctx.round, draft=draft,
                feedback=feedback,
                disposition=disposition, score=score,
            ))

            if disposition is CriticActorDisposition.ACCEPTED:
                self._emit("loop_accepted", {"rounds": ctx.round})
                return self._to_dict(self.finalize(ctx))

            if disposition is CriticActorDisposition.ESCALATE:
                self._emit("loop_escalated", {"rounds": ctx.round})
                return self._to_dict(self.escalate(ctx))

            if disposition is CriticActorDisposition.FAIL:
                self._emit("loop_failed", {"rounds": ctx.round})
                return self._to_dict(self.fail(ctx))

            self._emit("loop_rejected", {"round": ctx.round, "score": score})

        # max rounds reached without terminal disposition
        if finalize_on_max:
            self._emit("loop_accepted", {
                "reason": "max_rounds_reached",
                "rounds": ctx.round,
            })
            return self._to_dict(self.finalize(ctx))

        self._emit("loop_escalated", {
            "reason": "max_rounds_reached",
            "rounds": ctx.round,
        })
        return self._to_dict(self.escalate(ctx))

    # ------------------------------------------------------------------
    # Abstract — must be implemented by every subclass
    # ------------------------------------------------------------------

    @abstractmethod
    def generate(self, ctx: CriticActorContext) -> Any:
        """
        Actor: produce the initial draft from the payload.

        Called only on round 1.  From round 2 onwards ``refine()`` is called
        instead.  Return any value — passed unchanged to ``critique()``.
        """

    @abstractmethod
    def critique(self, draft: Any, ctx: CriticActorContext) -> Dict[str, Any]:
        """
        Critic: evaluate the draft and return structured feedback.

        Convention: return a dict with at least:
            accepted : bool  — True if the draft meets the acceptance bar
            score    : float — 0.0 (rejected) to 1.0 (perfect)
            issues   : list  — specific problems the Actor should fix

        The Critic can be an LLM, a test runner, a schema validator,
        a compliance checker, or any callable that produces structured feedback.
        """

    @abstractmethod
    def refine(self, draft: Any, feedback: Dict[str, Any], ctx: CriticActorContext) -> Any:
        """
        Actor: produce an improved draft using the Critic's feedback.

        Has access to the full ``ctx.steps`` history — prior drafts and
        all feedback received so far.  Return value is passed to ``critique()``.
        """

    @abstractmethod
    def should_accept(
        self, feedback: Dict[str, Any], ctx: CriticActorContext
    ) -> CriticActorDisposition:
        """
        Decide what happens next based on the Critic's feedback.

        Return one of:
            ACCEPTED  — output is good enough; produce final result
            REJECTED  — Actor must refine and try again
            ESCALATE  — cannot converge; route to HIL
            FAIL      — definitively unacceptable; cannot be fixed
        """

    @abstractmethod
    def finalize(self, ctx: CriticActorContext) -> CriticActorResult:
        """
        Produce the final accepted output.  Called when ACCEPTED or when
        max_rounds is reached with finalize_on_max_rounds=True.
        """

    # ------------------------------------------------------------------
    # Optional overrides — defaults provided
    # ------------------------------------------------------------------

    def escalate(self, ctx: CriticActorContext) -> CriticActorResult:
        """Route to human-in-the-loop.  Override for domain HIL logic."""
        return CriticActorResult(
            disposition  = CriticActorDisposition.ESCALATE,
            output       = {"reason": "escalated_for_human_review"},
            steps        = ctx.steps,
            rounds       = ctx.round,
            final_score  = self._last_score(ctx),
        )

    def fail(self, ctx: CriticActorContext) -> CriticActorResult:
        """Return a definitive failure.  Override for domain failure output."""
        return CriticActorResult(
            disposition  = CriticActorDisposition.FAIL,
            output       = {"reason": "critic_rejected_all_drafts"},
            steps        = ctx.steps,
            rounds       = ctx.round,
            final_score  = 0.0,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _emit(self, event_type: str, data: Dict[str, Any]) -> None:
        event = {"type": event_type, "agent": self.layer, **data}
        if hasattr(self, "publish_event"):
            self.publish_event(event)
        else:
            self.logger.info("[%s] event: %s", self.layer, event)

    def _extract_score(self, feedback: Any) -> float:
        if isinstance(feedback, dict):
            try:
                return min(1.0, max(0.0, float(feedback.get("score", 0.0))))
            except (TypeError, ValueError):
                return 0.0
        return 0.0

    def _last_score(self, ctx: CriticActorContext) -> float:
        return ctx.steps[-1].score if ctx.steps else 0.0

    @staticmethod
    def _parse_bool(value: Any, default: bool) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            return bool(value)
        if isinstance(value, str):
            return value.strip().lower() in ("true", "1", "yes", "on")
        return default

    def _to_dict(self, result: CriticActorResult) -> Dict[str, Any]:
        return {
            "agent":       self.layer,
            "disposition": result.disposition.value,
            "output":      result.output,
            "rounds":      result.rounds,
            "final_score": result.final_score,
            "critique_log": result.critique_log,
            "steps": [
                {
                    "round":       s.round,
                    "disposition": s.disposition.value,
                    "score":       s.score,
                    "issues":      s.feedback.get("issues", []),
                    # draft and full feedback intentionally excluded —
                    # may contain sensitive content; add in finalize() if needed
                }
                for s in result.steps
            ],
        }
