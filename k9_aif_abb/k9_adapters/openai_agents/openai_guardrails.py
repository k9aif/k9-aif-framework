# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

"""
The OpenAI Agents SDK's own agent guardrails, under K9-AIF (1.35.0).

An agent YAML may attach the developer's own SDK guardrails (``@input_guardrail`` /
``@output_guardrail`` functions, or plain functions with the SDK's guardrail signature)::

    input_guardrails:
      - {function: churn_detection_tripwire, module: support.guardrails, on_trip: hil, hil_queue: retention}
    output_guardrails:
      - {function: no_refund_promises, module: support.guardrails}

The SDK runs them exactly as it always does; K9-AIF's own checks (Zero Trust, k9x Shield, Guardian,
the tool guardrails) still run beside them. They add to each other; neither replaces the other.

A tripwire is mapped into K9-AIF:

- ``on_trip: block`` (default): ``PermissionError``, the same signal as a k9x Shield block. The
  orchestrator records it.
- ``on_trip: hil`` (input guardrails only): ``RequiresHIL``. The orchestrator opens a K9X HIL case
  (``hil_queue``, else the agent's ``hil_queue``). When the person approves, the run starts again
  without that guardrail; when they don't, the run ends with ``PermissionError``. Output guardrails
  can only block: the run that produced the output can't be resumed, and a rerun would write a
  different answer from the one the person saw.

A guardrail that runs an agent of its own (the guide's churn check does) passes the run's config on:
``Runner.run(check_agent, input, run_config=current_run_config())``. The check's model call is then routed by
the K9 Model Router, and its client lives on the run's event loop. Without it the check would call the SDK's
default provider (OpenAI), which no one governs.

SDK semantics apply: input guardrails run for a run's first agent, output guardrails for the agent
that writes the final output. A ``K9OpenAIAgent`` squad step is a run of its own, so its guardrails
run on every step.
"""

from __future__ import annotations

import importlib
import inspect
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from agents import (
    InputGuardrail,
    InputGuardrailTripwireTriggered,
    OutputGuardrail,
    OutputGuardrailTripwireTriggered,
)

from k9_aif_abb.k9_core.orchestration.base_hil_adapter import HILDecision
from k9_aif_abb.k9_core.orchestration.hil_signal import RequiresHIL
from k9_aif_abb.k9_utils.trace_events import emit_trace_event

from .k9_model_provider import current_run_config  # noqa: F401  (for guardrails that run an agent of their own)

_ON_TRIP = ("block", "hil")
RESUME_KEY = "guardrail"


@dataclass(frozen=True)
class GuardrailPolicy:
    name: str
    kind: str              # "input" | "output"
    on_trip: str           # "block" | "hil"
    hil_queue: Optional[str]


def _load_one(entry: Any, kind: str, owner: str):
    if not isinstance(entry, dict) or not entry.get("function") or not entry.get("module"):
        raise ValueError(f"[{owner}] each {kind}_guardrails entry needs 'function' and 'module', got {entry!r}")
    on_trip = str(entry.get("on_trip") or "block")
    if on_trip not in _ON_TRIP:
        raise ValueError(f"[{owner}] {kind} guardrail {entry['function']}: on_trip must be one of {_ON_TRIP}, "
                         f"got {on_trip!r}")
    if on_trip == "hil" and kind == "output":
        raise ValueError(f"[{owner}] output guardrail {entry['function']}: on_trip: hil is for input guardrails. "
                         "An output can't be resumed after review (a rerun writes a different answer); use block.")
    module = importlib.import_module(str(entry["module"]))
    obj = getattr(module, str(entry["function"]), None)
    if obj is None:
        raise ImportError(f"[{owner}] {entry['module']} has no {entry['function']}")
    wanted, other = (InputGuardrail, OutputGuardrail) if kind == "input" else (OutputGuardrail, InputGuardrail)
    if isinstance(obj, other):
        raise ValueError(f"[{owner}] {entry['function']} is an {'output' if kind == 'input' else 'input'} guardrail, "
                         f"listed under {kind}_guardrails")
    if isinstance(obj, wanted):
        guardrail = obj
    elif callable(obj) and not inspect.isclass(obj):
        guardrail = wanted(guardrail_function=obj, name=getattr(obj, "__name__", None))
    else:
        raise ValueError(f"[{owner}] {entry['module']}.{entry['function']} is not a guardrail function")
    policy = GuardrailPolicy(name=guardrail.get_name(), kind=kind, on_trip=on_trip,
                             hil_queue=entry.get("hil_queue"))
    return guardrail, policy


