import logging
from typing import Dict, Any, List, Optional, Tuple

from brain.agents.base_agent import BaseAgent

logger = logging.getLogger("aria")


class AgentManager:
    """
    Registers agents and selects the most suitable one.
    """

    def __init__(self):
        self.agents: List[BaseAgent] = []

    def register(self, agent: BaseAgent):
        self.agents.append(agent)

        logger.info(
            "[AgentManager] Registered agent: %s",
            agent.name
        )

    def get(self, name: str) -> Optional[BaseAgent]:
        """
        Retrieves a registered agent by its name.
        """
        for agent in self.agents:
            if agent.name == name:
                return agent
        return None

    async def select_agent(
        self,
        query: str,
        context: Dict[str, Any]
    ) -> Tuple[Optional[BaseAgent], float]:

        best_agent = None
        best_score = 0.0

        for agent in self.agents:
            score = await agent.can_handle(query, context)

            logger.info(
                "[AgentManager] %s score=%.2f (priority=%d)",
                agent.name,
                score,
                getattr(agent, "priority", 0)
            )

            if (
                score > best_score or
                (
                    score == best_score and
                    best_agent is not None and
                    getattr(agent, "priority", 0) > getattr(best_agent, "priority", 0)
                )
            ):
                best_score = score
                best_agent = agent

        return best_agent, best_score
