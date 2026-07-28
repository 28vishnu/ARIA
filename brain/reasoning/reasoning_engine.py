import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

from brain.agents.agent_workflow import AgentWorkflow

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
    workflow: Optional[AgentWorkflow] = None


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
        Analyse the context and determine the primary action and agent workflow.
        """

        intent = context.get("intent")
        intent_name = intent.name if intent else None

        logger.info(
            "[Reasoning] Intent=%s Query=%s",
            intent_name,
            context.get("query")
        )
        query = context.get("query", "").lower().strip()

        logger.info(
            "[Reasoning] AgentManager exists: %s",
            self.agent_manager is not None
        )

        workflow = AgentWorkflow()

        # Multi-agent workflow construction based on intent
        if self.agent_manager:
            if intent_name == "planner":
                planning_agent = self.agent_manager.get("planning")
                writing_agent = self.agent_manager.get("writing")
                if planning_agent:
                    workflow.add(planning_agent)
                if writing_agent:
                    workflow.add(writing_agent)

            elif intent_name == "coding":
                code_agent = self.agent_manager.get("code")
                if code_agent:
                    workflow.add(code_agent)

            elif intent_name == "writing":
                writing_agent = self.agent_manager.get("writing")
                if writing_agent:
                    workflow.add(writing_agent)

            elif intent_name == "chat":
                research_agent = self.agent_manager.get("research")
                if research_agent:
                    workflow.add(research_agent)

            elif intent_name and intent_name.startswith("memory"):
                memory_agent = self.agent_manager.get("memory")
                if memory_agent:
                    workflow.add(memory_agent)

            else:
                best_agent, score = await self.agent_manager.select_agent(
                    query,
                    context
                )
                if best_agent:
                    logger.info(
                        "[Reasoning] Fallback selected agent: %s (%.2f)",
                        best_agent.name,
                        score
                    )
                    workflow.add(best_agent)

        # Greeting
        if intent_name == "greeting":
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
                },
                workflow=workflow
            )

        # Memory
        if intent_name and intent_name.startswith("memory"):
            return ReasoningResult(
                primary_action="memory_conversation",
                secondary_actions=[],
                confidence=intent.confidence if intent else 0.9,
                reasoning="Memory operation detected.",
                metadata={
                    "goal": "memory_operation",
                    "execution_plan": [
                        "memory_conversation"
                    ]
                },
                workflow=workflow
            )

        # Planning
        if intent_name == "planner":
            return ReasoningResult(
                primary_action="planner",
                secondary_actions=["chat"],
                confidence=intent.confidence if intent else 0.9,
                reasoning="Planning request detected.",
                metadata={
                    "goal": "planning",
                    "execution_plan": [
                        "planner",
                        "chat"
                    ]
                },
                workflow=workflow
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
            workflow=workflow
        )
