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
    required_tools: List[str] = field(default_factory=list)
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

    def _looks_like_calculator_request(self, query: str, context: Dict[str, Any]) -> bool:
        q = query.lower().strip()

        calculator_words = (
            "calculate",
            "calculator",
            "compute",
            "solve",
            "add ",
            "plus ",
            "subtract ",
            "minus ",
            "multiply ",
            "times ",
            "divide ",
            "divided by ",
            "multiply by ",
            "divide by ",
            "increase by ",
            "decrease by ",
            "double ",
            "triple ",
            "half ",
        )

        if any(word in q for word in calculator_words):
            return True

        # Direct mathematical expression
        if any(symbol in q for symbol in (
            "+",
            "-",
            "*",
            "/",
            "%",
            "^",
            "×",
            "÷",
        )):
            return any(char.isdigit() for char in q)

        return False

    async def decide(self, query: str, intent, context) -> Decision:
        decision = Decision(
            action="chat",
            reasoning_mode="knowledge_first",
            confidence=1.0,
        )

        route = getattr(intent, "route", None)

        if route:
            route = str(route).lower().strip()

            if "calculator" in route or "calculation" in route:
                decision.action = "calculator"
                decision.use_tools = True
                decision.reasoning_mode = "calculator"
                decision.selected_agents.append("calculator")

            elif "memory" in route:
                decision.use_memory = True
                decision.reasoning_mode = "memory_first"
                decision.selected_agents.append("memory")

            elif "coding" in route:
                decision.action = "coding"
                decision.use_executor = True
                decision.reasoning_mode = "coding"

                if "coding" not in decision.selected_agents:
                    decision.selected_agents.append("coding")

            elif "planner" in route:
                # =========================================================
                # PLANNER / EXECUTION ROUTE
                # =========================================================
                #
                # Route.PLANNER must explicitly set action="planner".
                #
                # CognitiveCore uses decision.action to determine whether
                # the Planner → Executor workflow should be entered.
                # =========================================================

                decision.action = "planner"
                decision.use_planner = True
                decision.use_executor = True
                decision.reasoning_mode = "planning"

                if "planning" not in decision.selected_agents:
                    decision.selected_agents.append("planning")

            elif "research" in route:
                decision.use_world_model = True
                decision.reasoning_mode = "research"
                decision.selected_agents.append("research")

            elif "document" in route:
                decision.use_documents = True
                decision.reasoning_mode = "document"
                decision.selected_agents.append("document")

            elif "vision" in route:
                decision.use_tools = True
                decision.reasoning_mode = "vision"
                decision.selected_agents.append("vision")

        # ---------------------------------------------------------
        # DETERMINISTIC CAPABILITY OVERRIDE
        # ---------------------------------------------------------
        # Intent analysis is probabilistic.
        # Deterministic capabilities must not be lost simply because
        # the intent classifier called the request "chat".

        if self._looks_like_calculator_request(query, context):
            decision.action = "calculator"
            decision.use_tools = True
            decision.reasoning_mode = "calculator"

            if "calculator" not in decision.selected_agents:
                decision.selected_agents.append("calculator")

            decision.confidence = max(
                decision.confidence,
                0.98,
            )

        # Remove duplicates
        decision.selected_agents = list(dict.fromkeys(decision.selected_agents))
        decision.required_tools = decision.selected_agents

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
