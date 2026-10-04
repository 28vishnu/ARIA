"""Final outcome contract for ARIA autonomous engineering."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EngineeringOutcome(str, Enum):
    """Canonical engineering outcomes."""

    ACCEPTED = "accepted"
    REVISE = "revise"
    BLOCKED = "blocked"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class EngineeringResult:
    """Auditable result returned by the autonomous engineering engine."""

    outcome: EngineeringOutcome
    session_id: str
    summary: str = ""

    requirement_satisfied: bool = False
    acceptance_satisfied: bool = False

    changed_paths: tuple[str, ...] = ()
    test_paths: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()

    errors: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()

    confidence: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return self.outcome is EngineeringOutcome.ACCEPTED

    def __post_init__(self) -> None:
        if not str(self.session_id).strip():
            raise ValueError(
                "session_id must not be empty."
            )

        if (
            self.confidence is not None
            and not 0.0 <= self.confidence <= 1.0
        ):
            raise ValueError(
                "confidence must be between 0 and 1."
            )

        if self.outcome is EngineeringOutcome.ACCEPTED:
            if not self.requirement_satisfied:
                raise ValueError(
                    "An accepted result must satisfy the requirement."
                )

            if not self.acceptance_satisfied:
                raise ValueError(
                    "An accepted result must satisfy acceptance criteria."
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome.value,
            "session_id": self.session_id,
            "summary": self.summary,
            "success": self.success,
            "requirement_satisfied": self.requirement_satisfied,
            "acceptance_satisfied": self.acceptance_satisfied,
            "changed_paths": list(self.changed_paths),
            "test_paths": list(self.test_paths),
            "evidence_ids": list(self.evidence_ids),
            "errors": list(self.errors),
            "blockers": list(self.blockers),
            "confidence": self.confidence,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(
        cls,
        payload: dict[str, Any],
    ) -> "EngineeringResult":
        if not isinstance(payload, dict):
            raise TypeError(
                "EngineeringResult payload must be a dictionary."
            )

        raw_outcome = payload.get(
            "outcome",
            EngineeringOutcome.FAILED.value,
        )

        try:
            outcome = EngineeringOutcome(
                str(raw_outcome)
            )
        except ValueError as exc:
            raise ValueError(
                f"Unknown engineering outcome: {raw_outcome!r}"
            ) from exc

        return cls(
            outcome=outcome,
            session_id=str(
                payload.get(
                    "session_id",
                    "",
                )
            ),
            summary=str(
                payload.get(
                    "summary",
                    "",
                )
            ),
            requirement_satisfied=bool(
                payload.get(
                    "requirement_satisfied",
                    False,
                )
            ),
            acceptance_satisfied=bool(
                payload.get(
                    "acceptance_satisfied",
                    False,
                )
            ),
            changed_paths=tuple(
                str(item)
                for item in payload.get(
                    "changed_paths",
                    [],
                )
            ),
            test_paths=tuple(
                str(item)
                for item in payload.get(
                    "test_paths",
                    [],
                )
            ),
            evidence_ids=tuple(
                str(item)
                for item in payload.get(
                    "evidence_ids",
                    [],
                )
            ),
            errors=tuple(
                str(item)
                for item in payload.get(
                    "errors",
                    [],
                )
            ),
            blockers=tuple(
                str(item)
                for item in payload.get(
                    "blockers",
                    [],
                )
            ),
            confidence=payload.get(
                "confidence"
            ),
            metadata=dict(
                payload.get(
                    "metadata",
                    {},
                )
            ),
        )