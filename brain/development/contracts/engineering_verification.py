"""Authoritative verification contracts for ARIA.

Step 12 defines the canonical verification boundary.

Verification must answer:

- What exactly was required?
- What was implemented?
- What evidence proves it?
- Which verification dimensions passed?
- Which dimensions remain unproven?
- Should ARIA accept the work?
- Should ARIA diagnose/recover/retest?

This contract does not execute tests itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence


class VerificationDimension(str, Enum):
    """Canonical verification dimensions."""

    IMPLEMENTATION = "implementation"
    ISOLATION = "isolation"
    STATIC = "static"
    BEHAVIORAL = "behavioral"
    ACCEPTANCE = "acceptance"


class VerificationStatus(str, Enum):
    """Canonical verification result."""

    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    PASSED = "passed"
    FAILED = "failed"
    INCONCLUSIVE = "inconclusive"
    BLOCKED = "blocked"


class VerificationAction(str, Enum):
    """What the engineering lifecycle should do next."""

    ACCEPT = "accept"
    TEST = "test"
    DIAGNOSE = "diagnose"
    REPAIR = "repair"
    REASSESS = "reassess"
    BLOCK = "block"


@dataclass(frozen=True)
class VerificationRequirement:
    """One verification requirement."""

    requirement_id: str

    dimension: VerificationDimension

    description: str

    evidence_required: tuple[str, ...] = ()

    verification_methods: tuple[str, ...] = ()

    mandatory: bool = True

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        if not self.requirement_id.strip():
            raise ValueError(
                "requirement_id must not be empty."
            )

        if not self.description.strip():
            raise ValueError(
                "Verification description must not be empty."
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "requirement_id": self.requirement_id,
            "dimension": self.dimension.value,
            "description": self.description,
            "evidence_required": list(
                self.evidence_required
            ),
            "verification_methods": list(
                self.verification_methods
            ),
            "mandatory": self.mandatory,
            "metadata": dict(
                self.metadata
            ),
        }


@dataclass(frozen=True)
class VerificationFinding:
    """One verification finding."""

    requirement_id: str

    dimension: VerificationDimension

    status: VerificationStatus

    message: str

    evidence_ids: tuple[str, ...] = ()

    command: str | None = None

    exit_code: int | None = None

    stdout: str = ""

    stderr: str = ""

    duration_seconds: float | None = None

    affected_paths: tuple[str, ...] = ()

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "requirement_id": self.requirement_id,
            "dimension": self.dimension.value,
            "status": self.status.value,
            "message": self.message,
            "evidence_ids": list(
                self.evidence_ids
            ),
            "command": self.command,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "duration_seconds": (
                self.duration_seconds
            ),
            "affected_paths": list(
                self.affected_paths
            ),
            "metadata": dict(
                self.metadata
            ),
        }


@dataclass(frozen=True)
class VerificationDecision:
    """Authoritative verification decision."""

    status: VerificationStatus

    action: VerificationAction

    confidence: float

    findings: tuple[
        VerificationFinding,
        ...
    ] = ()

    missing_evidence: tuple[str, ...] = ()

    failed_requirements: tuple[str, ...] = ()

    passed_requirements: tuple[str, ...] = ()

    next_steps: tuple[str, ...] = ()

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                "confidence must be between 0 and 1."
            )

    @property
    def passed(self) -> bool:
        return self.status is VerificationStatus.PASSED

    @property
    def requires_diagnosis(self) -> bool:
        return self.action is VerificationAction.DIAGNOSE

    @property
    def requires_reassessment(self) -> bool:
        return self.action is VerificationAction.REASSESS

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "action": self.action.value,
            "confidence": self.confidence,
            "findings": [
                item.to_dict()
                for item in self.findings
            ],
            "missing_evidence": list(
                self.missing_evidence
            ),
            "failed_requirements": list(
                self.failed_requirements
            ),
            "passed_requirements": list(
                self.passed_requirements
            ),
            "next_steps": list(
                self.next_steps
            ),
            "metadata": dict(
                self.metadata
            ),
        }


@dataclass(frozen=True)
class VerificationRequest:
    """Canonical request sent to the verification engine."""

    session_id: str

    task_id: str

    requirement: str

    acceptance_criteria: tuple[str, ...]

    verification_requirements: tuple[
        VerificationRequirement,
        ...
    ] = ()

    changed_paths: tuple[str, ...] = ()

    workspace_id: str | None = None

    implementation_evidence: tuple[
        str,
        ...
    ] = ()

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

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "task_id": self.task_id,
            "requirement": self.requirement,
            "acceptance_criteria": list(
                self.acceptance_criteria
            ),
            "verification_requirements": [
                item.to_dict()
                for item in self.verification_requirements
            ],
            "changed_paths": list(
                self.changed_paths
            ),
            "workspace_id": self.workspace_id,
            "implementation_evidence": list(
                self.implementation_evidence
            ),
            "metadata": dict(
                self.metadata
            ),
        }


@dataclass(frozen=True)
class VerificationResult:
    """Complete canonical verification result."""

    session_id: str

    task_id: str

    decision: VerificationDecision

    evidence: tuple[
        VerificationFinding,
        ...
    ] = ()

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    @property
    def passed(self) -> bool:
        return self.decision.passed

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "task_id": self.task_id,
            "decision": self.decision.to_dict(),
            "evidence": [
                item.to_dict()
                for item in self.evidence
            ],
            "metadata": dict(
                self.metadata
            ),
        }


def _string_tuple(
    value: Any,
) -> tuple[str, ...]:
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
    "VerificationDimension",
    "VerificationStatus",
    "VerificationAction",
    "VerificationRequirement",
    "VerificationFinding",
    "VerificationDecision",
    "VerificationRequest",
    "VerificationResult",
]