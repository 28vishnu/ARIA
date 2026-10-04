from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence


class ExperienceKind(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    DIAGNOSIS = "diagnosis"
    REPAIR = "repair"
    VERIFICATION = "verification"
    ACCEPTANCE = "acceptance"
    RECOVERY = "recovery"
    REPLAN = "replan"
    BLOCKED = "blocked"


class ExperienceOutcome(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    MIXED = "mixed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class EngineeringExperience:
    experience_id: str
    session_id: str
    kind: ExperienceKind
    outcome: ExperienceOutcome
    summary: str
    context: Mapping[str, Any] = field(default_factory=dict)
    evidence_ids: tuple[str, ...] = ()
    changed_paths: tuple[str, ...] = ()
    failure_signatures: tuple[str, ...] = ()
    root_causes: tuple[str, ...] = ()
    repair_actions: tuple[str, ...] = ()
    successful_actions: tuple[str, ...] = ()
    failed_actions: tuple[str, ...] = ()
    lessons: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    confidence: float = 0.0
    reusable: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "experience_id": self.experience_id,
            "session_id": self.session_id,
            "kind": self.kind.value,
            "outcome": self.outcome.value,
            "summary": self.summary,
            "context": dict(self.context),
            "evidence_ids": list(self.evidence_ids),
            "changed_paths": list(self.changed_paths),
            "failure_signatures": list(self.failure_signatures),
            "root_causes": list(self.root_causes),
            "repair_actions": list(self.repair_actions),
            "successful_actions": list(self.successful_actions),
            "failed_actions": list(self.failed_actions),
            "lessons": list(self.lessons),
            "tags": list(self.tags),
            "confidence": self.confidence,
            "reusable": self.reusable,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
    ) -> "EngineeringExperience":
        return cls(
            experience_id=str(payload.get("experience_id", "")),
            session_id=str(payload.get("session_id", "")),
            kind=ExperienceKind(
                payload.get("kind", ExperienceKind.FAILURE.value)
            ),
            outcome=ExperienceOutcome(
                payload.get("outcome", ExperienceOutcome.UNKNOWN.value)
            ),
            summary=str(payload.get("summary", "")),
            context=dict(payload.get("context", {})),
            evidence_ids=tuple(payload.get("evidence_ids", ())),
            changed_paths=tuple(payload.get("changed_paths", ())),
            failure_signatures=tuple(
                payload.get("failure_signatures", ())
            ),
            root_causes=tuple(payload.get("root_causes", ())),
            repair_actions=tuple(payload.get("repair_actions", ())),
            successful_actions=tuple(
                payload.get("successful_actions", ())
            ),
            failed_actions=tuple(payload.get("failed_actions", ())),
            lessons=tuple(payload.get("lessons", ())),
            tags=tuple(payload.get("tags", ())),
            confidence=float(payload.get("confidence", 0.0)),
            reusable=bool(payload.get("reusable", True)),
            metadata=dict(payload.get("metadata", {})),
        )


@dataclass(frozen=True)
class ExperienceQuery:
    query: str = ""
    kind: ExperienceKind | None = None
    outcome: ExperienceOutcome | None = None
    tags: tuple[str, ...] = ()
    failure_signature: str | None = None
    root_cause: str | None = None
    limit: int = 10
    min_confidence: float = 0.0


@dataclass(frozen=True)
class ExperienceMatch:
    experience: EngineeringExperience
    score: float
    matched_fields: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "experience": self.experience.to_dict(),
            "score": self.score,
            "matched_fields": list(self.matched_fields),
        }


@dataclass(frozen=True)
class EngineeringExperienceContext:
    query: ExperienceQuery
    matches: tuple[ExperienceMatch, ...] = ()
    recommendations: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": {
                "query": self.query.query,
                "kind": (
                    self.query.kind.value
                    if self.query.kind
                    else None
                ),
                "outcome": (
                    self.query.outcome.value
                    if self.query.outcome
                    else None
                ),
                "tags": list(self.query.tags),
                "failure_signature": self.query.failure_signature,
                "root_cause": self.query.root_cause,
                "limit": self.query.limit,
                "min_confidence": self.query.min_confidence,
            },
            "matches": [
                match.to_dict()
                for match in self.matches
            ],
            "recommendations": list(self.recommendations),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class ExperienceLearningResult:
    recorded: tuple[EngineeringExperience, ...] = ()
    rejected: tuple[str, ...] = ()
    recommendations: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "recorded": [
                experience.to_dict()
                for experience in self.recorded
            ],
            "rejected": list(self.rejected),
            "recommendations": list(self.recommendations),
            "warnings": list(self.warnings),
            "metadata": dict(self.metadata),
        }