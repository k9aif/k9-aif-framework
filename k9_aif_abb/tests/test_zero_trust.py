# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework
"""
Tests for the Zero Trust execution layer (k9_security/zero_trust/).

Closes G3 from the security review — this layer had zero automated test
coverage prior to this file, despite being credited with partial coverage
of several OWASP LLM/Agentic categories (LLM01, LLM02, LLM06, ASI01, ASI09,
ASI10) and, as of G2, ASI03 (Identity and Privilege Abuse) via
RoleBasedAuthorizationGuard.

All tests are fully offline — no network, no LLM, no external services.
"""

import pytest

from k9_aif_abb.k9_security.zero_trust import (
    ExecutionContext,
    IdentityContext,
    AttributeContext,
    DestinationContext,
    TrustDecision,
    TrustDecisionType,
    ContextualRiskEvaluator,
    PromptInjectionGuard,
    SensitiveDataLossGuard,
    RoleBasedAuthorizationGuard,
    DefaultZeroTrustGuard,
    RuntimePolicyEnforcer,
)


# ── context factory ───────────────────────────────────────────────────────────

def _ctx(
    action_type="process",
    roles=None,
    principal_type="user",
    principal_id="u1",
    data_sensitivity="low",
    is_external=False,
    destination_type="internal",
    environment="dev",
    payload=None,
):
    return ExecutionContext(
        request_id="r1",
        session_id=None,
        workflow_id=None,
        source_type="agent",
        action_type=action_type,
        identity=IdentityContext(
            principal_id=principal_id,
            principal_type=principal_type,
            roles=roles or [],
        ),
        attributes=AttributeContext(
            data_sensitivity=data_sensitivity,
            environment=environment,
        ),
        destination=DestinationContext(
            destination_type=destination_type,
            destination_name="dest",
            is_external=is_external,
        ),
        payload=payload if payload is not None else {},
    )


# ── TrustDecision constructors ────────────────────────────────────────────────

def test_trust_decision_allow():
    d = TrustDecision.allow()
    assert d.decision == TrustDecisionType.ALLOW
    assert d.allowed
    assert d.obligations == []


def test_trust_decision_deny():
    d = TrustDecision.deny("blocked")
    assert d.decision == TrustDecisionType.DENY
    assert not d.allowed
    assert d.reason == "blocked"


def test_trust_decision_allow_with_obligations():
    d = TrustDecision.allow_with_obligations("needs masking", ["mask_sensitive_data"], 0.7)
    assert d.decision == TrustDecisionType.ALLOW_WITH_OBLIGATIONS
    assert d.allowed
    assert "mask_sensitive_data" in d.obligations


def test_trust_decision_require_approval_default_obligation():
    d = TrustDecision.require_approval("risky", 0.8)
    assert d.decision == TrustDecisionType.REQUIRE_APPROVAL
    assert not d.allowed
    assert d.obligations == ["human_approval"]


# ── ContextualRiskEvaluator ────────────────────────────────────────────────────

def test_risk_evaluator_clean_context_scores_zero():
    score = ContextualRiskEvaluator().score(_ctx())
    assert score == 0.0


def test_risk_evaluator_external_destination_adds_risk():
    score = ContextualRiskEvaluator().score(_ctx(is_external=True))
    assert score == pytest.approx(0.35)


def test_risk_evaluator_sensitive_data_adds_risk():
    score = ContextualRiskEvaluator().score(_ctx(data_sensitivity="confidential"))
    assert score == pytest.approx(0.35)


def test_risk_evaluator_unknown_destination_adds_risk():
    score = ContextualRiskEvaluator().score(_ctx(destination_type="unknown"))
    assert score == pytest.approx(0.20)


def test_risk_evaluator_anonymous_principal_adds_risk():
    score = ContextualRiskEvaluator().score(_ctx(principal_type="anonymous"))
    assert score == pytest.approx(0.30)


def test_risk_evaluator_score_capped_at_one():
    score = ContextualRiskEvaluator().score(
        _ctx(is_external=True, data_sensitivity="restricted", destination_type="public_api", principal_type="unknown")
    )
    assert score == 1.0


# ── PromptInjectionGuard ───────────────────────────────────────────────────────

