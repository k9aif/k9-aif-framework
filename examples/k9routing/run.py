# SPDX-License-Identifier: Apache-2.0
"""
K9-AIF Intent Routing Demo
==========================
Demonstrates deterministic + non-deterministic routing OOB and SBB overrides.
Runs entirely in-memory — no Kafka or LLM required.

Scenarios
---------
1. Deterministic routing    — event_type in routing table → direct topic publish
2. Non-deterministic (OOB)  — event_type unknown → intent.in → K9IntentAgent
                              resolves via intent_map (no LLM) → domain topic
3. Clarification (OOB)      — intent cannot be determined → responses.out
4. SBB override — ConfigListIntentAgent  (keyword matching, no LLM)
5. SBB override — AcmeIntentOrchestrator (custom execute_flow + message)

Routing table used
------------------
Router table (event_type → topic):
  claims_submitted → claims.in      [deterministic — Router resolves directly]

IntentOrchestrator table (intent → topic):
  fraud     → fraud.in
  claims    → claims.in
  document  → documents.in

intent_map in K9IntentAgent (event_type → intent, no LLM):
  fraud_report  → fraud
  claim_form    → claims
  doc_uploaded  → document
"""

import os
import sys
import yaml

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from k9_aif_abb.k9_core.router.k9_event_router import K9EventRouter
from k9_aif_abb.k9_orchestrators.intent_orchestrator import IntentOrchestrator
from k9_aif_abb.k9_squad.intent_squad import IntentSquad

from examples.k9routing.sbb.config_list_intent_agent import ConfigListIntentAgent
from examples.k9routing.sbb.acme_intent_orchestrator import AcmeIntentOrchestrator