def load_guardrails(spec: Dict[str, Any], owner: str) -> Tuple[List[Any], List[Any], Dict[str, GuardrailPolicy]]:
    """The agent's SDK input and output guardrails from its YAML, and each one's K9 policy by name."""
    inputs, outputs, policies = [], [], {}
    for kind, bucket in (("input", inputs), ("output", outputs)):
        for entry in spec.get(f"{kind}_guardrails") or []:
            guardrail, policy = _load_one(entry, kind, owner)
            if policy.name in policies:
                raise ValueError(f"[{owner}] guardrail name {policy.name!r} is used twice")
            bucket.append(guardrail)
            policies[policy.name] = policy
    return inputs, outputs, policies


def _reason(output_info: Any) -> str:
    for key in ("reasoning", "reason", "message"):
        value = output_info.get(key) if isinstance(output_info, dict) else getattr(output_info, key, None)
        if value:
            return str(value)
    return ""


def _info(output_info: Any) -> Any:
    if hasattr(output_info, "model_dump"):
        return output_info.model_dump()
    if isinstance(output_info, (dict, list, str, int, float, bool)) or output_info is None:
        return output_info
    return repr(output_info)


def map_tripwire(exc: BaseException, policies: Dict[str, GuardrailPolicy], owner: str,
                 default_queue: Optional[str] = None) -> BaseException:
    """The K9-AIF signal for an SDK guardrail tripwire: ``PermissionError`` or ``RequiresHIL``."""
    result = exc.guardrail_result
    name = result.guardrail.get_name()
    kind = "input" if isinstance(exc, InputGuardrailTripwireTriggered) else "output"
    policy = policies.get(name) or GuardrailPolicy(name, kind, "block", None)
    output_info = getattr(result.output, "output_info", None)
    reason = _reason(output_info)
    emit_trace_event({"type": "OpenAIGuardrailTripped", "agent": owner, "guardrail": name, "kind": kind,
                      "on_trip": policy.on_trip})
    if policy.on_trip == "hil":
        return RequiresHIL(
            f"{owner}: guardrail {name} needs a person" + (f": {reason}" if reason else ""),
            context={"agent": owner, "guardrail": name, "output_info": _info(output_info)},
            queue=policy.hil_queue or default_queue, task_type="guardrail-review",
            resume_state={RESUME_KEY: {owner: name}})
    return PermissionError(f"[{owner}] {kind} guardrail {name} tripped" + (f": {reason}" if reason else ""))


def is_tripwire(exc: BaseException) -> bool:
    return isinstance(exc, (InputGuardrailTripwireTriggered, OutputGuardrailTripwireTriggered))


def cleared_on_resume(payload: Dict[str, Any], owner: str) -> Optional[str]:
    """When ``payload`` resumes this owner's guardrail review: the guardrail the person cleared (run again
    without it), or ``PermissionError`` if they didn't approve. None when it isn't such a resume."""
    payload = payload or {}
    if "hil_decision" not in payload:
        return None
    name = ((payload.get("_k9_resume") or {}).get(RESUME_KEY) or {}).get(owner)
    if not name:
        return None
    decision = HILDecision.from_reply(payload.get("hil_decision") or {})
    if not decision.approved:
        raise PermissionError(f"[{owner}] guardrail {name}: the review {decision.rejection_message()}")
    return name


def without(agent: Any, guardrail_name: str) -> Any:
    """A copy of ``agent`` without one input guardrail (the one a person cleared)."""
    return agent.clone(input_guardrails=[g for g in agent.input_guardrails if g.get_name() != guardrail_name])
