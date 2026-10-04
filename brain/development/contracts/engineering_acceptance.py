from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence


class AcceptanceStatus(str, Enum):
    NOT_STARTED = "not_started"
    EVALUATING = "evaluating"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    INCONCLUSIVE = "inconclusive"
    BLOCKED = "blocked"


class AcceptanceDecision(str, Enum):
    ACCEPT = "accept"
    REPAIR = "repair"
    REVERIFY = "reverify"
    RETEST = "retest"
    REASSESS = "reassess"
    BLOCK = "block"


class AcceptanceCriterionStatus(str, Enum):
    UNKNOWN = "unknown"
    SATISFIED = "satisfied"
    UNSATISFIED = "unsatisfied"
    INCONCLUSIVE = "inconclusive"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class AcceptanceCriterion:
    criterion_id: str
    description: str
    required: bool = True
    status: AcceptanceCriterionStatus = AcceptanceCriterionStatus.UNKNOWN
    evidence_ids: tuple[str, ...] = ()
    verification_ids: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def with_status(
        self,
        status: AcceptanceCriterionStatus,
        *,
        evidence_ids: Sequence[str] = (),
        verification_ids: Sequence[str] = (),
        notes: Sequence[str] = (),
    ) -> "AcceptanceCriterion":
        return AcceptanceCriterion(
            criterion_id=self.criterion_id,
            description=self.description,
            required=self.required,
            status=status,
            evidence_ids=tuple(evidence_ids),
            verification_ids=tuple(verification_ids),
            notes=tuple(notes),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "criterion_id": self.criterion_id,
            "description": self.description,
            "required": self.required,
            "status": self.status.value,
            "evidence_ids": list(self.evidence_ids),
            "verification_ids": list(self.verification_ids),
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class AcceptanceFinding:
    finding_id: str
    criterion_id: str | None
    status: AcceptanceCriterionStatus
    statement: str
    evidence_ids: tuple[str, ...] = ()
    verification_ids: tuple[str, ...] = ()
    severity: str = "info"
    confidence: float = 0.0
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "criterion_id": self.criterion_id,
            "status": self.status.value,
            "statement": self.statement,
            "evidence_ids": list(self.evidence_ids),
            "verification_ids": list(self.verification_ids),
            "severity": self.severity,
            "confidence": self.confidence,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class AcceptanceRequest:
    session_id: str
    requirement: str
    objective: str
    criteria: tuple[AcceptanceCriterion, ...] = ()
    verification_status: str = "unknown"
    verification_findings: tuple[Mapping[str, Any], ...] = ()
    evidence: tuple[Mapping[str, Any], ...] = ()
    implementation_summary: str = ""
    changed_paths: tuple[str, ...] = ()
    protected_paths: tuple[str, ...] = ()
    workspace_id: str | None = None
    constraints: tuple[str, ...] = ()
    forbidden_actions: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AcceptanceDecisionResult:
    status: AcceptanceStatus
    decision: AcceptanceDecision
    confidence: float
    criterion_results: tuple[AcceptanceCriterion, ...] = ()
    findings: tuple[AcceptanceFinding, ...] = ()
    missing_evidence: tuple[str, ...] = ()
    violated_constraints: tuple[str, ...] = ()
    next_actions: tuple[str, ...] = ()
    rationale: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def accepted(self) -> bool:
        return self.status == AcceptanceStatus.ACCEPTED

    @property
    def blocked(self) -> bool:
        return self.status == AcceptanceStatus.BLOCKED

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "decision": self.decision.value,
            "confidence": self.confidence,
            "criterion_results": [
                criterion.to_dict() for criterion in self.criterion_results
            ],
            "findings": [finding.to_dict() for finding in self.findings],
            "missing_evidence": list(self.missing_evidence),
            "violated_constraints": list(self.violated_constraints),
            "next_actions": list(self.next_actions),
            "rationale": self.rationale,
            "metadata": dict(self.metadata),
        }