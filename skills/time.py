from datetime import datetime
from skills.base import BaseSkill
from personality.response import SystemResponse

class TimeSkill(BaseSkill):
    name = "time"
    description = "Returns current local time."
    version = "1.0"
    priority = 20
    requires_llm = False

    def can_run(self, query: str, context: dict) -> float:
        cleaned = query.lower().strip()
        keywords = ["time", "current time", "what time", "time now"]
        if any(kw in cleaned for kw in keywords):
            return 0.95
        return 0.0

    async def execute(self, query: str, context: dict) -> SystemResponse:
        current_time = datetime.now().strftime("%I:%M %p")
        return SystemResponse(
            success=True,
            confidence=0.95,
            source=self.name,
            data={"time": current_time}
        )
