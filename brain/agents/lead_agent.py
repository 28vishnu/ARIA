import logging

logger = logging.getLogger("aria")


class LeadAgent:

    async def create_execution_plan(
        self,
        query,
        context,
        selected_agents,
    ):

        logger.info(
            "[LeadAgent] Creating execution plan."
        )

        return {
            "query": query,
            "agents": selected_agents,
            "context": context,
        }