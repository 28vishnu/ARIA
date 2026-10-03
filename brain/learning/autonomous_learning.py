import logging
from datetime import datetime
from typing import Any, Dict

logger = logging.getLogger("aria")


class AutonomousLearning:
    """
    Central automatic learning system.

    Every important event inside ARIA comes here.

    Nobody else stores knowledge directly.

    IMPORTANT:
    Autonomous learning events must remain small.

    MongoDB has a hard 16 MB BSON document limit.
    Therefore this class deliberately bounds learning signals before
    sending them to the knowledge database.

    Large documents / corpora should be handled by the dedicated
    knowledge ingestion pipeline, not by autonomous learning events.
    """

    # =========================================================
    # SAFETY LIMITS
    # =========================================================

    # Keep substantially below MongoDB's 16 MB BSON limit because
    # database.store() may add metadata and embeddings.
    MAX_LEARNING_CONTENT_CHARS = 32_000

    MAX_METADATA_CHARS = 8_000

    MAX_VALUE_CHARS = 8_000

    MAX_DICT_ITEMS = 40

    MAX_LIST_ITEMS = 40

    # =========================================================
    # INITIALIZATION
    # =========================================================

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
            "improvement_signals": 0,
            "planner_feedback": 0,
            "reasoning_feedback": 0,
            "consolidations": 0,
            "payloads_trimmed": 0,
        }

    # =========================================================
    # HELPERS
    # =========================================================

    def _truncate(
        self,
        value: Any,
        limit: int,
        label: str = "payload",
    ) -> str:
        """
        Convert a value to text and safely bound its size.
        """

        if value is None:
            return ""

        if isinstance(value, str):
            text = value.strip()
        else:
            text = str(value).strip()

        if len(text) <= limit:
            return text

        self.statistics["payloads_trimmed"] += 1

        logger.warning(
            "[AutonomousLearning] %s exceeded %d characters; "
            "truncating from %d characters.",
            label,
            limit,
            len(text),
        )

        return (
            text[:limit]
            + "\n\n[TRUNCATED BY AUTONOMOUS LEARNING SAFETY LIMIT]"
        )

    def _compact_value(
        self,
        value: Any,
        depth: int = 0,
    ) -> Any:
        """
        Safely reduce arbitrary runtime objects.

        Autonomous learning must never serialize an entire runtime
        state, reasoning context, tool output, or conversation object
        into MongoDB.
        """

        if depth > 3:
            return self._truncate(
                value,
                self.MAX_VALUE_CHARS,
                "nested learning value",
            )

        if value is None:
            return None

        if isinstance(value, str):
            return self._truncate(
                value,
                self.MAX_VALUE_CHARS,
                "learning string",
            )

        if isinstance(value, (int, float, bool)):
            return value

        if isinstance(value, dict):

            compacted = {}

            items = list(value.items())

            if len(items) > self.MAX_DICT_ITEMS:
                self.statistics["payloads_trimmed"] += 1

                logger.warning(
                    "[AutonomousLearning] Large dictionary detected; "
                    "keeping first %d of %d items.",
                    self.MAX_DICT_ITEMS,
                    len(items),
                )

            for key, item in items[:self.MAX_DICT_ITEMS]:

                safe_key = self._truncate(
                    key,
                    200,
                    "learning dictionary key",
                )

                compacted[safe_key] = self._compact_value(
                    item,
                    depth + 1,
                )

            if len(items) > self.MAX_DICT_ITEMS:
                compacted["_truncated_items"] = (
                    len(items) - self.MAX_DICT_ITEMS
                )

            return compacted

        if isinstance(value, (list, tuple, set)):

            items = list(value)

            if len(items) > self.MAX_LIST_ITEMS:
                self.statistics["payloads_trimmed"] += 1

                logger.warning(
                    "[AutonomousLearning] Large list detected; "
                    "keeping first %d of %d items.",
                    self.MAX_LIST_ITEMS,
                    len(items),
                )

            compacted = [
                self._compact_value(
                    item,
                    depth + 1,
                )
                for item in items[:self.MAX_LIST_ITEMS]
            ]

            if len(items) > self.MAX_LIST_ITEMS:
                compacted.append(
                    f"[TRUNCATED: {len(items) - self.MAX_LIST_ITEMS} "
                    f"additional items]"
                )

            return compacted

        return self._truncate(
            value,
            self.MAX_VALUE_CHARS,
            "learning object",
        )

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

            compacted = self._compact_value(value)

            parts = []

            for key, item in compacted.items():

                if item is None:
                    continue

                parts.append(
                    f"{key}: {item}"
                )

            return "\n".join(parts).strip()

        if isinstance(value, (list, tuple, set)):

            compacted = self._compact_value(value)

            return "\n".join(
                self._normalize_text(item)
                for item in compacted
                if item is not None
            ).strip()

        return self._truncate(
            value,
            self.MAX_VALUE_CHARS,
            "learning value",
        )

    def _safe_learning_content(
        self,
        value: Any,
        label: str = "learning content",
    ) -> str:
        """
        Final content boundary before knowledge_database.store().
        """

        content = self._normalize_text(value)

        return self._truncate(
            content,
            self.MAX_LEARNING_CONTENT_CHARS,
            label,
        )

    def _safe_metadata(
        self,
        value: Any,
    ) -> Dict[str, Any]:
        """
        Produce small, bounded metadata.
        """

        if not isinstance(value, dict):
            return {}

        compacted = self._compact_value(value)

        if not isinstance(compacted, dict):
            return {}

        metadata_text = self._truncate(
            self._normalize_text(compacted),
            self.MAX_METADATA_CHARS,
            "learning metadata",
        )

        return {
            "summary": metadata_text
        }

    def _is_learnable(
        self,
        content: str,
    ) -> bool:
        """
        Prevent empty, trivial, or obviously non-learning events.
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

    async def _store_learning(
        self,
        title: str,
        content: Any,
        source: str,
        metadata: Dict[str, Any] = None,
    ):
        """
        Central safe storage wrapper.

        Every autonomous learning signal passes through this method.
        """

        safe_title = self._truncate(
            title,
            500,
            "learning title",
        )

        safe_content = self._safe_learning_content(
            content,
            label=f"{source} learning content",
        )

        if not self._is_learnable(safe_content):
            return False

        kwargs = {
            "title": safe_title,
            "content": safe_content,
            "source": source,
        }

        if metadata:
            kwargs["metadata"] = self._safe_metadata(
                metadata
            )

        try:

            await self.database.store(
                **kwargs
            )

            return True

        except Exception:

            logger.exception(
                "[AutonomousLearning] Safe knowledge storage "
                "failed for source=%s.",
                source,
            )

            return False

    # =========================================================
    # ADVANCED LEARNING METHODS
    # =========================================================

    async def learn_from_reasoning(
        self,
        reasoning_result: Any,
    ):
        """
        Store reusable reasoning signals rather than raw arbitrary
        objects.

        Large reasoning contexts are deliberately reduced.
        """

        try:

            trace = getattr(
                reasoning_result,
                "reasoning_trace",
                None,
            )

            if not trace:

                if isinstance(
                    reasoning_result,
                    dict,
                ):

                    trace = (
                        reasoning_result.get(
                            "reasoning_trace"
                        )
                        or reasoning_result.get(
                            "summary"
                        )
                        or reasoning_result.get(
                            "result"
                        )
                    )

                if not trace:

                    trace = self._normalize_text(
                        reasoning_result
                    )

            trace = self._safe_learning_content(
                trace,
                "reasoning trace",
            )

            if not self._is_learnable(trace):
                return

            metadata = getattr(
                reasoning_result,
                "metadata",
                {},
            )

            if not isinstance(
                metadata,
                dict,
            ):

                if isinstance(
                    reasoning_result,
                    dict,
                ):

                    metadata = reasoning_result.get(
                        "metadata",
                        {},
                    )

                else:

                    metadata = {}

            # IMPORTANT:
            # Do not use a nested f-string expression here.
            # Build metadata separately so the module remains valid
            # Python syntax.

            metadata_text = self._truncate(
                self._normalize_text(metadata),
                self.MAX_METADATA_CHARS,
                "reasoning metadata",
            )

            content = (
                f"Reasoning trace:\n"
                f"{trace}\n\n"
                f"Metadata:\n"
                f"{metadata_text}"
            )

            stored = await self._store_learning(
                title="Reasoning Pattern Learned",
                content=content,
                source="reasoning_engine",
            )

            if stored:

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

        Reflection objects can contain the entire conversation,
        reasoning context, retrieval results, tool outputs, etc.

        Never serialize that complete object into MongoDB.
        """

        try:

            if isinstance(
                reflection_data,
                dict,
            ):

                evaluation = reflection_data.get(
                    "evaluation",
                    {},
                )

                suggestions = reflection_data.get(
                    "suggestions",
                    [],
                )

                correction = (
                    reflection_data.get(
                        "correction"
                    )
                    or reflection_data.get(
                        "improvement"
                    )
                    or reflection_data.get(
                        "lesson"
                    )
                    or reflection_data.get(
                        "reflection"
                    )
                )

                selected = {
                    "evaluation": self._compact_value(
                        evaluation
                    ),
                    "suggestions": self._compact_value(
                        suggestions
                    ),
                }

                if correction is not None:

                    selected["reflection"] = (
                        self._compact_value(
                            correction
                        )
                    )

                content = self._normalize_text(
                    selected
                )

            else:

                content = self._normalize_text(
                    reflection_data
                )

            content = self._safe_learning_content(
                content,
                "reflection content",
            )

            if not self._is_learnable(content):
                return

            stored = await self._store_learning(
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

                try:

                    await self.world.record_reflection(
                        content
                    )

                except Exception:

                    logger.exception(
                        "[AutonomousLearning] "
                        "World reflection recording failed."
                    )

            if stored:

                self.statistics[
                    "reflections_learned"
                ] += 1

            if isinstance(
                reflection_data,
                dict,
            ):

                suggestions = (
                    reflection_data.get(
                        "suggestions",
                        [],
                    )
                    or []
                )

                evaluation = reflection_data.get(
                    "evaluation",
                    {},
                )

                safe_evaluation = (
                    self._compact_value(
                        evaluation
                    )
                )

                for suggestion in suggestions:

                    signal = (
                        self._safe_learning_content(
                            suggestion,
                            "reflection improvement signal",
                        )
                    )

                    if not self._is_learnable(
                        signal
                    ):
                        continue

                    stored_signal = (
                        await self._store_learning(
                            title=(
                                "Reflection "
                                "Improvement Signal"
                            ),
                            content=signal,
                            source=(
                                "reflection_improvement"
                            ),
                            metadata={
                                "evaluation":
                                    safe_evaluation
                            },
                        )
                    )

                    if stored_signal:

                        self.statistics[
                            "improvement_signals"
                        ] += 1

        except Exception:

            logger.exception(
                "[AutonomousLearning] "
                "learn_from_reflection failed."
            )

    async def learn_from_execution(
        self,
        execution_result: Dict[str, Any],
    ):
        """
        Convert execution outcomes into reusable learning signals.

        Only useful execution fields are retained.
        """

        try:

            if not isinstance(
                execution_result,
                dict,
            ):

                execution_result = {
                    "result": self._normalize_text(
                        execution_result
                    )
                }

            safe_execution = {}

            important_fields = (
                "success",
                "status",
                "result",
                "error",
                "error_type",
                "tool",
                "tool_name",
                "action",
                "attempts",
                "duration",
                "reflection",
                "execution_reflection",
            )

            for key in important_fields:

                if key not in execution_result:
                    continue

                value = execution_result.get(
                    key
                )

                if value is None:
                    continue

                safe_execution[key] = (
                    self._compact_value(
                        value
                    )
                )

            content = self._safe_learning_content(
                safe_execution,
                "execution learning content",
            )

            if not self._is_learnable(content):
                return

            success = bool(
                execution_result.get(
                    "success",
                    False,
                )
            )

            source_type = (
                "execution_success"
                if success
                else "execution_failure"
            )

            stored = await self._store_learning(
                title=(
                    f"Execution Outcome: "
                    f"{source_type}"
                ),
                content=content,
                source=source_type,
            )

            if stored:

                self.statistics[
                    "executions_learned"
                ] += 1

            reflection = (
                execution_result.get(
                    "reflection"
                )
                or execution_result.get(
                    "execution_reflection"
                )
            )

            if reflection:

                await self.learn_from_reflection(
                    reflection
                )

        except Exception:

            logger.exception(
                "[AutonomousLearning] "
                "learn_from_execution failed."
            )

    async def improve_planner(
        self,
        plan: Any,
        feedback: str,
    ):
        """
        Store reusable planner feedback.
        """

        try:

            feedback_text = (
                self._safe_learning_content(
                    feedback,
                    "planner feedback",
                )
            )

            plan_text = (
                self._safe_learning_content(
                    plan,
                    "planner plan",
                )
            )

            if not self._is_learnable(
                feedback_text
            ):
                return

            content = (
                f"Plan Feedback:\n"
                f"{feedback_text}\n\n"
                f"Plan:\n"
                f"{plan_text}"
            )

            stored = await self._store_learning(
                title="Planner Optimization",
                content=content,
                source="planner_improvement",
            )

            if stored:

                self.statistics[
                    "planner_feedback"
                ] += 1

                self.statistics[
                    "improvement_signals"
                ] += 1

        except Exception:

            logger.exception(
                "[AutonomousLearning] "
                "improve_planner failed."
            )

    async def improve_reasoning(
        self,
        query: str,
        correction: str,
    ):
        """
        Store reusable reasoning corrections.
        """

        try:

            query_text = (
                self._safe_learning_content(
                    query,
                    "reasoning query",
                )
            )

            correction_text = (
                self._safe_learning_content(
                    correction,
                    "reasoning correction",
                )
            )

            if not self._is_learnable(
                correction_text
            ):
                return

            content = (
                f"Query:\n"
                f"{query_text}\n\n"
                f"Correction:\n"
                f"{correction_text}"
            )

            stored = await self._store_learning(
                title="Reasoning Optimization",
                content=content,
                source="reasoning_improvement",
            )

            if stored:

                self.statistics[
                    "reasoning_feedback"
                ] += 1

                self.statistics[
                    "improvement_signals"
                ] += 1

        except Exception:

            logger.exception(
                "[AutonomousLearning] "
                "improve_reasoning failed."
            )

    # =========================================================
    # INDIVIDUAL PROCESSING METHODS
    # =========================================================

    async def process_chat(
        self,
        user,
        assistant,
    ):

        user_text = self._normalize_text(
            user
        )

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
            f"User:\n"
            f"{user_text}\n\n"
            f"Assistant:\n"
            f"{assistant_text}"
        )

        content = self._safe_learning_content(
            content,
            "conversation learning content",
        )

        if self._is_learnable(content):

            await self._store_learning(
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

            await self.graph.learn(
                content
            )

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

        self.statistics[
            "chats"
        ] += 1

    async def process_document(
        self,
        filename,
        summary,
    ):

        filename_text = self._truncate(
            filename,
            500,
            "document filename",
        )

        summary_text = self._normalize_text(
            summary
        )

        await self.learning.learn_document(
            filename_text,
            summary_text,
        )

        await self.memory.remember(
            summary_text
        )

        await self._store_learning(
            title=filename_text,
            content=summary_text,
            source="document",
        )

        if (
            self.graph is not None
            and hasattr(
                self.graph,
                "learn",
            )
        ):

            await self.graph.learn(
                self._safe_learning_content(
                    summary_text,
                    "document graph learning",
                )
            )

        if (
            self.world is not None
            and hasattr(
                self.world,
                "learn_document",
            )
        ):

            await self.world.learn_document(
                filename_text,
                summary_text,
            )

        self.statistics[
            "documents"
        ] += 1

    async def process_web(
        self,
        query,
        answer,
    ):

        query_text = self._normalize_text(
            query
        )

        answer_text = self._normalize_text(
            answer
        )

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

        await self._store_learning(
            title=(
                query_text
                or "Web Knowledge"
            ),
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
                self._safe_learning_content(
                    answer_text,
                    "web graph learning",
                )
            )

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

        self.statistics[
            "web"
        ] += 1

    async def process_skill(
        self,
        skill_name,
        result,
    ):

        skill_text = self._truncate(
            skill_name,
            500,
            "skill name",
        )

        result_text = self._normalize_text(
            result
        )

        content = (
            f"Skill {skill_text} "
            f"executed with result: "
            f"{result_text}"
        )

        await self._store_learning(
            title=f"Skill: {skill_text}",
            content=content,
            source="skill",
        )

        if hasattr(
            self.memory,
            "remember",
        ):

            await self.memory.remember(
                self._safe_learning_content(
                    content,
                    "skill memory",
                )
            )

        self.statistics[
            "skills"
        ] += 1

    async def process_plan(
        self,
        plan,
    ):

        content = self._safe_learning_content(
            plan,
            "plan learning content",
        )

        await self._store_learning(
            title="Execution Plan",
            content=content,
            source="plan",
        )

        if (
            self.world is not None
            and hasattr(
                self.world,
                "add_goal",
            )
        ):

            self.world.add_goal(
                "Latest Plan",
                {
                    "plan": content
                },
            )

        self.statistics[
            "plans"
        ] += 1

    async def process_profile(
        self,
        profile,
    ):

        profile_str = (
            self._safe_learning_content(
                profile,
                "profile learning content",
            )
        )

        if hasattr(
            self.memory,
            "store_profile",
        ):

            await self.memory.store_profile(
                profile
            )

        await self._store_learning(
            title="User Profile",
            content=profile_str,
            source="profile",
        )

        if (
            self.graph is not None
            and hasattr(
                self.graph,
                "learn",
            )
        ):

            await self.graph.learn(
                profile_str
            )

        if hasattr(
            self.learning,
            "learn_profile",
        ):

            await self.learning.learn_profile(
                profile
            )

    async def process_failure(
        self,
        query,
    ):

        query_text = (
            self._safe_learning_content(
                query,
                "failure query",
            )
        )

        await self._store_learning(
            title="Knowledge Gap",
            content=query_text,
            source="unknown",
        )

        self.statistics[
            "failures"
        ] += 1

    async def process_success(
        self,
        query,
        answer,
    ):

        query_text = (
            self._safe_learning_content(
                query,
                "success query",
            )
        )

        answer_text = (
            self._safe_learning_content(
                answer,
                "success answer",
            )
        )

        content = (
            f"Query: "
            f"{query_text}\n"
            f"Answer: "
            f"{answer_text}"
        )

        await self._store_learning(
            title="Successful Interaction",
            content=content,
            source="success",
        )

        self.statistics[
            "success"
        ] += 1

    # =========================================================
    # MAINTENANCE & UTILITIES
    # =========================================================

    async def consolidate(
        self,
    ):
        """
        Safely reinforce learned signals.

        Large-scale knowledge consolidation belongs in the
        dedicated knowledge ingestion pipeline.
        """

        try:

            collection = getattr(
                self.database,
                "collection",
                None,
            )

            if collection is None:

                return {
                    "status":
                        "consolidation_unavailable",
                    "processed": 0,
                    "reinforced": 0,
                }

            cursor = collection.find(
                {
                    "active": True,
                    "source": {
                        "$in": [
                            "self_reflection",
                            "reflection_improvement",
                            "execution_success",
                            "execution_failure",
                            "planner_improvement",
                            "reasoning_improvement",
                        ]
                    },
                },
                {
                    "_id": 1,
                    "title": 1,
                    "content": 1,
                    "access_count": 1,
                },
            ).sort(
                "updated_at",
                -1,
            ).limit(100)

            records = await cursor.to_list(
                100
            )

            seen = set()
            reinforced = 0

            for record in records:

                if not isinstance(
                    record,
                    dict,
                ):
                    continue

                key = (
                    str(
                        record.get(
                            "title",
                            "",
                        )
                    ).strip().lower(),

                    str(
                        record.get(
                            "content",
                            "",
                        )
                    ).strip(),
                )

                if (
                    not key[0]
                    or not key[1]
                    or key in seen
                ):
                    continue

                seen.add(key)

                record_id = record.get(
                    "_id"
                )

                if not record_id:
                    continue

                try:

                    access_count = int(
                        record.get(
                            "access_count",
                            0,
                        )
                    )

                except (
                    TypeError,
                    ValueError,
                ):

                    access_count = 0

                if (
                    access_count > 0
                    and hasattr(
                        self.database,
                        "increase_confidence",
                    )
                ):

                    await self.database.increase_confidence(
                        str(record_id)
                    )

                    reinforced += 1

            self.statistics[
                "consolidations"
            ] += 1

            return {
                "status":
                    "consolidation_complete",
                "processed":
                    len(records),
                "unique":
                    len(seen),
                "reinforced":
                    reinforced,
            }

        except Exception:

            logger.exception(
                "[AutonomousLearning] "
                "Consolidation failed."
            )

            return {
                "status":
                    "consolidation_failed",
                "processed": 0,
                "reinforced": 0,
            }

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

    async def handle(
        self,
        event,
    ):

        data = getattr(
            event,
            "data",
            {},
        ) or {}

        return await self.learn(
            event.type,
            **data,
        )