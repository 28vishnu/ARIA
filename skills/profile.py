from skills.base import BaseSkill, SkillResponse

class ProfileSkill(BaseSkill):
    name = "profile"
    description = "Retrieves user profile details (name, education, college)."
    version = "1.0.0"
    priority = 30
    requires_llm = False

    async def can_run(self, query: str, context: dict) -> float:
        lower = query.lower()
        if any(k in lower for k in ["what's my name", "who am i", "my profile", "college", "course"]):
            return 0.95
        return 0.0

    async def execute(self, query: str, context: dict) -> SkillResponse:
        app_state = context.get("app_state")
        profile = app_state.ram_cache.get("profile", {}) if app_state else {}
        return SkillResponse(success=True, confidence=0.95, source=self.name, data=profile)
