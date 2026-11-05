from typing import Dict, Any

from skills.base import BaseSkill, SkillResponse


class AgentSkill(BaseSkill):
    """
    Executes the agent selected by the Reasoning Engine.
    """

    name = "agent"
    description = "Executes specialised AI agents."
    version = "1.0.0"
    priority = 100
    requires_llm = False

    async def can_run(self, query: str, context: Dict[str, Any]) -> float:
        agent_result = context.get("agent_result")

        if agent_result:
            return 1.0

        return 0.0

    async def execute(
        self,
        query: str,
        context: Dict[str, Any]
    ) -> SkillResponse:

        agent_result = context.get("agent_result")

        if agent_result is None:
            return SkillResponse(
                success=False,
                confidence=0.0,
                source=self.name,
                error="No agent selected."
            )

        return SkillResponse(
            success=agent_result.success,
            confidence=agent_result.confidence,
            source=agent_result.agent,
            data=agent_result.data
        )