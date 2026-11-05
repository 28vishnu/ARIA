from __future__ import annotations

"""
ARIA Phase 1 — Step 44
Intelligent Task Graph

Builds a dependency-aware engineering graph from the adaptive plan,
repository evidence, generated changes, tests, and failure evidence.

The graph is deterministic and read-only. It does not execute commands,
write files, deploy, or bypass safety controls.
"""

from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass(frozen=True)
class EngineeringTask:
    task_id: str
    kind: str
    title: str
    description: str
    dependencies: tuple[str, ...] = ()
    evidence_required: tuple[str, ...] = ()
    verification: tuple[str, ...] = ()
    priority: int = 50
    risk: str = "normal"
    status: str = "pending"
    related_paths: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "kind": self.kind,
            "title": self.title,
            "description": self.description,
            "dependencies": list(self.dependencies),
            "evidence_required": list(self.evidence_required),
            "verification": list(self.verification),
            "priority": self.priority,
            "risk": self.risk,
            "status": self.status,
            "related_paths": list(self.related_paths),
        }


@dataclass(frozen=True)
class TaskGraph:
    tasks: tuple[EngineeringTask, ...] = ()
    execution_order: tuple[str, ...] = ()
    parallel_groups: tuple[tuple[str, ...], ...] = ()
    blocked_tasks: tuple[str, ...] = ()
    graph_warnings: tuple[str, ...] = ()
    confidence: str = "medium"

    def to_dict(self) -> dict[str, Any]:
        return {
            "tasks": [task.to_dict() for task in self.tasks],
            "execution_order": list(self.execution_order),
            "parallel_groups": [list(group) for group in self.parallel_groups],
            "blocked_tasks": list(self.blocked_tasks),
            "graph_warnings": list(self.graph_warnings),
            "confidence": self.confidence,
        }

    def task(self, task_id: str) -> EngineeringTask | None:
        for item in self.tasks:
            if item.task_id == task_id:
                return item
        return None


