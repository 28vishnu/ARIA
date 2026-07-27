from skills.base import BaseSkill, SkillResponse

class ChatSkill(BaseSkill):
    name = "chat"
    description = "Handles general conversation, explanations, coding help, and summaries."
    version = "1.0.0"
    priority = 1
    requires_llm = True

    async def can_run(self, query: str, context: dict) -> float:
        cleaned = query.lower().strip()
        if cleaned:
            return 0.40  # Explicit fallback score
        return 0.0

    async def execute(self, query: str, context: dict) -> SkillResponse:
        app_state = context.get("app_state")
        if not app_state or not app_state.registry.has("llm_router"):
            return SkillResponse(
                success=False,
                confidence=0.0,
                source=self.name,
                error="LLM router unavailable."
            )

        llm_router = app_state.registry.get("llm_router")
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
