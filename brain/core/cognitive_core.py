import logging
from typing import Dict, Any, Optional
from personality.response import SystemResponse

logger = logging.getLogger("aria")

class CognitiveCore:
    """The central orchestrator of ARIA 2.0, coordinating skills, memory, planning, and execution."""
    def __init__(
        self,
        planner,
        executor,
        skill_manager,
        memory_router=None,
        state_manager=None,
        intent_analyzer=None,
        context_builder=None,
        decision_engine=None
    ):
        self.planner = planner
        self.executor = executor
        self.skill_manager = skill_manager
        self.memory_router = memory_router
        self.state_manager = state_manager
        self.intent_analyzer = intent_analyzer
        self.context_builder = context_builder
        self.decision_engine = decision_engine

    async def process(
        self,
        query: str,
        session_id: str = "",
        user_id: str = "",
        base_context: Optional[Dict[str, Any]] = None
    ) -> SystemResponse:
        """Orchestrates the core request-processing flow using existing skill routing, planning, and execution."""
        try:
            # 1. Get State
            state = {}
            if self.state_manager:
                state = self.state_manager.get_state(session_id)

            # 2. Get Memory
            memories = []
            if self.memory_router:
                memories = await self.memory_router.get_relevant_memories(query)

            # 3. Build Context (including state and memories)
            ctx = {}
            if self.context_builder:
                ctx = await self.context_builder.build(
                    query=query,
                    session_id=session_id,
                    user_id=user_id,
                    base_context=base_context,
                    memory=memories,
                    state=state
                )
            else:
                ctx = base_context or {}
                ctx["state"] = state
                ctx["memory"] = memories

            # Store the current request in the session state
            if self.state_manager:
                self.state_manager.update_state(
                    session_id,
                    last_query=query
                )

            intent = None
            if self.intent_analyzer:
                intent = await self.intent_analyzer.analyze(query)
                ctx["intent"] = intent

            # 4. Decision Engine
            decision = None
            if self.decision_engine:
                decision = await self.decision_engine.decide(
                    context=ctx,
                    skill_manager=self.skill_manager,
                    planner=self.planner
                )

            if decision:

                # Memory response
                if decision.action == "memory":
                    return SystemResponse(
                        success=True,
                        confidence=decision.confidence,
                        data=decision.data,
                        source="memory"
                    )

                # Direct skill
                elif decision.action == "skill":
                    if self.skill_manager and hasattr(self.skill_manager, "route_and_execute"):
                        skill_res = await self.skill_manager.route_and_execute(query, ctx)

                        if skill_res:
                            return SystemResponse(
                                success=skill_res.success,
                                confidence=skill_res.confidence,
                                data=skill_res.data,
                                source=skill_res.source
                            )

                # Planner
                elif decision.action == "planner":
                    pass

            # 2. Otherwise, fall back to Planner + Executor Orchestration
            plan = None
            if self.planner and hasattr(self.planner, "create_plan"):
                plan = await self.planner.create_plan(query, ctx)
            elif self.planner and hasattr(self.planner, "plan"):
                # Handle sync planner if applicable
                plan = self.planner.plan(query, ctx)

            # Graceful handling if planner returns empty or no tasks
            if not plan or not getattr(plan, "tasks", None):
                return SystemResponse(
                    success=True,
                    confidence=getattr(plan, "confidence", 0.5),
                    data={"intent": "conversational", "query": query},
                    source="planner_conversational"
                )

            # 3. Execute the generated plan
            exec_result = {}
            if self.executor and hasattr(self.executor, "execute_plan"):
                exec_result = await self.executor.execute_plan(plan, ctx)
            elif self.executor and hasattr(self.executor, "execute"):
                exec_result = self.executor.execute(plan, ctx)

            final_data = exec_result.get("task_outputs", {}) if isinstance(exec_result, dict) else exec_result
            success = exec_result.get("success", True) if isinstance(exec_result, dict) else True

            if self.state_manager:
                self.state_manager.update_state(
                    session_id,
                    last_action="planner_executor",
                    last_success=success
                )

            return SystemResponse(
                success=success,
                confidence=getattr(plan, "confidence", 0.85),
                data=final_data,
                source="planner_executor",
                error=None if success else "Orchestration tasks encountered failures."
            )

        except Exception as e:
            logger.exception("[CognitiveCore ERROR] Processing failed: %s", e)
            return SystemResponse(
                success=False,
                confidence=0.0,
                source="cognitive_core",
                error=str(e)
            )
