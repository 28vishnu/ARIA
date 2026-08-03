from dataclasses import dataclass, field
from datetime import datetime
import uuid
import logging
import json
from pathlib import Path
from dataclasses import asdict

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

    priority: int = 1

    milestones: list = field(default_factory=list)

    completed_steps: list = field(default_factory=list)

    metadata: dict = field(default_factory=dict)

    created_at: datetime = field(default_factory=datetime.utcnow)

    updated_at: datetime = field(default_factory=datetime.utcnow)


class TaskManager:

    def __init__(self):

        self.tasks = []
        self.storage_path = Path("data/tasks.json")
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

        self.load()

    def save(self):

        data = [asdict(task) for task in self.tasks]

        with open(self.storage_path, "w", encoding="utf-8") as f:
            json.dump(
                data,
                f,
                indent=2,
                default=str,
            )

    def load(self):

        if not self.storage_path.exists():
            return

        try:

            with open(self.storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            self.tasks = []

            for item in data:

                if isinstance(item.get("created_at"), str):
                    item["created_at"] = datetime.fromisoformat(item["created_at"])

                if isinstance(item.get("updated_at"), str):
                    item["updated_at"] = datetime.fromisoformat(item["updated_at"])

                self.tasks.append(Task(**item))

            logger.info(
                "[TaskManager] Loaded %d tasks",
                len(self.tasks),
            )

        except Exception as e:

            logger.exception(
                "[TaskManager] Failed loading tasks: %s",
                e,
            )

    def create_task(
        self,
        title,
        description="",
        goal_id=None,
        priority=1,
        metadata=None,
    ):

        task = Task(
            title=title,
            description=description,
            goal_id=goal_id,
            priority=priority,
            metadata=metadata or {}
        )

        self.tasks.append(task)

        logger.info(
            "[TaskManager] Created task: %s",
            title,
        )

        self.save()
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

    def set_priority(self, task_id, priority):

        for task in self.tasks:

            if task.id == task_id:

                task.priority = priority

                task.updated_at = datetime.utcnow()

                logger.info(
                    "[TaskManager] Updated priority for '%s' to %d",
                    task.title,
                    priority,
                )

                self.save()
                return task

    def highest_priority_task(self):

        active = [

            task

            for task in self.tasks

            if task.status == "active"

        ]

        if not active:
            return None

        return sorted(
            active,
            key=lambda t: (
                -t.priority,
                -t.progress,
                t.created_at,
            ),
        )[0]

    def pause_task(self, task_id):

        for task in self.tasks:

            if task.id == task_id:

                task.status = "paused"

                task.updated_at = datetime.utcnow()

                self.save()
                return task

    def resume_task(self, task_id):

        for task in self.tasks:

            if task.id == task_id:

                task.status = "active"

                task.updated_at = datetime.utcnow()

                self.save()
                return task

    def complete_task(self, task_id):

        for task in self.tasks:

            if task.id == task_id:

                task.status = "completed"

                task.progress = 100.0

                task.updated_at = datetime.utcnow()

                self.save()
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

                self.save()
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

                self.save()
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

                self.save()
                return task

    def active_tasks(self):

        return [

            task

            for task in self.tasks

            if task.status == "active"

        ]
