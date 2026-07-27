from skills.base import BaseSkill, SkillResponse

class SearchSkill(BaseSkill):
    name = "search"
    description = "Performs web or knowledge lookups."
    version = "1.0.0"
    priority = 20
    requires_llm = False

    async def can_run(self, query: str, context: dict) -> float:
        cleaned = query.lower().strip()
        keywords = [
            "search",
            "find",
            "look up",
            "lookup",
            "google",
            "bing",
            "latest",
            "news"
        ]
        return 0.90 if any(kw in cleaned for kw in keywords) else 0.0

    async def execute(self, query: str, context: dict) -> SkillResponse:
        return SkillResponse(
            success=True,
            confidence=0.90,
            source=self.name,
            data={
                "status": "pending",
                "message": "Search functionality not implemented yet."
            }
        )
