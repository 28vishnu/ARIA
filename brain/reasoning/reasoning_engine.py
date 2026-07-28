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

        # Direct reasoning from query (before intent routing)
        memory_words = (
            "remember",
            "forget",
            "delete",
            "remove",
            "my ",
            "i am",
            "i'm"
        )

        planner_words = (
            "build",
            "create",
            "design",
            "generate",
            "develop",
            "make"
        )

        if any(word in query for word in memory_words):
            return ReasoningResult(
                primary_action="memory_conversation",
                secondary_actions=[],
                confidence=0.95,
                reasoning="Reasoned that this is a memory operation.",
                metadata={
                    "goal": "memory_operation",
                    "execution_plan": [
                        "memory_conversation"
                    ]
                }
            )

        if any(word in query for word in planner_words):
            return ReasoningResult(
                primary_action="planner",
                secondary_actions=[],
                confidence=0.92,
                reasoning="Reasoned that this is a planning request.",
                metadata={
                    "goal": "planning",
                    "execution_plan": [
                        "planner"
                    ]
                }
            )

        # Greeting
        if intent and intent.name == "greeting":
            return ReasoningResult(
                primary_action="chat",
                secondary_actions=[],
                confidence=0.99,
                reasoning="Greeting detected.",
                metadata={
                    "goal": "conversation",
                    "execution_plan": [
                        "chat"
                    ]
                }
            )

        # Memory
        if intent and intent.name.startswith("memory"):
            return ReasoningResult(
                primary_action="memory_conversation",
                secondary_actions=[],
                confidence=intent.confidence,
                reasoning="Memory operation detected.",
                metadata={
                    "goal": "memory_operation",
                    "execution_plan": [
                        "memory_conversation"
                    ]
                }
            )

        # Planning
        if intent and intent.name == "planner":
            return ReasoningResult(
                primary_action="planner",
                secondary_actions=[],
                confidence=intent.confidence,
                reasoning="Planning request detected.",
                metadata={
                    "goal": "planning",
                    "execution_plan": [
                        "planner"
                    ]
                }
            )

        # Default
        return ReasoningResult(
            primary_action="chat",
            secondary_actions=[],
            confidence=0.80,
            reasoning="General conversation.",
            metadata={
                "goal": "conversation",
                "execution_plan": [
                    "chat"
                ]
            }
        )
