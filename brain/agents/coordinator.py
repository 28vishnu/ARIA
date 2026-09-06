import asyncio
import copy
import logging
import time
from typing import List, Dict, Any, Optional

logger = logging.getLogger("aria")


class AgentCoordinator:
    """
    ARIA Phase-11 specialist-agent coordinator.

    Responsibilities:
      - Resolve agents from the canonical cognitive decision.
      - Normalize object/dict decision contracts.
      - Execute only explicitly requested specialist agents.
      - Preserve shared context between sequential agents.
      - Support bounded parallel execution for explicitly independent jobs.
      - Score and aggregate agent results.
      - Produce a deterministic consensus object.
      - Keep bounded execution history.

    The coordinator does NOT independently infer user intent.
    CognitiveCore/CognitiveController remain the orchestration owners.
    """

    VERSION = "11.6"
    MAX_HISTORY = 100
    DEFAULT_MAX_PARALLEL_AGENTS = 3
    MAX_PARALLEL_AGENTS = 8

    def __init__(
        self,
        agent_manager=None,
        max_parallel_agents: int = DEFAULT_MAX_PARALLEL_AGENTS,
    ):
        self.agent_manager = agent_manager

        try:
            requested_parallel = int(max_parallel_agents)
        except (TypeError, ValueError):
            requested_parallel = self.DEFAULT_MAX_PARALLEL_AGENTS

        self.max_parallel_agents = max(
            1,
            min(
                requested_parallel,
                self.MAX_PARALLEL_AGENTS,
            ),
        )

        # Maps cognitive capabilities/aliases to registered specialist agents.
        self.skill_agent_map = {
            "chat": "chat",
            "coding": "coding",
            "research": "research",
            "planning": "planning",
            "writing": "writing",
            "math": "math",
            "memory": "memory",
            "document": "document",
            "reasoning": "reasoning",
            "execution": "execution",
            "memory_engine": "memory",
            "document_intelligence": "document",
            "web": "research",
            "web_search": "research",
        }

        self.valid_agents = {
            "chat",
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

        self.agent_priority = {
            "memory": 10,
            "document": 20,
            "research": 30,
            "coding": 40,
            "planning": 50,
            "writing": 60,
            "math": 70,
            "reasoning": 80,
            "execution": 90,
            "chat": 100,
        }

        self.execution_history: List[Dict[str, Any]] = []

    # =========================================================
    # GENERIC HELPERS
    # =========================================================

    @staticmethod
    def _decision_value(
        decision: Any,
        key: str,
        default=None,
    ):
        if decision is None:
            return default

        if isinstance(decision, dict):
            return decision.get(key, default)

        return getattr(
            decision,
            key,
            default,
        )

    @staticmethod
    def _as_list(value: Any) -> List[Any]:
        if value is None:
            return []

        if isinstance(value, (list, tuple, set)):
            return list(value)

        return [value]

    @staticmethod
    def _as_dict(value: Any) -> Dict[str, Any]:
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _safe_confidence(value: Any, default: float = 0.0) -> float:
        try:
            confidence = float(value)
        except (TypeError, ValueError):
            confidence = default

        if confidence != confidence:  # NaN
            confidence = default

        return max(
            0.0,
            min(
                confidence,
                1.0,
            ),
        )

    def _normalize_agent_name(
        self,
        value: Any,
    ) -> Optional[str]:
        if value is None:
            return None

        name = str(value).strip().lower()

        if not name:
            return None

        name = self.skill_agent_map.get(
            name,
            name,
        )

        if name not in self.valid_agents:
            logger.warning(
                "[AgentCoordinator] Ignoring unknown agent/capability: %s",
                value,
            )
            return None

        return name

    # =========================================================
    # EXECUTION PLAN RESOLUTION
    # =========================================================

    def _resolve_execution_plan(
        self,
        decision,
    ) -> List[str]:
        """
        Resolve the final specialist list from the canonical decision.

        Precedence:
          1. Explicit selected agents.
          2. Selected skills.
          3. Selected tools.
          4. Required tools.
          5. Required capability flags.

        Unknown capabilities are rejected rather than invented.
        """

        if decision is None:
            return []

        execution_plan: List[str] = []

        def add_agent(value):
            normalized = self._normalize_agent_name(
                value
            )

            if (
                normalized
                and normalized not in execution_plan
            ):
                execution_plan.append(normalized)

        for agent in self._as_list(
            self._decision_value(
                decision,
                "selected_agents",
                [],
            )
        ):
            add_agent(agent)

        for skill in self._as_list(
            self._decision_value(
                decision,
                "selected_skills",
                [],
            )
        ):
            add_agent(skill)

        for tool in self._as_list(
            self._decision_value(
                decision,
                "selected_tools",
                [],
            )
        ):
            add_agent(tool)

        for tool in self._as_list(
            self._decision_value(
                decision,
                "required_tools",
                [],
            )
        ):
            add_agent(tool)

        required_capabilities = {
            "memory": self._decision_value(
                decision,
                "requires_memory",
                False,
            ),
            "document": self._decision_value(
                decision,
                "requires_documents",
                False,
            ),
            "research": self._decision_value(
                decision,
                "requires_web",
                False,
            ),
            "planning": self._decision_value(
                decision,
                "requires_planning",
                False,
            ),
        }

        for capability, required in required_capabilities.items():
            if bool(required):
                add_agent(capability)

        execution_plan.sort(
            key=lambda agent: self.agent_priority.get(
                agent,
                999,
            )
        )

        return execution_plan

    # =========================================================
    # AGENT RESOLUTION
    # =========================================================

    def _resolve_agent(
        self,
        agent_name: str,
    ):
        if self.agent_manager is None:
            return None

        try:
            getter = getattr(
                self.agent_manager,
                "get",
                None,
            )

            if callable(getter):
                return getter(agent_name)
        except Exception:
            logger.exception(
                "[AgentCoordinator] AgentManager.get failed for %s.",
                agent_name,
            )

        try:
            agents = getattr(
                self.agent_manager,
                "agents",
                {},
            )

            if isinstance(agents, dict):
                return agents.get(agent_name)

        except Exception:
            logger.exception(
                "[AgentCoordinator] Failed reading AgentManager agents."
            )

        return None

    # =========================================================
    # RESULT SCORING
    # =========================================================

    def score_result(
        self,
        agent: str,
        result,
    ) -> float:
        if result is None:
            return 0.0

        score = 0.5

        if isinstance(result, dict):
            if result.get("success") is False:
                return 0.0

            explicit_confidence = result.get(
                "confidence"
            )

            if explicit_confidence is not None:
                score = self._safe_confidence(
                    explicit_confidence,
                    0.5,
                )

            value = result.get(
                "result",
                result.get(
                    "output",
                    result.get(
                        "data",
                        result,
                    ),
                ),
            )

        else:
            value = result

        text = str(value or "").strip()

        if len(text) > 150:
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

        # Only apply the heuristic bonus when the result did not explicitly
        # provide a confidence score.
        if not (
            isinstance(result, dict)
            and result.get("confidence") is not None
        ):
            score += agent_bonus.get(
                agent,
                0.0,
            )

        return max(
            0.0,
            min(
                score,
                1.0,
            ),
        )

    # =========================================================
    # PARALLEL EXECUTION
    # =========================================================

    async def run_parallel(
        self,
        jobs,
    ):
        """
        Execute explicitly independent jobs concurrently.

        The caller is responsible for deciding that jobs are independent.
        This method only applies the concurrency bound.
        """

        if not jobs:
            return []

        semaphore = asyncio.Semaphore(
            self.max_parallel_agents
        )

        async def limited_job(job):
            async with semaphore:
                try:
                    if callable(job):
                        result = job()
                        if hasattr(
                            result,
                            "__await__",
                        ):
                            return await result
                        return result

                    if hasattr(
                        job,
                        "__await__",
                    ):
                        return await job

                    return job

                except asyncio.CancelledError:
                    raise

                except Exception as exc:
                    logger.exception(
                        "[AgentCoordinator] Parallel agent job failed."
                    )
                    return exc

        return await asyncio.gather(
            *[
                limited_job(job)
                for job in jobs
            ],
            return_exceptions=False,
        )

    # =========================================================
    # CONSENSUS
    # =========================================================

    async def consensus(
        self,
        query,
        agent_results,
    ):
        """
        Produce a deterministic consensus summary.

        Consensus is intentionally lightweight: it selects the strongest
        successful result and reports agreement/confidence. It does not make
        another LLM call or invent a new answer.
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
                successful.append(result)
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
                successful.append(result)

        if not successful:
            return None

        best_result = max(
            successful,
            key=lambda item: self._safe_confidence(
                item.get(
                    "confidence",
                    0.0,
                )
            ),
        )

        confidence_values = [
            self._safe_confidence(
                item.get(
                    "confidence",
                    0.0,
                )
            )
            for item in successful
        ]

        average_confidence = (
            sum(confidence_values)
            / len(confidence_values)
        )

        return {
            "answer": (
                best_result.get("result")
                or best_result.get("output")
                or best_result.get("data")
            ),
            "agreement": round(
                len(successful)
                / max(
                    1,
                    len(agent_results),
                ),
                3,
            ),
            "confidence": round(
                average_confidence,
                3,
            ),
            "best_agent": best_result.get(
                "agent"
            ),
            "participating_agents": [
                item.get("agent")
                for item in successful
                if item.get("agent")
            ],
        }

    # =========================================================
    # SINGLE AGENT EXECUTION
    # =========================================================

    async def _execute_agent(
        self,
        agent_name: str,
        query: str,
        shared_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        agent = self._resolve_agent(
            agent_name
        )

        if (
            agent is None
            and not (
                self.agent_manager
                and callable(
                    getattr(
                        self.agent_manager,
                        "execute_agent",
                        None,
                    )
                )
            )
        ):
            return {
                "agent": agent_name,
                "error": (
                    f"Agent '{agent_name}' is unavailable."
                ),
                "confidence": 0.0,
                "success": False,
            }

        try:
            if (
                agent is not None
                and callable(
                    getattr(
                        agent,
                        "execute",
                        None,
                    )
                )
            ):
                output = await agent.execute(
                    query=query,
                    context=shared_context,
                )

            else:
                output = await self.agent_manager.execute_agent(
                    agent_name,
                    query,
                    shared_context,
                )

            confidence = self.score_result(
                agent_name,
                output,
            )

            if isinstance(output, dict):
                success = bool(
                    output.get(
                        "success",
                        True,
                    )
                )
            else:
                success = output is not None

            return {
                "agent": agent_name,
                "result": output,
                "output": output,
                "confidence": confidence,
                "success": success,
            }

        except asyncio.CancelledError:
            raise

        except Exception as exc:
            logger.exception(
                "[AgentCoordinator] Agent %s failed.",
                agent_name,
            )

            return {
                "agent": agent_name,
                "error": str(exc),
                "confidence": 0.0,
                "success": False,
            }

    # =========================================================
    # MAIN COORDINATION
    # =========================================================

    async def coordinate(
        self,
        decision,
        query: str,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Execute the explicitly requested specialist-agent workflow.

        Agents are sequential by default because each agent receives the
        previous outputs. Parallel execution is available separately through
        run_parallel() for callers that can establish independence.
        """

        execution_plan = self._resolve_execution_plan(
            decision
        )

        logger.info(
            "[AgentCoordinator] Resolved execution plan: %s",
            execution_plan,
        )

        shared_context = copy.deepcopy(
            context or {}
        )

        shared_context["agent_outputs"] = {}

        outputs: List[Dict[str, Any]] = []
        merged: Dict[str, Any] = {}

        logger.info(
            "[Coordinator] %d agents scheduled.",
            len(execution_plan),
        )

        for index, agent_name in enumerate(
            execution_plan
        ):
            shared_context["previous_agents"] = copy.deepcopy(
                outputs
            )
            shared_context["current_agent"] = agent_name
            shared_context["remaining_agents"] = list(
                execution_plan[index + 1:]
            )

            logger.info(
                "[AgentCoordinator] %s received %d previous agent outputs.",
                agent_name,
                len(outputs),
            )

            result = await self._execute_agent(
                agent_name=agent_name,
                query=query,
                shared_context=shared_context,
            )

            outputs.append(result)
            merged[agent_name] = result

            if result.get("success"):
                output = result.get(
                    "result",
                    result.get("output"),
                )
                shared_context["agent_outputs"][
                    agent_name
                ] = copy.deepcopy(output)
                shared_context["latest_result"] = copy.deepcopy(
                    output
                )

        ranked_outputs = sorted(
            outputs,
            key=lambda item: self._safe_confidence(
                item.get(
                    "confidence",
                    0.0,
                )
            ),
            reverse=True,
        )

        consensus_result = await self.consensus(
            query,
            ranked_outputs,
        )

        shared_context["agent_consensus"] = copy.deepcopy(
            consensus_result
        )

        agreement = (
            consensus_result.get(
                "agreement",
                0.0,
            )
            if consensus_result
            else 0.0
        )

        logger.info(
            "[AgentCoordinator] Executed agents: %s. "
            "Agreement: %.0f%%",
            execution_plan,
            agreement * 100,
        )

        # A coordinator with no executable agents is not a successful
        # multi-agent execution. This prevents a misleading success result
        # when a decision referenced unavailable specialists.
        successful_count = sum(
            1
            for item in outputs
            if item.get("success", False)
        )

        result = {
            "success": (
                bool(execution_plan)
                and successful_count > 0
            ),
            "results": copy.deepcopy(
                merged
            ),
            "outputs": copy.deepcopy(
                ranked_outputs
            ),
            "shared_context": shared_context,
            "consensus": copy.deepcopy(
                consensus_result
            ),
            "execution_plan": list(
                execution_plan
            ),
            "successful_agents": successful_count,
            "failed_agents": max(
                0,
                len(outputs) - successful_count,
            ),
            "coordinator_version": self.VERSION,
        }

        self.execution_history.append(
            copy.deepcopy(result)
        )

        if len(self.execution_history) > self.MAX_HISTORY:
            del self.execution_history[:-self.MAX_HISTORY]

        return result

    # =========================================================
    # COMPATIBILITY API
    # =========================================================

    async def execute(
        self,
        agents: List[str],
        query: str,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Compatibility wrapper for direct specialist-agent execution.
        """

        class DummyDecision:
            def __init__(self, selected):
                self.selected_agents = list(
                    selected or []
                )
                self.selected_skills = []
                self.selected_tools = []
                self.required_tools = []
                self.requires_memory = (
                    "memory" in self.selected_agents
                )
                self.requires_documents = (
                    "document" in self.selected_agents
                )
                self.requires_web = (
                    "research" in self.selected_agents
                )
                self.requires_planning = (
                    "planning" in self.selected_agents
                )

        decision = DummyDecision(
            agents
        )

        return await self.coordinate(
            decision=decision,
            query=query,
            context=context,
        )

    async def prepare(
        self,
        agent_name: str,
        query: str,
        context=None,
    ):
        """
        Compatibility wrapper for CognitiveCore.
        """
        return await self.execute(
            agents=[agent_name],
            query=query,
            context=context or {},
        )

    def last_execution(self):
        if not self.execution_history:
            return None

        return copy.deepcopy(
            self.execution_history[-1]
        )

    def clear_history(self):
        self.execution_history.clear()

    def health(self) -> Dict[str, Any]:
        return {
            "status": "healthy",
            "version": self.VERSION,
            "agent_manager": self.agent_manager is not None,
            "max_parallel_agents": self.max_parallel_agents,
            "known_agents": sorted(
                self.valid_agents
            ),
            "history_size": len(
                self.execution_history
            ),
        }
