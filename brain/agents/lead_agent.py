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
        # Phase 2: Normalize execution capabilities
        # -----------------------------------------------------

        execution_agents = list(
            dict.fromkeys(
                selected_agents or []
            )
        )

        # Decision-selected skills are additional capabilities.
        for skill in selected_skills:
            if skill and skill not in execution_agents:
                execution_agents.append(skill)

        # Required subsystems must never be omitted.
        required_capabilities = []

        if requires_memory:
            required_capabilities.append("memory")

        if requires_documents:
            required_capabilities.append("document")

        if requires_web:
            required_capabilities.append("research")

        if requires_planning:
            required_capabilities.append("planning")

        for capability in required_capabilities:
            if capability not in execution_agents:
                execution_agents.append(capability)

        # Always have a conversational fallback.
        if not execution_agents:
            execution_agents.append("chat")

        execution_agents = list(
            dict.fromkeys(execution_agents)
        )

        # -----------------------------------------------------
        # Phase 2: Deterministic execution ordering
        # -----------------------------------------------------

        agent_priority = {
            "memory": 10,
            "document": 20,
            "research": 30,
            "coding": 40,
            "planning": 50,
            "writing": 60,
            "chat": 70,
        }

        execution_order = sorted(
            execution_agents,
            key=lambda agent: agent_priority.get(
                agent,
                100,
            ),
        )

        estimated_steps = max(
            1,
            len(execution_order),
        )

        # -----------------------------------------------------
        # Phase 2: Structured execution steps
        # -----------------------------------------------------

        steps = []

        for index, agent in enumerate(
            execution_order,
            start=1,
        ):
            steps.append({
                "step": index,
                "agent": agent,
                "status": "pending",
                "priority": agent_priority.get(
                    agent,
                    100,
                ),
            })

        return {
            "goal": query,
            "priority": priority,
            "estimated_steps": estimated_steps,

            "agents": execution_agents,

            "execution_order": execution_order,

            "steps": steps,

            "requires_confirmation": (
                requires_confirmation
            ),

            "requirements": {
                "memory": requires_memory,
                "documents": requires_documents,
                "web": requires_web,
                "planning": requires_planning,
            },

            "routing": {
                "source": "reasoning_engine",
                "priority": priority,
                "agent_count": len(execution_agents),
                "deterministic": True,
            },

            "selected_skills": selected_skills,
            "selected_tools": selected_tools,

            "context": context,
        }
