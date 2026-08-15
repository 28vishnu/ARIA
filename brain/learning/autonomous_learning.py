import logging
from datetime import datetime
from typing import Any, Dict

logger = logging.getLogger("aria")


class AutonomousLearning:

    """
    Central automatic learning system.

    Every important event inside ARIA comes here.

    Nobody else stores knowledge directly.
    """

    def __init__(
        self,
        memory_engine,
        learning_engine,
        knowledge_database,
        knowledge_graph,
        world_model,
    ):

        self.memory = memory_engine
        self.learning = learning_engine
        self.database = knowledge_database
        self.graph = knowledge_graph
        self.world = world_model

        self.statistics = {

            "documents": 0,

            "chats": 0,

            "web": 0,

            "skills": 0,

            "plans": 0,

            "failures": 0,

            "success": 0,

            "reasoning_learned": 0,

            "reflections_learned": 0,

            "executions_learned": 0,

        }

    # =========================================================
    # HELPERS
    # =========================================================

    def _normalize_text(
        self,
        value: Any,
    ) -> str:
        """
        Convert learning input into safe textual form.
        """

        if value is None:
            return ""

        if isinstance(value, str):
            return value.strip()

        if isinstance(value, dict):
            parts = []

            for key, item in value.items():
                if item is None:
                    continue

                parts.append(
                    f"{key}: {item}"
                )

            return "\n".join(parts).strip()

        if isinstance(value, (list, tuple)):
            return "\n".join(
                self._normalize_text(item)
                for item in value
                if item is not None
            ).strip()

        return str(value).strip()

    def _is_learnable(
        self,
        content: str,
    ) -> bool:
        """
        Prevent empty, trivial, or obviously non-learning events
        from polluting the knowledge base.
        """

        if not content:
            return False

        if len(content) < 10:
            return False

        trivial = {
            "hi",
            "hello",
            "hey",
            "thanks",
            "thank you",
            "ok",
            "okay",
        }

        return content.lower().strip() not in trivial

    # =========================================================
    # ADVANCED LEARNING METHODS (NEW)
    # =========================================================

    async def learn_from_reasoning(
        self,
        reasoning_result: Any,
    ):
        """
        Store reusable reasoning signals rather than raw arbitrary
        objects.
        """

        try:
            trace = getattr(
                reasoning_result,
                "reasoning_trace",
                None,
            )

            if not trace:
                trace = self._normalize_text(
                    reasoning_result
                )

            if not self._is_learnable(trace):
                return

            metadata = getattr(
                reasoning_result,
                "metadata",
                {},
            )

            content = (
                f"Reasoning trace:\n{trace}\n\n"
                f"Metadata:\n"
                f"{self._normalize_text(metadata)}"
            )

            await self.database.store(
                title="Reasoning Pattern Learned",
                content=content,
                source="reasoning_engine",
            )

            self.statistics[
                "reasoning_learned"
            ] += 1

        except Exception:
            logger.exception(
                "[AutonomousLearning] "
                "learn_from_reasoning failed."
            )

    async def learn_from_reflection(
        self,
        reflection_data: Any,
    ):
        """
        Convert reflection into reusable learning signals.
        """

        try:
            content = self._normalize_text(
                reflection_data
            )

            if not self._is_learnable(content):
                return

            await self.database.store(
                title="Self-Critique Reflection",
                content=content,
                source="self_reflection",
            )

            if (
                self.world is not None
                and hasattr(
                    self.world,
                    "record_reflection",
                )
            ):
                await self.world.record_reflection(
                    content
                )

            self.statistics[
                "reflections_learned"
            ] += 1

        except Exception:
            logger.exception(
                "[AutonomousLearning] "
                "learn_from_reflection failed."
            )

    async def learn_from_execution(self, execution_result: Dict[str, Any]):
        """
        Learn from workflow execution successes or failures to refine timing, retries, and parameters.
        """
        try:
            success = execution_result.get("success", False)
            content = str(execution_result)
            source_type = "execution_success" if success else "execution_failure"
            await self.database.store(
                title=f"Execution Outcome: {source_type}",
                content=content,
                source=source_type,
            )
            self.statistics["executions_learned"] += 1
        except Exception:
            logger.exception("[AutonomousLearning] learn_from_execution failed.")

    async def improve_planner(self, plan: Any, feedback: str):
        """
        Fine-tune future planning strategies based on plan performance feedback.
        """
        try:
            content = f"Plan Feedback: {feedback}\nPlan: {str(plan)}"
            await self.database.store(
                title="Planner Optimization",
                content=content,
                source="planner_improvement",
            )
        except Exception:
            logger.exception("[AutonomousLearning] improve_planner failed.")

    async def improve_reasoning(self, query: str, correction: str):
        """
        Enhance reasoning logic and prompt structures based on corrections.
        """
        try:
            content = f"Query: {query}\nCorrection: {correction}"
            await self.database.store(
                title="Reasoning Optimization",
                content=content,
                source="reasoning_improvement",
            )
        except Exception:
            logger.exception("[AutonomousLearning] improve_reasoning failed.")

    # =========================================================
    # INDIVIDUAL PROCESSING METHODS
    # =========================================================

    async def process_chat(
        self,
        user,
        assistant,
    ):
        user_text = self._normalize_text(user)
        assistant_text = self._normalize_text(
            assistant
        )

        if not user_text:
            return

        await self.memory.store_chat(
            {
                "user": user_text,
                "assistant": assistant_text,
            }
        )

        if hasattr(
            self.learning,
            "learn_chat",
        ):
            await self.learning.learn_chat(
                user_text,
                assistant_text,
            )

        content = (
            f"User:\n{user_text}\n\n"
            f"Assistant:\n{assistant_text}"
        )

        # Do not automatically promote every conversation
        # into durable knowledge.
        if self._is_learnable(content):
            await self.database.store(
                title="Conversation Experience",
                content=content,
                source="conversation",
            )

        if (
            self.graph is not None
            and hasattr(
                self.graph,
                "learn",
            )
        ):
            await self.graph.learn(content)

        if (
            self.world is not None
            and hasattr(
                self.world,
                "learn",
            )
        ):
            await self.world.learn(
                user_text,
                assistant_text,
            )

        self.statistics["chats"] += 1

    async def process_document(
        self,
        filename,
        summary,
    ):
        await self.learning.learn_document(
            filename,
            summary,
        )

        await self.memory.remember(
            summary
        )

        await self.database.store(
            title=filename,
            content=summary,
            source="document",
        )

        if hasattr(self.graph, "learn"):
            await self.graph.learn(summary)

        if hasattr(self.world, "learn_document"):
            await self.world.learn_document(
                filename,
                summary,
            )

        self.statistics["documents"] += 1

    async def process_web(
        self,
        query,
        answer,
    ):
        query_text = self._normalize_text(query)
        answer_text = self._normalize_text(answer)

        if not answer_text:
            return

        if hasattr(
            self.learning,
            "learn_web",
        ):
            await self.learning.learn_web(
                query_text,
                answer_text,
            )

        await self.database.store(
            title=query_text or "Web Knowledge",
            content=answer_text,
            source="web",
        )

        if (
            self.graph is not None
            and hasattr(
                self.graph,
                "learn",
            )
        ):
            await self.graph.learn(
                answer_text
            )

        # IMPORTANT:
        # Web knowledge must not automatically become
        # personal memory.

        if (
            self.world is not None
            and hasattr(
                self.world,
                "learn",
            )
        ):
            await self.world.learn(
                query_text,
                answer_text,
            )

        self.statistics["web"] += 1

    async def process_skill(
        self,
        skill_name,
        result,
    ):
        content = f"Skill {skill_name} executed with result: {result}"
        await self.database.store(
            title=f"Skill: {skill_name}",
            content=content,
            source="skill",
        )

        if hasattr(self.memory, "remember"):
            await self.memory.remember(content)

        self.statistics["skills"] += 1

    async def process_plan(
        self,
        plan,
    ):
        content = str(plan)
        await self.database.store(
            title="Execution Plan",
            content=content,
            source="plan",
        )

        if hasattr(self.world, "add_goal"):
            self.world.add_goal("Latest Plan", {"plan": content})

        self.statistics["plans"] += 1

    async def process_profile(
        self,
        profile,
    ):
        profile_str = str(profile)
        if hasattr(self.memory, "store_profile"):
            await self.memory.store_profile(profile)

        await self.database.store(
            title="User Profile",
            content=profile_str,
            source="profile",
        )

        if hasattr(self.graph, "learn"):
            await self.graph.learn(profile_str)

        if hasattr(self.learning, "learn_profile"):
            await self.learning.learn_profile(profile)

    async def process_failure(
        self,
        query,
    ):
        await self.database.store(
            title="Knowledge Gap",
            content=query,
            source="unknown",
        )

        self.statistics["failures"] += 1

    async def process_success(
        self,
        query,
        answer,
    ):
        content = f"Query: {query}\nAnswer: {answer}"
        await self.database.store(
            title="Successful Interaction",
            content=content,
            source="success",
        )

        self.statistics["success"] += 1

    # =========================================================
    # MAINTENANCE & UTILITIES
    # =========================================================

    async def consolidate(
        self,
    ):
        pass

    def summary(
        self,
    ):
        return self.statistics

    # =========================================================
    # UNIVERSAL ENTRY POINT
    # =========================================================

    async def learn(
        self,
        source: str,
        **kwargs,
    ):
        """
        Universal learning event dispatcher.

        Every learning event is normalized before entering
        the appropriate subsystem.
        """

        source = str(
            source or ""
        ).strip().lower()

        try:
            if source == "chat":
                await self.process_chat(
                    kwargs.get("user"),
                    kwargs.get("assistant"),
                )

            elif source == "document":
                await self.process_document(
                    kwargs.get("filename"),
                    kwargs.get("summary"),
                )

            elif source == "web":
                await self.process_web(
                    kwargs.get("query"),
                    kwargs.get("answer"),
                )

            elif source == "skill":
                await self.process_skill(
                    kwargs.get("skill_name"),
                    kwargs.get("result"),
                )

            elif source == "profile":
                await self.process_profile(
                    kwargs.get("profile"),
                )

            elif source == "plan":
                await self.process_plan(
                    kwargs.get("plan"),
                )

            elif source == "failure":
                await self.process_failure(
                    kwargs.get("query"),
                )

            elif source == "success":
                await self.process_success(
                    kwargs.get("query"),
                    kwargs.get("answer"),
                )

            elif source == "reasoning":
                await self.learn_from_reasoning(
                    kwargs.get("reasoning")
                )

            elif source == "reflection":
                await self.learn_from_reflection(
                    kwargs.get("reflection")
                )

            elif source == "execution":
                await self.learn_from_execution(
                    kwargs.get("execution")
                )

            else:
                logger.debug(
                    "[AutonomousLearning] "
                    "Unknown learning source: %s",
                    source,
                )

        except Exception:
            logger.exception(
                "[AutonomousLearning] "
                "Learning event failed: %s",
                source,
            )

    async def handle(self, event):
        data = getattr(event, "data", {}) or {}

        return await self.learn(
            event.type,
            **data,
        )
