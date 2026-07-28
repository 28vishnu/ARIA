import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any

logger = logging.getLogger("aria")


@dataclass
class ReasoningResult:
    """
    Represents the reasoning outcome before execution.
    """

    primary_action: str
    secondary_actions: List[str] = field(default_factory=list)
    confidence: float = 1.0
    reasoning: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


class ReasoningEngine:
    """
    ARIA's reasoning layer.

    It analyses the user's request and decides what should happen next.
    It DOES NOT execute skills, memory, or planning.
    """

    async def reason(self, context: Dict[str, Any]) -> ReasoningResult:
        """
        Analyse the context and determine the primary action.
        """

        intent = context.get("intent")
        logger.info(
            "[Reasoning] Intent=%s Query=%s",
            intent.name if intent else None,
            context.get("query")
        )
        query = context.get("query", "").lower().strip()

        # Greeting
        if intent and intent.name == "greeting":
            return ReasoningResult(
                primary_action="chat",
                confidence=0.99,
                reasoning="Greeting detected."
            )

        # Memory
        if intent and intent.name.startswith("memory"):
            return ReasoningResult(
                primary_action="memory_conversation",
                confidence=intent.confidence,
                reasoning="Memory operation detected."
            )

        # Planning
        if intent and intent.name == "planner":
            return ReasoningResult(
                primary_action="planner",
                confidence=intent.confidence,
                reasoning="Planning request detected."
            )

        # Default
        return ReasoningResult(
            primary_action="chat",
            confidence=0.80,
            reasoning="General conversation."
        )
