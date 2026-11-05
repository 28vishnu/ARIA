from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence


class UpgradeGateStatus(str, Enum):
    NOT_EVALUATED = "not_evaluated"
    APPROVED = "approved"
    REQUIRES_APPROVAL = "requires_approval"
    REJECTED = "rejected"
    BLOCKED = "blocked"


class UpgradeGateAction(str, Enum):
    PROCEED = "proceed"
    REQUEST_APPROVAL = "request_approval"
    REPLAN = "replan"
    BLOCK = "block"


class UpgradeAuthority(str, Enum):
    USER = "user"
    SYSTEM = "system"
    POLICY = "policy"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class UpgradeAuthorization:
    authority: UpgradeAuthority
    granted: bool
    scope: tuple[str, ...] = ()
    actions: tuple[str, ...] = ()
    reason: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority.value,
            "granted": self.granted,
            "scope": list(self.scope),
            "actions": list(self.actions),
            "reason": self.reason,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class UpgradeGateFinding:
    finding_id: str
    severity: str
    statement: str
    blocking: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "severity": self.severity,
            "statement": self.statement,
            "blocking": self.blocking,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class SelfUpgradeGateRequest:
    session_id: str
    plan: Mapping[str, Any]
    authorization: UpgradeAuthorization | None = None
    current_branch: str | None = None
    workspace_id: str | None = None
    repository_clean: bool = False
    verification_passed: bool = False
    acceptance_passed: bool = False
    rollback_available: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SelfUpgradeGateDecision:
    status: UpgradeGateStatus
    action: UpgradeGateAction
    authority: UpgradeAuthority
    confidence: float
    rationale: str
    findings: tuple[UpgradeGateFinding, ...] = ()
    blockers: tuple[str, ...] = ()
    required_approvals: tuple[str, ...] = ()
    permitted_actions: tuple[str, ...] = ()
    next_actions: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def approved(self) -> bool:
        return self.status == UpgradeGateStatus.APPROVED

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "action": self.action.value,
            "authority": self.authority.value,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "findings": [
                finding.to_dict()
                for finding in self.findings
            ],
            "blockers": list(self.blockers),
            "required_approvals": list(self.required_approvals),
            "permitted_actions": list(self.permitted_actions),
            "next_actions": list(self.next_actions),
            "metadata": dict(self.metadata),
        }