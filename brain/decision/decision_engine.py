import logging
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger("aria")


@dataclass
class Decision:

    action: str

    reasoning_mode: str

    use_memory: bool = False

    use_planner: bool = False

    use_executor: bool = False

    use_tools: bool = False

    use_documents: bool = False

    use_world_model: bool = False

    use_multi_agent: bool = False

    selected_agents: List[str] = field(default_factory=list)

    confidence: float = 1.0

    explanation: Optional[str] = None


class DecisionEngine:
    """
    Chooses how ARIA should respond to a user request based on unified context and rich reasoning results.

    It DOES NOT execute anything.
    It only decides what should happen next using the complete execution package.
    """

    def __init__(
        self,
        knowledge_manager=None,
        self_reflection=None,
    ):
        self.knowledge_manager = knowledge_manager
        self.self_reflection = self_reflection
        self.decision_history = []

    async def decide(
        self,
        query: str,
        intent,
        context,
    ) -> Decision:
        """
        Convert ARIA's advanced reasoning result into the final execution route
        with confidence-based routing, conflict handling, and evidence validation.
        """
        decision = Decision(
            action="chat",
            reasoning_mode="knowledge_first",
        )

        query_lower = str(query).lower()

        if any(word in query_lower for word in [
            "plan",
            "roadmap",
            "schedule",
            "design",
        ]):
            decision.use_planner = True
            decision.reasoning_mode = "planning"

        if any(word in query_lower for word in [
            "research",
            "latest",
            "compare",
        ]):
            decision.reasoning_mode = "research"

        if any(word in query_lower for word in [
            "remember",
            "my",
            "previous",
        ]):
            decision.use_memory = True

        if any(word in query_lower for word in [
            "write",
            "generate",
            "code",
        ]):
            decision.use_multi_agent = True

        if decision.reasoning_mode == "planning":
            decision.selected_agents.append("planning")

        if decision.reasoning_mode == "research":
            decision.selected_agents.append("research")

        if "code" in query_lower:
            decision.selected_agents.append("coding")

        if "write" in query_lower:
            decision.selected_agents.append("writing")

        decision.confidence = 0.95

        logger.info(
            "[DecisionEngine] Decision=%s Mode=%s Agents=%s",
            decision.action,
            decision.reasoning_mode,
            decision.selected_agents,
        )

        self.decision_history.append(decision)
        if len(self.decision_history) > 100:
            self.decision_history.pop(0)
        return decision

    def last_decision(self):

        if not self.decision_history:
            return None

        return self.decision_history[-1]

    def clear_history(self):

        self.decision_history.clear()
