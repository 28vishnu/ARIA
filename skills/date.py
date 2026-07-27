from datetime import datetime
from skills.base import BaseSkill, SkillResponse

class DateSkill(BaseSkill):
    name = "date"
    description = "Returns current local date."
    version = "1.0.0"
    priority = 20
    requires_llm = False

    async def can_run(self, query: str, context: dict) -> float:
        cleaned = query.lower().strip()
        keywords = ["date", "today's date", "current date", "what day", "which month"]
        return 0.95 if any(kw in cleaned for kw in keywords) else 0.0

    async def execute(self, query: str, context: dict) -> SkillResponse:
        current_date = datetime.now().strftime("%d %B %Y")
        return SkillResponse(
            success=True,
            confidence=0.95,
            source=self.name,
            data={
                "status": "success",
                "date": current_date
            }
        )
