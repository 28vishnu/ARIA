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

    async def process(
        self,
        query: str,
        context: Dict[str, Any],
    ) -> str:
        """
        Execute ARIA's cognitive loop:

        observe
            -> understand
            -> route
            -> reason
            -> execute
            -> reflect

        Vision context is preserved throughout the current
        cognitive cycle so ARIA can reason about an image
        while responding to the user's conversation.
        """

        context = context or {}

        try:
            # ---------------------------------------------------------
            # 1. Initialize ephemeral working context
            # ---------------------------------------------------------
            session_id = context.get(
                "session_id",
                "default",
            )

            self.working_memory.initialize(
                session_id,
                query,
            )

            # Preserve vision information inside working memory.
            # This allows downstream cognitive components to access
            # the image analysis during the current request.
            vision_result = context.get("vision_result")

            if vision_result:
                self.working_memory.set(
                    "vision_result",
                    vision_result,
                )

                logger.info(
                    "[CognitiveConductor] Vision context attached."
                )

            # Also preserve raw image metadata when supplied.
            image_metadata = context.get("image_metadata")

            if image_metadata:
                self.working_memory.set(
                    "image_metadata",
                    image_metadata,
                )

            # ---------------------------------------------------------
            # 2. Understand: Extract structured intent
            # ---------------------------------------------------------
            intent = await self.intent_analyzer.analyze(
                query,
                context,
            )

            self.working_memory.set(
                "intent",
                intent,
            )

            logger.info(
                "[CognitiveConductor] Resolved Intent Type: %s "
                "(Confidence: %.2f)",
                intent.get("type"),
                intent.get("confidence", 0.0),
            )

            # ---------------------------------------------------------
            # 3. Route request
            # ---------------------------------------------------------
            route = self.router.route(intent)

            logger.info(
                "[Router] Selected route: %s",
                route.value,
            )

            if route.value == "greeting":
                logger.info("[Router] Greeting Route")

            elif route.value == "document":
                logger.info("[Router] Document Route")

            elif route.value == "vision":
                logger.info("[Router] Vision Route")

                # Explicitly mark this request as vision-aware.
                self.working_memory.set(
                    "vision_active",
                    True,
                )

            elif route.value == "tool":
                logger.info("[Router] Tool Route")

            elif route.value == "planner":
                logger.info("[Router] Planner Route")

                if self.brain and hasattr(
                    self.brain,
                    "plan",
                ):
                    plan = await self.brain.plan(query)

                    self.working_memory.set(
                        "plan",
                        plan,
                    )

                    logger.info(
                        "[Router] Generated plan: %s",
                        plan,
                    )

            else:
                logger.info("[Router] General Route")

            # ---------------------------------------------------------
            # 4. Reason & Decide
            # ---------------------------------------------------------
            strategy = await self.decision_engine.decide(
                intent,
                context,
                self.memory_engine,
            )

            self.working_memory.set(
                "strategy",
                strategy,
            )

            # ---------------------------------------------------------
            # 5. Plan & Execute
            # ---------------------------------------------------------
            execution_results = (
                await self.execution_graph.execute(
                    strategy,
                    self.working_memory,
                )
            )

            self.working_memory.set(
                "results",
                execution_results,
            )

            # ---------------------------------------------------------
            # 6. Reflect & Learn
            # ---------------------------------------------------------
            reflection = await self.reflection_engine.evaluate(
                intent,
                execution_results,
            )

            self.working_memory.set(
                "reflection",
                reflection,
            )

            # ---------------------------------------------------------
            # 7. Finalize
            # ---------------------------------------------------------
            output = execution_results.get(
                "output",
                "Execution completed successfully, Sir.",
            )

            self.working_memory.clear()

            return output

        except Exception as e:
            logger.exception(
                "[CognitiveConductor ERROR] Pipeline failed: %s",
                e,
            )

            self.working_memory.clear()

            return (
                "An error occurred during cognitive processing: "
                f"{str(e)}"
            )