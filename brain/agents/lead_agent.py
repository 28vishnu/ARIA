import logging
from typing import Dict, Any, List

logger = logging.getLogger("aria")


class LeadAgent:
    """
    LeadAgent is responsible for creating the high-level execution
    strategy before specialist agents begin working.
    """

    async def create_execution_plan(
        self,
        query: str,
        context: Dict[str, Any],
        selected_agents: List[str],
    ) -> Dict[str, Any]:

        logger.info("[LeadAgent] Creating execution strategy.")

        query_lower = query.lower()

        priority = "normal"

        if any(
            word in query_lower
            for word in [
                "urgent",
                "immediately",
                "important",
                "asap",
            ]
        ):
            priority = "high"

        requires_confirmation = any(
            word in query_lower
            for word in [
                "delete",
                "remove",
                "format",
                "shutdown",
                "restart",
            ]
        )

        estimated_steps = max(1, len(selected_agents))

        execution_order = list(selected_agents)

        return {
            "goal": query,
            "priority": priority,
            "estimated_steps": estimated_steps,
            "agents": selected_agents,
            "execution_order": execution_order,
            "requires_confirmation": requires_confirmation,
            "context": context,
        }
