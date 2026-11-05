from typing import Optional, Dict, Any

from brain.models.intent import Intent
from brain.models.context import Context
from brain.models.decision import Decision
from brain.models.goal import Goal

from brain.plan import ExecutionPlan
from brain.task import Task
from brain.state_models import WorldState

class CognitiveStateManager:
    def __init__(self):
        self.intent: Optional[Intent] = None
        self.context: Optional[Context] = None
        self.decision: Optional[Decision] = None
        self.goal: Optional[Goal] = None
        self.plan: Optional[ExecutionPlan] = None
        self.task: Optional[Task] = None
        self.world_state: WorldState = WorldState()

    def reset(self) -> None:
        self.intent = None
        self.context = None
        self.decision = None
        self.goal = None
        self.plan = None
        self.task = None
        self.world_state = WorldState()

    def set_intent(self, intent: Intent) -> None:
        self.intent = intent

    def set_context(self, context: Context) -> None:
        self.context = context

    def set_decision(self, decision: Decision) -> None:
        self.decision = decision

    def set_goal(self, goal: Goal) -> None:
        self.goal = goal

    def set_plan(self, plan: ExecutionPlan) -> None:
        self.plan = plan

    def set_task(self, task: Task) -> None:
        self.task = task

    def snapshot(self) -> Dict[str, Any]:
        return {
            "intent": self.intent,
            "context": self.context,
            "decision": self.decision,
            "goal": self.goal,
            "plan": self.plan,
            "task": self.task,
            "world_state": self.world_state
        }
