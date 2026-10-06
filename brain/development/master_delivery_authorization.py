"""Explicit Master authorization coordinator for GitHub and deployment.

This module does not perform GitHub pushes or deployments itself. It connects
ARIA's existing ApprovalManager to the canonical Phase1DeliveryGateway so
that a delivery operation must have a concrete, auditable Master decision
before its authorization object is produced.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

from brain.development.approval_manager import ApprovalManager, ApprovalDecision
from brain.development.contracts.engineering_git import GitAuthorization, GitOperation
from brain.development.contracts.engineering_deployment import DeploymentAuthorization


@dataclass(frozen=True)
class AuthorizationEnvelope:
    request_id: str
    operation: str
    approved: bool
    authority: str
    reason: str
    metadata: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "operation": self.operation,
            "approved": self.approved,
            "authority": self.authority,
            "reason": self.reason,
            "metadata": dict(self.metadata),
        }


class MasterDeliveryAuthorization:
    """Single coordinator for human approval of delivery operations."""

    VERSION = "ARIA-MASTER-DELIVERY-AUTHORIZATION-20261006"
    MASTER_AUTHORITY = "Master"

    _GIT_OPERATIONS = {
        GitOperation.PUSH.value: GitOperation.PUSH,
        GitOperation.MERGE_PR.value: GitOperation.MERGE_PR,
        GitOperation.CREATE_PR.value: GitOperation.CREATE_PR,
        GitOperation.COMMIT.value: GitOperation.COMMIT,
        GitOperation.CREATE_BRANCH.value: GitOperation.CREATE_BRANCH,
        GitOperation.REVERT.value: GitOperation.REVERT,
    }

    def __init__(
        self,
        *,
        approval_manager: ApprovalManager,
        delivery_gateway: Any,
    ) -> None:
        if approval_manager is None:
            raise ValueError("approval_manager is required")
        if delivery_gateway is None:
            raise ValueError("delivery_gateway is required")
        self.approval_manager = approval_manager
        self.delivery_gateway = delivery_gateway

    def health(self) -> dict[str, Any]:
        gateway_health = self._safe_health()
        return {
            "healthy": bool(gateway_health.get("healthy", False)),
            "version": self.VERSION,
            "approval_manager_connected": self.approval_manager is not None,
            "delivery_gateway_connected": self.delivery_gateway is not None,
            "master_authority": self.MASTER_AUTHORITY,
            "github_push_requires_authorization": True,
            "merge_requires_authorization": True,
            "deployment_requires_authorization": True,
            "rollback_requires_authorization": True,
            "production_direct_write": False,
            "automatic_delivery": False,
        }

    def request_approval(
        self,
        *,
        operation: str,
        reason: str,
        risk_level: str = "high",
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> dict[str, Any]:
        """Create an approval request; this never executes delivery."""
        request = self.approval_manager.create_request(
            operation=operation,
            reason=reason,
            risk_level=risk_level,
            metadata=dict(metadata or {}),
        )
        return request.to_dict()

    def approve(
        self,
        request_id: str,
        *,
        reason: str = "Approved by Master.",
    ) -> dict[str, Any]:
        decision = self.approval_manager.approve(
            request_id,
            decided_by=self.MASTER_AUTHORITY,
            reason=reason,
        )
        return decision.to_dict()

    def reject(
        self,
        request_id: str,
        *,
        reason: str = "Rejected by Master.",
    ) -> dict[str, Any]:
        decision = self.approval_manager.reject(
            request_id,
            decided_by=self.MASTER_AUTHORITY,
            reason=reason,
        )
        return decision.to_dict()

    def authorization_for_git(
        self,
        request_id: str,
        operation: GitOperation,
    ) -> GitAuthorization:
        decision = self._decision(request_id)
        return GitAuthorization(
            operation=operation,
            granted=self._is_master_approved(decision),
            authority=decision.decided_by if decision else "none",
            scope=(operation.value,),
            reason=(decision.reason if decision else "No Master approval."),
            metadata={
                "approval_request_id": request_id,
                "approval_granted": bool(decision and decision.approved),
            },
        )

    def authorization_for_deployment(
        self,
        request_id: str,
        *,
        scope: tuple[str, ...] = ("deploy",),
    ) -> DeploymentAuthorization:
        decision = self._decision(request_id)
        return DeploymentAuthorization(
            granted=self._is_master_approved(decision),
            authority=decision.decided_by if decision else "none",
            scope=scope,
            reason=(decision.reason if decision else "No Master approval."),
            metadata={
                "approval_request_id": request_id,
                "approval_granted": bool(decision and decision.approved),
            },
        )

    def authorization_for_rollback(
        self,
        request_id: str,
    ) -> DeploymentAuthorization:
        return self.authorization_for_deployment(
            request_id,
            scope=("rollback",),
        )

    def status(self, request_id: str) -> dict[str, Any]:
        decision = self._decision(request_id)
        return {
            "request_id": request_id,
            "approved": bool(decision and decision.approved),
            "decided": decision is not None,
            "authority": decision.decided_by if decision else None,
            "reason": decision.reason if decision else None,
        }

    def _decision(self, request_id: str) -> Optional[ApprovalDecision]:
        decisions = getattr(self.approval_manager, "_decisions", {})
        value = decisions.get(request_id)
        return value if isinstance(value, ApprovalDecision) else None

    @staticmethod
    def _is_master_approved(decision: Optional[ApprovalDecision]) -> bool:
        return bool(
            decision is not None
            and decision.approved
            and decision.decided_by.strip().lower() == "master"
        )

    def _safe_health(self) -> dict[str, Any]:
        method = getattr(self.delivery_gateway, "health", None)
        if not callable(method):
            return {"healthy": False}
        try:
            value = method()
            return dict(value) if isinstance(value, Mapping) else {"healthy": False}
        except Exception:
            return {"healthy": False}


__all__ = ["AuthorizationEnvelope", "MasterDeliveryAuthorization"]
