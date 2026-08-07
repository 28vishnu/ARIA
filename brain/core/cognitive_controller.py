from enum import Enum
from dataclasses import dataclass, field
from typing import List, Dict
import logging

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
    expertise: str = "general"
    mood: str = "neutral"
    emotion: str = "neutral"
    response_style: str = "balanced"

    tone: str = "professional"
    detail_level: str = "balanced"
    teaching_mode: bool = False

    user_profile: dict = field(default_factory=dict)

    use_memory: bool = False
    use_documents: bool = False
    use_repository: bool = False
    use_semantic_memory: bool = False
    use_reasoning: bool = True
    use_agents: bool = False
    use_planner: bool = False
    use_web: bool = False

    evidence_sources: List[str] = field(default_factory=list)

    required_tools: list = field(default_factory=list)
    
    action: str = "chat"
    reasoning_mode: str = "balanced"
    confidence: float = 1.0


class CognitiveController:
    """
    Decides HOW ARIA should think before reasoning begins.
    It does not answer questions—it builds a thinking strategy.
    """

    def summary(self, decision):

        return {
            "expertise": decision.expertise,
            "emotion": decision.emotion,
            "tools": decision.required_tools,
            "tone": decision.tone,
            "detail": decision.detail_level,
            "teaching": decision.teaching_mode,
            "semantic_memory": decision.use_semantic_memory,
        }

    def _build_user_profile(
        self,
        decision: CognitiveDecision,
    ):
        decision.user_profile = {
            "expertise": decision.expertise,
            "preferred_detail": decision.detail_level,
            "teaching_mode": decision.teaching_mode,
            "tone": decision.tone,
        }

    def analyze(self, query: str, context: Dict | None = None) -> CognitiveDecision:
        context = context or {}
        execution_decision = context.get("execution_decision")

        if execution_decision is not None:
            route = getattr(execution_decision, "route", None)

            if route == Route.GREETING:
                return CognitiveDecision(
                    action="chat",
                    reasoning_mode="fast",
                    use_memory=False,
                    use_reasoning=False,
                    confidence=1.0,
                )

            if route == Route.MEMORY:
                return CognitiveDecision(
                    action="memory",
                    reasoning_mode="fast",
                    use_memory=True,
                    use_reasoning=False,
                    confidence=1.0,
                )

            if route == Route.CODING:
                return CognitiveDecision(
                    action="coding",
                    reasoning_mode="expert",
                    use_reasoning=False,
                    confidence=1.0,
                )

        decision = CognitiveDecision()

        q = (query or "").lower()

        # ---------- Expertise ----------
        if any(word in q for word in [
            "python", "fastapi", "docker", "api",
            "repository", "code", "refactor"
        ]):
            decision.expertise = "software_developer"

        elif any(word in q for word in [
            "study", "exam", "chapter", "notes",
            "quiz", "explain"
        ]):
            decision.expertise = "student"

        elif any(word in q for word in [
            "business",
            "startup",
            "marketing",
            "finance",
        ]):
            decision.expertise = "business"

        # ---------- Detail Level ----------

        if any(word in q for word in [
            "brief",
            "short",
            "quick",
        ]):
            decision.detail_level = "short"

        elif any(word in q for word in [
            "detailed",
            "deep",
            "comprehensive",
            "complete",
        ]):
            decision.detail_level = "detailed"

        # ---------- Teaching Detection ----------
        if any(word in q for word in [
            "teach",
            "learn",
            "explain",
            "understand",
            "study",
        ]):
            decision.teaching_mode = True

        # ---------- Tone Detection ----------
        if decision.teaching_mode:

            decision.tone = "teacher"

        elif decision.expertise == "software_developer":

            decision.tone = "technical"

        else:

            decision.tone = "professional"

        # ---------- Evidence ----------
        if any(word in q for word in [
            "remember", "previous", "before",
            "earlier", "last time"
        ]):
            decision.use_memory = True
            decision.evidence_sources.append("memory")

        # ---------- Semantic Memory ----------

        semantic_keywords = [
            "continue",
            "again",
            "same project",
            "previous project",
            "resume",
            "last conversation",
            "roadmap",
            "architecture",
            "repository",
        ]

        if any(keyword in q for keyword in semantic_keywords):

            decision.use_semantic_memory = True

            decision.evidence_sources.append("semantic_memory")

        if any(word in q for word in [
            "pdf", "document", "notes"
        ]):
            decision.use_documents = True
            decision.evidence_sources.append("documents")

        if any(word in q for word in [
            "repository", "repo", "project",
            "codebase", "github"
        ]):
            decision.use_repository = True
            decision.evidence_sources.append("repository")

        self._build_user_profile(decision)

        # ---------- Tool Selection ----------

        if decision.use_documents:

            decision.required_tools.append("document")

        if decision.use_repository:

            decision.required_tools.append("repository")

        if decision.use_memory:

            decision.required_tools.append("memory")

        if decision.use_semantic_memory:

            decision.required_tools.append("semantic_memory")

        if decision.teaching_mode:

            decision.required_tools.append("study")

        if decision.expertise == "software_developer":

            decision.required_tools.append("coding")

        if decision.use_planner:

            decision.required_tools.append("planner")

        logger.info(
            "[CognitiveController] %s",
            self.summary(decision),
        )

        return decision
