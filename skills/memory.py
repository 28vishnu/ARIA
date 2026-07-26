from skills.base import BaseSkill, SkillResponse

class MemorySkill(BaseSkill):
    name = "memory"
    description = "Recalls user preferences and permanent facts."
    version = "1.0.0"
    priority = 40
    requires_llm = False

    async def can_run(self, query: str, context: dict) -> float:
        lower = query.lower()
        if any(k in lower for k in ["what do i like", "my favorite", "my birthday", "what did i say"]):
            return 0.90
        return 0.0

    async def execute(self, query: str, context: dict) -> SkillResponse:
        app_state = context.get("app_state")
        memory_eng = getattr(app_state, "memory_engine", None) if app_state else None
        if memory_eng is not None:
            memories = await memory_eng.get_relevant_memories(query)
            return SkillResponse(success=True, confidence=0.90, source=self.name, data=memories)
        return SkillResponse(success=False, confidence=0.90, source=self.name, error="Memory engine offline.")
