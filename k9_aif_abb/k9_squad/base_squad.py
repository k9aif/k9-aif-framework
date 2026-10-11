# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

import json
import logging
import time

log = logging.getLogger(__name__)


def _resolve_path(key: str, ctx: dict):
    """Dot-notation traversal into ctx. Returns None if any segment is missing."""
    val = ctx
    for part in key.split("."):
        if not isinstance(val, dict):
            return None
        val = val.get(part)
    return val


def _eval_when(when_cfg, ctx: dict) -> bool:
    """
    Evaluate a ``when:`` condition block against the accumulated step context.

    Returns True (step should run) if:
    - ``when_cfg`` is None (unconditional)
    - ``when.any`` list: at least one sub-condition is true (OR)
    - ``when.all`` list: every sub-condition is true (AND)
    - single condition with ``key`` + operator (eq/ne/lt/lte/gt/gte)
    """
    if when_cfg is None:
        return True
    if isinstance(when_cfg, list):
        return any(_eval_when(c, ctx) for c in when_cfg)
    if not isinstance(when_cfg, dict):
        return bool(when_cfg)
    if "any" in when_cfg:
        return any(_eval_when(c, ctx) for c in when_cfg["any"])
    if "all" in when_cfg:
        return all(_eval_when(c, ctx) for c in when_cfg["all"])
    key = when_cfg.get("key")
    val = _resolve_path(key, ctx) if key else None
    if "eq"  in when_cfg: return val == when_cfg["eq"]
    if "ne"  in when_cfg: return val != when_cfg["ne"]
    if "lt"  in when_cfg: return val is not None and val <  when_cfg["lt"]
    if "lte" in when_cfg: return val is not None and val <= when_cfg["lte"]
    if "gt"  in when_cfg: return val is not None and val >  when_cfg["gt"]
    if "gte" in when_cfg: return val is not None and val >= when_cfg["gte"]
    return True


SYNTHESIS_MODES = ("off", "auto", "always")
DEFAULT_SYNTHESIS_MAX_CHARS = 24000   # about 6k tokens of upstream results


def synthesis_config(metadata) -> dict:
    """Normalize a squad's ``synthesis:`` setting.

    ``synthesis: auto`` or ``synthesis: {mode: auto, max_context_chars: 24000,
    agent: MySynthesizer}``. Missing or ``off`` means no synthesis (pre-1.16
    behaviour)."""
    cfg = (metadata or {}).get("synthesis") if isinstance(metadata, dict) else None
    if cfg is None or cfg is False:
        cfg = {"mode": "off"}
    elif cfg is True:
        cfg = {"mode": "auto"}
    elif isinstance(cfg, str):
        cfg = {"mode": cfg}
    cfg = dict(cfg)
    mode = str(cfg.get("mode", "off")).lower()
    if mode not in SYNTHESIS_MODES:
        raise ValueError(f"synthesis.mode must be one of {SYNTHESIS_MODES}, got {mode!r}")
    cfg["mode"] = mode
    cfg["max_context_chars"] = int(cfg.get("max_context_chars", DEFAULT_SYNTHESIS_MAX_CHARS))
    return cfg


