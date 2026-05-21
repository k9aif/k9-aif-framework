# SPDX-License-Identifier: Apache-2.0
# K9-AIF EOC — test_eoc_router.py
#
# Validates:
# - EOCRouter imports correctly
# - Deterministic routing table is complete and correct
# - route() publishes to correct Kafka topic (mocked)
# - route() returns False for unknown event types
# - Router does NOT directly invoke orchestrators

from unittest.mock import MagicMock, patch
import pytest

from examples.K9X_Enterprise_Insurance_OperationsCenter.router.eoc_router import (
    EOCRouter,
    _ROUTING_TABLE,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_bus():
    bus = MagicMock()
    bus.publish = MagicMock()
    return bus


@pytest.fixture
def router(mock_bus):
    """EOCRouter with all K9EventBus instances replaced by mocks."""
    with patch(
        "examples.K9X_Enterprise_Insurance_OperationsCenter.router.eoc_router.K9EventBus",
        return_value=mock_bus,
    ):
        r = EOCRouter(config={"messaging": {"brokers": ["localhost:9092"]}})
    return r


# ---------------------------------------------------------------------------
# Routing table completeness
# ---------------------------------------------------------------------------

EXPECTED_ROUTES = {
    "claim_submitted":             "eoc-claims",
    "document_received":           "eoc-documents",
    "fraud_signal_raised":         "eoc-fraud",
    "policy_change_requested":     "eoc-policy",
    "catastrophe_alert_issued":    "eoc-catastrophe",
    "customer_interaction_logged": "eoc-customer",
    "audit_query_received":        "eoc-audit",
}

def test_routing_table_is_complete():
    assert set(_ROUTING_TABLE.keys()) == set(EXPECTED_ROUTES.keys())


@pytest.mark.parametrize("event_type,expected_topic", EXPECTED_ROUTES.items())
def test_routing_table_maps_correctly(event_type, expected_topic):
    assert _ROUTING_TABLE[event_type] == expected_topic


# ---------------------------------------------------------------------------
# EOCRouter import and construction
# ---------------------------------------------------------------------------

def test_router_imports():
    assert EOCRouter is not None


def test_router_instantiates_with_empty_config():
    with patch("examples.K9X_Enterprise_Insurance_OperationsCenter.router.eoc_router.K9EventBus"):
        r = EOCRouter(config={})
    assert r is not None


def test_router_supported_event_types_returns_all():
    with patch("examples.K9X_Enterprise_Insurance_OperationsCenter.router.eoc_router.K9EventBus"):
        r = EOCRouter(config={})
    types = r.supported_event_types()
    assert set(types) == set(EXPECTED_ROUTES.keys())


# ---------------------------------------------------------------------------
# route() publishes to correct topic, does NOT call orchestrators
# ---------------------------------------------------------------------------

def test_route_returns_true_for_known_event(router, mock_bus):
    payload = {"event_id": "e1", "correlation_id": "c1", "claim_id": "CLM-001"}
    result = router.route("claim_submitted", payload)
    assert result is True


def test_route_calls_publish_once(router, mock_bus):
    payload = {"event_id": "e1", "correlation_id": "c1"}
    router.route("claim_submitted", payload)
    mock_bus.publish.assert_called_once()


def test_route_publishes_event_type_in_payload(router, mock_bus):
    payload = {"event_id": "e2", "correlation_id": "c2"}
    router.route("fraud_signal_raised", payload)
    published = mock_bus.publish.call_args[0][0]
    assert published["event_type"] == "fraud_signal_raised"


def test_route_is_case_insensitive(router, mock_bus):
    payload = {"event_id": "e3", "correlation_id": "c3"}
    result = router.route("CLAIM_SUBMITTED", payload)
    assert result is True
    mock_bus.publish.assert_called_once()


def test_route_returns_false_for_unknown_event(router, mock_bus):
    result = router.route("unknown_event_xyz", {"event_id": "e4"})
    assert result is False
    mock_bus.publish.assert_not_called()


def test_route_does_not_import_or_call_orchestrators(router, mock_bus):
    # Router module must not import any orchestrator class directly
    import importlib
    router_module = importlib.import_module(
        "examples.K9X_Enterprise_Insurance_OperationsCenter.router.eoc_router"
    )
    source = open(router_module.__file__).read()
    assert "ClaimsProcessingOrchestrator" not in source
    assert "handle_event" not in source
    assert "execute_flow" not in source


# ---------------------------------------------------------------------------
# All 7 event types route correctly
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("event_type", EXPECTED_ROUTES.keys())
def test_all_event_types_route_successfully(event_type, mock_bus):
    with patch(
        "examples.K9X_Enterprise_Insurance_OperationsCenter.router.eoc_router.K9EventBus",
        return_value=mock_bus,
    ):
        r = EOCRouter(config={"messaging": {"brokers": ["localhost:9092"]}})
    payload = {"event_id": "smoke", "correlation_id": "smoke-corr"}
    result = r.route(event_type, payload)
    assert result is True
    mock_bus.publish.assert_called()
