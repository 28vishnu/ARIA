from skills.base import BaseSkill, SkillResponse

class ChatSkill(BaseSkill):
    name = "chat"
    description = "Handles general conversation, explanations, coding help, and summaries."
    version = "1.0.0"
    priority = 1  # Lowest priority so specialized skills run first
    requires_llm = True

    async def can_run(self, query: str, context: dict) -> float:
        cleaned = query.lower().strip()
        if not cleaned:
            return 0.0
        return 0.30  # Weak possibility / fallback score

    async def execute(self, query: str, context: dict) -> SkillResponse:
        llm_router = context.get("app_state").registry.get("llm_router")
        messages = [
            {"role": "system", "content": "You are ARIA, an advanced AI operating platform."},
            {"role": "user", "content": query}
        ]
        response_text = await llm_router.chat(messages)
        return SkillResponse(
            success=True,
            confidence=0.85,
            source=self.name,
            data={
                "status": "success",
                "response": response_text
            }
        )
