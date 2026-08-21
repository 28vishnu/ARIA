import logging
import asyncio
from typing import List, Dict, Any

logger = logging.getLogger("aria")


class AgentCoordinator:
    """
    Coordinates the execution of multiple specialist agents,
    passing shared context and cumulative agent outputs sequentially,
    scoring results, sorting by confidence, returning a structured
    merged dictionary response, and producing agent consensus.
    """

    def __init__(self, agent_manager):
        self.agent_manager = agent_manager
        self.max_parallel_agents = 3

        # Maps cognitive skills/tools to registered specialist agents.
        self.skill_agent_map = {
            "coding": "coding",
            "research": "research",
            "planning": "planning",
            "writing": "writing",
            "math": "math",
            "memory_engine": "memory",
            "document_intelligence": "document",
            "reasoning": "reasoning",
            "execution": "execution",
        }

        # Stores previous agent executions
        self.execution_history = []

    def _resolve_execution_plan(
        self,
        decision,
    ) -> List[str]:
        """
        Convert the canonical Decision object into concrete
        specialist agents.

        New architecture:
            Decision.selected_skills
            Decision.selected_tools
                    ↓
              specialist agents

        Legacy fields are retained as fallbacks.
        """

        if decision is None:
            return []

        execution_plan = []

        # -----------------------------------------------------
        # Preferred Phase-1 fields
        # -----------------------------------------------------

        selected_skills = getattr(
            decision,
            "selected_skills",
            [],
        )

        selected_tools = getattr(
            decision,
            "selected_tools",
            [],
        )

        for skill in selected_skills or []:
            agent_name = self.skill_agent_map.get(
                skill,
                skill,
            )

            if agent_name:
                execution_plan.append(
                    agent_name
                )

        # Tools can explicitly request specialist execution.
        for tool in selected_tools or []:
            agent_name = self.skill_agent_map.get(
                tool,
                tool,
            )

            if agent_name:
                execution_plan.append(
                    agent_name
                )

        # -----------------------------------------------------
        # Legacy compatibility
        # -----------------------------------------------------

        if not execution_plan:

            required_tools = getattr(
                decision,
                "required_tools",
                [],
            )

            selected_agents = getattr(
                decision,
                "selected_agents",
                [],
            )

            execution_plan.extend(
                required_tools or []
            )

            execution_plan.extend(
                selected_agents or []
            )

        # -----------------------------------------------------
        # Normalize + deduplicate
        # -----------------------------------------------------

        valid_agents = {
            "coding",
            "research",
            "planning",
            "writing",
            "math",
            "memory",
            "document",
            "reasoning",
            "execution",
        }

        execution_plan = [
            agent
            for agent in execution_plan
            if agent in valid_agents
        ]

        return list(
            dict.fromkeys(
                execution_plan
            )
        )

    def score_result(
        self,
        agent: str,
        result,
    ):

        if result is None:
            return 0.0

        score = 0.5

        if isinstance(result, dict):

            if result.get("success") is False:
                return 0.0

            text = str(
                result.get(
                    "result",
                    result.get(
                        "output",
                        result,
                    ),
                )
            )

        else:
            text = str(result)

        if len(text.strip()) > 150:
            score += 0.1

        if "error" in text.lower():
            score -= 0.3

        agent_bonus = {
            "research": 0.20,
            "coding": 0.15,
            "planning": 0.10,
            "writing": 0.05,
            "math": 0.10,
            "reasoning": 0.10,
        }

        score += agent_bonus.get(
            agent,
            0.0,
        )

        return max(
            0.0,
            min(score, 1.0),
        )

    async def run_parallel(
        self,
        jobs,
    ):
        """
        Execute independent agent jobs concurrently while
        respecting the configured concurrency limit.
        """

        if not jobs:
            return []

        semaphore = asyncio.Semaphore(
            self.max_parallel_agents
        )

        async def limited_job(job):
            async with semaphore:
                return await job

        return await asyncio.gather(
            *[
                limited_job(job)
                for job in jobs
            ],
            return_exceptions=True,
        )

    async def consensus(
        self,
        query,
        agent_results,
    ):
        """
        Produce a consensus from multiple agent outputs.
        """

        if not agent_results:
            return None

        successful = []

        for result in agent_results:

            if not isinstance(
                result,
                dict,
            ):
                continue

            if result.get(
                "success",
                False,
            ):
                successful.append(
                    result
                )
                continue

            value = result.get(
                "result"
            )

            if (
                value is not None
                and "error" not in str(
                    value
                ).lower()
            ):
                successful.append(
                    result
                )

        if not successful:
            return None

        best_result = max(
            successful,
            key=lambda item: item.get(
                "confidence",
                0.0,
            ),
        )

        average_confidence = (
            sum(
                item.get(
                    "confidence",
                    0.0,
                )
                for item in successful
            )
            / len(successful)
        )

        return {
            "answer": (
                best_result.get("result")
                or best_result.get("output")
            ),
            "agreement": (
                len(successful)
                / len(agent_results)
            ),
            "confidence": round(
                average_confidence,
                3,
            ),
            "best_agent": best_result.get(
                "agent"
            ),
        }

    async def coordinate(
        self,
        decision,
        query: str,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Main entry point for multi-agent coordination.
        Executes agents sequentially based on the decision's required tools or selected agents,
        never stopping on failures, scoring/sorting results, and returning
        structured merged outputs along with a consensus evaluation.
        """
        # -----------------------------------------------------
        # Resolve canonical Phase-1 decision
        # -----------------------------------------------------

        execution_plan = self._resolve_execution_plan(
            decision
        )

        logger.info(
            "[AgentCoordinator] Resolved execution plan: %s",
            execution_plan,
        )

        shared_context = dict(context)
        shared_context["agent_outputs"] = {}

        outputs = []

        merged = {
            "planning": None,
            "research": None,
            "coding": None,
            "writing": None,
            "math": None,
        }

        logger.info(
            "[Coordinator] %d agents scheduled.",
            len(execution_plan),
        )

        for agent_name in execution_plan:
            agent = None
            if self.agent_manager:
                if hasattr(self.agent_manager, "get"):
                    agent = self.agent_manager.get(agent_name)
                elif hasattr(self.agent_manager, "agents"):
                    agent = self.agent_manager.agents.get(agent_name)

            if not agent and not (self.agent_manager and hasattr(self.agent_manager, "execute_agent")):
                continue

            logger.info(
                "[AgentCoordinator] %s received %d previous agent outputs",
                agent_name,
                len(outputs),
            )

            shared_context["previous_agents"] = outputs
            shared_context["current_agent"] = agent_name
            shared_context["remaining_agents"] = [
                a for a in execution_plan
                if a != agent_name
            ]

            output = None
            try:
                if agent and hasattr(agent, "execute"):
                    output = await agent.execute(
                        query=query,
                        context=shared_context,
                    )
                elif self.agent_manager and hasattr(self.agent_manager, "execute_agent"):
                    output = await self.agent_manager.execute_agent(
                        agent_name,
                        query,
                        shared_context,
                    )

                confidence = self.score_result(agent_name, output)

                success = output is not None

                if isinstance(
                    output,
                    dict,
                ):
                    success = output.get(
                        "success",
                        True,
                    )

                res_item = {
                    "agent": agent_name,
                    "result": output,
                    "output": output,
                    "confidence": confidence,
                    "success": bool(success),
                }

                outputs.append(res_item)
                merged[agent_name] = res_item
                shared_context["agent_outputs"][agent_name] = output
                shared_context["latest_result"] = output

            except Exception as e:
                logger.exception(e)
                logger.warning(
                    "[AgentCoordinator] Agent %s failed",
                    agent_name,
                )
                err_item = {
                    "agent": agent_name,
                    "error": str(e),
                    "confidence": 0.0,
                    "success": False,
                }
                outputs.append(err_item)
                merged[agent_name] = err_item

        outputs.sort(
            key=lambda x: x.get("confidence", 0.0),
            reverse=True,
        )

        for output in outputs:
            if "confidence" in output:
                logger.info(
                    "[AgentCoordinator] %s confidence %.2f",
                    output["agent"],
                    output["confidence"],
                )

        consensus_result = await self.consensus(
            query,
            outputs,
        )

        shared_context["agent_consensus"] = consensus_result

        logger.info(
            "[AgentCoordinator] Executed agents: %s. Agreement: %.0f%%",
            execution_plan,
            (consensus_result.get("agreement", 0.0) * 100) if consensus_result else 0.0,
        )

        logger.info(
            "[Coordinator] Multi-agent execution completed."
        )

        result = {
            "success": True,
            "results": merged,
            "outputs": outputs,
            "shared_context": shared_context,
            "consensus": consensus_result,
        }

        self.execution_history.append(result)

        if len(self.execution_history) > 100:
            self.execution_history.pop(0)

        return result

    async def execute(
        self,
        agents: List[str],
        query: str,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Legacy compatibility wrapper mapping to coordinate().
        """
        class DummyDecision:
            def __init__(self, ags):
                self.selected_agents = ags
                self.required_tools = ags

        decision = DummyDecision(agents)
        coord_res = await self.coordinate(decision, query, context)
        return {
            "outputs": coord_res["outputs"],
            "shared_context": coord_res["shared_context"],
        }

    async def prepare(
        self,
        agent_name: str,
        query: str,
        context=None,
    ):
        """
        Compatibility wrapper for CognitiveCore.
        """

        if context is None:
            context = {}

        return await self.execute(
            [agent_name],
            query,
            context,
        )

    def last_execution(self):
        if not self.execution_history:
            return None
        return self.execution_history[-1]

    def clear_history(self):
        self.execution_history.clear()
