from enum import Enum
from dataclasses import dataclass, field
from typing import List, Dict, Any
import logging
import re


logger = logging.getLogger("aria")


class Route(str, Enum):
    GREETING = "greeting"
    CHAT = "chat"
    CODING = "coding"
    MEMORY = "memory"
    DOCUMENT = "document"
    VISION = "vision"
    TOOL = "tool"
    PLANNER = "planner"
    RESEARCH = "research"
    WEB = "web"
    TASK = "task"
    AUTOMATION = "automation"


@dataclass
class CognitiveDecision:
    """
    Structured representation of ARIA's cognitive strategy.

    The controller does not answer the user.
    It decides what ARIA needs in order to answer correctly.
    """

    expertise: str = "general"

    mood: str = "neutral"
    emotion: str = "neutral"

    response_style: str = "balanced"
    tone: str = "professional"
    detail_level: str = "balanced"
    teaching_mode: bool = False

    user_profile: dict = field(default_factory=dict)

    # Cognitive requirements
    use_memory: bool = False
    use_documents: bool = False
    use_repository: bool = False
    use_semantic_memory: bool = False
    use_reasoning: bool = True
    use_agents: bool = False
    use_planner: bool = False
    use_web: bool = False

    # Decision metadata
    evidence_sources: List[str] = field(default_factory=list)
    required_tools: list = field(default_factory=list)

    # Core decision
    action: str = "chat"
    reasoning_mode: str = "balanced"
    confidence: float = 0.5

    # New cognitive information
    intent: str = "conversation"
    goal: str = ""
    entities: List[str] = field(default_factory=list)
    constraints: Dict[str, Any] = field(default_factory=dict)
    decision_reason: str = ""


