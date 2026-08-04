from dataclasses import dataclass, field
from typing import List, Dict
import logging

logger = logging.getLogger("aria")


@dataclass
class CognitiveDecision:
    expertise: str = "general"
    mood: str = "neutral"
    response_style: str = "balanced"

    tone: str = "professional"
    detail_level: str = "balanced"
    teaching_mode: bool = False

    user_profile: dict = field(default_factory=dict)

    use_memory: bool = False
    use_documents: bool = False
    use_repository: bool = False
    use_reasoning: bool = True
    use_agents: bool = False
    use_planner: bool = False
    use_web: bool = False

    evidence_sources: List[str] = field(default_factory=list)


class CognitiveController:
    """
    Decides HOW ARIA should think before reasoning begins.
    It does not answer questions—it builds a thinking strategy.
    """

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

        logger.info(
            "[CognitiveController] "
            "Profile=%s",
            decision.user_profile,
        )

        return decision
