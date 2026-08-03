import asyncio
import logging

logger = logging.getLogger("aria")


class AgentCoordinator:

    def __init__(self, agent_manager):
        self.agent_manager = agent_manager

    async def execute(self, agents, query, context):

        if not agents:
            return []

        logger.info(
            "[Coordinator] Executing %d agents",
            len(agents),
        )

        tasks = [
            self.agent_manager.execute_agent(
                agent,
                query,
                context,
            )
            for agent in agents
        ]

        results = await asyncio.gather(
            *tasks,
            return_exceptions=True,
        )

        outputs = []

        for agent, result in zip(agents, results):

            if isinstance(result, Exception):

                logger.exception(
                    "[Coordinator] %s failed",
                    agent,
                )

                continue

            outputs.append(
                {
                    "agent": agent,
                    "result": result,
                }
            )

        return outputs