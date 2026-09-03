from dataclasses import dataclass, field
from datetime import datetime
import uuid
import logging
from typing import List, Optional, Dict, Any

logger = logging.getLogger("aria")


@dataclass
class SubGoal:
    title: str
    status: str = "pending"
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)


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
        self.goals: List[Goal] = []
        self.working_memory = working_memory

    # =========================================================
    # GOAL CREATION
    # =========================================================

    def generate_subgoals(self, title: str) -> List[SubGoal]:
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

        # Generic autonomous goal
        return [
            SubGoal("Understand objective"),
            SubGoal("Plan required actions"),
            SubGoal("Execute planned actions"),
            SubGoal("Verify results"),
        ]

    def add_goal(self, title: str, metadata=None) -> Goal:
        active = self.current_goal()

        if active and active.title.lower() == title.lower():
            return active

        goal = Goal(
            title=title,
            metadata=metadata or {},
            subgoals=self.generate_subgoals(title),
        )

        self.goals.append(goal)

        logger.info(
            "[GoalManager] Created goal: %s (%s)",
            goal.title,
            goal.id,
        )

        if self.working_memory:
            try:
                semantic = self.working_memory.semantic()
                semantic.add_node(
                    node_id=goal.id,
                    node_type="goal",
                    value=goal.title,
                    metadata=goal.metadata,
                )
            except Exception:
                logger.exception(
                    "[GoalManager] Failed to persist goal to semantic memory"
                )

        return goal

    create_goal = add_goal

    # =========================================================
    # GOAL LOOKUP
    # =========================================================

    def get_goal(self, goal_id: str) -> Optional[Goal]:
        for goal in self.goals:
            if goal.id == goal_id:
                return goal
        return None

    def current_goal(self) -> Optional[Goal]:
        for goal in reversed(self.goals):
            if goal.status == "active":
                return goal
        return None

    def list_active_goals(self) -> List[Goal]:
        return [
            goal for goal in self.goals
            if goal.status == "active"
        ]

    # =========================================================
    # GOAL STATE
    # =========================================================

    def complete_goal(self, goal_id: str):
        goal = self.get_goal(goal_id)

        if not goal:
            return None

        goal.status = "completed"
        goal.progress = 100.0
        goal.updated_at = datetime.utcnow()

        logger.info(
            "[GoalManager] Completed goal: %s",
            goal.title,
        )

        return goal

    def pause_goal(self, goal_id: str):
        goal = self.get_goal(goal_id)

        if not goal:
            return None

        goal.status = "paused"
        goal.updated_at = datetime.utcnow()

        logger.info(
            "[GoalManager] Paused goal: %s",
            goal.title,
        )

        return goal

    def resume_goal(self, goal_id: str):
        goal = self.get_goal(goal_id)

        if not goal:
            return None

        goal.status = "active"
        goal.updated_at = datetime.utcnow()

        logger.info(
            "[GoalManager] Resumed goal: %s",
            goal.title,
        )

        return goal

    def fail_goal(self, goal_id: str, reason: str = ""):
        goal = self.get_goal(goal_id)

        if not goal:
            return None

        goal.status = "failed"
        goal.updated_at = datetime.utcnow()

        if reason:
            goal.metadata["failure_reason"] = reason

        logger.warning(
            "[GoalManager] Goal failed: %s | %s",
            goal.title,
            reason,
        )

        return goal

    def cancel_goal(self, goal_id: str):
        goal = self.get_goal(goal_id)

        if not goal:
            return None

        goal.status = "cancelled"
        goal.updated_at = datetime.utcnow()

        logger.info(
            "[GoalManager] Cancelled goal: %s",
            goal.title,
        )

        return goal

    # =========================================================
    # PROGRESS
    # =========================================================

    def update_progress(self, goal_id: str, progress: float):
        goal = self.get_goal(goal_id)

        if not goal:
            return None

        goal.progress = max(0.0, min(100.0, float(progress)))
        goal.updated_at = datetime.utcnow()

        if goal.progress >= 100.0:
            return self.complete_goal(goal.id)

        logger.info(
            "[GoalManager] Goal '%s' progress: %.1f%%",
            goal.title,
            goal.progress,
        )

        return goal

    # =========================================================
    # SUBGOALS
    # =========================================================

    def next_subgoal(self, goal: Optional[Goal] = None):
        goal = goal or self.current_goal()

        if not goal:
            return None

        for subgoal in goal.subgoals:
            if subgoal.status == "pending":
                return subgoal

        return None

    get_next_subgoal = next_subgoal

    def complete_subgoal(self, goal: Goal, title: str):
        for subgoal in goal.subgoals:
            if subgoal.title.lower() == title.lower():
                subgoal.status = "completed"
                subgoal.updated_at = datetime.utcnow()

                completed = sum(
                    1
                    for item in goal.subgoals
                    if item.status == "completed"
                )

                if goal.subgoals:
                    goal.progress = (
                        completed / len(goal.subgoals)
                    ) * 100.0

                goal.updated_at = datetime.utcnow()

                if goal.progress >= 100.0:
                    self.complete_goal(goal.id)

                return subgoal

        return None

    def update_subgoal(
        self,
        goal_id: str,
        title: str,
        status: str,
    ):
        goal = self.get_goal(goal_id)

        if not goal:
            return None

        for subgoal in goal.subgoals:
            if subgoal.title.lower() == title.lower():
                subgoal.status = status
                subgoal.updated_at = datetime.utcnow()
                return subgoal

        return None

    # =========================================================
    # CONTEXT FOR PLANNER / EXECUTOR
    # =========================================================

    def get_goal_context(self, goal_id: Optional[str] = None):
        goal = (
            self.get_goal(goal_id)
            if goal_id
            else self.current_goal()
        )

        if not goal:
            return None

        return {
            "goal_id": goal.id,
            "goal_title": goal.title,
            "goal_status": goal.status,
            "progress": goal.progress,
            "subgoals": [
                {
                    "title": subgoal.title,
                    "status": subgoal.status,
                    "metadata": subgoal.metadata,
                }
                for subgoal in goal.subgoals
            ],
            "next_subgoal": (
                self.next_subgoal(goal).title
                if self.next_subgoal(goal)
                else None
            ),
            "metadata": goal.metadata,
        }

    # =========================================================
    # OBSERVATION
    # =========================================================

    async def observe(self, query, context):
        query_lower = str(query).lower().strip()

        # Explicit completion
        if query_lower in [
            "finished",
            "done",
            "complete",
            "completed",
            "it's done",
            "it is done",
        ]:
            active = self.current_goal()

            if active:
                self.complete_goal(active.id)

            return

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
                idx = query_lower.find(phrase) + len(phrase)
                subject = query[idx:].strip(" .!?")

                if subject:
                    matched_title = f"Build {subject.capitalize()}"
                else:
                    matched_title = "New Project Goal"

                break

        if matched_title:
            return self.add_goal(matched_title)

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
                    break

        return active

    # =========================================================
    # SERIALIZATION
    # =========================================================

    def serialize_goal(self, goal: Goal):
        return {
            "id": goal.id,
            "title": goal.title,
            "status": goal.status,
            "progress": goal.progress,
            "created_at": goal.created_at.isoformat(),
            "updated_at": goal.updated_at.isoformat(),
            "metadata": goal.metadata,
            "subgoals": [
                {
                    "title": subgoal.title,
                    "status": subgoal.status,
                    "metadata": subgoal.metadata,
                }
                for subgoal in goal.subgoals
            ],
        }