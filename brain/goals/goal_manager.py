from dataclasses import dataclass, field
from datetime import datetime
import uuid
import logging

logger = logging.getLogger("aria")


@dataclass
class Goal:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    title: str = ""
    status: str = "active"

    progress: float = 0.0

    created_at: datetime = field(default_factory=datetime.utcnow)

    updated_at: datetime = field(default_factory=datetime.utcnow)

    metadata: dict = field(default_factory=dict)


class GoalManager:

    def __init__(self):
        self.goals = []

    def add_goal(self, title, metadata=None):
        active = self.current_goal()

        if active and active.title.lower() == title.lower():
            return active

        goal = Goal(
            title=title,
            metadata=metadata or {}
        )

        self.goals.append(goal)
        logger.info("[GoalManager] Created new goal: %s", title)

        return goal

    def current_goal(self):

        for goal in reversed(self.goals):

            if goal.status == "active":
                return goal

        return None

    def complete_goal(self, goal_id):

        for goal in self.goals:

            if goal.id == goal_id:

                goal.status = "completed"

                goal.progress = 100.0

                goal.updated_at = datetime.utcnow()
                logger.info("[GoalManager] Completed goal: %s", goal.title)

                return goal

    def update_progress(self, goal_id, progress):

        for goal in self.goals:

            if goal.id == goal_id:

                goal.progress = progress

                goal.updated_at = datetime.utcnow()
                logger.info("[GoalManager] Updated goal '%s' progress to %.1f%%", goal.title, progress)

                return goal

    async def observe(
        self,
        query,
        context,
    ):
        query_lower = str(query).lower().strip()

        # Check for completion keywords
        if query_lower in ["finished", "done", "complete", "completed", "it's done"]:
            active = self.current_goal()
            if active:
                self.complete_goal(active.id)
            return

        # Check for goal initialization phrases
        building_phrases = [
            "i'm building",
            "im building",
            "i am building",
            "i'm creating",
            "im creating",
            "i am creating",
            "i'm making",
            "im making",
            "i want to build",
            "i want to create",
            "let's build",
            "lets build",
            "start a project",
        ]

        matched_title = None
        for phrase in building_phrases:
            if phrase in query_lower:
                # Extract the objective following the phrase
                idx = query_lower.find(phrase) + len(phrase)
                subject = query[idx:].strip(" .!?")
                if subject:
                    matched_title = f"Build {subject.capitalize()}"
                else:
                    matched_title = "New Project Goal"
                break

        if matched_title:
            self.add_goal(matched_title)
        else:
            # Simple heuristic goal matching or progress incremental update for active goals
            active = self.current_goal()
            if active:
                # Increment progress slightly or keep tracking
                new_progress = min(90.0, active.progress + 25.0)
                self.update_progress(active.id, new_progress)

    def list_active_goals(self):

        return [
            g
            for g in self.goals
            if g.status == "active"
        ]
