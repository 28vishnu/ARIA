from datetime import datetime
from skills.base import BaseSkill
from personality.response import SystemResponse

class DateSkill(BaseSkill):
    name = "date"
    description = "Returns current local date."
    version = "1.0"
    priority = 20
    requires_llm = False

    def can_run(self, query: str, context: dict) -> float:
        cleaned = query.lower().strip()
        keywords = ["date", "today's date", "current date", "what day", "which month"]
        if any(kw in cleaned for kw in keywords):
            return 0.95
        return 0.0

    async def execute(self, query: str, context: dict) -> SystemResponse:
        current_date = datetime.now().strftime("%d %B %Y")
        return SystemResponse(
            success=True,
            confidence=0.95,
            source=self.name,
            data={"date": current_date}
        )
