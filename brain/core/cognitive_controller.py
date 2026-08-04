from dataclasses import dataclass, field
from typing import List, Dict


@dataclass
class CognitiveDecision:
    expertise: str = "general"
    mood: str = "neutral"
    response_style: str = "balanced"

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

    def analyze(self, query: str, context: Dict | None = None) -> CognitiveDecision:
        decision = CognitiveDecision()

        q = (query or "").lower()

        # ---------- Expertise ----------
        if any(word in q for word in [
            "python", "fastapi", "docker", "api",
            "repository", "code", "refactor"
        ]):
            decision.expertise = "developer"

        elif any(word in q for word in [
            "study", "exam", "chapter", "notes",
            "quiz", "explain"
        ]):
            decision.expertise = "student"

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

        return decision