"""State contracts for ARIA autonomous engineering.

This module defines the vocabulary of an engineering session. It deliberately
contains no orchestration logic. Step 3 will introduce the authoritative
mutable session that owns this state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EngineeringPhase(str, Enum):
    """Canonical lifecycle phases for autonomous engineering."""

    CREATED = "created"
    UNDERSTANDING = "understanding"
    PLANNING = "planning"
    GRAPH_READY = "graph_ready"
    IMPLEMENTING = "implementing"
    VERIFYING = "verifying"
    TESTING = "testing"
    DIAGNOSING = "diagnosing"
    RECOVERING = "recovering"
    RETESTING = "retesting"
    REASSESSING = "reassessing"
    ACCEPTING = "accepting"
    ACCEPTED = "accepted"
    BLOCKED = "blocked"
    FAILED = "failed"


TERMINAL_PHASES = frozenset(
    {
        EngineeringPhase.ACCEPTED,
        EngineeringPhase.BLOCKED,
        EngineeringPhase.FAILED,
    }
)


@dataclass
class EngineeringState:
    """Serializable state shared by every engineering subsystem.

    This is a data contract, not the owner of lifecycle transitions.
    EngineeringSession will become the authoritative owner in Step 3.
    """

    phase: EngineeringPhase = EngineeringPhase.CREATED
    goal: str = ""
    objective: str = ""

    constraints: list[str] = field(default_factory=list)
    acceptance_criteria: list[str] = field(default_factory=list)

    permissions: dict[str, Any] = field(default_factory=dict)

    repository_snapshot: dict[str, Any] = field(default_factory=dict)
    workspace: dict[str, Any] = field(default_factory=dict)
    plan: dict[str, Any] = field(default_factory=dict)
    task_graph: dict[str, Any] = field(default_factory=dict)

    current_task: str | None = None
    completed_tasks: list[str] = field(default_factory=list)

    evidence_ids: list[str] = field(default_factory=list)
    failure_ids: list[str] = field(default_factory=list)
    repair_ids: list[str] = field(default_factory=list)

    verification: dict[str, Any] = field(default_factory=dict)
    acceptance: dict[str, Any] = field(default_factory=dict)

    revision: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe representation of the state."""

        return {
            "phase": self.phase.value,
            "goal": self.goal,
            "objective": self.objective,
            "constraints": list(self.constraints),
            "acceptance_criteria": list(self.acceptance_criteria),
            "permissions": dict(self.permissions),
            "repository_snapshot": dict(self.repository_snapshot),
            "workspace": dict(self.workspace),
            "plan": dict(self.plan),
            "task_graph": dict(self.task_graph),
            "current_task": self.current_task,
            "completed_tasks": list(self.completed_tasks),
            "evidence_ids": list(self.evidence_ids),
            "failure_ids": list(self.failure_ids),
            "repair_ids": list(self.repair_ids),
            "verification": dict(self.verification),
            "acceptance": dict(self.acceptance),
            "revision": self.revision,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "EngineeringState":
        """Restore state from a serialized mapping."""

        if not isinstance(payload, dict):
            raise TypeError("EngineeringState payload must be a dictionary.")

        raw_phase = payload.get(
            "phase",
            EngineeringPhase.CREATED.value,
        )

        try:
            phase = EngineeringPhase(str(raw_phase))
        except ValueError as exc:
            raise ValueError(
                f"Unknown engineering phase: {raw_phase!r}"
            ) from exc

        return cls(
            phase=phase,
            goal=str(payload.get("goal", "")),
            objective=str(payload.get("objective", "")),
            constraints=_string_list(payload.get("constraints")),
            acceptance_criteria=_string_list(
                payload.get("acceptance_criteria")
            ),
            permissions=_mapping(payload.get("permissions")),
            repository_snapshot=_mapping(
                payload.get("repository_snapshot")
            ),
            workspace=_mapping(payload.get("workspace")),
            plan=_mapping(payload.get("plan")),
            task_graph=_mapping(payload.get("task_graph")),
            current_task=_optional_string(
                payload.get("current_task")
            ),
            completed_tasks=_string_list(
                payload.get("completed_tasks")
            ),
            evidence_ids=_string_list(
                payload.get("evidence_ids")
            ),
            failure_ids=_string_list(
                payload.get("failure_ids")
            ),
            repair_ids=_string_list(
                payload.get("repair_ids")
            ),
            verification=_mapping(payload.get("verification")),
            acceptance=_mapping(payload.get("acceptance")),
            revision=_non_negative_int(
                payload.get("revision", 0)
            ),
            metadata=_mapping(payload.get("metadata")),
        )


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []

    if not isinstance(value, (list, tuple, set)):
        raise TypeError(
            "Expected a list-like value of strings."
        )

    return [str(item) for item in value]


def _mapping(value: Any) -> dict[str, Any]:
    if value is None:
        return {}

    if not isinstance(value, dict):
        raise TypeError(
            "Expected a dictionary value."
        )

    return dict(value)


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None

    return str(value)


def _non_negative_int(value: Any) -> int:
    number = int(value)

    if number < 0:
        raise ValueError(
            "Revision must be non-negative."
        )

    return number