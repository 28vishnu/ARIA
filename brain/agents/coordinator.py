import logging
import asyncio
from typing import List, Dict, Any

logger = logging.getLogger("aria")


class AgentCoordinator:
    """
    Coordinates the execution of multiple specialist agents,
    passing shared context and cumulative agent outputs sequentially,
    scoring results, and sorting by confidence.
    """

    def __init__(self, agent_manager):
        self.agent_manager = agent_manager

    def score_result(self, agent: str, result):

        if result is None:
            return 0.0

        score = 0.5

        text = str(result)

        if len(text) > 150:
            score += 0.1

        if "error" in text.lower():
            score -= 0.3

        if agent == "research":
            score += 0.2

        if agent == "coding":
            score += 0.15

        if agent == "planning":
            score += 0.1

        return max(0.0, min(score, 1.0))

    async def execute(
        self,
        agents: List[str],
        query: str,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Execute agents sequentially, making prior agent outputs
        available to subsequent agents in the workflow, scoring results,
        and sorting them by confidence.
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

            confidence = self.score_result(
                agent,
                result,
            )

            outputs.append(
                {
                    "agent": agent,
                    "result": result,
                    "confidence": confidence,
                }
            )

            shared_context["agent_outputs"][agent] = result

        outputs.sort(
            key=lambda x: x["confidence"],
            reverse=True,
        )

        for output in outputs:

            logger.info(
                "[Coordinator] %s confidence %.2f",
                output["agent"],
                output["confidence"],
            )

        logger.info(
            "[Coordinator] Completed execution chain for %d agents.",
            len(agents),
        )

        return {
            "outputs": outputs,
            "shared_context": shared_context,
        }
