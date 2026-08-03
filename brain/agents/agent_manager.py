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

    def get_agent(self, name: str) -> Optional[BaseAgent]:
        """
        Retrieves a registered agent by its name (alias for sequential execution support).
        """
        return self.get(name)

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

    async def execute_agents(self, plan, context=None):
        """
        Execute multiple agents sequentially.

        plan example:

        [
            {
                "agent": "research",
                "task": "Find information about Tesla"
            },
            {
                "agent": "writing",
                "task": "Summarize the findings"
            }
        ]
        """

        results = []

        if not plan:
            return results

        for step in plan:

            agent_name = step.get("agent")

            task = step.get("task")

            agent = self.get_agent(agent_name)

            if not agent:
                results.append({
                    "agent": agent_name,
                    "success": False,
                    "error": "Agent not found"
                })
                continue

            try:

                if hasattr(agent, "run"):
                    output = await agent.run(task, context)

                elif hasattr(agent, "execute"):
                    output = await agent.execute(task, context)

                else:
                    output = {
                        "error": "Agent has no run() or execute() method"
                    }

                results.append({
                    "agent": agent_name,
                    "success": True,
                    "result": output
                })

            except Exception as e:

                results.append({
                    "agent": agent_name,
                    "success": False,
                    "error": str(e)
                })

        return results
