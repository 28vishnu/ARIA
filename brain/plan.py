from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

from brain.task import Task


@dataclass
class ExecutionPlan:
    """
    Represents a complete executable workflow produced by the Planner.

    Phase 3 capabilities:
    - multiple dependent tasks
    - skill + action tasks
    - execution progress tracking
    - workflow pause/resume
    - confirmation state
    - task result propagation
    """

    # =========================================================
    # PLAN IDENTITY
    # =========================================================

    goal: str

    tasks: List[Task] = field(
        default_factory=list
    )

    confidence: float = 0.0

    metadata: Dict[str, Any] = field(
        default_factory=dict
    )

    # =========================================================
    # EXECUTION STATE
    # =========================================================

    status: str = "pending"
    # pending
    # running
    # awaiting_confirmation
    # completed
    # failed
    # cancelled

    completed_tasks: List[str] = field(
        default_factory=list
    )

    failed_tasks: List[str] = field(
        default_factory=list
    )

    skipped_tasks: List[str] = field(
        default_factory=list
    )

    # Results produced by completed tasks.
    #
    # Example:
    #
    # {
    #     "read_file": {
    #         "content": "Hello JARVIS"
    #     }
    # }
    task_outputs: Dict[str, Any] = field(
        default_factory=dict
    )

    # =========================================================
    # WORKFLOW SUSPENSION / CONFIRMATION
    # =========================================================

    awaiting_task_id: Optional[str] = None

    requires_confirmation: bool = False

    # =========================================================
    # FAILURE STATE
    # =========================================================

    error: Optional[str] = None

    # =========================================================
    # HELPERS
    # =========================================================

    def get_task(
        self,
        task_id: str
    ) -> Optional[Task]:
        """
        Find a task by ID.
        """

        for task in self.tasks:

            if task.id == task_id:
                return task

        return None

    def get_pending_tasks(self) -> List[Task]:
        """
        Return tasks that have not yet completed execution.
        """

        return [
            task
            for task in self.tasks
            if task.status in (
                "pending",
                "awaiting_confirmation",
            )
        ]

    def get_completed_task_ids(self) -> List[str]:
        """
        Return completed task IDs.
        """

        return list(
            self.completed_tasks
        )

    def is_complete(self) -> bool:
        """
        Determine whether every task reached a terminal state.
        """

        if not self.tasks:
            return True

        terminal_states = {
            "completed",
            "failed",
            "skipped",
        }

        return all(
            task.status in terminal_states
            for task in self.tasks
        )

    def has_failures(self) -> bool:
        """
        Return True when at least one task failed.
        """

        return bool(
            self.failed_tasks
        )

    # =========================================================
    # PLAN LIFECYCLE
    # =========================================================

    def mark_running(self):
        self.status = "running"
        self.error = None

    def mark_awaiting_confirmation(
        self,
        task_id: str
    ):
        """
        Pause the workflow because a task requires approval.
        """

        self.status = "awaiting_confirmation"

        self.awaiting_task_id = task_id

        self.requires_confirmation = True

    def clear_confirmation(self):
        """
        Clear workflow confirmation state after approval.
        """

        self.awaiting_task_id = None

        self.requires_confirmation = False

        if self.status == "awaiting_confirmation":
            self.status = "pending"

    def mark_completed(self):
        self.status = "completed"

        self.awaiting_task_id = None
        self.requires_confirmation = False
        self.error = None

    def mark_failed(
        self,
        error: Optional[str] = None
    ):
        self.status = "failed"

        self.awaiting_task_id = None
        self.requires_confirmation = False

        self.error = (
            str(error)
            if error
            else "Workflow execution failed."
        )

    def mark_cancelled(self):
        self.status = "cancelled"

        self.awaiting_task_id = None
        self.requires_confirmation = False

    # =========================================================
    # EXECUTION PROGRESS
    # =========================================================

    def record_completed_task(
        self,
        task_id: str,
        output: Optional[Dict[str, Any]] = None
    ):
        """
        Record successful task execution.
        """

        if task_id not in self.completed_tasks:
            self.completed_tasks.append(
                task_id
            )

        if output is not None:
            self.task_outputs[
                task_id
            ] = output

        if task_id in self.failed_tasks:
            self.failed_tasks.remove(
                task_id
            )

        if task_id in self.skipped_tasks:
            self.skipped_tasks.remove(
                task_id
            )

    def record_failed_task(
        self,
        task_id: str
    ):
        """
        Record task failure.
        """

        if task_id not in self.failed_tasks:
            self.failed_tasks.append(
                task_id
            )

    def record_skipped_task(
        self,
        task_id: str
    ):
        """
        Record a skipped task.
        """

        if task_id not in self.skipped_tasks:
            self.skipped_tasks.append(
                task_id
            )

    # =========================================================
    # VALIDATION
    # =========================================================

    def validate_dependencies(self) -> bool:
        """
        Validate that all dependency IDs refer to real tasks.

        Also rejects a task depending directly on itself.
        """

        task_ids = {
            task.id
            for task in self.tasks
        }

        for task in self.tasks:

            for dependency in task.depends_on:

                if dependency not in task_ids:
                    return False

                if dependency == task.id:
                    return False

        return True