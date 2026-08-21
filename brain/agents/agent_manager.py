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

        # Fast canonical name → agent lookup.
        self.agent_registry: Dict[str, BaseAgent] = {}

    def register(self, agent: BaseAgent):
        if agent is None:
            return

        agent_name = str(
            getattr(agent, "name", "")
        ).strip()

        if not agent_name:
            logger.warning(
                "[AgentManager] Cannot register unnamed agent."
            )
            return

        # Prevent duplicate registration.
        existing = self.agent_registry.get(
            agent_name
        )

        if existing is not None:
            logger.warning(
                "[AgentManager] Replacing existing agent: %s",
                agent_name,
            )

            try:
                self.agents.remove(existing)
            except ValueError:
                pass

        self.agents.append(agent)
        self.agent_registry[agent_name] = agent

        logger.info(
            "[AgentManager] Registered agent: %s",
            agent_name,
        )

    def get(
        self,
        name: str,
    ) -> Optional[BaseAgent]:
        """
        Retrieve a registered agent by canonical name.
        """

        if not name:
            return None

        return self.agent_registry.get(
            str(name).strip()
        )

    def get_agent(self, name: str) -> Optional[BaseAgent]:
        """
        Retrieves a registered agent by its name (alias for sequential execution support).
        """
        return self.get(name)

    def list_agents(self) -> List[str]:
        """
        Return registered agent names.
        """

        return list(
            self.agent_registry.keys()
        )

    def has_agent(
        self,
        name: str,
    ) -> bool:
        """
        Check whether a specialist is registered.
        """

        return self.get(name) is not None

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

    async def execute_agent(
        self,
        agent_name: str,
        query: str,
        context: Optional[Dict[str, Any]] = None,
    ):
        """
        Execute one named specialist agent.

        This is the canonical execution interface used by
        AgentCoordinator.
        """

        context = (
            context
            if isinstance(context, dict)
            else {}
        )

        agent = self.get_agent(
            agent_name
        )

        if agent is None:
            raise ValueError(
                f"Agent not found: {agent_name}"
            )

        logger.info(
            "[AgentManager] Executing agent: %s",
            agent_name,
        )

        if hasattr(agent, "execute"):
            return await agent.execute(
                query=query,
                context=context,
            )

        if hasattr(agent, "run"):
            return await agent.run(
                query,
                context,
            )

        raise RuntimeError(
            f"Agent '{agent_name}' has neither "
            f"execute() nor run()."
        )

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

            try:

                output = await self.execute_agent(
                    agent_name,
                    task,
                    context,
                )

                success = output is not None

                if isinstance(
                    output,
                    dict,
                ):
                    success = output.get(
                        "success",
                        True,
                    )

                results.append({
                    "agent": agent_name,
                    "success": bool(success),
                    "result": output,
                })

            except Exception as e:

                logger.exception(
                    "[AgentManager] Agent execution failed: %s",
                    agent_name,
                )

                results.append({
                    "agent": agent_name,
                    "success": False,
                    "error": str(e),
                })

        return results
