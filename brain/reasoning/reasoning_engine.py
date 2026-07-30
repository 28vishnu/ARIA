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

    def __init__(
        self,
        agent_manager=None,
        task_planner=None
    ):
        self.agent_manager = agent_manager
        self.task_planner = task_planner

    async def reason(self, context: Dict[str, Any]) -> ReasoningResult:
        """
        Determine what ARIA should do using the complete working context.

        Intent is one signal, not the entire decision.
        Memory, conversation continuity, document state and task
        complexity are considered together.
        """

        intent = context.get("intent")
        intent_name = intent.name if intent else "chat"
        intent_confidence = (
            getattr(intent, "confidence", 0.80)
            if intent
            else 0.80
        )

        query = str(context.get("query", "")).strip()
        normalized_query = query.lower()

        conversation = context.get("conversation", {}) or {}
        knowledge = context.get("knowledge", {}) or {}
        document = context.get("document", {}) or {}
        response_info = context.get("response", {}) or {}

        looks_like_follow_up = conversation.get(
            "looks_like_follow_up",
            False
        )

        has_relevant_memory = knowledge.get(
            "has_relevant_memory",
            False
        )

        document_active = document.get(
            "active",
            False
        )

        response_depth = response_info.get(
            "depth",
            "normal"
        )

        logger.info(
            "[Reasoning] Intent=%s Query=%s FollowUp=%s Memory=%s "
            "Document=%s Depth=%s",
            intent_name,
            query,
            looks_like_follow_up,
            has_relevant_memory,
            document_active,
            response_depth
        )

        workflow = AgentWorkflow()
        task_plan = None
        task_workflows = []

        # -----------------------------------------------------
        # Task planning
        # -----------------------------------------------------

        if self.task_planner:
            try:
                task_plan = self.task_planner.create_plan(query)
            except Exception:
                logger.exception(
                    "[Reasoning] Task planner failed."
                )
                task_plan = None

        if task_plan:
            try:
                iterable_plan = (
                    task_plan.tasks
                    if hasattr(task_plan, "tasks")
                    else task_plan
                )

                for task in iterable_plan:
                    workflow_item = AgentWorkflow()

                    if (
                        getattr(task, "agent", "auto") != "auto"
                        and self.agent_manager
                    ):
                        agent = self.agent_manager.get(task.agent)

                        if agent:
                            workflow_item.add(agent)

                    task_workflows.append(
                        (task, workflow_item)
                    )

            except Exception:
                logger.exception(
                    "[Reasoning] Failed to build task workflows."
                )

        # -----------------------------------------------------
        # Agent selection helper
        # -----------------------------------------------------

        async def add_best_agent():
            if not self.agent_manager:
                return

            try:
                best_agent, score = (
                    await self.agent_manager.select_agent(
                        query,
                        context
                    )
                )

                if best_agent:
                    logger.info(
                        "[Reasoning] Selected agent: %s (%.2f)",
                        best_agent.name,
                        score
                    )
                    workflow.add(best_agent)

            except Exception:
                logger.exception(
                    "[Reasoning] Agent selection failed."
                )

        # -----------------------------------------------------
        # DOCUMENT MANAGEMENT
        # -----------------------------------------------------

        if intent_name == "delete_document":
            return ReasoningResult(
                primary_action="delete_document",
                confidence=intent_confidence,
                reasoning="Delete a specific stored document.",
                metadata={
                    "goal": "delete_document",
                    "execution_plan": ["delete_document"],
                    "response_depth": "concise",
                    "task_plan": task_plan,
                    "task_workflows": task_workflows,
                },
                workflow=workflow
            )

        if intent_name == "delete_all_documents":
            return ReasoningResult(
                primary_action="delete_all_documents",
                confidence=intent_confidence,
                reasoning="Delete all stored documents.",
                metadata={
                    "goal": "delete_all_documents",
                    "execution_plan": ["delete_all_documents"],
                    "response_depth": "concise",
                    "task_plan": task_plan,
                    "task_workflows": task_workflows,
                },
                workflow=workflow
            )

        # -----------------------------------------------------
        # MEMORY OPERATIONS
        # -----------------------------------------------------

        if intent_name and intent_name.startswith("memory"):

            if self.agent_manager:
                memory_agent = self.agent_manager.get("memory")

                if memory_agent:
                    workflow.add(memory_agent)

            return ReasoningResult(
                primary_action="memory_conversation",
                confidence=intent_confidence,
                reasoning="Personal memory operation.",
                metadata={
                    "goal": "memory_operation",
                    "execution_plan": [
                        "memory_conversation"
                    ],
                    "response_depth": response_depth,
                    "has_relevant_memory": has_relevant_memory,
                    "task_plan": task_plan,
                    "task_workflows": task_workflows,
                },
                workflow=workflow
            )

        # -----------------------------------------------------
        # DOCUMENT-AWARE CONVERSATION
        # -----------------------------------------------------

        if document_active:

            await add_best_agent()

            return ReasoningResult(
                primary_action="chat",
                confidence=max(intent_confidence, 0.90),
                reasoning="Active document context available.",
                metadata={
                    "goal": "document_conversation",
                    "execution_plan": ["chat"],
                    "use_document_context": True,
                    "response_depth": response_depth,
                    "task_plan": task_plan,
                    "task_workflows": task_workflows,
                },
                workflow=workflow
            )

        # -----------------------------------------------------
        # CONVERSATIONAL FOLLOW-UP
        # -----------------------------------------------------

        if looks_like_follow_up:

            await add_best_agent()

            return ReasoningResult(
                primary_action="chat",
                confidence=max(intent_confidence, 0.90),
                reasoning="Contextual conversational follow-up.",
                metadata={
                    "goal": "continue_conversation",
                    "execution_plan": ["chat"],
                    "preserve_context": True,
                    "response_depth": response_depth,
                    "task_plan": task_plan,
                    "task_workflows": task_workflows,
                },
                workflow=workflow
            )

        # -----------------------------------------------------
        # GREETING
        # -----------------------------------------------------

        if intent_name == "greeting":

            return ReasoningResult(
                primary_action="chat",
                confidence=0.99,
                reasoning="Greeting.",
                metadata={
                    "goal": "conversation",
                    "execution_plan": ["chat"],
                    "response_depth": "concise",
                    "task_plan": task_plan,
                    "task_workflows": task_workflows,
                },
                workflow=workflow
            )

        # -----------------------------------------------------
        # PYTHON
        # -----------------------------------------------------

        if intent_name == "python":

            if self.agent_manager:
                python_agent = self.agent_manager.get("python")

                if python_agent:
                    workflow.add(python_agent)

            return ReasoningResult(
                primary_action="chat",
                confidence=intent_confidence,
                reasoning="Python execution request.",
                metadata={
                    "goal": "python",
                    "execution_plan": ["chat"],
                    "response_depth": response_depth,
                    "task_plan": task_plan,
                    "task_workflows": task_workflows,
                },
                workflow=workflow
            )

        # -----------------------------------------------------
        # CODING
        # -----------------------------------------------------

        if intent_name == "coding":

            if self.agent_manager:
                code_agent = self.agent_manager.get("code")

                if code_agent:
                    workflow.add(code_agent)

            return ReasoningResult(
                primary_action="chat",
                confidence=intent_confidence,
                reasoning="Coding request.",
                metadata={
                    "goal": "coding",
                    "execution_plan": ["chat"],
                    "response_depth": response_depth,
                    "task_plan": task_plan,
                    "task_workflows": task_workflows,
                },
                workflow=workflow
            )

        # -----------------------------------------------------
        # WRITING
        # -----------------------------------------------------

        if intent_name == "writing":

            if self.agent_manager:
                writing_agent = self.agent_manager.get("writing")

                if writing_agent:
                    workflow.add(writing_agent)

            return ReasoningResult(
                primary_action="chat",
                confidence=intent_confidence,
                reasoning="Writing request.",
                metadata={
                    "goal": "writing",
                    "execution_plan": ["chat"],
                    "response_depth": response_depth,
                    "task_plan": task_plan,
                    "task_workflows": task_workflows,
                },
                workflow=workflow
            )

        # -----------------------------------------------------
        # PLANNING / MULTI-STEP ACTION
        # -----------------------------------------------------

        if intent_name == "planner":

            if self.agent_manager:
                planning_agent = self.agent_manager.get("planning")

                if planning_agent:
                    workflow.add(planning_agent)

            return ReasoningResult(
                primary_action="planner",
                secondary_actions=["chat"],
                confidence=intent_confidence,
                reasoning="Multi-step action request.",
                metadata={
                    "goal": "planning",
                    "execution_plan": [
                        "planner",
                        "chat"
                    ],
                    "response_depth": response_depth,
                    "task_plan": task_plan,
                    "task_workflows": task_workflows,
                },
                workflow=workflow
            )

        # -----------------------------------------------------
        # GENERAL INTELLIGENT CONVERSATION
        # -----------------------------------------------------

        await add_best_agent()

        return ReasoningResult(
            primary_action="chat",
            confidence=intent_confidence,
            reasoning="General context-aware conversation.",
            metadata={
                "goal": "conversation",
                "execution_plan": ["chat"],
                "response_depth": response_depth,
                "has_relevant_memory": has_relevant_memory,
                "preserve_context": looks_like_follow_up,
                "task_plan": task_plan,
                "task_workflows": task_workflows,
            },
            workflow=workflow
        )
