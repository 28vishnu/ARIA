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
        decision=None,
    ) -> Dict[str, Any]:

        logger.info("[LeadAgent] Creating execution strategy.")

        query_lower = query.lower()

        # -----------------------------------------------------
        # Canonical decision state
        # -----------------------------------------------------

        selected_skills = list(
            getattr(
                decision,
                "selected_skills",
                [],
            )
            or []
        )

        selected_tools = list(
            getattr(
                decision,
                "selected_tools",
                [],
            )
            or []
        )

        requires_planning = bool(
            getattr(
                decision,
                "requires_planning",
                False,
            )
        )

        requires_web = bool(
            getattr(
                decision,
                "requires_web",
                False,
            )
        )

        requires_memory = bool(
            getattr(
                decision,
                "requires_memory",
                False,
            )
        )

        requires_documents = bool(
            getattr(
                decision,
                "requires_documents",
                False,
            )
        )

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

        # -----------------------------------------------------
        # Normalize execution agents
        # -----------------------------------------------------

        execution_agents = list(
            dict.fromkeys(
                selected_agents
                or selected_skills
            )
        )

        # Planning can be requested by the decision even when
        # the upstream agent selector did not explicitly add it.
        if (
            requires_planning
            and "planning" not in execution_agents
        ):
            execution_agents.append(
                "planning"
            )

        estimated_steps = max(
            1,
            len(execution_agents),
        )

        execution_order = list(
            execution_agents
        )

        return {
            "goal": query,
            "priority": priority,
            "estimated_steps": estimated_steps,

            "agents": execution_agents,

            "execution_order": execution_order,

            "requires_confirmation": (
                requires_confirmation
            ),

            "requirements": {
                "memory": requires_memory,
                "documents": requires_documents,
                "web": requires_web,
                "planning": requires_planning,
            },

            "selected_skills": selected_skills,
            "selected_tools": selected_tools,

            "context": context,
        }
