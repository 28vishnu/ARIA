from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class GitOperation(str, Enum):
    NONE = "none"
    CREATE_BRANCH = "create_branch"
    COMMIT = "commit"
    PUSH = "push"
    CREATE_PR = "create_pr"
    MERGE_PR = "merge_pr"
    REVERT = "revert"


class GitLifecycleStatus(str, Enum):
    NOT_STARTED = "not_started"
    PLANNED = "planned"
    READY = "ready"
    AWAITING_APPROVAL = "awaiting_approval"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"


class GitRisk(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True)
class GitAuthorization:
    operation: GitOperation
    granted: bool
    authority: str = "unknown"
    scope: tuple[str, ...] = ()
    reason: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation.value,
            "granted": self.granted,
            "authority": self.authority,
            "scope": list(self.scope),
            "reason": self.reason,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class GitLifecyclePlan:
    session_id: str
    branch_name: str
    commit_message: str
    operations: tuple[GitOperation, ...] = ()
    risk: GitRisk = GitRisk.MEDIUM
    status: GitLifecycleStatus = GitLifecycleStatus.PLANNED
    changed_paths: tuple[str, ...] = ()
    remote: str = "origin"
    base_branch: str | None = None
    pr_title: str | None = None
    pr_body: str | None = None
    rollback_required: bool = True
    approval_required: tuple[GitOperation, ...] = ()
    rationale: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "branch_name": self.branch_name,
            "commit_message": self.commit_message,
            "operations": [
                operation.value
                for operation in self.operations
            ],
            "risk": self.risk.value,
            "status": self.status.value,
            "changed_paths": list(self.changed_paths),
            "remote": self.remote,
            "base_branch": self.base_branch,
            "pr_title": self.pr_title,
            "pr_body": self.pr_body,
            "rollback_required": self.rollback_required,
            "approval_required": [
                operation.value
                for operation in self.approval_required
            ],
            "rationale": self.rationale,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class GitLifecycleRequest:
    session_id: str
    requirement: str
    branch_name: str
    commit_message: str
    changed_paths: tuple[str, ...] = ()
    base_branch: str | None = None
    remote: str = "origin"
    create_pr: bool = False
    merge_pr: bool = False
    explicit_push_authorized: bool = False
    explicit_merge_authorized: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GitLifecycleResult:
    status: GitLifecycleStatus
    operation: GitOperation
    branch_name: str
    commit_sha: str | None = None
    remote: str | None = None
    pushed: bool = False
    pull_request_url: str | None = None
    merged: bool = False
    rollback_available: bool = False
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    evidence: tuple[Mapping[str, Any], ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "operation": self.operation.value,
            "branch_name": self.branch_name,
            "commit_sha": self.commit_sha,
            "remote": self.remote,
            "pushed": self.pushed,
            "pull_request_url": self.pull_request_url,
            "merged": self.merged,
            "rollback_available": self.rollback_available,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "evidence": [
                dict(item)
                for item in self.evidence
            ],
            "metadata": dict(self.metadata),
        }