import logging
import asyncio
from typing import List, Dict, Any

logger = logging.getLogger("aria")


class AgentCoordinator:
    """
    Coordinates the execution of multiple specialist agents,
    passing shared context and cumulative agent outputs sequentially.
    """

    def __init__(self, agent_manager):
        self.agent_manager = agent_manager

    async def execute(
        self,
        agents: List[str],
        query: str,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Execute agents sequentially, making prior agent outputs
        available to subsequent agents in the workflow.
        """
        shared_context = dict(context)
        shared_context["agent_outputs"] = {}

        outputs = []

        for agent in agents:
            logger.info(
                "[Coordinator] %s received %d previous agent outputs",
                agent,
                len(outputs),
            )

            shared_context["previous_agents"] = outputs

            result = await self.agent_manager.execute_agent(
                agent,
                query,
                shared_context,
            )

            outputs.append(
                {
                    "agent": agent,
                    "result": result,
                }
            )

            shared_context["agent_outputs"][agent] = result

        logger.info(
            "[Coordinator] Completed execution chain for %d agents.",
            len(agents),
        )

        return {
            "outputs": outputs,
            "shared_context": shared_context,
        }
