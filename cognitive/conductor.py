import logging
from typing import Dict, Any
from cognitive.intent import IntentAnalyzer
from cognitive.decision import DecisionEngine
from cognitive.working_memory import WorkingMemory
from cognitive.execution_graph import ExecutionGraph
from cognitive.reflection import ReflectionEngine
from core.request_router import RequestRouter

logger = logging.getLogger("aria")

class CognitiveConductor:
    """Master orchestrator for ARIA 2.0 executing the full cognitive processing loop."""
    def __init__(self, registry, memory_engine):
        self.registry = registry
        self.memory_engine = memory_engine
        self.intent_analyzer = IntentAnalyzer()
        self.decision_engine = DecisionEngine(registry)
        self.working_memory = WorkingMemory()
        self.execution_graph = ExecutionGraph(registry)
        self.reflection_engine = ReflectionEngine(memory_engine)
        self.router = RequestRouter()
        self.brain = registry.get("brain") if registry else None

    async def process(self, query: str, context: Dict[str, Any]) -> str:
        """Executes the complete observe -> understand -> reason -> execute -> reflect loop."""
        try:
            # 1. Initialize ephemeral working context
            session_id = context.get("session_id", "default")
            self.working_memory.initialize(session_id, query)
            
            # 2. Understand: Extract structured intent
            intent = await self.intent_analyzer.analyze(query, context)
            self.working_memory.set("intent", intent)
            logger.info("[CognitiveConductor] Resolved Intent Type: %s (Confidence: %.2f)", intent.get("type"), intent.get("confidence", 0.0))

            # Route determination & verification logging (added per instructions)
            route = self.router.route(intent)
            logger.info("[Router] Selected route: %s", route.value)

            if route.value == "greeting":
                logger.info("[Router] Greeting Route")
            elif route.value == "document":
                logger.info("[Router] Document Route")
            elif route.value == "vision":
                logger.info("[Router] Vision Route")
            elif route.value == "tool":
                logger.info("[Router] Tool Route")
            elif route.value == "planner":
                logger.info("[Router] Planner Route")
                if self.brain and hasattr(self.brain, "plan"):
                    plan = await self.brain.plan(query)
                    logger.info(plan)
            else:
                logger.info("[Router] General Route")

            # 3. Reason & Decide: Build execution strategy
            strategy = await self.decision_engine.decide(intent, context, self.memory_engine)
            self.working_memory.set("strategy", strategy)

            # 4. Plan & Execute: Run task graph / tool chain
            execution_results = await self.execution_graph.execute(strategy, self.working_memory)
            self.working_memory.set("results", execution_results)

            # 5. Reflect & Learn: Evaluate success and extract lessons
            reflection = await self.reflection_engine.evaluate(intent, execution_results)
            
            # 6. Finalize and clear ephemeral state
            output = execution_results.get("output", "Execution completed successfully, Sir.")
            self.working_memory.clear()
            
            return output

        except Exception as e:
            logger.exception("[CognitiveConductor ERROR] Pipeline failed: %s", e)
            self.working_memory.clear()
            return f"An error occurred during cognitive processing: {str(e)}"

cognitive/conductor.py
