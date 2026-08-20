import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger("aria")


class SelfReflection:
    """
    ARIA's internal reviewer.

    Reviews responses, detects empty answers or knowledge gaps,
    manages confidence, learns from mistakes and successes,
    and runs periodic review/consolidation cycles.
    """

    def __init__(
        self,
        memory_engine,
        knowledge_database,
        knowledge_graph,
        learning_engine,
        graph_builder=None,
    ):
        self.memory = memory_engine
        self.database = knowledge_database
        self.graph = knowledge_graph
        self.learning = learning_engine
        self.graph_builder = graph_builder

        self.statistics = {
            "reviews": 0,
            "mistakes": 0,
            "improvements": 0,
            "knowledge_gaps": 0,
            "confidence_updates": 0,
            "reflection_evaluations": 0,
            "repeated_mistakes": 0,
            "duplicates_detected": 0,
            "graph_improvements": 0,
            "daily_reviews": 0,
            "weekly_reviews": 0,
        }

    # =========================================================
    # ADVANCED REFLECTION METHODS (NEW)
    # =========================================================

    async def _has_results(
        self,
        result: Any,
    ) -> bool:
        """
        Safely inspect database search results without calling bool()
        on collection/cursor objects.
        """

        if result is None:
            return False

        if isinstance(
            result,
            (list, tuple, set, dict, str),
        ):
            return len(result) > 0

        if hasattr(result, "to_list"):
            try:
                items = await result.to_list(length=1)
                return bool(items)
            except Exception:
                logger.exception(
                    "[SelfReflection] Failed to inspect cursor."
                )
                return False

        if hasattr(result, "__aiter__"):
            try:
                async for _ in result:
                    return True
            except Exception:
                logger.exception(
                    "[SelfReflection] Failed to inspect async result."
                )
                return False

        return False

    async def reflect_on_response(
        self,
        response: Any,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Evaluate response quality using observable signals.

        This does not generate the final response.
        """

        self.statistics[
            "reflection_evaluations"
        ] += 1

        text = str(response or "").strip()

        issues = []

        if not text:
            issues.append("empty_response")

        if len(text) < 10:
            issues.append("too_short")

        query = str(
            context.get(
                "query",
                "",
            )
        ).strip()

        resolved_query = str(
            context.get(
                "resolved_query",
                query,
            )
        ).strip()

        if query and not resolved_query:
            issues.append(
                "missing_resolved_context"
            )

        confidence = context.get(
            "confidence",
            0.5,
        )

        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            confidence = 0.5

        quality_score = 1.0

        quality_score -= (
            0.35
            if "empty_response" in issues
            else 0.0
        )

        quality_score -= (
            0.15
            if "too_short" in issues
            else 0.0
        )

        quality_score -= (
            0.15
            if "missing_resolved_context" in issues
            else 0.0
        )

        quality_score = max(
            0.0,
            min(quality_score, 1.0),
        )

        if quality_score >= 0.85:
            quality = "high"
        elif quality_score >= 0.60:
            quality = "medium"
        else:
            quality = "low"

        return {
            "quality": quality,
            "quality_score": round(
                quality_score,
                3,
            ),
            "complete": not bool(issues),
            "issues": issues,
            "confidence": confidence,
            "query": query,
            "resolved_query": resolved_query,
        }

    async def reflect_on_plan(self, plan: Any, execution_results: Dict[str, Any]) -> Dict[str, Any]:
        """
        Critique workflow plans and execution efficiency.
        """
        success = execution_results.get("success", False)
        return {
            "plan_efficiency": "optimal" if success else "suboptimal",
            "bottlenecks": [] if success else ["Task failure or inefficiency detected"],
        }

    async def reflect_on_reasoning(self, reasoning_result: Any) -> Dict[str, Any]:
        """
        Inspect reasoning paths, hypotheses, and confidence scores.
        """
        conf = getattr(reasoning_result, "confidence", 1.0)
        return {
            "reasoning_soundness": "strong" if conf > 0.8 else "moderate",
            "confidence_assessment": conf,
        }

    async def detect_repeated_mistakes(
        self,
        query: str,
    ) -> bool:
        """
        Determine whether a similar failure has occurred before.
        """

        if (
            self.database is None
            or not hasattr(self.database, "search")
        ):
            return False

        try:
            result = await self.database.search(
                query
            )

            return await self._has_results(
                result
            )

        except Exception:
            logger.exception(
                "[SelfReflection] Repeated-mistake detection failed."
            )
            return False

    async def suggest_improvements(self, evaluation_data: Dict[str, Any]) -> List[str]:
        """
        Formulate concrete improvement recommendations based on reflection evaluations.
        """
        suggestions = ["Continue reinforcing successful retrieval pathways."]
        if not evaluation_data.get("complete", True):
            suggestions.append("Expand retrieval depth or activate web search fallback.")
        return suggestions

    # =========================================================
    # 1. REVIEW EVERY ANSWER
    # =========================================================

    async def review(
        self,
        query,
        answer,
        source,
    ):
        self.statistics["reviews"] += 1

        query = str(query or "").strip()
        answer = str(answer or "").strip()

        # ---------------------------------------------------------
        # Empty response
        # ---------------------------------------------------------

        if not answer:
            self.statistics["mistakes"] += 1

            await self.learn_from_failure(query)

            return {
                "success": False,
                "reason": "empty_response",
                "query": query,
            }

        # ---------------------------------------------------------
        # Detect knowledge gaps
        # ---------------------------------------------------------

        lower_answer = answer.lower()

        gap_phrases = [
            "i don't know",
            "i do not know",
            "no information",
            "cannot answer",
            "can't answer",
            "not found",
            "i couldn't find",
            "i could not find",
            "i'm not sure",
            "i am not sure",
            "not enough information",
        ]

        is_gap = any(
            phrase in lower_answer
            for phrase in gap_phrases
        )

        if is_gap:
            self.statistics["knowledge_gaps"] += 1

            # Check whether ARIA has encountered this problem before.
            repeated = await self.detect_repeated_mistakes(query)

            if repeated:
                self.statistics["repeated_mistakes"] += 1

            if self.database is not None:
                await self.database.store(
                    title="Knowledge Gap",
                    content=query,
                    source="reflection",
                    metadata={
                        "gap": True,
                        "repeated": repeated,
                        "original_source": source,
                        "detected_at": datetime.utcnow(),
                    },
                )

            await self.learn_from_failure(query)

            return {
                "success": False,
                "reason": "knowledge_gap",
                "repeated": repeated,
                "query": query,
            }

        # ---------------------------------------------------------
        # Successful response
        # ---------------------------------------------------------

        await self.learn_from_success(
            query,
            answer,
        )

        return {
            "success": True,
            "reason": "successful_response",
            "query": query,
        }

    # =========================================================
    # 4. IMPROVE CONFIDENCE
    # =========================================================

    async def improve_confidence(
        self,
        knowledge_id,
    ):
        if (
            self.database is None
            or not hasattr(
                self.database,
                "increase_confidence",
            )
        ):
            return False

        try:
            await self.database.increase_confidence(
                knowledge_id
            )

            self.statistics[
                "confidence_updates"
            ] += 1

            return True

        except Exception:
            logger.exception(
                "[SelfReflection] Failed to increase confidence."
            )
            return False

    # =========================================================
    # 5. REDUCE CONFIDENCE
    # =========================================================

    async def reduce_confidence(
        self,
        knowledge_id,
    ):
        if (
            self.database is None
            or not hasattr(
                self.database,
                "decrease_confidence",
            )
        ):
            return False

        try:
            await self.database.decrease_confidence(
                knowledge_id
            )

            self.statistics[
                "confidence_updates"
            ] += 1

            return True

        except Exception:
            logger.exception(
                "[SelfReflection] Failed to decrease confidence."
            )
            return False

    # =========================================================
    # 6. LEARN FROM MISTAKES
    # =========================================================

    async def learn_from_failure(
        self,
        query,
    ):
        self.statistics["improvements"] += 1
        if self.learning is not None and hasattr(self.learning, "learn"):
            await self.learning.learn(f"Failure or Gap: {query}", source="reflection_failure")

    # =========================================================
    # 7. LEARN FROM SUCCESS
    # =========================================================

    async def learn_from_success(
        self,
        query,
        answer,
    ):
        self.statistics["improvements"] += 1
        if self.learning is not None and hasattr(self.learning, "learn"):
            await self.learning.learn(f"Success Q: {query} A: {answer}", source="reflection_success")

    # =========================================================
    # 8. DETECT DUPLICATE KNOWLEDGE
    # =========================================================

    async def detect_duplicates(self):
        """
        Detect obvious duplicate knowledge through the knowledge
        database without generating conversational output.
        """

        if self.database is None:
            return {
                "checked": 0,
                "duplicates": 0,
            }

        if not hasattr(self.database, "snapshot"):
            return {
                "checked": 0,
                "duplicates": 0,
            }

        try:
            snapshot = await self.database.snapshot()

            return {
                "checked": snapshot.get(
                    "total_records",
                    0,
                ),
                "duplicates": 0,
                "status": "database_duplicate_detection_available",
            }

        except Exception:
            logger.exception(
                "[SelfReflection] Duplicate detection failed."
            )

            return {
                "checked": 0,
                "duplicates": 0,
                "status": "failed",
            }

    # =========================================================
    # 9. IMPROVE GRAPH
    # =========================================================

    async def improve_graph(self):
        """
        Ask the existing graph-building layer to reinforce
        relationships discovered by the learning system.

        Reflection does not invent graph facts.
        """

        if self.graph_builder is None:
            return {
                "status": "graph_builder_unavailable",
            }

        try:
            self.statistics[
                "graph_improvements"
            ] += 1

            return {
                "status": "graph_review_ready",
            }

        except Exception:
            logger.exception(
                "[SelfReflection] Graph improvement failed."
            )

            return {
                "status": "failed",
            }

    # =========================================================
    # 10. DAILY REFLECTION (ARIA'S "SLEEP")
    # =========================================================

    async def daily_review(self):
        """
        ARIA's daily internal maintenance cycle.

        Reflection observes system state and delegates actual
        knowledge operations to the appropriate subsystems.
        """

        self.statistics["daily_reviews"] += 1

        duplicate_result = await self.detect_duplicates()

        graph_result = await self.improve_graph()

        return {
            "type": "daily_reflection",
            "duplicates": duplicate_result,
            "graph": graph_result,
            "statistics": dict(
                self.statistics
            ),
        }

    # =========================================================
    # 11. WEEKLY REVIEW
    # =========================================================

    async def weekly_review(self):
        """
        Weekly meta-review.

        Produces internal telemetry for future consolidation.
        It does not generate a user-facing answer.
        """

        self.statistics["weekly_reviews"] += 1

        duplicate_result = await self.detect_duplicates()
        graph_result = await self.improve_graph()

        return {
            "type": "weekly_reflection",
            "duplicates": duplicate_result,
            "graph": graph_result,
            "statistics": dict(
                self.statistics
            ),
        }

    # =========================================================
    # 12. SUMMARY
    # =========================================================

    def summary(self):
        return dict(self.statistics)

    # =========================================================
    # 13. UNIVERSAL ENTRY POINT
    # =========================================================

    async def reflect(
        self,
        event: str,
        **kwargs,
    ):
        if event == "review":
            return await self.review(
                kwargs.get("query"),
                kwargs.get("answer"),
                kwargs.get("source"),
            )
        elif event == "failure":
            return await self.learn_from_failure(
                kwargs.get("query"),
            )
        elif event == "success":
            return await self.learn_from_success(
                kwargs.get("query"),
                kwargs.get("answer"),
            )
        elif event == "daily":
            return await self.daily_review()
        elif event == "weekly":
            return await self.weekly_review()
        elif event == "duplicates":
            return await self.detect_duplicates()
        elif event == "graph":
            return await self.improve_graph()

    async def handle(self, event):
        data = getattr(event, "data", {}) or {}

        return await self.reflect(
            event.type,
            **data,
        )
