from datetime import datetime
from skills.base import BaseSkill, SkillResponse

class TimeSkill(BaseSkill):
    name = "time"
    description = "Returns current local time."
    version = "1.0.0"
    priority = 20
    requires_llm = False

    async def can_run(self, query: str, context: dict) -> float:
        cleaned = query.lower().strip()
        keywords = [
            "time",
            "current time",
            "what time",
            "time now",
            "local time",
            "clock"
        ]
        return 0.95 if any(kw in cleaned for kw in keywords) else 0.0

    async def execute(self, query: str, context: dict) -> SkillResponse:
        current_time = datetime.now().strftime("%I:%M %p")
        return SkillResponse(
            success=True,
            confidence=0.95,
            source=self.name,
            data={
                "status": "success",
                "time": current_time
            }
        )
