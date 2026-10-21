"""Weather skill that fails closed until a live provider is wired in.

The production weather implementation lives in ``actions/actions/weather.py``.
This skill intentionally does not fabricate weather or report a pending
integration as a successful result. The orchestrator should route live weather
requests to the registered ``weather_action`` instead.
"""
from __future__ import annotations

from typing import Any

from skills.base import BaseSkill, SkillResponse


class WeatherSkill(BaseSkill):
    name = "weather"
    description = "Detects weather questions; live data must come from weather_action."
    version = "1.1.0"
    priority = 20
    requires_llm = False

    KEYWORDS = (
        "weather", "temperature", "forecast", "humidity", "rain",
        "raining", "climate", "wind", "sunrise", "sunset",
    )

    async def can_run(self, query: str, context: dict[str, Any]) -> float:
        cleaned = (query or "").casefold().strip()
        return 0.95 if any(keyword in cleaned for keyword in self.KEYWORDS) else 0.0

    async def execute(self, query: str, context: dict[str, Any]) -> SkillResponse:
        """Return a truthful unavailable result rather than fake success.

        Live weather execution is handled by the action manager because that
        path owns validation, provider calls, timeouts, and action auditing.
        """
        action_manager = (context or {}).get("action_manager")
        if action_manager is not None:
            has_action = getattr(action_manager, "has_action", None)
            execute_action = getattr(action_manager, "execute_action", None)
            if callable(has_action) and callable(execute_action) and has_action("weather_action"):
                # Do not guess a location from the user's profile or IP. The
                # orchestrator must extract and pass an explicit location.
                location = (context or {}).get("weather_location")
                if isinstance(location, str) and location.strip():
                    result = await execute_action(
                        "weather_action", {"location": location.strip()}, confirmed=False
                    )
                    success = bool(getattr(result, "success", False))
                    return SkillResponse(
                        success=success,
                        confidence=0.95 if success else 0.0,
                        source=self.name,
                        data=getattr(result, "data", None),
                        error=getattr(result, "error", None),
                    )
        return SkillResponse(
            success=False,
            confidence=0.0,
            source=self.name,
            data={
                "status": "unavailable",
                "message": (
                    "Live weather is not available through this skill route. "
                    "Route the request to the registered weather_action and provide a location."
                ),
            },
            error="No live weather action/location was available to this skill.",
        )
