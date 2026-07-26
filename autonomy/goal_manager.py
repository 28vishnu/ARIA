import logging
from typing import Dict, List, Optional
from autonomy.models import Goal

logger = logging.getLogger("aria")

class GoalManager:
    def __init__(self):
        self.goals: Dict[str, Goal] = {}

    def create_goal(self, goal_id: str, description: str, priority: int = 5, deadline=None) -> Goal:
        goal = Goal(id=goal_id, description=description, priority=priority, deadline=deadline, status="pending")
        self.goals[goal_id] = goal
        logger.info("[GoalManager] Created goal: '%s' (ID: %s, Priority: %d)", description, goal_id, priority)
        return goal

    def pause_goal(self, goal_id: str):
        if goal_id in self.goals:
            self.goals[goal_id].status = "paused"
            logger.info("[GoalManager] Paused goal ID: %s", goal_id)

    def resume_goal(self, goal_id: str):
        if goal_id in self.goals:
            self.goals[goal_id].status = "active"
            logger.info("[GoalManager] Resumed goal ID: %s", goal_id)

    def cancel_goal(self, goal_id: str):
        if goal_id in self.goals:
            self.goals[goal_id].status = "cancelled"
            logger.info("[GoalManager] Cancelled goal ID: %s", goal_id)

    def get_pending_goals(self) -> List[Goal]:
        return sorted([g for g in self.goals.values() if g.status in ["pending", "active"]], key=lambda x: x.priority)
