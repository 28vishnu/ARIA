"""
ARIA Phase 1 — Step 10: Multi-Task Phase Planner.

Creates structured multi-task execution plans without executing them.

Responsibilities:
- decompose a goal into ordered phases;
- represent dependencies between phases;
- merge explicit planner output when available;
- infer safe lightweight task structure when necessary;
- preserve existing ARIA Task / ExecutionPlan contracts;
- validate dependency graphs;
- expose ready/runnable tasks;
- remain execution-free.

This module does NOT execute tools, call agents, modify files, or perform
external actions. Execution belongs to the execution layer.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence

from brain.plan import ExecutionPlan
from brain.task import Task

logger = logging.getLogger("aria")


@dataclass(frozen=True)
class PhaseDefinition:
    """Immutable definition of one planning phase."""

    name: str
    description: str
    skill: str
    phase_type: str = "execution"
    depends_on: tuple[str, ...] = ()
    priority: int = 1
    requires_confirmation: bool = False
    input: Dict[str, Any] = field(
        default_factory=dict
    )


class PhasePlanner:
    """
    Multi-task planning layer for ARIA.

    The planner produces an ExecutionPlan but never executes it.

    Architecture:

        Goal
          ↓
        Analyze
          ↓
        Decompose
          ↓
        Dependency Graph
          ↓
        Validate
          ↓
        Optimize
          ↓
        ExecutionPlan
    """

    VERSION = "PHASE1-MULTI-TASK-PLANNER-20261004"

    MAX_TASKS = 32
    MAX_DEPENDENCIES_PER_TASK = 8

    DEFAULT_PRIORITY = {
        "research": 7,
        "planning": 8,
        "coding": 9,
        "testing": 9,
        "verification": 10,
        "writing": 6,
        "chat": 3,
        "general": 5,
    }

    def __init__(
        self,
        existing_planner=None,
        skill_manager=None,
        action_manager=None,
        knowledge_manager=None,
    ) -> None:

        self.existing_planner = (
            existing_planner
        )

        self.skill_manager = (
            skill_manager
        )

        self.action_manager = (
            action_manager
        )

        self.knowledge_manager = (
            knowledge_manager
        )

        self.statistics = {
            "plans_created": 0,
            "plans_rejected": 0,
            "plans_optimized": 0,
            "tasks_created": 0,
            "dependency_repairs": 0,
        }

    # =========================================================
    # PUBLIC API
    # =========================================================

    async def create_plan(
        self,
        goal: str,
        context: Optional[Dict[str, Any]] = None,
        explicit_phases: Optional[
            Sequence[Dict[str, Any] | PhaseDefinition]
        ] = None,
    ) -> ExecutionPlan:
        """
        Create a multi-task ExecutionPlan.

        Priority:

        1. Explicit phases supplied by caller.
        2. Existing planner decomposition.
        3. Deterministic phase inference.
        """

        context = (
            context
            if isinstance(context, dict)
            else {}
        )

        goal = self._normalize_text(
            goal
        )

        if not goal:
            self.statistics[
                "plans_rejected"
            ] += 1

            return ExecutionPlan(
                goal="",
                tasks=[],
                confidence=0.0,
                metadata={
                    "planner": self.VERSION,
                    "error": "empty_goal",
                },
            )

        phases = []

        # -----------------------------------------------------
        # Explicit phases
        # -----------------------------------------------------

        if explicit_phases:
            phases = self._normalize_phases(
                explicit_phases
            )

        # -----------------------------------------------------
        # Existing planner
        # -----------------------------------------------------

        if not phases:
            phases = await self._from_existing_planner(
                goal=goal,
                context=context,
            )

        # -----------------------------------------------------
        # Deterministic fallback
        # -----------------------------------------------------

        if not phases:
            phases = self.infer_phases(
                goal
            )

        phases = self._bound_phases(
            phases
        )

        tasks = self._phases_to_tasks(
            goal=goal,
            phases=phases,
            context=context,
        )

        plan = ExecutionPlan(
            goal=goal,
            tasks=tasks,
            confidence=self._calculate_confidence(
                phases
            ),
            metadata={
                "planner": self.VERSION,
                "phase_count": len(phases),
                "task_count": len(tasks),
                "planning_only": True,
                "execution_started": False,
            },
        )

        if not self.validate_plan(
            plan
        ):
            self.statistics[
                "plans_rejected"
            ] += 1

            plan.confidence = 0.0
            plan.metadata[
                "validation_failed"
            ] = True

            return plan

        plan = self.optimize_plan(
            plan
        )

        self.statistics[
            "plans_created"
        ] += 1

        self.statistics[
            "tasks_created"
        ] += len(
            plan.tasks
        )

        return plan

    def infer_phases(
        self,
        goal: str,
    ) -> List[PhaseDefinition]:
        """
        Deterministically infer a sensible phase graph.

        This is deliberately conservative. It creates only the phases
        that can be justified by the request.
        """

        text = goal.casefold()

        is_building = any(
            keyword in text
            for keyword in (
                "build",
                "create",
                "develop",
                "implement",
                "make",
                "developing",
            )
        )

        is_coding = any(
            keyword in text
            for keyword in (
                "code",
                "coding",
                "program",
                "script",
                "debug",
                "fix",
                "api",
                "software",
                "app",
                "application",
            )
        )

        is_research = any(
            keyword in text
            for keyword in (
                "research",
                "find",
                "investigate",
                "analyze",
                "analyse",
                "compare",
                "study",
            )
        )

        is_writing = any(
            keyword in text
            for keyword in (
                "write",
                "draft",
                "email",
                "essay",
                "report",
                "document",
                "summarize",
                "summary",
            )
        )

        is_plan_request = any(
            keyword in text
            for keyword in (
                "plan",
                "roadmap",
                "strategy",
                "schedule",
            )
        )

        phases: List[
            PhaseDefinition
        ] = []

        if is_building or is_coding:

            if is_research:
                phases.append(
                    PhaseDefinition(
                        name="research",
                        description=(
                            "Research requirements, "
                            "constraints and relevant "
                            "technical information."
                        ),
                        skill="research",
                        phase_type="research",
                        priority=7,
                    )
                )

            phases.append(
                PhaseDefinition(
                    name="planning",
                    description=(
                        "Design the implementation "
                        "approach and task sequence."
                    ),
                    skill="planning",
                    phase_type="planning",
                    depends_on=(
                        ("research",)
                        if is_research
                        else ()
                    ),
                    priority=8,
                )
            )

            phases.append(
                PhaseDefinition(
                    name="implementation",
                    description=(
                        "Implement the requested "
                        "software changes."
                    ),
                    skill="coding",
                    phase_type="execution",
                    depends_on=("planning",),
                    priority=9,
                )
            )

            phases.append(
                PhaseDefinition(
                    name="testing",
                    description=(
                        "Test the implementation and "
                        "identify failures."
                    ),
                    skill="testing",
                    phase_type="verification",
                    depends_on=(
                        "implementation",
                    ),
                    priority=9,
                )
            )

            phases.append(
                PhaseDefinition(
                    name="verification",
                    description=(
                        "Verify that the requested "
                        "goal has been satisfied."
                    ),
                    skill="verification",
                    phase_type="verification",
                    depends_on=(
                        "testing",
                    ),
                    priority=10,
                )
            )

            return phases

        if is_research:

            phases.append(
                PhaseDefinition(
                    name="research",
                    description=goal,
                    skill="research",
                    phase_type="research",
                    priority=7,
                )
            )

            if is_writing:
                phases.append(
                    PhaseDefinition(
                        name="writing",
                        description=(
                            "Prepare a clear result "
                            "from the research."
                        ),
                        skill="writing",
                        phase_type="output",
                        depends_on=(
                            "research",
                        ),
                        priority=6,
                    )
                )

            return phases

        if is_plan_request:

            phases.append(
                PhaseDefinition(
                    name="planning",
                    description=goal,
                    skill="planning",
                    phase_type="planning",
                    priority=8,
                )
            )

            if is_writing:
                phases.append(
                    PhaseDefinition(
                        name="writing",
                        description=(
                            "Present the resulting "
                            "plan clearly."
                        ),
                        skill="writing",
                        phase_type="output",
                        depends_on=(
                            "planning",
                        ),
                        priority=6,
                    )
                )

            return phases

        if is_writing:

            return [
                PhaseDefinition(
                    name="writing",
                    description=goal,
                    skill="writing",
                    phase_type="output",
                    priority=6,
                )
            ]

        return [
            PhaseDefinition(
                name="response",
                description=goal,
                skill="chat",
                phase_type="response",
                priority=3,
            )
        ]

    # =========================================================
    # EXISTING PLANNER ADAPTER
    # =========================================================

    async def _from_existing_planner(
        self,
        goal: str,
        context: Dict[str, Any],
    ) -> List[PhaseDefinition]:

        planner = self.existing_planner

        if planner is None:
            return []

        method = getattr(
            planner,
            "decompose_goal",
            None,
        )

        if method is None:
            return []

        try:
            result = method(
                goal
            )

            if hasattr(
                result,
                "__await__",
            ):
                result = await result

        except Exception:
            logger.exception(
                "[PhasePlanner] "
                "Existing planner decomposition failed."
            )
            return []

        if not isinstance(
            result,
            (list, tuple),
        ):
            return []

        phases: List[
            PhaseDefinition
        ] = []

        previous: Optional[
            str
        ] = None

        for index, item in enumerate(
            result,
            start=1,
        ):

            text = self._normalize_text(
                item
            )

            if not text:
                continue

            name = self._phase_name(
                text,
                index,
            )

            skill = self._skill_for_text(
                text
            )

            dependencies = (
                (previous,)
                if previous
                else ()
            )

            phases.append(
                PhaseDefinition(
                    name=name,
                    description=text,
                    skill=skill,
                    phase_type="execution",
                    depends_on=dependencies,
                    priority=self._priority_for_skill(
                        skill
                    ),
                )
            )

            previous = name

        return phases

    # =========================================================
    # NORMALIZATION
    # =========================================================

    def _normalize_phases(
        self,
        phases: Sequence[
            Dict[str, Any] | PhaseDefinition
        ],
    ) -> List[PhaseDefinition]:

        result: List[
            PhaseDefinition
        ] = []

        for index, raw in enumerate(
            phases,
            start=1,
        ):

            if isinstance(
                raw,
                PhaseDefinition,
            ):
                result.append(raw)
                continue

            if not isinstance(
                raw,
                dict,
            ):
                continue

            name = self._normalize_text(
                raw.get(
                    "name"
                )
                or raw.get(
                    "id"
                )
                or f"phase_{index}"
            )

            description = self._normalize_text(
                raw.get(
                    "description"
                )
                or raw.get(
                    "task"
                )
                or name
            )

            skill = self._normalize_text(
                raw.get(
                    "skill"
                )
                or raw.get(
                    "agent"
                )
                or self._skill_for_text(
                    description
                )
            )

            dependencies = raw.get(
                "depends_on",
                (),
            )

            if isinstance(
                dependencies,
                str,
            ):
                dependencies = (
                    dependencies,
                )

            if not isinstance(
                dependencies,
                (list, tuple, set),
            ):
                dependencies = ()

            try:
                priority = int(
                    raw.get(
                        "priority",
                        self._priority_for_skill(
                            skill
                        ),
                    )
                )
            except (
                TypeError,
                ValueError,
            ):
                priority = self._priority_for_skill(
                    skill
                )

            result.append(
                PhaseDefinition(
                    name=name,
                    description=description,
                    skill=skill,
                    phase_type=self._normalize_text(
                        raw.get(
                            "phase_type",
                            "execution",
                        )
                    ),
                    depends_on=tuple(
                        self._normalize_text(
                            item
                        )
                        for item in dependencies
                        if self._normalize_text(
                            item
                        )
                    ),
                    priority=max(
                        1,
                        min(
                            100,
                            priority,
                        ),
                    ),
                    requires_confirmation=bool(
                        raw.get(
                            "requires_confirmation",
                            False,
                        )
                    ),
                    input=(
                        dict(
                            raw.get(
                                "input",
                                {},
                            )
                        )
                        if isinstance(
                            raw.get(
                                "input",
                                {},
                            ),
                            dict,
                        )
                        else {}
                    ),
                )
            )

        return result

    def _bound_phases(
        self,
        phases: Sequence[
            PhaseDefinition
        ],
    ) -> List[
        PhaseDefinition
    ]:

        result = list(
            phases[
                : self.MAX_TASKS
            ]
        )

        if len(result) != len(
            phases
        ):
            logger.warning(
                "[PhasePlanner] "
                "Phase list truncated to %d tasks.",
                self.MAX_TASKS,
            )

        return result

    # =========================================================
    # TASK GRAPH
    # =========================================================

    def _phases_to_tasks(
        self,
        goal: str,
        phases: Sequence[
            PhaseDefinition
        ],
        context: Dict[str, Any],
    ) -> List[Task]:

        names = {
            phase.name
            for phase in phases
        }

        tasks: List[Task] = []

        for index, phase in enumerate(
            phases,
            start=1,
        ):

            task_id = (
                f"phase_{index}"
            )

            dependencies: List[
                str
            ] = []

            for dependency in (
                phase.depends_on
            ):

                dependency = str(
                    dependency
                ).strip()

                if dependency in names:
                    dependency_index = (
                        self._phase_index(
                            phases,
                            dependency,
                        )
                    )

                    if dependency_index:
                        dependencies.append(
                            f"phase_{dependency_index}"
                        )

            dependencies = list(
                dict.fromkeys(
                    dependencies[
                        : self.MAX_DEPENDENCIES_PER_TASK
                    ]
                )
            )

            task_input = dict(
                phase.input
            )

            task_input.setdefault(
                "goal",
                goal,
            )

            task_input.setdefault(
                "phase",
                phase.name,
            )

            task_input.setdefault(
                "phase_type",
                phase.phase_type,
            )

            task_input.setdefault(
                "context",
                context,
            )

            task = Task(
                id=task_id,
                name=phase.description,
                skill=phase.skill,
                task_type="skill",
                input=task_input,
                depends_on=dependencies,
                priority=phase.priority,
                requires_confirmation=(
                    phase.requires_confirmation
                ),
            )

            tasks.append(
                task
            )

        return tasks

    @staticmethod
    def _phase_index(
        phases: Sequence[
            PhaseDefinition
        ],
        name: str,
    ) -> Optional[int]:

        for index, phase in enumerate(
            phases,
            start=1,
        ):
            if phase.name == name:
                return index

        return None

    # =========================================================
    # VALIDATION
    # =========================================================

    def validate_plan(
        self,
        plan: ExecutionPlan,
    ) -> bool:
        """
        Validate task identity, dependency references and cycles.
        """

        if not plan:
            return False

        if not plan.tasks:
            return False

        if len(plan.tasks) > self.MAX_TASKS:
            return False

        task_map = {
            task.id: task
            for task in plan.tasks
        }

        if len(task_map) != len(
            plan.tasks
        ):
            return False

        for task in plan.tasks:

            if not task.id:
                return False

            if not task.skill:
                return False

            if len(
                task.depends_on
            ) > self.MAX_DEPENDENCIES_PER_TASK:
                return False

            for dependency in (
                task.depends_on
            ):

                if dependency not in task_map:
                    return False

                if dependency == task.id:
                    return False

        # DFS cycle detection.
        visiting = set()
        visited = set()

        def visit(
            task_id: str,
        ) -> bool:

            if task_id in visiting:
                return False

            if task_id in visited:
                return True

            visiting.add(
                task_id
            )

            for dependency in (
                task_map[
                    task_id
                ].depends_on
            ):

                if not visit(
                    dependency
                ):
                    return False

            visiting.remove(
                task_id
            )

            visited.add(
                task_id
            )

            return True

        return all(
            visit(task.id)
            for task in plan.tasks
        )

    # =========================================================
    # OPTIMIZATION
    # =========================================================

    def optimize_plan(
        self,
        plan: ExecutionPlan,
    ) -> ExecutionPlan:

        if not plan.tasks:
            return plan

        unique_tasks: List[
            Task
        ] = []

        signatures = set()

        for task in plan.tasks:

            signature = (
                task.skill,
                task.name.casefold(),
                tuple(
                    sorted(
                        task.depends_on
                    )
                ),
            )

            if signature in signatures:
                continue

            signatures.add(
                signature
            )

            unique_tasks.append(
                task
            )

        if len(unique_tasks) != len(
            plan.tasks
        ):
            self.statistics[
                "plans_optimized"
            ] += 1

        plan.tasks = (
            unique_tasks
        )

        # Recalculate metadata after optimization.
        plan.metadata.update(
            {
                "task_count": len(
                    plan.tasks
                ),
                "estimated_steps": len(
                    plan.tasks
                ),
                "estimated_time_seconds": (
                    sum(
                        self._estimated_seconds(
                            task
                        )
                        for task in plan.tasks
                    )
                ),
                "dependency_edges": sum(
                    len(
                        task.depends_on
                    )
                    for task in plan.tasks
                ),
            }
        )

        return plan

    # =========================================================
    # READY TASKS
    # =========================================================

    def get_ready_tasks(
        self,
        plan: ExecutionPlan,
    ) -> List[Task]:
        """
        Return tasks whose dependencies are complete.

        Tasks requiring confirmation are returned but remain pending;
        the executor is responsible for approval handling.
        """

        completed = set(
            plan.completed_tasks
        )

        ready = [
            task
            for task in plan.tasks
            if task.is_ready(
                list(completed)
            )
        ]

        ready.sort(
            key=lambda task: (
                -task.priority,
                task.id,
            )
        )

        return ready

    def get_execution_waves(
        self,
        plan: ExecutionPlan,
    ) -> List[List[str]]:
        """
        Convert the dependency graph into parallel-safe execution waves.

        Tasks in the same wave have no dependency on another task in
        that same wave.
        """

        task_map = {
            task.id: task
            for task in plan.tasks
        }

        completed = set()
        waves: List[
            List[str]
        ] = []

        remaining = set(
            task_map
        )

        while remaining:

            current: List[
                str
            ] = []

            for task_id in sorted(
                remaining
            ):

                task = task_map[
                    task_id
                ]

                if all(
                    dependency in completed
                    for dependency in task.depends_on
                ):
                    current.append(
                        task_id
                    )

            if not current:
                # Dependency cycle or invalid graph.
                return []

            waves.append(
                current
            )

            completed.update(
                current
            )

            remaining.difference_update(
                current
            )

        return waves

    # =========================================================
    # HELPERS
    # =========================================================

    @staticmethod
    def _normalize_text(
        value: Any,
    ) -> str:

        text = str(
            value or ""
        )

        text = re.sub(
            r"\s+",
            " ",
            text,
        ).strip()

        return text

    def _phase_name(
        self,
        text: str,
        index: int,
    ) -> str:

        normalized = re.sub(
            r"[^a-z0-9]+",
            "_",
            text.casefold(),
        ).strip("_")

        if not normalized:
            normalized = (
                f"phase_{index}"
            )

        return normalized[
            :64
        ]

    def _skill_for_text(
        self,
        text: str,
    ) -> str:

        lower = text.casefold()

        if any(
            word in lower
            for word in (
                "test",
                "verify",
                "validate",
                "check",
            )
        ):
            return "testing"

        if any(
            word in lower
            for word in (
                "code",
                "implement",
                "develop",
                "debug",
                "program",
                "script",
            )
        ):
            return "coding"

        if any(
            word in lower
            for word in (
                "research",
                "investigate",
                "find",
                "analyze",
                "analyse",
            )
        ):
            return "research"

        if any(
            word in lower
            for word in (
                "plan",
                "design",
                "architecture",
                "strategy",
            )
        ):
            return "planning"

        if any(
            word in lower
            for word in (
                "write",
                "draft",
                "summarize",
                "document",
            )
        ):
            return "writing"

        return "chat"

    def _priority_for_skill(
        self,
        skill: str,
    ) -> int:

        return self.DEFAULT_PRIORITY.get(
            skill.casefold(),
            5,
        )

    @staticmethod
    def _estimated_seconds(
        task: Task,
    ) -> int:

        values = {
            "research": 8,
            "planning": 5,
            "coding": 20,
            "testing": 10,
            "verification": 8,
            "writing": 8,
            "chat": 3,
        }

        return values.get(
            task.skill.casefold(),
            5,
        )

    @staticmethod
    def _calculate_confidence(
        phases: Sequence[
            PhaseDefinition
        ],
    ) -> float:

        if not phases:
            return 0.0

        confidence = 0.70

        if len(phases) > 1:
            confidence += 0.05

        if all(
            phase.skill
            for phase in phases
        ):
            confidence += 0.05

        if all(
            len(
                phase.depends_on
            ) <= 8
            for phase in phases
        ):
            confidence += 0.05

        return min(
            1.0,
            confidence,
        )

    def describe(
        self,
    ) -> Dict[str, Any]:

        return {
            "version": self.VERSION,
            "role": (
                "multi-task phase planning"
            ),
            "execution": False,
            "max_tasks": self.MAX_TASKS,
            "max_dependencies_per_task": (
                self.MAX_DEPENDENCIES_PER_TASK
            ),
            "features": [
                "goal decomposition",
                "phase graph",
                "dependency validation",
                "cycle detection",
                "execution waves",
                "ready-task selection",
                "plan optimization",
                "existing-planner adapter",
            ],
        }


__all__ = [
    "PhaseDefinition",
    "PhasePlanner",
]