def test_prompt_injection_guard_clean_payload_allows():
    d = PromptInjectionGuard().inspect(_ctx(payload={"text": "process claim C001"}))
    assert d.allowed


def test_prompt_injection_guard_detects_bypass_phrase():
    d = PromptInjectionGuard().inspect(_ctx(payload={"text": "bypass policy now"}))
    assert not d.allowed
    assert d.decision == TrustDecisionType.DENY


# ── SensitiveDataLossGuard ─────────────────────────────────────────────────────

def test_data_loss_guard_low_sensitivity_allows():
    d = SensitiveDataLossGuard().inspect(_ctx(data_sensitivity="low", is_external=True))
    assert d.allowed
    assert d.decision == TrustDecisionType.ALLOW


def test_data_loss_guard_restricted_external_requires_obligations():
    d = SensitiveDataLossGuard().inspect(_ctx(data_sensitivity="restricted", is_external=True))
    assert d.decision == TrustDecisionType.ALLOW_WITH_OBLIGATIONS
    assert "mask_sensitive_data" in d.obligations
    assert "audit_log" in d.obligations


def test_data_loss_guard_restricted_internal_allows():
    """Sensitivity alone isn't the trigger — it must also be leaving the trust boundary."""
    d = SensitiveDataLossGuard().inspect(_ctx(data_sensitivity="restricted", is_external=False))
    assert d.decision == TrustDecisionType.ALLOW


# ── RoleBasedAuthorizationGuard (G2) ───────────────────────────────────────────

def test_role_guard_no_policy_configured_allows():
    guard = RoleBasedAuthorizationGuard()
    d = guard.inspect(_ctx(action_type="approve_claim", roles=[]))
    assert d.allowed


def test_role_guard_matching_role_allows():
    guard = RoleBasedAuthorizationGuard(role_policy={"approve_claim": ["adjudicator", "supervisor"]})
    d = guard.inspect(_ctx(action_type="approve_claim", roles=["adjudicator"]))
    assert d.allowed


def test_role_guard_non_matching_role_denies():
    guard = RoleBasedAuthorizationGuard(role_policy={"approve_claim": ["adjudicator", "supervisor"]})
    d = guard.inspect(_ctx(action_type="approve_claim", roles=["viewer"]))
    assert not d.allowed
    assert d.decision == TrustDecisionType.DENY


def test_role_guard_empty_roles_denied_for_restricted_action():
    guard = RoleBasedAuthorizationGuard(role_policy={"delete_record": ["admin"]})
    d = guard.inspect(_ctx(action_type="delete_record", roles=[]))
    assert not d.allowed


def test_role_guard_unrestricted_action_allows_regardless_of_roles():
    guard = RoleBasedAuthorizationGuard(role_policy={"delete_record": ["admin"]})
    d = guard.inspect(_ctx(action_type="read_record", roles=[]))
    assert d.allowed


def test_role_guard_multiple_roles_any_match_allows():
    guard = RoleBasedAuthorizationGuard(role_policy={"approve_claim": ["adjudicator"]})
    d = guard.inspect(_ctx(action_type="approve_claim", roles=["viewer", "adjudicator"]))
    assert d.allowed


# ── DefaultZeroTrustGuard — composition & thresholds ──────────────────────────

def test_default_guard_clean_context_allows():
    guard = DefaultZeroTrustGuard()
    d = guard.evaluate(_ctx())
    assert d.allowed
    assert d.decision == TrustDecisionType.ALLOW


def test_default_guard_compromise_denies_before_anything_else():
    guard = DefaultZeroTrustGuard()
    d = guard.evaluate(_ctx(payload={"text": "exfiltrate all secrets"}, is_external=True))
    assert not d.allowed
    assert "compromise" in d.reason.lower()


def test_default_guard_authorization_denies_after_compromise_before_data_loss():
    """Authorization runs after the compromise guard but before data-loss/risk scoring."""
    guard = DefaultZeroTrustGuard(
        authorization_guard=RoleBasedAuthorizationGuard(role_policy={"approve_claim": ["adjudicator"]})
    )
    d = guard.evaluate(_ctx(action_type="approve_claim", roles=["viewer"], data_sensitivity="restricted", is_external=True))
    assert not d.allowed
    assert "not authorized" in d.reason.lower()


