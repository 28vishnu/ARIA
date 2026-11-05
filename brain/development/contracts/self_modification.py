from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence


class SelfModificationKind(str, Enum):
    BUG_FIX = "bug_fix"
    FEATURE = "feature"
    REFACTOR = "refactor"
    PERFORMANCE = "performance"
    RELIABILITY = "reliability"
    SECURITY = "security"
    ARCHITECTURE = "architecture"
    CAPABILITY = "capability"
    LEARNING = "learning"
    SELF_IMPROVEMENT = "self_improvement"


class SelfModificationRisk(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class SelfModificationScope(str, Enum):
    LOCAL = "local"
    COMPONENT = "component"
    SUBSYSTEM = "subsystem"
    SYSTEM = "system"


class SelfModificationStatus(str, Enum):
    PLANNED = "planned"
    ANALYZING = "analyzing"
    READY = "ready"
    BLOCKED = "blocked"
    REJECTED = "rejected"


class SelfModificationAction(str, Enum):
    IMPLEMENT = "implement"
    RESEARCH = "research"
    REPLAN = "replan"
    REQUEST_APPROVAL = "request_approval"
    BLOCK = "block"


@dataclass(frozen=True)
class SelfModificationTarget:
    path: str
    reason: str = ""
    component: str | None = None
    protected: bool = False
    writable: bool = True
    risk: SelfModificationRisk = SelfModificationRisk.MEDIUM
    dependencies: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "reason": self.reason,
            "component": self.component,
            "protected": self.protected,
            "writable": self.writable,
            "risk": self.risk.value,
            "dependencies": list(self.dependencies),
        }


@dataclass(frozen=True)
class SelfModificationConstraint:
    constraint_id: str
    description: str
    mandatory: bool = True
    source: str = "system"

    def to_dict(self) -> dict[str, Any]:
        return {
            "constraint_id": self.constraint_id,
            "description": self.description,
            "mandatory": self.mandatory,
            "source": self.source,
        }


@dataclass(frozen=True)
class SelfModificationVerification:
    verification_id: str
    description: str
    command: str | None = None
    required: bool = True
    affected_paths: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "verification_id": self.verification_id,
            "description": self.description,
            "command": self.command,
            "required": self.required,
            "affected_paths": list(self.affected_paths),
        }


@dataclass(frozen=True)
class SelfModificationRollback:
    rollback_id: str
    description: str
    trigger: str
    required: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "rollback_id": self.rollback_id,
            "description": self.description,
            "trigger": self.trigger,
            "required": self.required,
        }


@dataclass(frozen=True)
class SelfModificationPlan:
    plan_id: str
    session_id: str
    requirement: str
    objective: str
    kind: SelfModificationKind
    scope: SelfModificationScope
    risk: SelfModificationRisk
    status: SelfModificationStatus = SelfModificationStatus.PLANNED
    targets: tuple[SelfModificationTarget, ...] = ()
    constraints: tuple[SelfModificationConstraint, ...] = ()
    verification: tuple[SelfModificationVerification, ...] = ()
    rollback: tuple[SelfModificationRollback, ...] = ()
    rationale: str = ""
    assumptions: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()
    expected_benefits: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()
    forbidden_paths: tuple[str, ...] = ()
    approval_required: bool = True
    confidence: float = 0.0
    revision: int = 0
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "session_id": self.session_id,
            "requirement": self.requirement,
            "objective": self.objective,
            "kind": self.kind.value,
            "scope": self.scope.value,
            "risk": self.risk.value,
            "status": self.status.value,
            "targets": [
                target.to_dict()
                for target in self.targets
            ],
            "constraints": [
                constraint.to_dict()
                for constraint in self.constraints
            ],
            "verification": [
                item.to_dict()
                for item in self.verification
            ],
            "rollback": [
                item.to_dict()
                for item in self.rollback
            ],
            "rationale": self.rationale,
            "assumptions": list(self.assumptions),
            "risks": list(self.risks),
            "expected_benefits": list(self.expected_benefits),
            "dependencies": list(self.dependencies),
            "forbidden_paths": list(self.forbidden_paths),
            "approval_required": self.approval_required,
            "confidence": self.confidence,
            "revision": self.revision,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class SelfModificationRequest:
    session_id: str
    requirement: str
    objective: str
    repository_paths: tuple[str, ...] = ()
    protected_paths: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    acceptance_criteria: tuple[str, ...] = ()
    requested_permissions: tuple[str, ...] = ()
    forbidden_actions: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SelfModificationDecision:
    status: SelfModificationStatus
    action: SelfModificationAction
    risk: SelfModificationRisk
    scope: SelfModificationScope
    confidence: float
    rationale: str
    plan: SelfModificationPlan | None = None
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    required_approvals: tuple[str, ...] = ()
    next_actions: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "action": self.action.value,
            "risk": self.risk.value,
            "scope": self.scope.value,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "plan": (
                self.plan.to_dict()
                if self.plan is not None
                else None
            ),
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "required_approvals": list(self.required_approvals),
            "next_actions": list(self.next_actions),
        }