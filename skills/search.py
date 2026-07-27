from skills.base import BaseSkill
from personality.response import SystemResponse

class SearchSkill(BaseSkill):
    name = "search"
    description = "Performs web or knowledge lookups."
    version = "1.0"
    priority = 20
    requires_llm = False

    def can_run(self, query: str, context: dict) -> float:
        cleaned = query.lower().strip()
        keywords = ["search", "look up", "find", "latest news", "google"]
        if any(cleaned.startswith(kw) for kw in keywords):
            return 0.90
        return 0.0

    async def execute(self, query: str, context: dict) -> SystemResponse:
        return SystemResponse(
            success=True,
            confidence=0.90,
            source=self.name,
            data={"response": "Search functionality not implemented yet, Sir."}
        )
