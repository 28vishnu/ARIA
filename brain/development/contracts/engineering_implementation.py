"""Authoritative implementation contracts for ARIA.

Step 11 establishes the contract between the authoritative engineering
session/task graph and ARIA's existing implementation services.

This layer does not directly generate code or execute commands.

It defines:

    Task Graph
        ↓
    Implementation Request
        ↓
    Existing DevelopmentAgent / Controller
        ↓
    Implementation Result
        ↓
    Engineering Evidence

The purpose is to prevent the legacy implementation layer from becoming
another source of engineering state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence


class ImplementationStatus(str, Enum):
    """Canonical implementation execution status."""

    NOT_STARTED = "not_started"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class ImplementationRequest:
    """Request to execute one implementation task."""

    session_id: str

    task_id: str

    requirement: str

    objective: str

    affected_paths: tuple[str, ...] = ()

    constraints: tuple[str, ...] = ()

    acceptance_criteria: tuple[str, ...] = ()

    evidence_required: tuple[str, ...] = ()

    verification: tuple[str, ...] = ()

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

        if not self.requirement.strip():
            raise ValueError(
                "requirement must not be empty."
            )

        if not self.objective.strip():
            raise ValueError(
                "objective must not be empty."
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "task_id": self.task_id,
            "requirement": self.requirement,
            "objective": self.objective,
            "affected_paths": list(
                self.affected_paths
            ),
            "constraints": list(
                self.constraints
            ),
            "acceptance_criteria": list(
                self.acceptance_criteria
            ),
            "evidence_required": list(
                self.evidence_required
            ),
            "verification": list(
                self.verification
            ),
            "workspace_id": self.workspace_id,
            "metadata": dict(
                self.metadata
            ),
        }

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
    ) -> "ImplementationRequest":
        if not isinstance(
            payload,
            Mapping,
        ):
            raise TypeError(
                "ImplementationRequest payload "
                "must be a mapping."
            )

        return cls(
            session_id=str(
                payload.get(
                    "session_id",
                    "",
                )
            ),
            task_id=str(
                payload.get(
                    "task_id",
                    "",
                )
            ),
            requirement=str(
                payload.get(
                    "requirement",
                    "",
                )
            ),
            objective=str(
                payload.get(
                    "objective",
                    "",
                )
            ),
            affected_paths=_string_tuple(
                payload.get(
                    "affected_paths"
                )
            ),
            constraints=_string_tuple(
                payload.get(
                    "constraints"
                )
            ),
            acceptance_criteria=_string_tuple(
                payload.get(
                    "acceptance_criteria"
                )
            ),
            evidence_required=_string_tuple(
                payload.get(
                    "evidence_required"
                )
            ),
            verification=_string_tuple(
                payload.get(
                    "verification"
                )
            ),
            workspace_id=(
                str(
                    payload.get(
                        "workspace_id"
                    )
                )
                if payload.get(
                    "workspace_id"
                )
                is not None
                else None
            ),
            metadata=dict(
                payload.get(
                    "metadata",
                    {},
                )
            ),
        )


@dataclass(frozen=True)
class ImplementationChange:
    """One proposed or applied repository change."""

    path: str

    content: str | None = None

    operation: str = "modify"

    reason: str = ""

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        if not self.path.strip():
            raise ValueError(
                "Implementation change path "
                "must not be empty."
            )

        allowed = {
            "create",
            "modify",
            "delete",
            "rename",
        }

        if self.operation not in allowed:
            raise ValueError(
                f"Unsupported implementation operation: "
                f"{self.operation}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "content": self.content,
            "operation": self.operation,
            "reason": self.reason,
            "metadata": dict(
                self.metadata
            ),
        }


@dataclass(frozen=True)
class ImplementationEvidence:
    """Evidence produced by an implementation attempt."""

    evidence_id: str

    task_id: str

    status: ImplementationStatus

    changed_paths: tuple[str, ...] = ()

    changes: tuple[
        ImplementationChange,
        ...,
    ] = ()

    workspace_id: str | None = None

    implementation_summary: str = ""

    diagnostics: tuple[str, ...] = ()

    errors: tuple[str, ...] = ()

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        if not self.evidence_id.strip():
            raise ValueError(
                "evidence_id must not be empty."
            )

        if not self.task_id.strip():
            raise ValueError(
                "task_id must not be empty."
            )

    @property
    def success(self) -> bool:
        return self.status is ImplementationStatus.COMPLETED

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "task_id": self.task_id,
            "status": self.status.value,
            "changed_paths": list(
                self.changed_paths
            ),
            "changes": [
                item.to_dict()
                for item in self.changes
            ],
            "workspace_id": self.workspace_id,
            "implementation_summary": (
                self.implementation_summary
            ),
            "diagnostics": list(
                self.diagnostics
            ),
            "errors": list(
                self.errors
            ),
            "metadata": dict(
                self.metadata
            ),
        }


@dataclass(frozen=True)
class ImplementationResult:
    """Canonical result returned by the implementation adapter."""

    session_id: str

    task_id: str

    status: ImplementationStatus

    evidence: ImplementationEvidence

    changes: tuple[
        ImplementationChange,
        ...
    ] = ()

    workspace_id: str | None = None

    next_action: str = ""

    blockers: tuple[str, ...] = ()

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    @property
    def success(self) -> bool:
        return self.status is ImplementationStatus.COMPLETED

    @property
    def failed(self) -> bool:
        return self.status is ImplementationStatus.FAILED

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "task_id": self.task_id,
            "status": self.status.value,
            "evidence": self.evidence.to_dict(),
            "changes": [
                item.to_dict()
                for item in self.changes
            ],
            "workspace_id": self.workspace_id,
            "next_action": self.next_action,
            "blockers": list(
                self.blockers
            ),
            "metadata": dict(
                self.metadata
            ),
        }


def _string_tuple(
    value: Any,
) -> tuple[str, ...]:
    """Normalize an arbitrary sequence into a string tuple."""

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
    "ImplementationStatus",
    "ImplementationRequest",
    "ImplementationChange",
    "ImplementationEvidence",
    "ImplementationResult",
]