_THIS_DIR = os.path.dirname(__file__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_config() -> dict:
    with open(os.path.join(_THIS_DIR, "config.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f)


class MockBus:
    """In-memory bus that captures (topic, payload) pairs — no Kafka needed."""

    def __init__(self):
        self._events: list = []

    def publish(self, event: dict):
        """Audit/status events (always go to k9aif-events)."""
        self._events.append(("k9aif-events", event))

    def publish_to(self, topic: str, event: dict):
        """Domain routing events (go to the specific topic)."""
        self._events.append((topic, event))

    def last_domain(self):
        """Return last event published to a domain topic (not k9aif-events)."""
        for topic, event in reversed(self._events):
            if topic != "k9aif-events":
                return topic, event
        return None, None

    def clear(self):
        self._events.clear()


def _header(title: str):
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print('─' * 60)


def _result(label: str, value):
    print(f"  {label:<22} {value}")


# ---------------------------------------------------------------------------
# Scenario 1 — Deterministic routing
# ---------------------------------------------------------------------------
def scenario_1_deterministic(cfg: dict, bus: MockBus):
    _header("Scenario 1 — Deterministic routing (event_type known)")
    bus.clear()

    router = K9EventRouter(config=cfg, message_bus=bus)
    payload = {"event_type": "claims_submitted", "claim_id": "CLM-001", "amount": 15000}
    result = router.route(payload)

    topic, _ = bus.last_domain()
    _result("event_type:", payload["event_type"])
    _result("strategy:", result["strategy"])
    _result("published to:", topic)
    assert result["strategy"] == "deterministic", f"Expected deterministic, got {result['strategy']}"
    assert topic == "claims.in", f"Expected claims.in, got {topic}"
    print("  ✓ PASS")


# ---------------------------------------------------------------------------
# Scenario 2 — Non-deterministic, intent resolved via intent_map (no LLM)
# ---------------------------------------------------------------------------
def scenario_2_intent_resolved(cfg: dict, bus: MockBus):
    _header("Scenario 2 — Non-deterministic: intent resolved via intent_map (no LLM)")

    # Step A: Router receives event_type="fraud_report" — not in routing table,
    # so it publishes to intent.in for IntentOrchestrator to handle.
    bus.clear()
    router = K9EventRouter(config=cfg, message_bus=bus)
    payload = {"event_type": "fraud_report", "account_id": "ACC-007", "message": "Unauthorized transaction"}
    route_result = router.route(payload)
    router_topic, _ = bus.last_domain()

    _result("event_type:", payload["event_type"])
    _result("router strategy:", route_result["strategy"])
    _result("router published to:", router_topic)
    assert route_result["strategy"] == "intent_required"
    assert router_topic == "intent.in"

    # Step B: IntentOrchestrator picks up from intent.in.
    # K9IntentAgent resolves intent via intent_map: "fraud_report" → "fraud"
    # No LLM call needed.
    orch_cfg = {
        **cfg,
        "routing": {
            **cfg["routing"],
            "intent_map": {
                "fraud_report": "fraud",
                "claim_form":   "claims",
                "doc_uploaded": "document",
            },
            "table": {
                "fraud":    "fraud.in",
                "claims":   "claims.in",
                "document": "documents.in",
            },
        },
    }
    bus.clear()
    orch = IntentOrchestrator(config=orch_cfg, message_bus=bus)
    orch_result = orch.execute_flow(payload)
    orch_topic, _ = bus.last_domain()

    _result("intent resolved:", orch_result.get("intent"))
    _result("confidence:", orch_result.get("confidence"))
    _result("orchestrator published to:", orch_topic)
    assert orch_result["status"] == "routed", f"Expected routed, got {orch_result}"
    assert orch_result["intent"] == "fraud"
    assert orch_topic == "fraud.in"
    print("  ✓ PASS")


# ---------------------------------------------------------------------------
# Scenario 3 — Intent unclear → clarification
# ---------------------------------------------------------------------------
def scenario_3_clarification(cfg: dict, bus: MockBus):
    _header("Scenario 3 — Intent unclear → clarification response")
    bus.clear()

    # Use a squad whose agent always returns "unknown" — no LLM needed.
    from k9_aif_abb.k9_agents.intent.k9_intent_agent import K9IntentAgent

    class AlwaysUnknownAgent(K9IntentAgent):
        def classify(self, payload):
            return "unknown"

    agent = AlwaysUnknownAgent(config=cfg)
    squad = IntentSquad(squad_id="TestSquad", agents=[agent])
    orch = IntentOrchestrator(config=cfg, squad=squad, message_bus=bus)

    payload = {"event_type": "other", "message": "..."}
    result = orch.execute_flow(payload)
    topic, event = bus.last_domain()

    _result("intent detected:", result.get("intent"))
    _result("status:", result.get("status"))
    _result("published to:", topic)
    _result("message:", (event or {}).get("message", "")[:60])
    assert result["status"] == "clarification_required"
    assert topic == "responses.out"
    print("  ✓ PASS")


# ---------------------------------------------------------------------------
# Scenario 4 — SBB override: ConfigListIntentAgent (keyword matching, no LLM)
# ---------------------------------------------------------------------------
def scenario_4_sbb_agent(cfg: dict, bus: MockBus):
    _header("Scenario 4 — SBB override: ConfigListIntentAgent (keyword matching)")

    sbb_cfg = {
        **cfg,
        "routing": {
            **cfg["routing"],
            "table": {
                "fraud":    "fraud.in",
                "claims":   "claims.in",
                "document": "documents.in",
            },
            "intent_keywords": {
                "fraud":    ["fraud", "scam", "suspicious", "unauthorized"],
                "claims":   ["claim", "accident", "damage", "repair"],
                "document": ["upload", "document", "attach", "file"],
            },
        },
    }

    agent = ConfigListIntentAgent(config=sbb_cfg)
    squad = IntentSquad(squad_id="SBBSquad", agents=[agent])
    orch = IntentOrchestrator(config=sbb_cfg, squad=squad, message_bus=bus)

    cases = [
        ("Please attach the file to my case", "document", "documents.in"),
        ("There is a suspicious charge on my account", "fraud", "fraud.in"),
        ("I need to file a claim for the damage", "claims", "claims.in"),
    ]

    for message, expected_intent, expected_topic in cases:
        bus.clear()
        payload = {"event_type": "other", "message": message}
        result = orch.execute_flow(payload)
        topic, _ = bus.last_domain()
        status = "✓" if result.get("intent") == expected_intent else "✗"
        print(f"  {status}  '{message[:46]}' → intent={result.get('intent')} topic={topic}")
        assert result.get("intent") == expected_intent
        assert topic == expected_topic

    print("  ✓ PASS")


# ---------------------------------------------------------------------------
# Scenario 5 — SBB override: AcmeIntentOrchestrator (custom execute_flow)
# ---------------------------------------------------------------------------
def scenario_5_sbb_orchestrator(cfg: dict, bus: MockBus):
    _header("Scenario 5 — SBB override: AcmeIntentOrchestrator (custom execute_flow + message)")

    sbb_cfg = {
        **cfg,
        "routing": {
            **cfg["routing"],
            "table": {
                "fraud":  "fraud.in",
                "claims": "claims.in",
            },
            "intent_keywords": {
                "fraud":  ["fraud", "scam"],
                "claims": ["claim", "accident"],
            },
        },
    }

    agent = ConfigListIntentAgent(config=sbb_cfg)
    squad = IntentSquad(squad_id="AcmeSquad", agents=[agent])
    orch = AcmeIntentOrchestrator(config=sbb_cfg, squad=squad, message_bus=bus)

    # Known intent — routes after normalising message casing
    bus.clear()
    payload = {"event_type": "other", "message": "  REPORT A FRAUD PLEASE  "}
    result = orch.execute_flow(payload)
    topic, _ = bus.last_domain()
    _result("message (raw):", payload["message"])
    _result("intent routed:", result.get("intent"))
    _result("published to:", topic)
    assert result["status"] == "routed"
    assert result["intent"] == "fraud"
    assert topic == "fraud.in"

    # Unknown intent — branded clarification message
    bus.clear()
    payload2 = {"event_type": "other", "message": "hello"}
    result2 = orch.execute_flow(payload2)
    _, event2 = bus.last_domain()
    _result("clarification:", (event2 or {}).get("message", "")[:70])
    assert "Acme Insurance" in (event2 or {}).get("message", "")
    print("  ✓ PASS")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    cfg = load_config()
    bus = MockBus()

    scenario_1_deterministic(cfg, bus)
    scenario_2_intent_resolved(cfg, bus)
    scenario_3_clarification(cfg, bus)
    scenario_4_sbb_agent(cfg, bus)
    scenario_5_sbb_orchestrator(cfg, bus)

    print(f"\n{'─' * 60}")
    print("  All scenarios passed.")
    print('─' * 60)
