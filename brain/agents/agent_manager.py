import logging
from typing import Dict, Any, List

from brain.agents.base_agent import BaseAgent

logger = logging.getLogger("aria")


class AgentManager:
    """
    Registers agents and routes requests
    to the most suitable one.
    """

    def __init__(self):
        self.agents: List[BaseAgent] = []

    def register(self, agent: BaseAgent):
        self.agents.append(agent)

        logger.info(
            "[AgentManager] Registered agent: %s",
            agent.name
        )

    async def select_agent(
        self,
        query: str,
        context: Dict[str, Any]
    ):

        best_agent = None
        best_score = 0.0

        for agent in self.agents:

            score = await agent.can_handle(
                query,
                context
            )

            logger.info(
                "[AgentManager] %s score=%.2f",
                agent.name,
                score
            )

            if score > best_score:
                best_score = score
                best_agent = agent

        return best_agent, best_score