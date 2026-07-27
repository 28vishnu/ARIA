from skills.base import BaseSkill
from personality.response import SystemResponse

class WeatherSkill(BaseSkill):
    name = "weather"
    description = "Fetches weather and temperature forecasts."
    version = "1.0"
    priority = 20
    requires_llm = False

    def can_run(self, query: str, context: dict) -> float:
        cleaned = query.lower().strip()
        keywords = ["weather", "temperature", "rain", "forecast", "humidity"]
        if any(kw in cleaned for kw in keywords):
            return 0.95
        return 0.0

    async def execute(self, query: str, context: dict) -> SystemResponse:
        return SystemResponse(
            success=True,
            confidence=0.95,
            source=self.name,
            data={"response": "Weather API integration is pending, Sir."}
        )
