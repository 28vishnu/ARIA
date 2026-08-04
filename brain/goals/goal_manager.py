from dataclasses import dataclass, field
from datetime import datetime
import uuid
import logging
from typing import List

logger = logging.getLogger("aria")


@dataclass
class SubGoal:
    title: str
    status: str = "pending"


@dataclass
class Goal:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    title: str = ""
    status: str = "active"

    progress: float = 0.0

    created_at: datetime = field(default_factory=datetime.utcnow)

    updated_at: datetime = field(default_factory=datetime.utcnow)

    metadata: dict = field(default_factory=dict)
    subgoals: List[SubGoal] = field(default_factory=list)


class GoalManager:

    def __init__(self, working_memory=None):
        self.goals = []
        self.working_memory = working_memory

    def generate_subgoals(self, title: str):

        title_lower = title.lower()

        if "weather app" in title_lower:
            return [
                SubGoal("Research libraries"),
                SubGoal("Design roadmap"),
                SubGoal("Create backend"),
                SubGoal("Create frontend"),
                SubGoal("Deploy application"),
                SubGoal("Testing"),
            ]

        if "telegram ai" in title_lower:
            return [
                SubGoal("Research architecture"),
                SubGoal("Memory system"),
                SubGoal("Reasoning engine"),
                SubGoal("Planner"),
                SubGoal("Deployment"),
                SubGoal("Optimization"),
            ]

        return []

    def add_goal(self, title, metadata=None):
        active = self.current_goal()

        if active and active.title.lower() == title.lower():
            return active

        goal = Goal(
            title=title,
            metadata=metadata or {},
            subgoals=self.generate_subgoals(title),
        )

        self.goals.append(goal)
        logger.info("[GoalManager] Created new goal: %s", title)

        if hasattr(self, "working_memory") and self.working_memory:

            semantic = self.working_memory.semantic()

            semantic.add_node(
                node_id=goal.id,
                node_type="goal",
                value=goal.title,
                metadata=goal.metadata,
            )

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

    def complete_subgoal(self, goal, title):

        for sg in goal.subgoals:

            if sg.title.lower() == title.lower():

                sg.status = "completed"

                completed = sum(
                    1
                    for s in goal.subgoals
                    if s.status == "completed"
                )

                if goal.subgoals:
                    goal.progress = (
                        completed / len(goal.subgoals)
                    ) * 100
                
                goal.updated_at = datetime.utcnow()

                if goal.progress >= 100.0:
                    self.complete_goal(goal.id)

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
            active = self.current_goal()

            if active:

                mapping = {
                    "roadmap": "Design roadmap",
                    "library": "Research libraries",
                    "libraries": "Research libraries",
                    "backend": "Create backend",
                    "frontend": "Create frontend",
                    "deploy": "Deploy application",
                    "test": "Testing",
                }

                for keyword, task in mapping.items():

                    if keyword in query_lower:

                        self.complete_subgoal(active, task)

    def next_subgoal(self):

        active = self.current_goal()

        if not active:
            return None

        for sg in active.subgoals:

            if sg.status == "pending":
                return sg

        return None

    def list_active_goals(self):

        return [
            g
            for g in self.goals
            if g.status == "active"
        ]
