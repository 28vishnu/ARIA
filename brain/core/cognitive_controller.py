from enum import Enum
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
import logging
import re
import copy


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
    Structured, side-effect-free representation of ARIA's cognitive strategy.

    CognitiveController determines requirements and preferences.
    It does not execute tools, agents, planners, memory operations,
    or answer the user.
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
    use_tools: bool = False

    # Decision metadata
    evidence_sources: List[str] = field(default_factory=list)
    required_tools: list = field(default_factory=list)

    # Core decision
    action: str = "chat"
    reasoning_mode: str = "balanced"
    confidence: float = 0.5

    # Cognitive information
    intent: str = "conversation"
    goal: str = ""
    entities: List[str] = field(default_factory=list)
    constraints: Dict[str, Any] = field(default_factory=dict)
    decision_reason: str = ""

    # Phase 11 orchestration metadata
    route: str = "chat"
    decision_version: int = 2
    requires_clarification: bool = False
    orchestration: Dict[str, Any] = field(default_factory=dict)


class CognitiveController:
    """
    ARIA's canonical cognitive decision layer.

    Responsibilities:
      - interpret the immediate request
      - combine upstream routing evidence with semantic signals
      - determine capability requirements
      - determine response preferences
      - produce one structured CognitiveDecision

    Non-responsibilities:
      - no LLM calls
      - no tool execution
      - no agent execution
      - no planning execution
      - no memory mutation
      - no persistent state mutation
      - no final answer generation

    CognitiveController is therefore safe to call repeatedly for the
    same request and remains a deterministic upstream decision layer.
    """

    DECISION_VERSION = 2
    MAX_ENTITIES = 12
    MAX_TOOLS = 24

    def summary(self, decision: CognitiveDecision) -> Dict[str, Any]:
        return {
            "intent": decision.intent,
            "goal": decision.goal,
            "expertise": decision.expertise,
            "action": decision.action,
            "route": decision.route,
            "reasoning_mode": decision.reasoning_mode,
            "emotion": decision.emotion,
            "tools": list(decision.required_tools),
            "tone": decision.tone,
            "detail": decision.detail_level,
            "teaching": decision.teaching_mode,
            "memory": decision.use_memory,
            "semantic_memory": decision.use_semantic_memory,
            "documents": decision.use_documents,
            "repository": decision.use_repository,
            "web": decision.use_web,
            "tools_required": decision.use_tools,
            "planner": decision.use_planner,
            "agents": decision.use_agents,
            "confidence": decision.confidence,
            "requires_clarification": decision.requires_clarification,
            "decision_version": decision.decision_version,
        }

    def _build_user_profile(
        self,
        decision: CognitiveDecision,
        context: Dict[str, Any],
    ) -> None:
        decision.user_profile = {
            "expertise": decision.expertise,
            "preferred_detail": decision.detail_level,
            "teaching_mode": decision.teaching_mode,
            "tone": decision.tone,
        }

        profile = context.get("user_profile")
        if isinstance(profile, dict):
            decision.user_profile.update(copy.deepcopy(profile))

    # ---------------------------------------------------------
    # Generic helpers
    # ---------------------------------------------------------

    @staticmethod
    def _text(query: Any) -> str:
        return re.sub(r"\s+", " ", str(query or "").strip()).lower()

    @staticmethod
    def _contains_any(text: str, phrases) -> bool:
        return any(str(phrase).lower() in text for phrase in phrases)

    @staticmethod
    def _append_unique(target: list, values) -> None:
        for value in values:
            if value and value not in target:
                target.append(value)

    @staticmethod
    def _intent_value(intent: Any, key: str, default: Any = None) -> Any:
        if intent is None:
            return default
        if isinstance(intent, dict):
            return intent.get(key, default)
        return getattr(intent, key, default)

    def _extract_entities(self, query: str) -> List[str]:
        entities = []

        # Preserve meaningful capitalized entities from the original query.
        matches = re.findall(
            r"\b[A-Z][A-Za-z0-9&.-]{2,}(?:\s+[A-Z][A-Za-z0-9&.-]{2,})*\b",
            query or "",
        )

        for item in matches:
            cleaned = re.sub(r"\s+", " ", item).strip()
            if cleaned and cleaned not in entities:
                entities.append(cleaned)

        # Also preserve explicit quoted subjects.
        quoted = re.findall(r'"([^"]{2,100})"|\'([^\']{2,100})\'', query or "")
        for left, right in quoted:
            item = (left or right).strip()
            if item and item not in entities:
                entities.append(item)

        return entities[: self.MAX_ENTITIES]

    def _set_action(
        self,
        decision: CognitiveDecision,
        action: str,
        *,
        intent: Optional[str] = None,
        reasoning_mode: Optional[str] = None,
    ) -> None:
        decision.action = action
        decision.route = action

        if intent:
            decision.intent = intent

        if reasoning_mode:
            decision.reasoning_mode = reasoning_mode

    # ---------------------------------------------------------
    # Intent understanding
    # ---------------------------------------------------------

    def _understand_intent(
        self,
        query: str,
        context: Dict[str, Any],
        decision: CognitiveDecision,
    ) -> None:

        text = self._text(query)
        previous = context.get("conversation")

        # -----------------------------------------------------
        # Contextual follow-up
        # -----------------------------------------------------

        contextual_terms = (
            "it", "that", "this", "those", "them", "the result",
            "the previous", "earlier", "above", "same", "continue",
            "again",
        )

        if self._contains_any(text, contextual_terms):
            decision.intent = "contextual_followup"
            decision.use_reasoning = True
            decision.use_semantic_memory = True
            decision.evidence_sources.append("conversation_context")

            if previous:
                decision.decision_reason = (
                    "The request contains contextual references and may "
                    "depend on previous conversation state."
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
            "save this",
            "store this",
            "remember this",
            "delete memory",
        )

        if self._contains_any(text, memory_patterns):
            decision.intent = "personal_memory"
            self._set_action(
                decision,
                "memory",
                intent="personal_memory",
                reasoning_mode="fast",
            )
            decision.use_memory = True
            decision.use_reasoning = False
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
            "calculate",
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

        if (
            mathematical_expression
            or self._contains_any(text, calculation_signals)
        ):
            self._set_action(
                decision,
                "tool",
                intent="calculation",
                reasoning_mode="fast",
            )
            decision.use_reasoning = False
            decision.use_tools = True
            decision.required_tools.append("calculator")
            decision.evidence_sources.append("calculator")

            decision.decision_reason = (
                "The request contains a mathematical operation that "
                "should be evaluated deterministically."
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
            self._set_action(
                decision,
                "document",
                intent="document_understanding",
                reasoning_mode="deep",
            )
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
            "code", "coding", "program", "programming", "python",
            "javascript", "typescript", "html", "css", "fastapi",
            "api", "github", "repository", "repo", "debug", "bug",
            "refactor", "function", "class",
        )

        if self._contains_any(text, coding_signals):
            decision.intent = "software_development"
            self._set_action(
                decision,
                "coding",
                intent="software_development",
                reasoning_mode="expert",
            )
            decision.expertise = "software_developer"
            decision.use_reasoning = True
            decision.use_tools = True
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
            "explain", "teach", "learn", "understand", "how does",
            "how do", "why does", "why do", "study", "notes", "exam",
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
                "latest", "today", "current", "recent", "news", "now",
                "research", "look up", "find information", "what happened",
            ),
        )

        if current_information:
            decision.intent = "current_information"
            self._set_action(
                decision,
                "research",
                intent="current_information",
                reasoning_mode="deep",
            )
            decision.use_web = True
            decision.use_reasoning = True
            decision.use_tools = True
            decision.required_tools.append("web")
            decision.evidence_sources.append("web")

            decision.decision_reason = (
                "The request depends on information that may have changed "
                "and therefore requires current external evidence."
            )

        # -----------------------------------------------------
        # Planning
        # -----------------------------------------------------

        planning_signals = (
            "plan", "roadmap", "strategy", "schedule", "steps",
            "how should i", "what should i do", "make me a plan",
        )

        if self._contains_any(text, planning_signals):
            decision.intent = "planning"
            self._set_action(
                decision,
                "planner",
                intent="planning",
                reasoning_mode="deep",
            )
            decision.use_planner = True
            decision.use_reasoning = True
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
            "remind me", "reminder", "every day", "every week",
            "schedule", "automatically", "monitor", "notify me when",
            "let me know when",
        )

        if self._contains_any(text, automation_signals):
            decision.intent = "automation"
            self._set_action(
                decision,
                "automation",
                intent="automation",
                reasoning_mode="deep",
            )
            decision.use_reasoning = True
            decision.use_tools = True
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
            ("trip", "travel", "itinerary", "vacation", "holiday"),
        ):
            decision.intent = "travel_planning"
            decision.use_reasoning = True
            decision.reasoning_mode = "deep"
            decision.use_planner = True
            decision.required_tools.append("planner")
            decision.evidence_sources.append("travel")

            if decision.action == "chat":
                self._set_action(
                    decision,
                    "planner",
                    intent="travel_planning",
                    reasoning_mode="deep",
                )

            decision.decision_reason = (
                "The request involves multi-step travel planning."
            )

        # -----------------------------------------------------
        # Research
        # -----------------------------------------------------

        if "research" in text:
            decision.intent = "research"
            self._set_action(
                decision,
                "research",
                intent="research",
                reasoning_mode="deep",
            )
            decision.use_reasoning = True
            decision.use_web = True
            decision.use_tools = True
            decision.required_tools.append("web")
            decision.evidence_sources.append("research")

        # -----------------------------------------------------
        # Vision / image understanding
        # -----------------------------------------------------

        if self._contains_any(
            text,
            (
                "image",
                "photo",
                "picture",
                "screenshot",
                "look at this",
                "what is in this image",
                "analyze this image",
                "analyse this image",
                "ocr",
            ),
        ):
            decision.intent = "vision"
            self._set_action(
                decision,
                "vision",
                intent="vision",
                reasoning_mode="deep",
            )
            decision.use_reasoning = True
            decision.use_tools = True
            decision.required_tools.append("vision")
            decision.evidence_sources.append("vision")

        # -----------------------------------------------------
        # Goal / autonomous-goal awareness
        # -----------------------------------------------------

        decision.goal = query.strip()

        autonomous_goal = (
            context.get("autonomous_goal")
            or context.get("goal")
        )

        if isinstance(autonomous_goal, dict):
            safe_goal = copy.deepcopy(autonomous_goal)

            decision.constraints["autonomous_goal"] = safe_goal

            autonomous_goal_id = str(
                safe_goal.get("goal_id", "") or ""
            ).strip()

            autonomous_goal_title = str(
                safe_goal.get("title", "") or ""
            ).strip()

            next_subgoal = safe_goal.get("next_subgoal")

            decision.constraints["autonomous_goal_id"] = autonomous_goal_id
            decision.constraints["autonomous_goal_title"] = (
                autonomous_goal_title
            )
            decision.constraints["next_subgoal"] = copy.deepcopy(next_subgoal)

            if autonomous_goal_id:
                decision.use_planner = True

                if "planner" not in decision.required_tools:
                    decision.required_tools.append("planner")

                if "autonomous_goal" not in decision.evidence_sources:
                    decision.evidence_sources.append("autonomous_goal")

                logger.info(
                    "[CognitiveController] Active autonomous goal: "
                    "%s | next_subgoal=%s",
                    autonomous_goal_title,
                    next_subgoal,
                )

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
    ) -> None:
        text = self._text(query)

        if self._contains_any(
            text,
            ("brief", "short", "quick", "just give me"),
        ):
            decision.detail_level = "short"

        elif self._contains_any(
            text,
            (
                "detailed", "deep", "comprehensive", "complete",
                "in detail", "step by step",
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
    # Decision normalization
    # ---------------------------------------------------------

    def _normalize_decision(
        self,
        decision: CognitiveDecision,
        query: str,
        context: Dict[str, Any],
    ) -> None:
        # Keep only supported, unique capability names.
        decision.required_tools = list(
            dict.fromkeys(
                str(tool).strip()
                for tool in decision.required_tools
                if str(tool).strip()
            )
        )[: self.MAX_TOOLS]

        decision.evidence_sources = list(
            dict.fromkeys(
                str(source).strip()
                for source in decision.evidence_sources
                if str(source).strip()
            )
        )

        # Semantic memory for contextual/continuation requests.
        if decision.intent == "contextual_followup":
            decision.use_semantic_memory = True
            self._append_unique(
                decision.required_tools,
                ["semantic_memory"],
            )

        if self._contains_any(
            self._text(query),
            (
                "continue", "resume", "same project",
                "previous project", "last conversation",
                "our project", "our architecture",
            ),
        ):
            decision.use_semantic_memory = True
            self._append_unique(
                decision.required_tools,
                ["semantic_memory"],
            )

        if decision.use_memory:
            self._append_unique(decision.required_tools, ["memory"])

        if decision.use_documents:
            self._append_unique(decision.required_tools, ["document"])

        if decision.use_web:
            self._append_unique(decision.required_tools, ["web"])

        if decision.use_planner:
            self._append_unique(decision.required_tools, ["planner"])

        if decision.use_repository:
            self._append_unique(decision.required_tools, ["repository"])

        # Repository/codebase requests require repository capability.
        if self._contains_any(
            self._text(query),
            ("repository", "repo", "codebase", "github"),
        ):
            decision.use_repository = True
            self._append_unique(decision.required_tools, ["repository"])
            self._append_unique(decision.evidence_sources, ["repository"])

        # Any explicit executable capability means ToolManager may be needed.
        executable_tools = {
            "calculator", "coding", "web", "document", "vision",
            "automation", "repository",
        }

        if any(
            tool in executable_tools
            for tool in decision.required_tools
        ):
            decision.use_tools = True

        # Agent orchestration is needed when a specialist capability is
        # requested. The coordinator remains responsible for execution.
        specialist_intents = {
            "software_development",
            "document_understanding",
            "current_information",
            "research",
            "planning",
            "travel_planning",
            "automation",
            "vision",
            "learning_or_explanation",
        }

        if decision.intent in specialist_intents:
            decision.use_agents = bool(
                context.get("agent_coordinator")
                or context.get("capabilities", {}).get("agents")
            )

        # A request that has no stronger signal remains ordinary chat.
        if decision.intent == "conversation" and decision.action == "chat":
            decision.route = "chat"

        # Keep route synchronized with the action unless an explicit route
        # was already supplied by the upstream router.
        if not decision.route:
            decision.route = decision.action

        try:
            decision.confidence = float(decision.confidence)
        except (TypeError, ValueError):
            decision.confidence = 0.5

        decision.confidence = max(
            0.0,
            min(1.0, decision.confidence),
        )

        # Deterministic confidence tiers.
        if decision.intent in {
            "calculation",
            "personal_memory",
            "document_understanding",
            "software_development",
            "current_information",
            "planning",
            "automation",
            "vision",
        }:
            decision.confidence = max(decision.confidence, 0.95)
        elif decision.intent in {
            "contextual_followup",
            "conversation",
        }:
            decision.confidence = max(decision.confidence, 0.55)
        else:
            decision.confidence = max(decision.confidence, 0.80)

        # Clarification is only a signal. Do not generate a question here.
        clean = self._text(query)
        decision.requires_clarification = (
            not clean
            or (
                len(clean.split()) <= 1
                and clean not in {"hi", "hello", "help", "status"}
                and not context.get("conversation")
            )
        )

        decision.decision_version = self.DECISION_VERSION

        decision.orchestration = {
            "execution_owner": "cognitive_core",
            "tool_owner": "tool_manager",
            "agent_owner": "agent_coordinator",
            "planning_owner": "planner",
            "answer_owner": "personality_or_llm",
            "controller_role": "decision_only",
        }

    # ---------------------------------------------------------
    # Main cognitive analysis
    # ---------------------------------------------------------

    def analyze(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> CognitiveDecision:

        context = context if isinstance(context, dict) else {}

        clean_query = str(query or "").strip()
        decision = CognitiveDecision(
            decision_version=self.DECISION_VERSION,
        )

        # -----------------------------------------------------
        # Preserve upstream routing evidence.
        # -----------------------------------------------------

        execution_decision = context.get("execution_decision")

        if execution_decision is not None:
            route = (
                execution_decision.get("route")
                if isinstance(execution_decision, dict)
                else getattr(execution_decision, "route", None)
            )

            route_value = (
                route.value
                if isinstance(route, Route)
                else str(route or "").lower()
            )

            route_mapping = {
                Route.GREETING.value: (
                    "greeting",
                    "chat",
                    "fast",
                    False,
                ),
                Route.MEMORY.value: (
                    "personal_memory",
                    "memory",
                    "fast",
                    False,
                ),
                Route.CODING.value: (
                    "software_development",
                    "coding",
                    "expert",
                    True,
                ),
                Route.DOCUMENT.value: (
                    "document_understanding",
                    "document",
                    "deep",
                    True,
                ),
                Route.VISION.value: (
                    "vision",
                    "vision",
                    "deep",
                    True,
                ),
                Route.TOOL.value: (
                    "tool",
                    "tool",
                    "fast",
                    False,
                ),
                Route.PLANNER.value: (
                    "planning",
                    "planner",
                    "deep",
                    True,
                ),
                Route.RESEARCH.value: (
                    "research",
                    "research",
                    "deep",
                    True,
                ),
                Route.WEB.value: (
                    "current_information",
                    "research",
                    "deep",
                    True,
                ),
                Route.AUTOMATION.value: (
                    "automation",
                    "automation",
                    "deep",
                    True,
                ),
            }

            mapped = route_mapping.get(route_value)
            if mapped:
                intent_name, action, mode, use_reasoning = mapped
                decision.intent = intent_name
                decision.action = action
                decision.route = route_value
                decision.reasoning_mode = mode
                decision.use_reasoning = use_reasoning
                decision.evidence_sources.append("router")
                decision.confidence = 1.0

                if route_value == Route.MEMORY.value:
                    decision.use_memory = True
                    decision.required_tools.append("memory")

                elif route_value in {
                    Route.CODING.value,
                    Route.TOOL.value,
                    Route.WEB.value,
                    Route.RESEARCH.value,
                    Route.AUTOMATION.value,
                }:
                    decision.use_tools = True

                elif route_value == Route.DOCUMENT.value:
                    decision.use_documents = True
                    decision.required_tools.append("document")
                    decision.use_tools = True

                elif route_value == Route.VISION.value:
                    decision.required_tools.append("vision")
                    decision.use_tools = True

                elif route_value == Route.PLANNER.value:
                    decision.use_planner = True
                    decision.required_tools.append("planner")

        # -----------------------------------------------------
        # Semantic cognitive analysis
        # -----------------------------------------------------

        self._understand_intent(
            clean_query,
            context,
            decision,
        )

        self._determine_response_strategy(
            clean_query,
            decision,
        )

        self._normalize_decision(
            decision,
            clean_query,
            context,
        )

        self._build_user_profile(
            decision,
            context,
        )

        logger.info(
            "[CognitiveController] Decision: %s",
            self.summary(decision),
        )

        return decision