class BaseSquad:
    """
    ABB: Represents a coordinated team of agents
    working together for a capability or use case.

    Agent coordination is driven by the ``flow`` config loaded from squads.yaml.
    Each step specifies which agent to call, what key to store its result under,
    and any static context overrides to merge before the call.
    """

    def __init__(self, squad_id, agents, orchestrator=None, monitor=None):
        self.squad_id = squad_id
        self.agents = agents or []
        self.monitor = monitor
        self.description = ""
        self.flow = []
        self.metadata = {}
        self.synthesizer = None   # set by SquadLoader, or created on first use

    def execute(self, payload: dict) -> dict:
        """
        Drive the agent pipeline from flow config in squads.yaml.

        Context scoping:
        - ``context_keys`` on a flow step limits which keys the agent sees.
          The original payload keys are always included; ``context_keys``
          controls which *upstream result keys* are passed through.
        - When ``context_keys`` is absent the agent receives the full
          accumulated context (backwards compatible).

        Squad coordinator (1.16): with ``synthesis: auto`` the upstream
        results a step would receive are replaced by a digest
        (``squad_digest``) once they exceed ``max_context_chars``;
        ``synthesis: always`` does so whenever there are upstream results.
        Steps with ``context_keys`` (explicit scoping) or ``synthesis: false``
        are never synthesized. The squad's results keep every full output,
        and ``squad_synthesis`` records each digest made (step, source keys,
        sizes) for audit.

        Steps with a ``when:`` field are skipped if the condition evaluates
        to False against the current context.
        """
        if not self.flow:
            raise RuntimeError(
                f"[{self.squad_id}] No flow defined — add a 'flow:' section to squads.yaml"
            )

        # Validate flow step structure before executing anything
        for i, step in enumerate(self.flow):
            if not isinstance(step, dict) or "agent" not in step:
                raise ValueError(
                    f"[{self.squad_id}] flow step {i} is missing required field 'agent': {step!r}"
                )

        agent_map = {a.__class__.__name__: a for a in self.agents}
        # Only check agents for unconditional steps (conditional ones may legitimately be absent)
        unconditional = [s["agent"] for s in self.flow if s.get("when") is None]
        missing = [name for name in unconditional if name not in agent_map]
        if missing:
            raise RuntimeError(
                f"[{self.squad_id}] Required agents not loaded: {missing}"
            )

        if self.monitor:
            self.monitor.on_squad_start(self.squad_id)

        context = {**payload, "squad_id": self.squad_id}
        results = {}
        synthesis = synthesis_config(self.metadata)
        synthesis_log = []
        digest_cache = {}

        for step_idx, step in enumerate(self.flow):
            agent_name = step["agent"]
            result_key = step.get("result_key", agent_name)
            when_cfg   = step.get("when")

            if not _eval_when(when_cfg, context):
                log.debug("[%s] step %d agent=%s skipped (when: condition false)",
                          self.squad_id, step_idx + 1, agent_name)
                continue

            if agent_name not in agent_map:
                raise RuntimeError(
                    f"[{self.squad_id}] Agent '{agent_name}' required by step {step_idx + 1} "
                    f"is not loaded"
                )

            context_keys = step.get("context_keys")
            if context_keys is not None:
                step_context = {
                    k: v for k, v in context.items()
                    if k in context_keys or k in payload or k == "squad_id"
                }
            else:
                step_context = {**context}
            if context_keys is None and step.get("synthesis", True) is not False:
                step_context = self._apply_synthesis(
                    step_idx, agent_name, step_context, results, synthesis,
                    digest_cache, synthesis_log)
            step_context.update(step.get("context", {}))
            log.info("[%s] step %d executing agent=%s", self.squad_id, step_idx + 1, agent_name)
            t0 = time.monotonic()
            try:
                result = agent_map[agent_name].execute(step_context)
            except Exception:
                elapsed_ms = int((time.monotonic() - t0) * 1000)
                log.exception("[%s] step %d agent=%s FAILED elapsed_ms=%d",
                              self.squad_id, step_idx + 1, agent_name, elapsed_ms)
                raise
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            log.info("[%s] step %d agent=%s done elapsed_ms=%d",
                     self.squad_id, step_idx + 1, agent_name, elapsed_ms)
            context[result_key] = result
            results[result_key] = result

        if self.monitor:
            self.monitor.on_squad_end(self.squad_id)

        out = {"status": "completed", "squad_id": self.squad_id, **results}
        if synthesis_log:
            out["squad_synthesis"] = synthesis_log
        return out

    # ------------------------------------------------------------------
    def _apply_synthesis(self, step_idx, agent_name, step_context, results,
                         synthesis, digest_cache, synthesis_log):
        """Replace upstream results in ``step_context`` by a digest when the
        squad's synthesis setting calls for it; otherwise return it unchanged."""
        mode = synthesis["mode"]
        upstream = {k: v for k, v in step_context.items() if k in results}
        if mode == "off" or not upstream:
            return step_context
        size = len(json.dumps(upstream, default=str, ensure_ascii=False))
        if mode == "auto" and size <= synthesis["max_context_chars"]:
            return step_context
        keys = tuple(upstream)
        if keys not in digest_cache:
            synthesizer = self._get_synthesizer(synthesis)
            res = synthesizer.execute({"results": upstream, "task": self.description})
            digest_cache[keys] = (res or {}).get("output", "") if isinstance(res, dict) else str(res)
        digest = digest_cache[keys]
        synthesis_log.append({"step": step_idx + 1, "agent": agent_name,
                              "source_keys": list(keys), "chars_in": size,
                              "chars_out": len(digest)})
        log.info("[%s] step %d agent=%s gets a digest of %s (%d -> %d chars)",
                 self.squad_id, step_idx + 1, agent_name, list(keys), size, len(digest))
        scoped = {k: v for k, v in step_context.items() if k not in results}
        scoped["squad_digest"] = digest
        scoped["squad_digest_keys"] = list(keys)
        return scoped

    def _get_synthesizer(self, synthesis):
        if self.synthesizer is None:
            from k9_aif_abb.k9_agents.synthesis import K9ContextSynthesizerAgent
            config = getattr(self.agents[0], "config", {}) if self.agents else {}
            self.synthesizer = K9ContextSynthesizerAgent(config=config)
        return self.synthesizer

    def run(self, payload):
        """Delegates to execute() — kept for backwards compatibility."""
        return self.execute(payload)