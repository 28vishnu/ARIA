import logging
import re
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

    def _looks_like_file_read_request(
        self,
        query: str,
    ) -> bool:
        """
        Detect requests that explicitly ask ARIA to inspect/read
        a file.

        These requests must use file_action(read) rather than
        normal conversational reasoning.
        """

        q = query.lower().strip()

        read_phrases = (
            "what's in",
            "whats in",
            "what is in",
            "what's inside",
            "whats inside",
            "what is inside",
            "show me",
            "show what's in",
            "show whats in",
            "read",
            "read the file",
            "open the file",
            "check the file",
            "check what's in",
            "check whats in",
            "contents of",
            "content of",
        )

        has_file_extension = bool(
            re.search(
                r"\b[\w\-]+\.(?:"
                r"txt|md|json|csv|py|js|ts|html|css|"
                r"pdf|docx|xlsx|pptx"
                r")\b",
                q,
                re.IGNORECASE,
            )
        )

        return (
            has_file_extension
            and any(
                phrase in q
                for phrase in read_phrases
            )
        )

    async def decide(self, query: str, intent, context) -> Decision:
        decision = Decision(
            action="chat",
            reasoning_mode="knowledge_first",
            confidence=1.0,
        )

        # ---------------------------------------------------------
        # DETERMINISTIC FILE READ OVERRIDE
        # ---------------------------------------------------------
        # Explicit requests such as:
        #
        #   "What's in phase3_test.txt?"
        #   "Read test.txt"
        #   "Show me notes.txt"
        #
        # must never fall through to chat/memory/LLM reasoning.
        # They require an actual file read.
        #
        # This override intentionally happens before route handling
        # because the upstream intent classifier may incorrectly
        # classify these requests as conversation/document/chat.
        # ---------------------------------------------------------

        if self._looks_like_file_read_request(query):

            decision.action = "file_read"
            decision.use_tools = True
            decision.reasoning_mode = "file_read"
            decision.selected_agents = ["file_action"]
            decision.required_tools = ["file_action"]
            decision.confidence = 0.99
            decision.explanation = (
                "Explicit file-content request detected."
            )

            logger.info(
                "[DecisionEngine] Deterministic file-read "
                "override activated for query=%r",
                query,
            )

            self.decision_history.append(decision)

            if len(self.decision_history) > 100:
                self.decision_history.pop(0)

            return decision

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

        # =========================================================
        # DETERMINISTIC ACTION INTENT OVERRIDE
        # =========================================================
        # The intent system may already have identified an exact
        # executable action such as:
        #     create_file
        #     read_file
        #     delete_file
        #     notification_action
        # These are executable operations and MUST NOT fall through
        # to chat/document/LLM reasoning.
        # The action intent takes priority over probabilistic
        # reasoning classification.
        # =========================================================
        intent_data = getattr(intent, "data", None)
        if isinstance(intent_data, dict):

            action_name = intent_data.get(
                "action_name"
            )

            if isinstance(action_name, str):

                action_name = action_name.strip().lower()

                EXECUTABLE_ACTIONS = {
                    "create_file",
                    "read_file",
                    "write_file",
                    "delete_file",
                    "remove_file",
                    "rename_file",
                    "move_file",
                    "copy_file",
                    "notification_action",
                    "send_notification",
                }

                if action_name in EXECUTABLE_ACTIONS:

                    decision.action = "planner"
                    decision.use_planner = True
                    decision.use_executor = True
                    decision.reasoning_mode = "action_execution"

                    if "planning" not in decision.selected_agents:
                        decision.selected_agents.append(
                            "planning"
                        )

                    decision.confidence = max(
                        decision.confidence,
                        0.99,
                    )

                    logger.info(
                        "[DecisionEngine] Deterministic executable "
                        "action detected: %s → planner/executor",
                        action_name,
                    )

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
