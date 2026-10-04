"""Authoritative engineering task-graph contracts for ARIA.

Step 10 defines the task graph used by the new engineering lifecycle.

The graph is deliberately independent of the existing legacy task-graph
implementation. Later integration will adapt the existing implementation to
this contract instead of allowing multiple competing sources of truth.

The graph:
- represents dependencies
- tracks task status
- records required evidence
- identifies ready work
- preserves completed work
- supports reassessment after new evidence

It does not execute code or modify repositories.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Sequence


class EngineeringTaskKind(str, Enum):
    """Canonical autonomous-engineering task types."""

    UNDERSTAND = "understand"
    RESEARCH = "research"
    PLAN = "plan"
    IMPLEMENT = "implement"
    STATIC_VALIDATE = "static_validate"
    TEST = "test"
    VERIFY = "verify"
    DIAGNOSE = "diagnose"
    REPAIR = "repair"
    RETEST = "retest"
    REASSESS = "reassess"
    ACCEPT = "accept"


class EngineeringTaskStatus(str, Enum):
    """Current status of an engineering task."""

    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class EngineeringTask:
    """One node in the authoritative engineering task graph."""

    task_id: str
    kind: EngineeringTaskKind
    title: str
    objective: str

    dependencies: tuple[str, ...] = ()

    evidence_required: tuple[str, ...] = ()

    verification: tuple[str, ...] = ()

    affected_paths: tuple[str, ...] = ()

    priority: int = 100

    risk: str = "normal"

    status: EngineeringTaskStatus = (
        EngineeringTaskStatus.PENDING
    )

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        if not self.task_id.strip():
            raise ValueError(
                "task_id must not be empty."
            )

        if not self.title.strip():
            raise ValueError(
                "Task title must not be empty."
            )

        if not self.objective.strip():
            raise ValueError(
                "Task objective must not be empty."
            )

        if self.priority < 0:
            raise ValueError(
                "Task priority must be non-negative."
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "kind": self.kind.value,
            "title": self.title,
            "objective": self.objective,
            "dependencies": list(
                self.dependencies
            ),
            "evidence_required": list(
                self.evidence_required
            ),
            "verification": list(
                self.verification
            ),
            "affected_paths": list(
                self.affected_paths
            ),
            "priority": self.priority,
            "risk": self.risk,
            "status": self.status.value,
            "metadata": dict(
                self.metadata
            ),
        }

    @classmethod
    def from_dict(
        cls,
        payload: dict[str, Any],
    ) -> "EngineeringTask":
        if not isinstance(
            payload,
            dict,
        ):
            raise TypeError(
                "EngineeringTask payload must be a dictionary."
            )

        try:
            kind = EngineeringTaskKind(
                str(
                    payload.get(
                        "kind",
                        EngineeringTaskKind.IMPLEMENT.value,
                    )
                )
            )
        except ValueError:
            kind = EngineeringTaskKind.IMPLEMENT

        try:
            status = EngineeringTaskStatus(
                str(
                    payload.get(
                        "status",
                        EngineeringTaskStatus.PENDING.value,
                    )
                )
            )
        except ValueError:
            status = EngineeringTaskStatus.PENDING

        return cls(
            task_id=str(
                payload.get(
                    "task_id",
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
            objective=str(
                payload.get(
                    "objective",
                    "",
                )
            ),
            dependencies=_string_tuple(
                payload.get(
                    "dependencies"
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
            affected_paths=_string_tuple(
                payload.get(
                    "affected_paths"
                )
            ),
            priority=int(
                payload.get(
                    "priority",
                    100,
                )
            ),
            risk=str(
                payload.get(
                    "risk",
                    "normal",
                )
            ),
            status=status,
            metadata=dict(
                payload.get(
                    "metadata",
                    {},
                )
            ),
        )


@dataclass
class EngineeringTaskGraph:
    """Mutable authoritative graph snapshot."""

    graph_id: str

    tasks: tuple[
        EngineeringTask,
        ...
    ] = ()

    execution_order: tuple[str, ...] = ()

    revision: int = 0

    confidence: float = 0.0

    warnings: list[str] = field(
        default_factory=list
    )

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        if not self.graph_id.strip():
            raise ValueError(
                "graph_id must not be empty."
            )

        if self.revision < 0:
            raise ValueError(
                "revision must be non-negative."
            )

        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                "confidence must be between 0 and 1."
            )

        self._validate_unique_task_ids()

        self._validate_dependencies()

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def task(
        self,
        task_id: str,
    ) -> EngineeringTask | None:
        target = str(task_id)

        for item in self.tasks:
            if item.task_id == target:
                return item

        return None

    def completed_tasks(
        self,
    ) -> tuple[str, ...]:
        return tuple(
            item.task_id
            for item in self.tasks
            if item.status
            is EngineeringTaskStatus.COMPLETED
        )

    def failed_tasks(
        self,
    ) -> tuple[str, ...]:
        return tuple(
            item.task_id
            for item in self.tasks
            if item.status
            is EngineeringTaskStatus.FAILED
        )

    def blocked_tasks(
        self,
    ) -> tuple[str, ...]:
        completed = set(
            self.completed_tasks()
        )

        blocked: list[str] = []

        for item in self.tasks:
            if item.status in {
                EngineeringTaskStatus.COMPLETED,
                EngineeringTaskStatus.SKIPPED,
            }:
                continue

            missing = [
                dependency
                for dependency in item.dependencies
                if dependency not in completed
            ]

            if missing:
                blocked.append(
                    item.task_id
                )

        return tuple(blocked)

    def ready_tasks(
        self,
    ) -> tuple[EngineeringTask, ...]:
        completed = set(
            self.completed_tasks()
        )

        ready: list[
            EngineeringTask
        ] = []

        for item in self.tasks:
            if item.status in {
                EngineeringTaskStatus.COMPLETED,
                EngineeringTaskStatus.SKIPPED,
                EngineeringTaskStatus.RUNNING,
            }:
                continue

            if all(
                dependency in completed
                for dependency in item.dependencies
            ):
                ready.append(
                    item
                )

        return tuple(
            sorted(
                ready,
                key=lambda item: (
                    item.priority,
                    item.task_id,
                ),
            )
        )

    def is_complete(self) -> bool:
        return all(
            item.status
            in {
                EngineeringTaskStatus.COMPLETED,
                EngineeringTaskStatus.SKIPPED,
            }
            for item in self.tasks
        )

    # ------------------------------------------------------------------
    # Task state
    # ------------------------------------------------------------------

    def mark_ready(
        self,
        task_id: str,
    ) -> "EngineeringTaskGraph":
        return self._replace_status(
            task_id,
            EngineeringTaskStatus.READY,
        )

    def mark_running(
        self,
        task_id: str,
    ) -> "EngineeringTaskGraph":
        self._require_ready(
            task_id
        )

        return self._replace_status(
            task_id,
            EngineeringTaskStatus.RUNNING,
        )

    def mark_completed(
        self,
        task_id: str,
    ) -> "EngineeringTaskGraph":
        task = self.task(
            task_id
        )

        if task is None:
            raise KeyError(
                f"Unknown engineering task: {task_id}"
            )

        if task.status not in {
            EngineeringTaskStatus.RUNNING,
            EngineeringTaskStatus.READY,
            EngineeringTaskStatus.PENDING,
        }:
            raise RuntimeError(
                f"Task '{task_id}' cannot be completed from "
                f"status '{task.status.value}'."
            )

        return self._replace_status(
            task_id,
            EngineeringTaskStatus.COMPLETED,
        )

    def mark_failed(
        self,
        task_id: str,
    ) -> "EngineeringTaskGraph":
        task = self.task(
            task_id
        )

        if task is None:
            raise KeyError(
                f"Unknown engineering task: {task_id}"
            )

        return self._replace_status(
            task_id,
            EngineeringTaskStatus.FAILED,
        )

    def mark_blocked(
        self,
        task_id: str,
    ) -> "EngineeringTaskGraph":
        task = self.task(
            task_id
        )

        if task is None:
            raise KeyError(
                f"Unknown engineering task: {task_id}"
            )

        return self._replace_status(
            task_id,
            EngineeringTaskStatus.BLOCKED,
        )

    # ------------------------------------------------------------------
    # Reassessment
    # ------------------------------------------------------------------

    def revise(
        self,
        *,
        tasks: Sequence[EngineeringTask],
        reason: str,
        confidence: float | None = None,
    ) -> "EngineeringTaskGraph":
        """Create a new graph revision while preserving completed work."""

        previous_completed = set(
            self.completed_tasks()
        )

        revised_tasks: list[
            EngineeringTask
        ] = []

        for task in tasks:
            if task.task_id in previous_completed:
                revised_tasks.append(
                    EngineeringTask(
                        task_id=task.task_id,
                        kind=task.kind,
                        title=task.title,
                        objective=task.objective,
                        dependencies=task.dependencies,
                        evidence_required=(
                            task.evidence_required
                        ),
                        verification=task.verification,
                        affected_paths=task.affected_paths,
                        priority=task.priority,
                        risk=task.risk,
                        status=(
                            EngineeringTaskStatus.COMPLETED
                        ),
                        metadata=task.metadata,
                    )
                )
            else:
                revised_tasks.append(
                    task
                )

        self.tasks = tuple(
            revised_tasks
        )

        self.revision += 1

        self.execution_order = (
            self._calculate_execution_order()
        )

        if confidence is not None:
            self.confidence = confidence

        self.warnings.append(
            f"Graph revised: {reason}"
        )

        self._validate_unique_task_ids()

        self._validate_dependencies()

        return self

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(
        self,
    ) -> dict[str, Any]:
        return {
            "graph_id": self.graph_id,

            "tasks": [
                item.to_dict()
                for item in self.tasks
            ],

            "execution_order": list(
                self.execution_order
            ),

            "revision": self.revision,

            "confidence": self.confidence,

            "warnings": list(
                self.warnings
            ),

            "metadata": dict(
                self.metadata
            ),
        }

    @classmethod
    def from_dict(
        cls,
        payload: dict[str, Any],
    ) -> "EngineeringTaskGraph":
        if not isinstance(
            payload,
            dict,
        ):
            raise TypeError(
                "EngineeringTaskGraph payload "
                "must be a dictionary."
            )

        tasks = tuple(
            EngineeringTask.from_dict(
                item
            )
            for item in payload.get(
                "tasks",
                [],
            )
            if isinstance(
                item,
                dict,
            )
        )

        graph = cls(
            graph_id=str(
                payload.get(
                    "graph_id",
                    "",
                )
            ),

            tasks=tasks,

            execution_order=_string_tuple(
                payload.get(
                    "execution_order"
                )
            ),

            revision=int(
                payload.get(
                    "revision",
                    0,
                )
            ),

            confidence=float(
                payload.get(
                    "confidence",
                    0.0,
                )
            ),

            warnings=list(
                _string_tuple(
                    payload.get(
                        "warnings"
                    )
                )
            ),

            metadata=dict(
                payload.get(
                    "metadata",
                    {},
                )
            ),
        )

        if not graph.execution_order:
            graph.execution_order = (
                graph._calculate_execution_order()
            )

        return graph

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _replace_status(
        self,
        task_id: str,
        status: EngineeringTaskStatus,
    ) -> "EngineeringTaskGraph":
        target = str(
            task_id
        )

        if self.task(target) is None:
            raise KeyError(
                f"Unknown engineering task: {target}"
            )

        updated: list[
            EngineeringTask
        ] = []

        for item in self.tasks:
            if item.task_id != target:
                updated.append(
                    item
                )
                continue

            updated.append(
                EngineeringTask(
                    task_id=item.task_id,
                    kind=item.kind,
                    title=item.title,
                    objective=item.objective,
                    dependencies=item.dependencies,
                    evidence_required=(
                        item.evidence_required
                    ),
                    verification=item.verification,
                    affected_paths=item.affected_paths,
                    priority=item.priority,
                    risk=item.risk,
                    status=status,
                    metadata=item.metadata,
                )
            )

        self.tasks = tuple(
            updated
        )

        return self

    def _require_ready(
        self,
        task_id: str,
    ) -> None:
        task = self.task(
            task_id
        )

        if task is None:
            raise KeyError(
                f"Unknown engineering task: {task_id}"
            )

        completed = set(
            self.completed_tasks()
        )

        missing = [
            dependency
            for dependency in task.dependencies
            if dependency not in completed
        ]

        if missing:
            raise RuntimeError(
                f"Task '{task_id}' is blocked; "
                f"dependencies not completed: {missing}"
            )

    def _validate_unique_task_ids(
        self,
    ) -> None:
        ids = [
            item.task_id
            for item in self.tasks
        ]

        if len(ids) != len(set(ids)):
            raise ValueError(
                "Engineering task graph contains duplicate task IDs."
            )

    def _validate_dependencies(
        self,
    ) -> None:
        ids = {
            item.task_id
            for item in self.tasks
        }

        for task in self.tasks:
            for dependency in task.dependencies:
                if dependency not in ids:
                    raise ValueError(
                        f"Task '{task.task_id}' depends on "
                        f"unknown task '{dependency}'."
                    )

                if dependency == task.task_id:
                    raise ValueError(
                        f"Task '{task.task_id}' cannot depend on itself."
                    )

        self._calculate_execution_order()

    def _calculate_execution_order(
        self,
    ) -> tuple[str, ...]:
        remaining = {
            item.task_id: set(
                item.dependencies
            )
            for item in self.tasks
        }

        order: list[str] = []

        while remaining:
            ready = sorted(
                task_id
                for task_id, dependencies
                in remaining.items()
                if not dependencies
            )

            if not ready:
                raise ValueError(
                    "Engineering task graph contains a dependency cycle."
                )

            order.extend(
                ready
            )

            for task_id in ready:
                remaining.pop(
                    task_id,
                    None,
                )

            for dependencies in remaining.values():
                dependencies.difference_update(
                    ready
                )

        return tuple(
            order
        )


def _string_tuple(
    value: Any,
) -> tuple[str, ...]:
    if value is None:
        return ()

    if isinstance(
        value,
        str,
    ):
        return (value,)

    if not isinstance(
        value,
        (list, tuple, set),
    ):
        raise TypeError(
            "Expected a string or sequence of strings."
        )

    return tuple(
        str(item)
        for item in value
    )


__all__ = [
    "EngineeringTaskKind",
    "EngineeringTaskStatus",
    "EngineeringTask",
    "EngineeringTaskGraph",
]