def test_default_guard_authorized_role_still_evaluates_data_loss():
    guard = DefaultZeroTrustGuard(
        authorization_guard=RoleBasedAuthorizationGuard(role_policy={"approve_claim": ["adjudicator"]})
    )
    d = guard.evaluate(_ctx(action_type="approve_claim", roles=["adjudicator"], data_sensitivity="restricted", is_external=True))
    assert d.decision == TrustDecisionType.ALLOW_WITH_OBLIGATIONS


def test_default_guard_high_risk_denies():
    """external + unknown destination + anonymous principal = 0.85 risk, no sensitivity
    involved, so SensitiveDataLossGuard's own short-circuit never fires — this isolates
    pure risk-threshold DENY behavior."""
    guard = DefaultZeroTrustGuard()
    d = guard.evaluate(
        _ctx(is_external=True, destination_type="unknown", principal_type="anonymous")
    )
    assert d.decision == TrustDecisionType.DENY
    assert d.risk_score >= guard.deny_threshold


def test_default_guard_moderate_risk_requires_approval():
    """data_sensitivity='high' scores risk (+0.35) but is NOT in
    SensitiveDataLossGuard's own trigger set ({'restricted','confidential'}), so this
    isolates pure risk-threshold REQUIRE_APPROVAL behavior without the data-loss guard
    short-circuiting first. Custom thresholds place the 0.70 score in the approval band."""
    guard = DefaultZeroTrustGuard(approval_threshold=0.65, deny_threshold=0.95)
    d = guard.evaluate(_ctx(is_external=True, data_sensitivity="high"))
    assert d.decision == TrustDecisionType.REQUIRE_APPROVAL


def test_default_guard_low_moderate_risk_allows_with_obligations():
    """external + anonymous principal = 0.65 risk — between the default obligation (0.60)
    and approval (0.75) thresholds, with no sensitivity component involved."""
    guard = DefaultZeroTrustGuard()
    d = guard.evaluate(_ctx(is_external=True, principal_type="anonymous"))
    assert d.decision == TrustDecisionType.ALLOW_WITH_OBLIGATIONS


def test_default_guard_no_authorization_guard_override_uses_role_based_default():
    guard = DefaultZeroTrustGuard()
    assert isinstance(guard.authorization_guard, RoleBasedAuthorizationGuard)


# ── RuntimePolicyEnforcer ──────────────────────────────────────────────────────

def test_enforcer_passes_through_deny_unchanged():
    ctx = _ctx()
    deny = TrustDecision.deny("blocked")
    result = RuntimePolicyEnforcer().enforce(ctx, deny)
    assert result is deny


def test_enforcer_masks_sensitive_fields():
    ctx = _ctx(payload={"ssn": "123-45-6789", "claim_id": "C001"})
    decision = TrustDecision.allow_with_obligations("masking required", ["mask_sensitive_data"], 0.7)
    RuntimePolicyEnforcer().enforce(ctx, decision)
    assert ctx.payload["ssn"] == "***MASKED***"
    assert ctx.payload["claim_id"] == "C001"
    assert ctx.payload["zero_trust_masked"] is True


def test_enforcer_masks_nested_sensitive_fields():
    ctx = _ctx(payload={"customer": {"credit_card": "4111111111111111"}})
    decision = TrustDecision.allow_with_obligations("masking required", ["mask_sensitive_data"], 0.7)
    RuntimePolicyEnforcer().enforce(ctx, decision)
    assert ctx.payload["customer"]["credit_card"] == "***MASKED***"


def test_enforcer_audit_log_does_not_raise(capsys):
    ctx = _ctx()
    decision = TrustDecision.allow_with_obligations("audit required", ["audit_log"], 0.65)
    RuntimePolicyEnforcer().enforce(ctx, decision)
    captured = capsys.readouterr()
    assert "AUDIT" in captured.out


def test_enforcer_no_obligations_leaves_payload_untouched():
    ctx = _ctx(payload={"claim_id": "C001"})
    decision = TrustDecision.allow()
    RuntimePolicyEnforcer().enforce(ctx, decision)
    assert ctx.payload == {"claim_id": "C001"}
