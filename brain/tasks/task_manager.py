from dataclasses import dataclass, field
from datetime import datetime
import uuid
import logging

logger = logging.getLogger("aria")


@dataclass
class Task:

    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    title: str = ""

    description: str = ""

    goal_id: str | None = None

    status: str = "active"
    # active
    # paused
    # completed
    # failed

    progress: float = 0.0

    milestones: list = field(default_factory=list)

    completed_steps: list = field(default_factory=list)

    metadata: dict = field(default_factory=dict)

    created_at: datetime = field(default_factory=datetime.utcnow)

    updated_at: datetime = field(default_factory=datetime.utcnow)


class TaskManager:

    def __init__(self):

        self.tasks = []

    def create_task(
        self,
        title,
        description="",
        goal_id=None,
        metadata=None,
    ):

        task = Task(
            title=title,
            description=description,
            goal_id=goal_id,
            metadata=metadata or {}
        )

        self.tasks.append(task)

        logger.info(
            "[TaskManager] Created task: %s",
            title,
        )

        return task

    def current_task(self):

        for task in reversed(self.tasks):

            if task.status == "active":

                return task

        return None

    def find_task(self, query: str):

        query = query.lower()

        for task in reversed(self.tasks):

            if task.title.lower() in query:
                return task

        return None

    def switch_task(self, query: str):

        task = self.find_task(query)

        if task:
            return task

        return self.current_task()

    def pause_task(self, task_id):

        for task in self.tasks:

            if task.id == task_id:

                task.status = "paused"

                task.updated_at = datetime.utcnow()

                return task

    def resume_task(self, task_id):

        for task in self.tasks:

            if task.id == task_id:

                task.status = "active"

                task.updated_at = datetime.utcnow()

                return task

    def complete_task(self, task_id):

        for task in self.tasks:

            if task.id == task_id:

                task.status = "completed"

                task.progress = 100.0

                task.updated_at = datetime.utcnow()

                return task

    def update_progress(
        self,
        task_id,
        progress,
    ):

        for task in self.tasks:

            if task.id == task_id:

                task.progress = progress

                task.updated_at = datetime.utcnow()

                return task

    def add_milestone(
        self,
        task_id,
        milestone,
    ):

        for task in self.tasks:

            if task.id == task_id:

                task.milestones.append(milestone)

                task.updated_at = datetime.utcnow()

                return task

    def complete_milestone(
        self,
        task_id,
        milestone,
    ):

        for task in self.tasks:

            if task.id == task_id:

                if milestone not in task.completed_steps:

                    task.completed_steps.append(milestone)

                task.updated_at = datetime.utcnow()

                return task

    def active_tasks(self):

        return [

            task

            for task in self.tasks

            if task.status == "active"

        ]
