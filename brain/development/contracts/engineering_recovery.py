"""Authoritative recovery and retest contracts for ARIA.

Step 14 defines the canonical recovery boundary.

Recovery consumes:

    Verification Failure
        +
    Root-Cause Diagnosis

and produces:

    Recovery Decision
        ↓
    Repair Request
        ↓
    Fresh Retest
        ↓
    Reassessment

Recovery never assumes that a repair succeeded.
A repair is only successful after fresh verification evidence proves
that the original failure has been resolved.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence


class RecoveryAction(str, Enum):
    """Canonical recovery actions."""

    REPAIR = "repair"
    GATHER_EVIDENCE = "gather_evidence"
    RETEST = "retest"
    REASSESS = "reassess"
    ACCEPT = "accept"
    BLOCK = "block"


class RecoveryStatus(str, Enum):
    """Current recovery state."""

    NOT_STARTED = "not_started"
    ANALYZING = "analyzing"
    REPAIRING = "repairing"
    RETESTING = "retesting"
    RECOVERED = "recovered"
    FAILED = "failed"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class RecoveryRequest:
    """Canonical request to recover from an engineering failure."""

    session_id: str

    task_id: str

    requirement: str

    failure: str

    diagnosis: dict[str, Any]

    affected_paths: tuple[str, ...] = ()

    workspace_id: str | None = None

    constraints: tuple[str, ...] = ()

    acceptance_criteria: tuple[str, ...] = ()

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        if not self.session_id.strip():
            raise ValueError(
                "session_id must not be empty."
            )

        if not self.task_id.strip():
            raise ValueError(
                "task_id must not be empty."
            )

        if not self.requirement.strip():
            raise ValueError(
                "requirement must not be empty."
            )

        if not self.failure.strip():
            raise ValueError(
                "failure must not be empty."
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "task_id": self.task_id,
            "requirement": self.requirement,
            "failure": self.failure,
            "diagnosis": dict(
                self.diagnosis
            ),
            "affected_paths": list(
                self.affected_paths
            ),
            "workspace_id": self.workspace_id,
            "constraints": list(
                self.constraints
            ),
            "acceptance_criteria": list(
                self.acceptance_criteria
            ),
            "metadata": dict(
                self.metadata
            ),
        }


@dataclass(frozen=True)
class RepairRequest:
    """Canonical repair instruction derived from diagnosis."""

    session_id: str

    task_id: str

    objective: str

    repair_direction: str

    affected_paths: tuple[str, ...] = ()

    protected_paths: tuple[str, ...] = ()

    constraints: tuple[str, ...] = ()

    evidence_required: tuple[str, ...] = ()

    workspace_id: str | None = None

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        if not self.session_id.strip():
            raise ValueError(
                "session_id must not be empty."
            )

        if not self.task_id.strip():
            raise ValueError(
                "task_id must not be empty."
            )

        if not self.objective.strip():
            raise ValueError(
                "repair objective must not be empty."
            )

        if not self.repair_direction.strip():
            raise ValueError(
                "repair direction must not be empty."
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "task_id": self.task_id,
            "objective": self.objective,
            "repair_direction": (
                self.repair_direction
            ),
            "affected_paths": list(
                self.affected_paths
            ),
            "protected_paths": list(
                self.protected_paths
            ),
            "constraints": list(
                self.constraints
            ),
            "evidence_required": list(
                self.evidence_required
            ),
            "workspace_id": self.workspace_id,
            "metadata": dict(
                self.metadata
            ),
        }


@dataclass(frozen=True)
class RetestRequest:
    """Canonical request for fresh verification after recovery."""

    session_id: str

    task_id: str

    requirement: str

    acceptance_criteria: tuple[str, ...]

    original_failure: str

    repair_attempt_id: str

    changed_paths: tuple[str, ...] = ()

    workspace_id: str | None = None

    verification_methods: tuple[str, ...] = ()

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        if not self.session_id.strip():
            raise ValueError(
                "session_id must not be empty."
            )

        if not self.task_id.strip():
            raise ValueError(
                "task_id must not be empty."
            )

        if not self.requirement.strip():
            raise ValueError(
                "requirement must not be empty."
            )

        if not self.repair_attempt_id.strip():
            raise ValueError(
                "repair_attempt_id must not be empty."
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "task_id": self.task_id,
            "requirement": self.requirement,
            "acceptance_criteria": list(
                self.acceptance_criteria
            ),
            "original_failure": (
                self.original_failure
            ),
            "repair_attempt_id": (
                self.repair_attempt_id
            ),
            "changed_paths": list(
                self.changed_paths
            ),
            "workspace_id": self.workspace_id,
            "verification_methods": list(
                self.verification_methods
            ),
            "metadata": dict(
                self.metadata
            ),
        }


@dataclass(frozen=True)
class RecoveryDecision:
    """Authoritative recovery decision."""

    status: RecoveryStatus

    action: RecoveryAction

    confidence: float

    reason: str

    repair_request: RepairRequest | None = None

    retest_required: bool = False

    additional_evidence: tuple[str, ...] = ()

    blockers: tuple[str, ...] = ()

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                "confidence must be between 0 and 1."
            )

    @property
    def repairable(self) -> bool:
        return (
            self.action is RecoveryAction.REPAIR
            and self.repair_request is not None
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "action": self.action.value,
            "confidence": self.confidence,
            "reason": self.reason,
            "repair_request": (
                self.repair_request.to_dict()
                if self.repair_request is not None
                else None
            ),
            "retest_required": self.retest_required,
            "additional_evidence": list(
                self.additional_evidence
            ),
            "blockers": list(
                self.blockers
            ),
            "metadata": dict(
                self.metadata
            ),
        }


@dataclass(frozen=True)
class RecoveryResult:
    """Complete recovery decision/result."""

    session_id: str

    task_id: str

    decision: RecoveryDecision

    repair_attempt_id: str | None = None

    retest_request: RetestRequest | None = None

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    @property
    def recovered(self) -> bool:
        return (
            self.decision.status
            is RecoveryStatus.RECOVERED
        )

    @property
    def needs_retest(self) -> bool:
        return self.decision.retest_required

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "task_id": self.task_id,
            "decision": self.decision.to_dict(),
            "repair_attempt_id": (
                self.repair_attempt_id
            ),
            "retest_request": (
                self.retest_request.to_dict()
                if self.retest_request is not None
                else None
            ),
            "metadata": dict(
                self.metadata
            ),
        }


def _string_tuple(
    value: Any,
) -> tuple[str, ...]:
    """Normalize an arbitrary value into a string tuple."""

    if value is None:
        return ()

    if isinstance(
        value,
        str,
    ):
        return (
            value,
        )

    if not isinstance(
        value,
        Sequence,
    ):
        return ()

    return tuple(
        str(item)
        for item in value
        if str(item).strip()
    )


__all__ = [
    "RecoveryAction",
    "RecoveryStatus",
    "RecoveryRequest",
    "RepairRequest",
    "RetestRequest",
    "RecoveryDecision",
    "RecoveryResult",
]