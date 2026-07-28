from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class Decision:
    """
    Represents the action the CognitiveCore should take.
    """
    action: str
    data: Optional[Dict[str, Any]] = None


class DecisionEngine:
    """
    Chooses how ARIA should respond to a user request.

    It DOES NOT execute anything.
    It only decides what should happen next.
    """

    async def decide(
        self,
        query: str,
        context: Dict[str, Any],
        memory=None,
        skill_manager=None,
        planner=None
    ) -> Decision:

        # 1. Memory
        if memory:
            return Decision(
                action="memory",
                data={"memories": memory}
            )

        # 2. Direct Skill
        if skill_manager:
            return Decision(
                action="skill"
            )

        # 3. Planning
        if planner:
            return Decision(
                action="planner"
            )

        # 4. Default
        return Decision(
            action="chat"
        )
