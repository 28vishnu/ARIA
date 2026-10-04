"""Authoritative root-cause diagnosis contracts for ARIA.

Step 13 defines the canonical diagnosis boundary for autonomous
engineering.

Diagnosis must distinguish between:

- observed failure
- proven root cause
- plausible alternative causes
- insufficient evidence
- evidence still required
- affected files
- recommended repair direction

The diagnosis layer does not modify files and does not perform repairs.

Its responsibility is to answer:

    "What is most likely wrong, and what evidence proves it?"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence


class DiagnosisCategory(str, Enum):
    """Canonical engineering root-cause categories."""

    SYNTAX = "syntax"
    IMPORT = "import"
    NAME = "name"
    TYPE = "type"
    ASSERTION = "assertion"
    FILE_OR_PATH = "file_or_path"
    PERMISSION = "permission"
    TIMEOUT = "timeout"
    DEPENDENCY = "dependency"
    CONFIGURATION = "configuration"
    ENVIRONMENT = "environment"
    INTERFACE = "interface"
    LOGIC = "logic"
    STATE = "state"
    INTEGRATION = "integration"
    RESOURCE = "resource"
    UNKNOWN = "unknown"


class DiagnosisConfidence(str, Enum):
    """Qualitative confidence in a diagnosis."""

    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    PROVEN = "proven"


class DiagnosisAction(str, Enum):
    """Recommended next lifecycle action."""

    REPAIR = "repair"
    GATHER_EVIDENCE = "gather_evidence"
    REASSESS = "reassess"
    BLOCK = "block"


@dataclass(frozen=True)
class DiagnosisEvidence:
    """One piece of evidence supporting or contradicting a hypothesis."""

    evidence_id: str

    description: str

    source: str = ""

    supports: bool = True

    strength: float = 0.0

    affected_paths: tuple[str, ...] = ()

    command: str | None = None

    exit_code: int | None = None

    stdout: str = ""

    stderr: str = ""

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        if not self.evidence_id.strip():
            raise ValueError(
                "evidence_id must not be empty."
            )

        if not self.description.strip():
            raise ValueError(
                "evidence description must not be empty."
            )

        if not 0.0 <= self.strength <= 1.0:
            raise ValueError(
                "evidence strength must be between 0 and 1."
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "description": self.description,
            "source": self.source,
            "supports": self.supports,
            "strength": self.strength,
            "affected_paths": list(
                self.affected_paths
            ),
            "command": self.command,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "metadata": dict(
                self.metadata
            ),
        }


@dataclass(frozen=True)
class RootCauseHypothesis:
    """One possible root cause."""

    hypothesis_id: str

    category: DiagnosisCategory

    statement: str

    confidence: float

    confidence_level: DiagnosisConfidence

    evidence_ids: tuple[str, ...] = ()

    affected_paths: tuple[str, ...] = ()

    repair_direction: str = ""

    falsification_conditions: tuple[str, ...] = ()

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        if not self.hypothesis_id.strip():
            raise ValueError(
                "hypothesis_id must not be empty."
            )

        if not self.statement.strip():
            raise ValueError(
                "hypothesis statement must not be empty."
            )

        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                "confidence must be between 0 and 1."
            )

    @property
    def is_actionable(self) -> bool:
        return bool(
            self.repair_direction.strip()
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "hypothesis_id": self.hypothesis_id,
            "category": self.category.value,
            "statement": self.statement,
            "confidence": self.confidence,
            "confidence_level": (
                self.confidence_level.value
            ),
            "evidence_ids": list(
                self.evidence_ids
            ),
            "affected_paths": list(
                self.affected_paths
            ),
            "repair_direction": (
                self.repair_direction
            ),
            "falsification_conditions": list(
                self.falsification_conditions
            ),
            "metadata": dict(
                self.metadata
            ),
        }


@dataclass(frozen=True)
class DiagnosisRequest:
    """Canonical request for root-cause analysis."""

    session_id: str

    task_id: str

    requirement: str

    observed_failure: str

    changed_paths: tuple[str, ...] = ()

    verification_status: str = ""

    verification_evidence: tuple[
        DiagnosisEvidence,
        ...
    ] = ()

    implementation_evidence: tuple[
        DiagnosisEvidence,
        ...
    ] = ()

    repository_context: dict[str, Any] = field(
        default_factory=dict
    )

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

        if not self.observed_failure.strip():
            raise ValueError(
                "observed_failure must not be empty."
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "task_id": self.task_id,
            "requirement": self.requirement,
            "observed_failure": self.observed_failure,
            "changed_paths": list(
                self.changed_paths
            ),
            "verification_status": (
                self.verification_status
            ),
            "verification_evidence": [
                item.to_dict()
                for item in self.verification_evidence
            ],
            "implementation_evidence": [
                item.to_dict()
                for item in self.implementation_evidence
            ],
            "repository_context": dict(
                self.repository_context
            ),
            "metadata": dict(
                self.metadata
            ),
        }


@dataclass(frozen=True)
class DiagnosisDecision:
    """Authoritative root-cause diagnosis."""

    primary: RootCauseHypothesis | None

    alternatives: tuple[
        RootCauseHypothesis,
        ...
    ] = ()

    evidence: tuple[
        DiagnosisEvidence,
        ...
    ] = ()

    evidence_quality: float = 0.0

    confidence: float = 0.0

    needs_more_evidence: bool = False

    next_evidence: tuple[str, ...] = ()

    action: DiagnosisAction = (
        DiagnosisAction.GATHER_EVIDENCE
    )

    observed_failure: str = ""

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        if not 0.0 <= self.evidence_quality <= 1.0:
            raise ValueError(
                "evidence_quality must be between 0 and 1."
            )

        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                "confidence must be between 0 and 1."
            )

    @property
    def has_root_cause(self) -> bool:
        return self.primary is not None

    @property
    def repairable(self) -> bool:
        return (
            self.primary is not None
            and self.primary.is_actionable
            and not self.needs_more_evidence
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "primary": (
                self.primary.to_dict()
                if self.primary is not None
                else None
            ),
            "alternatives": [
                item.to_dict()
                for item in self.alternatives
            ],
            "evidence": [
                item.to_dict()
                for item in self.evidence
            ],
            "evidence_quality": (
                self.evidence_quality
            ),
            "confidence": self.confidence,
            "needs_more_evidence": (
                self.needs_more_evidence
            ),
            "next_evidence": list(
                self.next_evidence
            ),
            "action": self.action.value,
            "observed_failure": (
                self.observed_failure
            ),
            "metadata": dict(
                self.metadata
            ),
        }


@dataclass(frozen=True)
class DiagnosisResult:
    """Complete canonical diagnosis result."""

    session_id: str

    task_id: str

    decision: DiagnosisDecision

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    @property
    def has_root_cause(self) -> bool:
        return self.decision.has_root_cause

    @property
    def repairable(self) -> bool:
        return self.decision.repairable

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "task_id": self.task_id,
            "decision": self.decision.to_dict(),
            "metadata": dict(
                self.metadata
            ),
        }


def confidence_level(
    confidence: float,
) -> DiagnosisConfidence:
    """Convert numeric confidence to a qualitative level."""

    if confidence >= 0.95:
        return DiagnosisConfidence.PROVEN

    if confidence >= 0.80:
        return DiagnosisConfidence.HIGH

    if confidence >= 0.55:
        return DiagnosisConfidence.MEDIUM

    if confidence > 0.0:
        return DiagnosisConfidence.LOW

    return DiagnosisConfidence.NONE


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
    "DiagnosisCategory",
    "DiagnosisConfidence",
    "DiagnosisAction",
    "DiagnosisEvidence",
    "RootCauseHypothesis",
    "DiagnosisRequest",
    "DiagnosisDecision",
    "DiagnosisResult",
    "confidence_level",
]