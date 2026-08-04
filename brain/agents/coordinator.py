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

        successful = [
            r
            for r in agent_results
            if r.get("success") or (r.get("result") is not None and "error" not in str(r.get("result")).lower())
        ]

        if not successful:
            return None

        return {
            "answer": successful[0].get("result") or successful[0].get("output"),
            "agreement": len(successful) / len(agent_results),
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
        structured merged outputs along with a consensus evaluation.[span_0](start_span)[span_0](end_span)
        """
        required_tools = getattr(decision, "required_tools", []) if decision else []
        selected_agents = getattr(decision, "selected_agents", []) if decision else []
        
        # Prefer decision.required_tools over reclassifying/selected_agents if available
        if required_tools:
            execution_plan = [tool for tool in required_tools if tool in ["coding", "research", "planning", "writing", "math"]]
        else:
            execution_plan = list(selected_agents)

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

                res_item = {
                    "agent": agent_name,
                    "result": output,
                    "output": output,
                    "confidence": confidence,
                    "success": True,
                }

                outputs.append(res_item)
                merged[agent_name] = res_item
                shared_context["agent_outputs"][agent_name] = output

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

        return {
            "success": True,
            "results": merged,
            "outputs": outputs,
            "shared_context": shared_context,
            "consensus": consensus_result,
        }

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
