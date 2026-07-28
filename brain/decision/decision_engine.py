import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional, List

logger = logging.getLogger("aria")


@dataclass
class Decision:
    """
    Represents the decision made by the DecisionEngine.
    """
    action: str
    confidence: float = 1.0
    secondary_actions: Optional[List[str]] = None
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

        logger.info(
            "[Decision] Context state = %s",
            context.get("state")
        )

        state = context.get("state", {})
        query_lower = query.lower()

        document_keywords = [
            "document",
            "pdf",
            "file",
            "chapter",
            "page",
            "summary",
            "summarize",
            "fees",
            "tuition",
            "according to",
            "this document",
            "uploaded",
            "scholarship",
            "course"
        ]

        if (
            state.get("active_document")
            and any(word in query_lower for word in document_keywords)
        ):
            logger.info("[Decision] Routing to DOCUMENT intelligence.")

            return Decision(
                action="document",
                confidence=1.0
            )

        intent = context.get("intent")
        reasoning = context.get("reasoning")

        # Let the Reasoning Engine decide first
        if reasoning:
            logger.info(
                "[Decision] Goal=%s Plan=%s",
                reasoning.metadata.get("goal"),
                reasoning.metadata.get("execution_plan")
            )

            return Decision(
                action=reasoning.primary_action,
                confidence=reasoning.confidence,
                secondary_actions=reasoning.secondary_actions
            )

        # Fallback (only if reasoning is unavailable)
        if skill_manager and await skill_manager.can_handle(query, context):
            return Decision(
                action="skill",
                confidence=0.95
            )

        # Active document takes highest priority
        if state.get("active_document"):

            return Decision(
                action="document",
                confidence=0.98
            )

        # Otherwise use keyword detection
        if any(keyword in query_lower for keyword in document_keywords):

            return Decision(
                action="document",
                confidence=0.90
            )

        # 4. Default
        return Decision(
            action="chat",
            confidence=0.80
        )
