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
        intent = context.get("intent")
        reasoning = context.get("reasoning")

        # Let the Reasoning Engine decide first
        if reasoning:
            return Decision(
                action=reasoning.primary_action,
                confidence=reasoning.confidence
            )

        # Fallback (only if reasoning is unavailable)
        if skill_manager and await skill_manager.can_handle(query, context):
            return Decision(
                action="skill",
                confidence=0.95
            )

        # 4. Default
        return Decision(
            action="chat",
            confidence=0.80
        )
