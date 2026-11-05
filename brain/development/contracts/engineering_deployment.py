from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class DeploymentOperation(str, Enum):
    NONE = "none"
    PREPARE = "prepare"
    DEPLOY = "deploy"
    HEALTH_CHECK = "health_check"
    ROLLBACK = "rollback"


class DeploymentStatus(str, Enum):
    NOT_STARTED = "not_started"
    PLANNED = "planned"
    AWAITING_APPROVAL = "awaiting_approval"
    READY = "ready"
    DEPLOYING = "deploying"
    HEALTH_CHECKING = "health_checking"
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    ROLLING_BACK = "rolling_back"
    ROLLED_BACK = "rolled_back"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"


class DeploymentRisk(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True)
class DeploymentAuthorization:
    granted: bool
    authority: str = "unknown"
    scope: tuple[str, ...] = ()
    reason: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "granted": self.granted,
            "authority": self.authority,
            "scope": list(self.scope),
            "reason": self.reason,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class HealthCheckDefinition:
    check_id: str
    description: str
    endpoint: str | None = None
    command: str | None = None
    timeout_seconds: float = 30.0
    required: bool = True
    expected_status: int | None = 200
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "description": self.description,
            "endpoint": self.endpoint,
            "command": self.command,
            "timeout_seconds": self.timeout_seconds,
            "required": self.required,
            "expected_status": self.expected_status,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class DeploymentRollbackPlan:
    rollback_id: str
    description: str
    trigger: str
    required: bool = True
    target_version: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rollback_id": self.rollback_id,
            "description": self.description,
            "trigger": self.trigger,
            "required": self.required,
            "target_version": self.target_version,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class DeploymentPlan:
    session_id: str
    environment: str
    version: str | None = None
    status: DeploymentStatus = DeploymentStatus.PLANNED
    risk: DeploymentRisk = DeploymentRisk.MEDIUM
    operations: tuple[DeploymentOperation, ...] = ()
    health_checks: tuple[HealthCheckDefinition, ...] = ()
    rollback: tuple[DeploymentRollbackPlan, ...] = ()
    approval_required: bool = True
    branch: str | None = None
    commit_sha: str | None = None
    changed_paths: tuple[str, ...] = ()
    rationale: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "environment": self.environment,
            "version": self.version,
            "status": self.status.value,
            "risk": self.risk.value,
            "operations": [
                operation.value
                for operation in self.operations
            ],
            "health_checks": [
                check.to_dict()
                for check in self.health_checks
            ],
            "rollback": [
                item.to_dict()
                for item in self.rollback
            ],
            "approval_required": self.approval_required,
            "branch": self.branch,
            "commit_sha": self.commit_sha,
            "changed_paths": list(self.changed_paths),
            "rationale": self.rationale,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class DeploymentRequest:
    session_id: str
    environment: str
    requirement: str
    version: str | None = None
    branch: str | None = None
    commit_sha: str | None = None
    changed_paths: tuple[str, ...] = ()
    health_endpoint: str | None = None
    health_command: str | None = None
    health_timeout_seconds: float = 60.0
    explicit_deploy_authorized: bool = False
    explicit_rollback_authorized: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HealthCheckResult:
    check_id: str
    passed: bool
    status_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    duration_seconds: float = 0.0
    error: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "passed": self.passed,
            "status_code": self.status_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "duration_seconds": self.duration_seconds,
            "error": self.error,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class DeploymentResult:
    status: DeploymentStatus
    operation: DeploymentOperation
    environment: str
    version: str | None = None
    deployment_id: str | None = None
    health_results: tuple[HealthCheckResult, ...] = ()
    rollback_performed: bool = False
    rollback_id: str | None = None
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    evidence: tuple[Mapping[str, Any], ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def healthy(self) -> bool:
        return self.status == DeploymentStatus.HEALTHY

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "operation": self.operation.value,
            "environment": self.environment,
            "version": self.version,
            "deployment_id": self.deployment_id,
            "health_results": [
                result.to_dict()
                for result in self.health_results
            ],
            "rollback_performed": self.rollback_performed,
            "rollback_id": self.rollback_id,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "evidence": [
                dict(item)
                for item in self.evidence
            ],
            "metadata": dict(self.metadata),
        }