"""Evidence contract for ARIA autonomous engineering."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EvidenceKind(str, Enum):
    """Canonical categories of engineering evidence."""

    REQUIREMENT = "requirement"
    REPOSITORY = "repository"
    PLAN = "plan"
    TASK = "task"
    IMPLEMENTATION = "implementation"
    STATIC = "static"
    TEST = "test"
    FAILURE = "failure"
    ROOT_CAUSE = "root_cause"
    REPAIR = "repair"
    VERIFICATION = "verification"
    ACCEPTANCE = "acceptance"
    PERMISSION = "permission"
    DEPLOYMENT = "deployment"
    HEALTH = "health"
    LEARNING = "learning"


@dataclass(frozen=True)
class EngineeringEvidence:
    """Immutable evidence record.

    Evidence is factual execution history. It is intentionally separate from
    conclusions so an acceptance decision can be audited later.
    """

    evidence_id: str
    kind: EvidenceKind
    title: str
    summary: str = ""

    source: str = ""
    task_id: str | None = None

    command: str | None = None
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    duration_seconds: float | None = None
    timed_out: bool = False

    paths: tuple[str, ...] = ()
    data: dict[str, Any] = field(default_factory=dict)

    success: bool | None = None
    confidence: float | None = None

    def __post_init__(self) -> None:
        if not str(self.evidence_id).strip():
            raise ValueError(
                "evidence_id must not be empty."
            )

        if not str(self.title).strip():
            raise ValueError(
                "Evidence title must not be empty."
            )

        if self.exit_code is not None and not isinstance(
            self.exit_code,
            int,
        ):
            raise TypeError(
                "exit_code must be an integer or None."
            )

        if (
            self.duration_seconds is not None
            and self.duration_seconds < 0
        ):
            raise ValueError(
                "duration_seconds must be non-negative."
            )

        if (
            self.confidence is not None
            and not 0.0 <= self.confidence <= 1.0
        ):
            raise ValueError(
                "confidence must be between 0 and 1."
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "kind": self.kind.value,
            "title": self.title,
            "summary": self.summary,
            "source": self.source,
            "task_id": self.task_id,
            "command": self.command,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "duration_seconds": self.duration_seconds,
            "timed_out": self.timed_out,
            "paths": list(self.paths),
            "data": dict(self.data),
            "success": self.success,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(
        cls,
        payload: dict[str, Any],
    ) -> "EngineeringEvidence":
        if not isinstance(payload, dict):
            raise TypeError(
                "EngineeringEvidence payload must be a dictionary."
            )

        raw_kind = payload.get(
            "kind",
            EvidenceKind.VERIFICATION.value,
        )

        try:
            kind = EvidenceKind(str(raw_kind))
        except ValueError as exc:
            raise ValueError(
                f"Unknown evidence kind: {raw_kind!r}"
            ) from exc

        return cls(
            evidence_id=str(
                payload.get(
                    "evidence_id",
                    "",
                )
            ),
            kind=kind,
            title=str(
                payload.get(
                    "title",
                    "",
                )
            ),
            summary=str(
                payload.get(
                    "summary",
                    "",
                )
            ),
            source=str(
                payload.get(
                    "source",
                    "",
                )
            ),
            task_id=_optional_string(
                payload.get("task_id")
            ),
            command=_optional_string(
                payload.get("command")
            ),
            exit_code=payload.get(
                "exit_code"
            ),
            stdout=str(
                payload.get(
                    "stdout",
                    "",
                )
            ),
            stderr=str(
                payload.get(
                    "stderr",
                    "",
                )
            ),
            duration_seconds=payload.get(
                "duration_seconds"
            ),
            timed_out=bool(
                payload.get(
                    "timed_out",
                    False,
                )
            ),
            paths=tuple(
                str(item)
                for item in payload.get(
                    "paths",
                    [],
                )
            ),
            data=dict(
                payload.get(
                    "data",
                    {},
                )
            ),
            success=payload.get(
                "success"
            ),
            confidence=payload.get(
                "confidence"
            ),
        )


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None

    return str(value)