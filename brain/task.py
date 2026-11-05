from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional


@dataclass
class Task:
    """
    Represents one executable step inside an ExecutionPlan.

    A task may execute either:

    1. A Skill
       Example: chat, search, reasoning

    2. A registered Action
       Example: file_action, notification_action

    Phase 3 also supports:
    - dependencies
    - result passing
    - retries
    - priorities
    - execution state
    - confirmation metadata
    """

    # ---------------------------------------------------------
    # Identity
    # ---------------------------------------------------------

    id: str
    name: str

    # Keep this for backwards compatibility with the existing
    # Planner / Executor / SkillRegistry architecture.
    skill: str = ""

    # ---------------------------------------------------------
    # Execution target
    # ---------------------------------------------------------

    # "skill" or "action"
    task_type: str = "skill"

    # Registered action name when task_type == "action".
    #
    # Example:
    # action_name = "file_action"
    action_name: Optional[str] = None

    # ---------------------------------------------------------
    # Inputs
    # ---------------------------------------------------------

    # Existing skill input.
    input: Dict[str, Any] = field(default_factory=dict)

    # Parameters supplied to ActionManager.
    #
    # Example:
    #
    # {
    #     "mode": "write",
    #     "path": "status.txt",
    #     "content": "build passed"
    # }
    params: Dict[str, Any] = field(default_factory=dict)

    # ---------------------------------------------------------
    # Dependencies
    # ---------------------------------------------------------

    # IDs of tasks that must complete before this task executes.
    depends_on: List[str] = field(default_factory=list)

    # ---------------------------------------------------------
    # Runtime state
    # ---------------------------------------------------------

    status: str = "pending"
    # pending
    # awaiting_confirmation
    # running
    # completed
    # failed
    # skipped

    max_retries: int = 2
    retry_count: int = 0

    priority: int = 1

    # ---------------------------------------------------------
    # Execution result
    # ---------------------------------------------------------

    output: Optional[Dict[str, Any]] = None

    error: Optional[str] = None

    execution_time_ms: float = 0.0

    # ---------------------------------------------------------
    # Permission / confirmation state
    # ---------------------------------------------------------

    requires_confirmation: bool = False

    confirmed: bool = False

    # ---------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------

    def is_action(self) -> bool:
        """
        Returns True when this task represents a registered action.
        """
        return (
            self.task_type == "action"
            and bool(self.action_name)
        )

    def is_skill(self) -> bool:
        """
        Returns True when this task represents a skill.
        """
        return self.task_type == "skill"

    def is_ready(
        self,
        completed_task_ids: List[str]
    ) -> bool:
        """
        Returns True when every dependency has completed
        and this task is still pending.
        """

        if self.status != "pending":
            return False

        return all(
            dependency in completed_task_ids
            for dependency in self.depends_on
        )

    def mark_running(self):
        self.status = "running"
        self.error = None

    def mark_completed(
        self,
        output: Optional[Dict[str, Any]] = None
    ):
        self.status = "completed"
        self.output = output or {}
        self.error = None

    def mark_failed(self, error: str):
        self.status = "failed"
        self.error = str(error)

    def mark_skipped(self, reason: Optional[str] = None):
        self.status = "skipped"

        if reason:
            self.error = str(reason)

    def mark_awaiting_confirmation(self):
        self.status = "awaiting_confirmation"
        self.requires_confirmation = True
        self.confirmed = False

    def confirm(self):
        self.confirmed = True
        self.requires_confirmation = False

        if self.status == "awaiting_confirmation":
            self.status = "pending"
