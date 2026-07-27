from skills.base import BaseSkill, SkillResponse

class WeatherSkill(BaseSkill):
    name = "weather"
    description = "Provides current weather and forecast information."
    version = "1.0.0"
    priority = 20
    requires_llm = False

    async def can_run(self, query: str, context: dict) -> float:
        cleaned = query.lower().strip()
        keywords = [
            "weather",
            "temperature",
            "forecast",
            "humidity",
            "rain",
            "raining",
            "climate",
            "wind"
        ]
        return 0.95 if any(k in cleaned for k in keywords) else 0.0

    async def execute(self, query: str, context: dict) -> SkillResponse:
        # TODO: Integrate OpenWeatherMap or another provider.
        return SkillResponse(
            success=True,
            confidence=0.95,
            source=self.name,
            data={
                "status": "pending",
                "message": "Weather API integration is not available yet."
            }
        )
