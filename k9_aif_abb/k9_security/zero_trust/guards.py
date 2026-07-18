# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

from abc import ABC, abstractmethod

from .context import ExecutionContext
from .decisions import TrustDecision, TrustDecisionType
from .evaluators import BaseRiskEvaluator, ContextualRiskEvaluator


class BaseCompromiseGuard(ABC):
    @abstractmethod
    def inspect(self, context: ExecutionContext) -> TrustDecision:
        raise NotImplementedError


class BaseDataLossGuard(ABC):
    @abstractmethod
    def inspect(self, context: ExecutionContext) -> TrustDecision:
        raise NotImplementedError


class BaseZeroTrustGuard(ABC):
    @abstractmethod
    def evaluate(self, context: ExecutionContext) -> TrustDecision:
        raise NotImplementedError


class BaseAuthorizationGuard(ABC):
    """
    ABB — evaluates whether a principal's roles/attributes authorize the
    action_type an ExecutionContext is requesting.

    Distinct from BaseRiskEvaluator: authorization is a privilege/identity
    decision (is this principal allowed to do this at all), not a continuous
    risk score. IdentityContext.roles already flows into every
    ExecutionContext; this is the evaluator that actually reads it.
    """

    @abstractmethod
    def inspect(self, context: ExecutionContext) -> TrustDecision:
        raise NotImplementedError


class PromptInjectionGuard(BaseCompromiseGuard):
    def inspect(self, context: ExecutionContext) -> TrustDecision:
        text = str(context.payload).lower()

        suspicious_terms = [
            "ignore previous instructions",
            "bypass policy",
            "disable guardrails",
            "exfiltrate",
            "leak secrets",
            "dump credentials",
        ]

        if any(term in text for term in suspicious_terms):
            return TrustDecision.deny(
                reason="Potential prompt injection or compromise attempt detected",
                risk_score=1.0,
            )

        return TrustDecision.allow(reason="No compromise indicator detected")


class RoleBasedAuthorizationGuard(BaseAuthorizationGuard):
    """
    OOB SBB — denies an action_type unless the principal's roles intersect
    the allowed-roles set configured for it.

    No policy is shipped by default. An action_type with no entry in
    `role_policy` is ALLOWED (no restriction configured) rather than denied —
    Zero Trust is opt-in already (enable_zero_trust: true), and silently
    denying every unconfigured action would break every existing deployment
    the moment this guard is composed into DefaultZeroTrustGuard by default.
    Authorization is enforced only for action_types a solution has
    deliberately restricted.

    A principal with an empty roles list against a *restricted* action_type
    is denied — there is nothing to intersect against, so there is no basis
    to allow it.

    Config (role_policy):
        {
          "approve_claim": ["adjudicator", "supervisor"],
          "delete_record": ["admin"],
        }
    """

    def __init__(self, role_policy: dict[str, list[str]] | None = None) -> None:
        self._role_policy: dict[str, list[str]] = role_policy or {}

    def inspect(self, context: ExecutionContext) -> TrustDecision:
        allowed_roles = self._role_policy.get(context.action_type)
        if allowed_roles is None:
            return TrustDecision.allow(
                reason=f"No role policy configured for action_type={context.action_type!r}"
            )

        principal_roles = set(context.identity.roles)
        if principal_roles.intersection(allowed_roles):
            return TrustDecision.allow(
                reason=f"Principal roles {sorted(principal_roles)} authorized for {context.action_type!r}"
            )

        return TrustDecision.deny(
            reason=(
                f"Principal '{context.identity.principal_id}' with roles "
                f"{sorted(principal_roles)} is not authorized for action_type="
                f"{context.action_type!r} (requires one of {sorted(allowed_roles)})"
            ),
            risk_score=1.0,
        )


class SensitiveDataLossGuard(BaseDataLossGuard):
    def inspect(self, context: ExecutionContext) -> TrustDecision:
        sensitivity = context.attributes.data_sensitivity.lower()

        if sensitivity in {"restricted", "confidential"} and context.destination.is_external:
            return TrustDecision.allow_with_obligations(
                reason="Sensitive data leaving trusted boundary requires masking and audit",
                obligations=["mask_sensitive_data", "audit_log"],
                risk_score=0.75,
            )

        return TrustDecision.allow(reason="No data loss concern detected")


class DefaultZeroTrustGuard(BaseZeroTrustGuard):
    """
    Default K9-AIF Zero Trust execution guard.

    Flow:
    Verify  -> identity/context present
    Control -> inspect compromise, data loss, risk
    Enforce -> return execution decision + obligations
    """

    def __init__(
        self,
        risk_evaluator: BaseRiskEvaluator | None = None,
        compromise_guard: BaseCompromiseGuard | None = None,
        data_loss_guard: BaseDataLossGuard | None = None,
        authorization_guard: BaseAuthorizationGuard | None = None,
        deny_threshold: float = 0.85,
        approval_threshold: float = 0.75,
        obligation_threshold: float = 0.60,
    ):
        self.risk_evaluator = risk_evaluator or ContextualRiskEvaluator()
        self.compromise_guard = compromise_guard or PromptInjectionGuard()
        self.data_loss_guard = data_loss_guard or SensitiveDataLossGuard()
        self.authorization_guard = authorization_guard or RoleBasedAuthorizationGuard()
        self.deny_threshold = deny_threshold
        self.approval_threshold = approval_threshold
        self.obligation_threshold = obligation_threshold

    def evaluate(self, context: ExecutionContext) -> TrustDecision:
        compromise_decision = self.compromise_guard.inspect(context)
        if not compromise_decision.allowed:
            return compromise_decision

        authorization_decision = self.authorization_guard.inspect(context)
        if not authorization_decision.allowed:
            return authorization_decision

        data_loss_decision = self.data_loss_guard.inspect(context)
        if data_loss_decision.decision == TrustDecisionType.ALLOW_WITH_OBLIGATIONS:
            return data_loss_decision

        risk_score = self.risk_evaluator.score(context)

        if risk_score >= self.deny_threshold:
            return TrustDecision.deny(
                reason="Risk score exceeds deny threshold",
                risk_score=risk_score,
            )

        if risk_score >= self.approval_threshold:
            return TrustDecision.require_approval(
                reason="Risk score requires human approval",
                risk_score=risk_score,
            )

        if risk_score >= self.obligation_threshold:
            return TrustDecision.allow_with_obligations(
                reason="Risk allowed with runtime obligations",
                obligations=["audit_log", "step_up_review"],
                risk_score=risk_score,
            )

        return TrustDecision.allow(
            reason="Zero Trust evaluation passed",
            risk_score=risk_score,
        )