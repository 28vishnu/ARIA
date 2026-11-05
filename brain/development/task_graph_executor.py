from __future__ import annotations

"""ARIA Phase 1 — Step 45: dependency-aware task execution state."""

from dataclasses import dataclass, field
from typing import Any, Iterable

from .intelligent_task_graph import TaskGraph


@dataclass
class TaskExecutionState:
    graph: TaskGraph
    completed: set[str] = field(default_factory=set)
    failed: set[str] = field(default_factory=set)
    evidence: dict[str, dict[str, Any]] = field(default_factory=dict)
    history: list[dict[str, Any]] = field(default_factory=list)

    def task(self, task_id: str):
        task = self.graph.task(task_id)
        if task is None:
            raise RuntimeError(f"Unknown engineering task: {task_id}")
        return task

    def require_ready(self, task_id: str) -> None:
        task = self.task(task_id)
        if task_id in self.completed:
            return
        if task_id in self.failed:
            raise RuntimeError(
                f"Task '{task_id}' failed; reassessment is required before retry."
            )
        missing = [dep for dep in task.dependencies if dep not in self.completed]
        if missing:
            raise RuntimeError(
                f"Task graph blocked '{task_id}'; dependencies not completed: {missing}"
            )

    def complete(self, task_id: str, evidence: dict[str, Any] | None = None) -> None:
        self.require_ready(task_id)
        payload = dict(evidence or {})
        self.completed.add(task_id)
        self.evidence[task_id] = payload
        self.history.append({"task_id": task_id, "status": "completed", "evidence": payload})

    def fail(self, task_id: str, evidence: dict[str, Any] | None = None) -> None:
        self.task(task_id)
        payload = dict(evidence or {})
        self.failed.add(task_id)
        self.evidence[task_id] = payload
        self.history.append({"task_id": task_id, "status": "failed", "evidence": payload})

    def next_ready(self) -> tuple[str, ...]:
        ready = []
        for task_id in self.graph.execution_order:
            if task_id in self.completed or task_id in self.failed:
                continue
            task = self.task(task_id)
            if all(dep in self.completed for dep in task.dependencies):
                ready.append(task_id)
        return tuple(ready)

    def to_dict(self) -> dict[str, Any]:
        return {
            "graph": self.graph.to_dict(),
            "completed": sorted(self.completed),
            "failed": sorted(self.failed),
            "next_ready": list(self.next_ready()),
            "evidence": dict(self.evidence),
            "history": list(self.history),
        }


class TaskGraphExecutor:
    """Build execution state and enforce graph dependency gates."""

    def start(
        self,
        graph: TaskGraph,
        *,
        preserve_completed: Iterable[str] = (),
    ) -> TaskExecutionState:
        if graph.blocked_tasks:
            raise RuntimeError(
                "Engineering task graph contains blocked tasks: "
                + ", ".join(graph.blocked_tasks)
            )
        if not graph.execution_order:
            raise RuntimeError("Engineering task graph has no executable order.")

        state = TaskExecutionState(graph=graph)
        known = {task.task_id for task in graph.tasks}
        state.completed.update(
            task_id for task_id in preserve_completed if task_id in known
        )
        return state