class CognitiveController:
    """
    ARIA Cognitive Controller.

    Responsibility:
        Understand the user's goal and determine HOW ARIA
        should think before execution.

    This layer does NOT answer the user.

    It creates a structured cognitive decision that downstream
    reasoning, memory, tools and planners can execute.
    """

    def summary(self, decision: CognitiveDecision):

        return {
            "intent": decision.intent,
            "goal": decision.goal,
            "expertise": decision.expertise,
            "action": decision.action,
            "reasoning_mode": decision.reasoning_mode,
            "emotion": decision.emotion,
            "tools": decision.required_tools,
            "tone": decision.tone,
            "detail": decision.detail_level,
            "teaching": decision.teaching_mode,
            "memory": decision.use_memory,
            "semantic_memory": decision.use_semantic_memory,
            "web": decision.use_web,
            "planner": decision.use_planner,
            "confidence": decision.confidence,
        }

    def _build_user_profile(
        self,
        decision: CognitiveDecision,
        context: Dict[str, Any],
    ):
        decision.user_profile = {
            "expertise": decision.expertise,
            "preferred_detail": decision.detail_level,
            "teaching_mode": decision.teaching_mode,
            "tone": decision.tone,
        }

        # Preserve any profile information already supplied
        profile = context.get("user_profile")

        if isinstance(profile, dict):
            decision.user_profile.update(profile)

    # ---------------------------------------------------------
    # Semantic helpers
    # ---------------------------------------------------------

    @staticmethod
    def _text(query: str) -> str:
        return re.sub(r"\s+", " ", (query or "").strip()).lower()

    @staticmethod
    def _contains_any(text: str, phrases) -> bool:
        return any(phrase in text for phrase in phrases)

    @staticmethod
    def _extract_entities(query: str) -> List[str]:

        entities = []

        # Preserve meaningful capitalized entities.
        matches = re.findall(
            r"\b[A-Z][A-Za-z0-9&.-]{2,}(?:\s+[A-Z][A-Za-z0-9&.-]{2,})*\b",
            query or "",
        )

        for item in matches:
            if item not in entities:
                entities.append(item)

        return entities[:12]

    # ---------------------------------------------------------
    # Intent understanding
    # ---------------------------------------------------------

    def _understand_intent(
        self,
        query: str,
        context: Dict[str, Any],
        decision: CognitiveDecision,
    ):

        text = self._text(query)

        previous = context.get("conversation")

        # -----------------------------------------------------
        # Contextual follow-up
        # -----------------------------------------------------

        contextual_terms = (
            "it",
            "that",
            "this",
            "those",
            "them",
            "the result",
            "the previous",
            "earlier",
            "above",
            "same",
            "continue",
            "again",
        )

        if self._contains_any(text, contextual_terms):

            decision.intent = "contextual_followup"
            decision.use_reasoning = True
            decision.use_semantic_memory = True

            decision.evidence_sources.append("conversation_context")

            if previous:
                decision.decision_reason = (
                    "The request contains contextual references and "
                    "may depend on previous conversation state."
                )

        # -----------------------------------------------------
        # Memory / personal information
        # -----------------------------------------------------

        memory_patterns = (
            "my name",
            "my favorite",
            "my favourite",
            "what do you remember",
            "what did i say",
            "do you remember",
            "remember that",
            "forget that",
            "about me",
        )

        if self._contains_any(text, memory_patterns):

            decision.intent = "personal_memory"
            decision.action = "memory"
            decision.use_memory = True
            decision.reasoning_mode = "fast"
            decision.required_tools.append("memory")
            decision.evidence_sources.append("memory")

            decision.decision_reason = (
                "The user is asking about personal information or "
                "requesting a memory operation."
            )

        # -----------------------------------------------------
        # Calculation
        # -----------------------------------------------------

        calculation_signals = (
            "%",
            "calculate",
            "what is",
            "how much is",
            "multiply",
            "divide",
            "subtract",
            "add",
            "plus",
            "minus",
            "times",
        )

        mathematical_expression = bool(
            re.search(
                r"\d+\s*(?:[+\-*/×÷%])\s*\d+",
                query or "",
            )
        )

        if mathematical_expression or self._contains_any(
            text,
            calculation_signals,
        ):

            # Don't hijack ordinary "what is X?" questions.
            if (
                mathematical_expression
                or any(char in text for char in "+-*/×÷%")
                or self._contains_any(
                    text,
                    (
                        "calculate",
                        "multiply",
                        "divide",
                        "subtract",
                        "add",
                        "plus",
                        "minus",
                        "times",
                    ),
                )
            ):
                decision.intent = "calculation"
                decision.action = "tool"
                decision.use_reasoning = False
                decision.reasoning_mode = "fast"
                decision.required_tools.append("calculator")
                decision.evidence_sources.append("calculator")

                decision.decision_reason = (
                    "The request contains a mathematical operation "
                    "that should be evaluated deterministically."
                )

        # -----------------------------------------------------
        # Documents
        # -----------------------------------------------------

        if self._contains_any(
            text,
            (
                "document",
                "pdf",
                "file",
                "attachment",
                "summarize this",
                "summarise this",
                "from the document",
            ),
        ):

            decision.intent = "document_understanding"
            decision.action = "document"
            decision.use_documents = True
            decision.use_reasoning = True
            decision.required_tools.append("document")
            decision.evidence_sources.append("documents")

            decision.decision_reason = (
                "The user is asking ARIA to understand or operate "
                "on document content."
            )

        # -----------------------------------------------------
        # Coding
        # -----------------------------------------------------

        coding_signals = (
            "code",
            "coding",
            "program",
            "programming",
            "python",
            "javascript",
            "typescript",
            "html",
            "css",
            "fastapi",
            "api",
            "github",
            "repository",
            "repo",
            "debug",
            "bug",
            "refactor",
            "function",
            "class",
        )

        if self._contains_any(text, coding_signals):

            decision.intent = "software_development"
            decision.action = "coding"
            decision.expertise = "software_developer"
            decision.use_reasoning = True
            decision.reasoning_mode = "expert"

            decision.required_tools.append("coding")
            decision.evidence_sources.append("software_context")

            decision.decision_reason = (
                "The request requires software-development knowledge "
                "or code manipulation."
            )

        # -----------------------------------------------------
        # Teaching / explanation
        # -----------------------------------------------------

        teaching_signals = (
            "explain",
            "teach",
            "learn",
            "understand",
            "how does",
            "how do",
            "why does",
            "why do",
            "study",
            "notes",
            "exam",
        )

        if self._contains_any(text, teaching_signals):

            decision.intent = "learning_or_explanation"
            decision.teaching_mode = True
            decision.use_reasoning = True
            decision.reasoning_mode = "deep"
            decision.required_tools.append("study")
            decision.evidence_sources.append("teaching_context")

            if decision.expertise == "general":
                decision.expertise = "student"

            decision.tone = "teacher"
            decision.decision_reason = (
                "The user wants understanding, teaching, or explanation."
            )

        # -----------------------------------------------------
        # Current information / research
        # -----------------------------------------------------

        current_information = self._contains_any(
            text,
            (
                "latest",
                "today",
                "current",
                "recent",
                "news",
                "now",
                "research",
                "look up",
                "find information",
                "what happened",
            ),
        )

        if current_information:

            decision.intent = "current_information"
            decision.action = "research"
            decision.use_web = True
            decision.use_reasoning = True
            decision.reasoning_mode = "deep"

            decision.required_tools.append("web")
            decision.evidence_sources.append("web")

            decision.decision_reason = (
                "The request depends on information that may have "
                "changed and therefore requires current external evidence."
            )

        # -----------------------------------------------------
        # Planning
        # -----------------------------------------------------

        planning_signals = (
            "plan",
            "roadmap",
            "strategy",
            "schedule",
            "steps",
            "how should i",
            "what should i do",
            "make me a plan",
        )

        if self._contains_any(text, planning_signals):

            decision.intent = "planning"
            decision.action = "planner"
            decision.use_planner = True
            decision.use_reasoning = True
            decision.reasoning_mode = "deep"

            decision.required_tools.append("planner")
            decision.evidence_sources.append("planning")

            decision.decision_reason = (
                "The user is asking ARIA to construct a multi-step "
                "plan or strategy."
            )

        # -----------------------------------------------------
        # Automation / tasks
        # -----------------------------------------------------

        automation_signals = (
            "remind me",
            "reminder",
            "every day",
            "every week",
            "schedule",
            "automatically",
            "monitor",
            "notify me when",
            "let me know when",
        )

        if self._contains_any(text, automation_signals):

            decision.intent = "automation"
            decision.action = "automation"
            decision.use_reasoning = True

            decision.required_tools.append("automation")
            decision.evidence_sources.append("automation")

            decision.decision_reason = (
                "The request contains a future or recurring action."
            )

        # -----------------------------------------------------
        # Travel
        # -----------------------------------------------------

        if self._contains_any(
            text,
            (
                "trip",
                "travel",
                "itinerary",
                "vacation",
                "holiday",
            ),
        ):

            decision.intent = "travel_planning"
            decision.use_reasoning = True
            decision.reasoning_mode = "deep"

            if "planner" not in decision.required_tools:
                decision.required_tools.append("planner")

            decision.use_planner = True
            decision.evidence_sources.append("travel")

            decision.decision_reason = (
                "The request involves multi-step travel planning."
            )

        # -----------------------------------------------------
        # Research
        # -----------------------------------------------------

        if "research" in text:

            decision.intent = "research"
            decision.action = "research"
            decision.use_reasoning = True
            decision.reasoning_mode = "deep"

            decision.use_web = True

            if "web" not in decision.required_tools:
                decision.required_tools.append("web")

            decision.evidence_sources.append("research")

        # -----------------------------------------------------
        # Goal
        # -----------------------------------------------------

        decision.goal = query.strip()

        # -----------------------------------------------------
        # Entities
        # -----------------------------------------------------

        decision.entities = self._extract_entities(query)

    # ---------------------------------------------------------
    # Response strategy
    # ---------------------------------------------------------

    def _determine_response_strategy(
        self,
        query: str,
        decision: CognitiveDecision,
    ):

        text = self._text(query)

        if self._contains_any(
            text,
            ("brief", "short", "quick", "just give me"),
        ):
            decision.detail_level = "short"

        elif self._contains_any(
            text,
            (
                "detailed",
                "deep",
                "comprehensive",
                "complete",
                "in detail",
                "step by step",
            ),
        ):
            decision.detail_level = "detailed"

        elif decision.teaching_mode:
            decision.detail_level = "detailed"

        elif decision.reasoning_mode == "deep":
            decision.detail_level = "balanced"

        if decision.teaching_mode:
            decision.tone = "teacher"

        elif decision.expertise == "software_developer":
            decision.tone = "technical"

        else:
            decision.tone = "professional"

    # ---------------------------------------------------------
    # Main cognitive analysis
    # ---------------------------------------------------------

    def analyze(
        self,
        query: str,
        context: Dict | None = None,
    ) -> CognitiveDecision:

        context = context or {}

        decision = CognitiveDecision()

        # Preserve upstream execution-router information.
        execution_decision = context.get("execution_decision")

        if execution_decision is not None:

            route = getattr(
                execution_decision,
                "route",
                None,
            )

            # Upstream router is evidence, not the entire brain.
            if route == Route.GREETING:
                decision.intent = "greeting"
                decision.action = "chat"
                decision.reasoning_mode = "fast"
                decision.use_reasoning = False
                decision.confidence = 1.0

            elif route == Route.MEMORY:
                decision.intent = "personal_memory"
                decision.action = "memory"
                decision.use_memory = True
                decision.reasoning_mode = "fast"
                decision.required_tools.append("memory")
                decision.evidence_sources.append("router")
                decision.confidence = 1.0

            elif route == Route.CODING:
                decision.intent = "software_development"
                decision.action = "coding"
                decision.expertise = "software_developer"
                decision.reasoning_mode = "expert"
                decision.required_tools.append("coding")
                decision.evidence_sources.append("router")
                decision.confidence = 1.0

        # Semantic cognitive analysis
        self._understand_intent(
            query,
            context,
            decision,
        )

        # Response strategy
        self._determine_response_strategy(
            query,
            decision,
        )

        # -----------------------------------------------------
        # Required capability normalization
        # -----------------------------------------------------

        # Remove duplicate tools while preserving order.
        decision.required_tools = list(
            dict.fromkeys(decision.required_tools)
        )

        # Semantic memory is useful for contextual requests.
        if decision.intent == "contextual_followup":
            decision.use_semantic_memory = True

            if "semantic_memory" not in decision.required_tools:
                decision.required_tools.append(
                    "semantic_memory"
                )

        # Personal memory should always be explicit.
        if decision.use_memory:
            if "memory" not in decision.required_tools:
                decision.required_tools.append("memory")

        # Web research requires current external evidence.
        if decision.use_web:
            if "web" not in decision.required_tools:
                decision.required_tools.append("web")

        # Planning requires planner.
        if decision.use_planner:
            if "planner" not in decision.required_tools:
                decision.required_tools.append("planner")

        # Repository requests require repository capability.
        if self._contains_any(
            self._text(query),
            (
                "repository",
                "repo",
                "codebase",
                "github",
            ),
        ):

            decision.use_repository = True
            decision.evidence_sources.append("repository")

            if "repository" not in decision.required_tools:
                decision.required_tools.append("repository")

        # Semantic memory for continuation requests.
        if self._contains_any(
            self._text(query),
            (
                "continue",
                "resume",
                "same project",
                "previous project",
                "last conversation",
                "our project",
                "our architecture",
            ),
        ):

            decision.use_semantic_memory = True

            if "semantic_memory" not in decision.required_tools:
                decision.required_tools.append(
                    "semantic_memory"
                )

        # -----------------------------------------------------
        # Confidence
        # -----------------------------------------------------

        if decision.intent in (
            "conversation",
            "contextual_followup",
        ):
            decision.confidence = max(
                0.55,
                decision.confidence,
            )
        else:
            decision.confidence = max(
                0.80,
                decision.confidence,
            )

        # Strong deterministic capabilities.
        if decision.intent in (
            "calculation",
            "personal_memory",
            "document_understanding",
            "software_development",
            "current_information",
            "planning",
            "automation",
        ):
            decision.confidence = 0.95

        self._build_user_profile(
            decision,
            context,
        )

        logger.info(
            "[CognitiveController] Decision: %s",
            self.summary(decision),
        )

        return decision