from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class Decision:
    """
    Represents the decision made by the DecisionEngine.
    """
    action: str
    confidence: float = 1.0
    data: Optional[Dict[str, Any]] = None


class DecisionEngine:
    """
    Chooses how ARIA should respond to a user request based on unified context.

    It DOES NOT execute anything.
    It only decides what should happen next.
    """

    async def decide(
        self,
        context: Dict[str, Any],
        skill_manager=None,
        planner=None
    ) -> Decision:

        query = context.get("query", "")
        memory = context.get("memory", [])
        state = context.get("state", {})
        intent = context.get("intent")

        if intent and intent.name == "greeting":
            return Decision(
                action="chat",
                confidence=0.99
            )

        # 1. Memory Conversation
        if intent and intent.name.startswith("memory"):
            return Decision(
                action="memory_conversation",
                confidence=intent.confidence
            )

        # 2. Direct Skill
        if skill_manager and await skill_manager.can_handle(query, context):
            return Decision(
                action="skill",
                confidence=0.95
            )

        # 3. Planning
        if intent and intent.name == "planner":
            return Decision(
                action="planner",
                confidence=intent.confidence
            )

        # 4. Default
        return Decision(
            action="chat",
            confidence=0.80
        )
