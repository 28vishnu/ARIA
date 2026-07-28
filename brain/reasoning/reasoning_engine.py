import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

from brain.agents.base_agent import BaseAgent

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
    selected_agent: Optional[BaseAgent] = None


class ReasoningEngine:
    """
    ARIA's reasoning layer.

    It analyses the user's request and decides what should happen next.
    It DOES NOT execute skills, memory, or planning.
    """

    def __init__(self, agent_manager=None):
        self.agent_manager = agent_manager

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

        logger.info(
            "[Reasoning] AgentManager exists: %s",
            self.agent_manager is not None
        )

        selected_agent = None
        score = 0.0

        if self.agent_manager:
            selected_agent, score = await self.agent_manager.select_agent(
                query,
                context
            )
            logger.info(
                "[Reasoning] Agent selection finished."
            )

        if selected_agent:
            logger.info(
                "[Reasoning] Selected agent: %s (%.2f)",
                selected_agent.name,
                score
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
                secondary_actions=["chat"],
                confidence=intent.confidence,
                reasoning="Planning request detected.",
                metadata={
                    "goal": "planning",
                    "execution_plan": [
                        "planner",
                        "chat"
                    ]
                },
                selected_agent=selected_agent
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
            },
            selected_agent=selected_agent
        )
