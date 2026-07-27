from typing import Dict, Any, Optional
from personality.response import SystemResponse

class CognitiveCore:
    """The central orchestrator of ARIA 2.0, accepting injected dependencies to coordinate the cognitive flow."""
    def __init__(
        self,
        planner,
        executor,
        skill_manager,
        memory_router,
        state_manager,
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

    def process(
        self,
        query: str,
        session_id: str = "",
        user_id: str = ""
    ) -> Dict[str, Any]:
        """Orchestrates the complete end-to-end cognitive loop using injected services."""
        # 1. Perception & Pipeline processing if available
        decision = None
        if self.intent_analyzer and self.context_builder and self.decision_engine and self.state_manager:
            # If a pipeline or modular components exist, evaluate through decision engine
            intent = self.intent_analyzer.analyze(query) if hasattr(self.intent_analyzer, "analyze") else None
            context = self.context_builder.build(intent=intent, session_id=session_id, user_id=user_id) if hasattr(self.context_builder, "build") else None
            if context:
                self.state_manager.context = context
            if self.decision_engine and hasattr(self.decision_engine, "decide"):
                decision = self.decision_engine.decide(intent, context)

        # 2. Plan generation if planner is available and required
        plan = None
        if decision and self.planner and hasattr(self.planner, "plan"):
            plan = self.planner.plan(decision=decision, context=self.state_manager.context)
            if self.state_manager and hasattr(self.state_manager, "set_plan"):
                self.state_manager.set_plan(plan)

        # 3. Execution via injected executor
        results = []
        if plan and self.executor and hasattr(self.executor, "execute"):
            results = self.executor.execute(plan=plan)

        return {
            "decision": decision,
            "plan": plan,
            "results": results
        }