class IntelligentTaskGraph:
    VERSION = "PHASE1-TASK-GRAPH-20261004"

    def build(
        self,
        *,
        requirement: Any = None,
        plan: Any = None,
        repository_reasoning: Any = None,
        generated_changes: Iterable[Any] = (),
        selected_tests: Iterable[str] = (),
        failure: Any = None,
        validation: Any = None,
    ) -> TaskGraph:
        tasks: list[EngineeringTask] = []
        warnings: list[str] = []

        changes = tuple(generated_changes or ())
        tests = tuple(
            str(item).strip()
            for item in selected_tests
            if str(item).strip()
        )

        # Stable foundational task.
        tasks.append(
            EngineeringTask(
                task_id="understand",
                kind="reason",
                title="Understand requirement and repository",
                description=(
                    "Confirm the engineering objective, repository architecture, "
                    "constraints, and affected areas before implementation."
                ),
                evidence_required=(
                    "requirement analysis",
                    "repository reasoning",
                    "change impact",
                ),
                verification=("objective is understood",),
                priority=100,
            )
        )

        change_paths = tuple(
            self._change_path(item)
            for item in changes
            if self._change_path(item)
        )

        # One implementation node per coherent change group.
        implementation_id = "implement"
        tasks.append(
            EngineeringTask(
                task_id=implementation_id,
                kind="implement",
                title="Implement coherent change set",
                description=(
                    "Apply the smallest coherent implementation that satisfies "
                    "the requirement while preserving existing architecture."
                ),
                dependencies=("understand",),
                evidence_required=(
                    "repository reasoning",
                    "adaptive plan",
                ),
                verification=("generated changes pass safety validation",),
                priority=90,
                risk=(
                    "high"
                    if self._has_shared_paths(repository_reasoning, change_paths)
                    else "normal"
                ),
                related_paths=change_paths,
            )
        )

        validation_id = "validate"
        tasks.append(
            EngineeringTask(
                task_id=validation_id,
                kind="validate",
                title="Run static validation",
                description=(
                    "Check the resulting workspace for syntax, structural, "
                    "safety, and repository-level validation failures."
                ),
                dependencies=(implementation_id,),
                evidence_required=("workspace changes",),
                verification=("static validation passes",),
                priority=80,
                related_paths=change_paths,
            )
        )

        test_id = "test"
        tasks.append(
            EngineeringTask(
                task_id=test_id,
                kind="test",
                title="Run targeted verification",
                description=(
                    "Execute the most relevant tests supported by the requirement "
                    "and changed areas, expanding scope when evidence requires it."
                ),
                dependencies=(validation_id,),
                evidence_required=("validated workspace",),
                verification=("targeted tests pass",),
                priority=80,
                related_paths=tests,
            )
        )

        if failure is not None:
            tasks.append(
                EngineeringTask(
                    task_id="diagnose",
                    kind="diagnose",
                    title="Diagnose observed failure",
                    description=(
                        "Use actual failure evidence to determine root cause; "
                        "do not assume an unfamiliar category is the root cause."
                    ),
                    dependencies=(test_id,),
                    evidence_required=(
                        "test result",
                        "stdout/stderr",
                        "exit status",
                    ),
                    verification=("root cause has supporting evidence",),
                    priority=95,
                    risk="normal",
                    related_paths=change_paths + tests,
                )
            )
            tasks.append(
                EngineeringTask(
                    task_id="repair",
                    kind="repair",
                    title="Repair root cause",
                    description=(
                        "Apply the smallest evidence-backed repair and preserve "
                        "the original requirement and safety constraints."
                    ),
                    dependencies=("diagnose",),
                    evidence_required=("root-cause diagnosis",),
                    verification=("repair is validated and retested",),
                    priority=90,
                    risk="high",
                    related_paths=change_paths,
                )
            )
            tasks.append(
                EngineeringTask(
                    task_id="retest",
                    kind="test",
                    title="Retest after repair",
                    description=(
                        "Re-run verification after the repair and reassess the "
                        "engineering plan if evidence changed."
                    ),
                    dependencies=("repair",),
                    evidence_required=("repair result",),
                    verification=("failure resolved or new evidence obtained",),
                    priority=85,
                    related_paths=tests,
                )
            )
            tasks.append(
                EngineeringTask(
                    task_id="reassess",
                    kind="reason",
                    title="Reassess engineering state",
                    description=(
                        "Compare new evidence with acceptance criteria and decide "
                        "whether to continue, revise, or stop."
                    ),
                    dependencies=("retest",),
                    evidence_required=("latest verification evidence",),
                    verification=("next action is evidence-backed",),
                    priority=100,
                )
            )
            final_dependency = "reassess"
        else:
            final_dependency = test_id

        tasks.append(
            EngineeringTask(
                task_id="accept",
                kind="accept",
                title="Evaluate acceptance",
                description=(
                    "Judge the complete requirement against explicit acceptance "
                    "criteria rather than treating file creation or one passing "
                    "command as proof of success."
                ),
                dependencies=(final_dependency,),
                evidence_required=(
                    "acceptance criteria",
                    "final validation evidence",
                ),
                verification=("all applicable acceptance criteria pass",),
                priority=100,
            )
        )

        # Detect impossible dependency references defensively.
        known = {task.task_id for task in tasks}
        for task in tasks:
            missing = [
                dep for dep in task.dependencies
                if dep not in known
            ]
            if missing:
                warnings.append(
                    f"{task.task_id} references missing dependencies: {missing}"
                )

        order = self._topological_order(tasks)
        groups = self._parallel_groups(tasks, order)
        blocked = tuple(
            task.task_id
            for task in tasks
            if any(dep not in known for dep in task.dependencies)
        )

        confidence = "high"
        if warnings or not order:
            confidence = "low"
        elif repository_reasoning is None:
            confidence = "medium"

        return TaskGraph(
            tasks=tuple(tasks),
            execution_order=tuple(order),
            parallel_groups=tuple(groups),
            blocked_tasks=blocked,
            graph_warnings=tuple(warnings),
            confidence=confidence,
        )

    def build_prompt_section(self, graph: TaskGraph) -> str:
        lines = [
            "",
            "INTELLIGENT ENGINEERING TASK GRAPH:",
            f"Graph version: {self.VERSION}",
            f"Graph confidence: {graph.confidence}",
            "",
            "Execution order:",
        ]

        if graph.execution_order:
            for index, task_id in enumerate(
                graph.execution_order,
                start=1,
            ):
                task = graph.task(task_id)
                if task is None:
                    continue
                lines.append(
                    f"{index}. [{task.kind}] {task.task_id}: {task.title}"
                )
        else:
            lines.append("- No executable order could be established.")

        lines.extend(["", "Parallel-safe groups:"])
        for group in graph.parallel_groups:
            lines.append("- " + ", ".join(group))

        lines.extend(["", "Task details:"])
        for task in graph.tasks:
            lines.append(
                f"- {task.task_id}: dependencies="
                f"{list(task.dependencies)}; priority={task.priority}; "
                f"risk={task.risk}; verify={list(task.verification)}"
            )

        if graph.blocked_tasks:
            lines.extend(["", "Blocked tasks:"])
            for task_id in graph.blocked_tasks:
                lines.append(f"- {task_id}")

        if graph.graph_warnings:
            lines.extend(["", "Graph warnings:"])
            for warning in graph.graph_warnings:
                lines.append(f"- {warning}")

        lines.extend(
            [
                "",
                "Task-graph rules:",
                "- Do not execute a task before its dependencies are satisfied.",
                "- Prefer the highest-priority unblocked task whose evidence is sufficient.",
                "- Parallelize only tasks with no dependency relationship and no shared mutable target.",
                "- Verification tasks are gates, not optional suggestions.",
                "- If evidence invalidates the current graph, rebuild or revise it instead of blindly continuing.",
                "- Never bypass deterministic safety, workspace, permission, or acceptance controls.",
            ]
        )

        return "\n".join(lines)

    @staticmethod
    def _change_path(change: Any) -> str:
        if isinstance(change, dict):
            value = change.get("path", "")
        else:
            value = getattr(change, "path", "")
        return str(value).replace("\\", "/").strip()

    @staticmethod
    def _has_shared_paths(
        repository_reasoning: Any,
        change_paths: tuple[str, ...],
    ) -> bool:
        if not change_paths or repository_reasoning is None:
            return False

        impact_map = getattr(
            repository_reasoning,
            "impact_map",
            {},
        ) or {}

        normalized = set(change_paths)
        return any(
            str(path) in impact_map
            and bool(impact_map.get(path))
            for path in normalized
        )

    @staticmethod
    def _topological_order(
        tasks: list[EngineeringTask],
    ) -> list[str]:
        remaining = {task.task_id: task for task in tasks}
        completed: set[str] = set()
        order: list[str] = []

        while remaining:
            ready = [
                task
                for task in remaining.values()
                if all(dep in completed for dep in task.dependencies)
            ]

            if not ready:
                break

            ready.sort(
                key=lambda item: (-item.priority, item.task_id)
            )

            for task in ready:
                order.append(task.task_id)
                completed.add(task.task_id)
                remaining.pop(task.task_id, None)

        return order

    @staticmethod
    def _parallel_groups(
        tasks: list[EngineeringTask],
        order: list[str],
    ) -> list[tuple[str, ...]]:
        by_id = {task.task_id: task for task in tasks}
        groups: list[tuple[str, ...]] = []

        for task_id in order:
            task = by_id[task_id]
            placed = False

            for index, group in enumerate(groups):
                group_tasks = [by_id[item] for item in group]
                if (
                    not task.dependencies
                    and all(
                        not other.dependencies
                        for other in group_tasks
                    )
                    and not set(task.related_paths).intersection(
                        *[
                            set(other.related_paths)
                            for other in group_tasks
                        ]
                    )
                ):
                    groups[index] = group + (task_id,)
                    placed = True
                    break

            if not placed:
                groups.append((task_id,))

        return groups
