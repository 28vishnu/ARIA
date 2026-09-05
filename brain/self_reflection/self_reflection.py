import logging
import math
from collections import Counter, deque
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("aria")


class SelfReflection:
    """
    ARIA's internal self-reflection and improvement coordinator.

    Responsibilities:
    - Evaluate response quality.
    - Detect knowledge gaps and repeated failures.
    - Track confidence and outcome trends.
    - Detect recurring weak patterns.
    - Generate actionable improvement recommendations.
    - Feed successful/failing patterns into the learning subsystem.
    - Perform daily/weekly maintenance reviews.

    This class does not generate the final conversational response.
    It observes outcomes and coordinates improvement.
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
            "successful_reviews": 0,
            "low_quality_reviews": 0,
            "medium_quality_reviews": 0,
            "high_quality_reviews": 0,
            "failure_patterns": 0,
            "improvement_suggestions": 0,
        }

        # Small bounded in-memory telemetry buffers.
        # These are intentionally bounded so reflection cannot
        # become an unbounded memory consumer.
        self._recent_reviews = deque(maxlen=100)
        self._failure_patterns = Counter()
        self._success_patterns = Counter()

    # =========================================================
    # INTERNAL UTILITIES
    # =========================================================

    @staticmethod
    def _now() -> datetime:
        """Return a timezone-aware UTC timestamp."""
        return datetime.now(timezone.utc)

    @staticmethod
    def _clamp(value: Any, minimum: float = 0.0, maximum: float = 1.0) -> float:
        """Safely clamp a numeric value."""
        try:
            value = float(value)
        except (TypeError, ValueError):
            value = minimum

        if not math.isfinite(value):
            value = minimum

        return max(minimum, min(value, maximum))

    @staticmethod
    def _normalise_text(value: Any) -> str:
        """Safely convert arbitrary values into normalized text."""
        return str(value or "").strip()

    @staticmethod
    def _pattern_key(query: str) -> str:
        """
        Create a conservative pattern key.

        We intentionally avoid storing the entire query as a pattern
        because that would create unnecessary memory growth.
        """
        text = " ".join(
            str(query or "").lower().split()
        )

        if not text:
            return ""

        words = text.split()

        # Keep enough information to identify repeated failures
        # while preventing huge keys.
        return " ".join(words[:12])

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

        if isinstance(result, (list, tuple, set, dict, str)):
            return len(result) > 0

        if hasattr(result, "to_list"):
            try:
                items = result.to_list(length=1)

                if hasattr(items, "__await__"):
                    items = await items

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

    # =========================================================
    # RESPONSE REFLECTION
    # =========================================================

    async def reflect_on_response(
        self,
        response: Any,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Evaluate response quality using observable signals.

        No LLM is required here. This is deterministic telemetry.
        """

        self.statistics["reflection_evaluations"] += 1

        context = context or {}
        text = self._normalise_text(response)

        issues: List[str] = []

        if not text:
            issues.append("empty_response")

        if text and len(text) < 10:
            issues.append("too_short")

        query = self._normalise_text(
            context.get("query", "")
        )

        resolved_query = self._normalise_text(
            context.get("resolved_query", query)
        )

        if query and not resolved_query:
            issues.append("missing_resolved_context")

        confidence = self._clamp(
            context.get("confidence", 0.5),
            0.0,
            1.0,
        )

        # Explicit failure signals from upstream components.
        if context.get("failed") is True:
            issues.append("execution_failure")

        if context.get("tool_error") is True:
            issues.append("tool_error")

        if context.get("timeout") is True:
            issues.append("timeout")

        if context.get("low_confidence") is True:
            issues.append("low_confidence_signal")

        quality_score = 1.0

        penalties = {
            "empty_response": 0.45,
            "too_short": 0.15,
            "missing_resolved_context": 0.15,
            "execution_failure": 0.30,
            "tool_error": 0.25,
            "timeout": 0.25,
            "low_confidence_signal": 0.10,
        }

        for issue in issues:
            quality_score -= penalties.get(issue, 0.0)

        # Confidence should influence the evaluation, but should
        # never completely override observable response quality.
        if confidence < 0.25:
            quality_score -= 0.10
        elif confidence >= 0.85 and not issues:
            quality_score += 0.03

        quality_score = self._clamp(
            quality_score,
            0.0,
            1.0,
        )

        if quality_score >= 0.85:
            quality = "high"
        elif quality_score >= 0.60:
            quality = "medium"
        else:
            quality = "low"

        if quality == "high":
            self.statistics["high_quality_reviews"] += 1
        elif quality == "medium":
            self.statistics["medium_quality_reviews"] += 1
        else:
            self.statistics["low_quality_reviews"] += 1

        if not issues:
            self.statistics["successful_reviews"] += 1

        evaluation = {
            "quality": quality,
            "quality_score": round(
                quality_score,
                3,
            ),
            "complete": not bool(issues),
            "issues": issues,
            "confidence": round(confidence, 3),
            "query": query,
            "resolved_query": resolved_query,
            "response_length": len(text),
            "evaluated_at": self._now(),
        }

        self._recent_reviews.append(evaluation)

        return evaluation

    # =========================================================
    # PLAN REFLECTION
    # =========================================================

    async def reflect_on_plan(
        self,
        plan: Any,
        execution_results: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Critique workflow plans and execution efficiency.
        """

        execution_results = execution_results or {}

        success = bool(
            execution_results.get("success", False)
        )

        errors = execution_results.get("errors", [])
        if isinstance(errors, str):
            errors = [errors]

        duration = execution_results.get(
            "duration",
            execution_results.get("duration_seconds"),
        )

        try:
            duration = float(duration) if duration is not None else None
        except (TypeError, ValueError):
            duration = None

        bottlenecks = []

        if not success:
            bottlenecks.append(
                "Task failure or inefficiency detected"
            )

        if errors:
            bottlenecks.append(
                "Execution reported one or more errors"
            )

        if duration is not None and duration > 30:
            bottlenecks.append(
                "Execution duration exceeded 30 seconds"
            )

        if success and not bottlenecks:
            efficiency = "optimal"
        elif success:
            efficiency = "acceptable"
        else:
            efficiency = "suboptimal"

        return {
            "plan_efficiency": efficiency,
            "bottlenecks": bottlenecks,
            "success": success,
            "duration_seconds": duration,
            "plan_available": plan is not None,
        }

    # =========================================================
    # REASONING REFLECTION
    # =========================================================

    async def reflect_on_reasoning(
        self,
        reasoning_result: Any,
    ) -> Dict[str, Any]:
        """
        Inspect reasoning confidence and observable reasoning metadata.

        This method does not attempt to expose hidden chain-of-thought.
        """

        if reasoning_result is None:
            return {
                "reasoning_soundness": "unknown",
                "confidence_assessment": 0.0,
                "reasoning_available": False,
            }

        conf = getattr(
            reasoning_result,
            "confidence",
            None,
        )

        if conf is None and isinstance(reasoning_result, dict):
            conf = reasoning_result.get(
                "confidence",
                0.5,
            )

        conf = self._clamp(conf, 0.0, 1.0)

        if conf >= 0.80:
            soundness = "strong"
        elif conf >= 0.50:
            soundness = "moderate"
        else:
            soundness = "weak"

        return {
            "reasoning_soundness": soundness,
            "confidence_assessment": round(conf, 3),
            "reasoning_available": True,
        }

    # =========================================================
    # REPEATED FAILURE DETECTION
    # =========================================================

    async def detect_repeated_mistakes(
        self,
        query: str,
    ) -> bool:
        """
        Determine whether a similar failure has occurred before.

        Checks both the bounded local failure history and the
        persistent knowledge database when available.
        """

        query = self._normalise_text(query)

        if not query:
            return False

        pattern = self._pattern_key(query)

        # Fast local check.
        if pattern and self._failure_patterns.get(pattern, 0) > 0:
            return True

        # Persistent database check.
        if (
            self.database is None
            or not hasattr(self.database, "search")
        ):
            return False

        try:
            result = await self.database.search(query)

            return await self._has_results(result)

        except Exception:
            logger.exception(
                "[SelfReflection] Repeated-mistake detection failed."
            )
            return False

    # =========================================================
    # IMPROVEMENT RECOMMENDATIONS
    # =========================================================

    async def suggest_improvements(
        self,
        evaluation_data: Dict[str, Any],
    ) -> List[str]:
        """
        Generate concrete, deterministic improvement recommendations.
        """

        evaluation_data = evaluation_data or {}

        suggestions: List[str] = []

        issues = evaluation_data.get("issues", [])
        if isinstance(issues, str):
            issues = [issues]

        if "empty_response" in issues:
            suggestions.append(
                "Verify response generation before returning the result."
            )

        if "too_short" in issues:
            suggestions.append(
                "Increase response completeness when the task requires explanation."
            )

        if "missing_resolved_context" in issues:
            suggestions.append(
                "Preserve resolved query context through the reasoning pipeline."
            )

        if "execution_failure" in issues:
            suggestions.append(
                "Inspect failed execution steps and retry through an appropriate fallback."
            )

        if "tool_error" in issues:
            suggestions.append(
                "Validate tool availability and improve tool-failure recovery."
            )

        if "timeout" in issues:
            suggestions.append(
                "Reduce unnecessary work or apply a bounded fallback when execution times out."
            )

        if "low_confidence_signal" in issues:
            suggestions.append(
                "Prefer stronger evidence or retrieval before committing to an answer."
            )

        if not suggestions:
            suggestions.append(
                "Continue reinforcing successful retrieval and execution pathways."
            )

        self.statistics["improvement_suggestions"] += len(
            suggestions
        )

        return suggestions

    # =========================================================
    # UNIFIED RESPONSE REVIEW
    # =========================================================

    async def evaluate_response(
        self,
        response: Any,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Perform a complete response reflection and return
        evaluation + improvement recommendations.
        """

        context = context or {}

        evaluation = await self.reflect_on_response(
            response,
            context,
        )

        improvements = await self.suggest_improvements(
            evaluation
        )

        if evaluation["quality"] == "low":
            self.statistics["mistakes"] += 1

        return {
            "evaluation": evaluation,
            "improvements": improvements,
            "success": evaluation["quality"] != "low",
        }

    # =========================================================
    # REVIEW EVERY ANSWER
    # =========================================================

    async def review(
        self,
        query,
        answer,
        source,
    ):
        self.statistics["reviews"] += 1

        query = self._normalise_text(query)
        answer = self._normalise_text(answer)

        # -----------------------------------------------------
        # Empty response
        # -----------------------------------------------------

        if not answer:
            self.statistics["mistakes"] += 1

            pattern = self._pattern_key(query)

            if pattern:
                self._failure_patterns[pattern] += 1

            await self.learn_from_failure(query)

            return {
                "success": False,
                "reason": "empty_response",
                "query": query,
                "repeated": (
                    self._failure_patterns.get(pattern, 0) > 1
                    if pattern
                    else False
                ),
            }

        # -----------------------------------------------------
        # Detect knowledge gaps
        # -----------------------------------------------------

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

            repeated = await self.detect_repeated_mistakes(
                query
            )

            if repeated:
                self.statistics["repeated_mistakes"] += 1

            pattern = self._pattern_key(query)

            if pattern:
                self._failure_patterns[pattern] += 1

                if self._failure_patterns[pattern] >= 2:
                    self.statistics["failure_patterns"] += 1

            if self.database is not None and hasattr(
                self.database,
                "store",
            ):
                try:
                    await self.database.store(
                        title="Knowledge Gap",
                        content=query,
                        source="reflection",
                        metadata={
                            "gap": True,
                            "repeated": repeated,
                            "original_source": source,
                            "detected_at": self._now(),
                        },
                    )
                except Exception:
                    logger.exception(
                        "[SelfReflection] Failed to persist knowledge gap."
                    )

            await self.learn_from_failure(query)

            return {
                "success": False,
                "reason": "knowledge_gap",
                "repeated": repeated,
                "query": query,
                "pattern": pattern,
            }

        # -----------------------------------------------------
        # Successful response
        # -----------------------------------------------------

        pattern = self._pattern_key(query)

        if pattern:
            self._success_patterns[pattern] += 1

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
    # CONFIDENCE MANAGEMENT
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
    # LEARNING FROM FAILURE
    # =========================================================

    async def learn_from_failure(
        self,
        query,
    ):
        self.statistics["improvements"] += 1

        query = self._normalise_text(query)

        pattern = self._pattern_key(query)

        if pattern:
            self._failure_patterns[pattern] += 1

            if self._failure_patterns[pattern] >= 2:
                self.statistics["failure_patterns"] += 1

        if (
            self.learning is not None
            and hasattr(self.learning, "learn")
        ):
            try:
                await self.learning.learn(
                    f"Failure or Knowledge Gap: {query}",
                    source="reflection_failure",
                )
            except Exception:
                logger.exception(
                    "[SelfReflection] Failure learning operation failed."
                )

    # =========================================================
    # LEARNING FROM SUCCESS
    # =========================================================

    async def learn_from_success(
        self,
        query,
        answer,
    ):
        self.statistics["improvements"] += 1

        query = self._normalise_text(query)
        answer = self._normalise_text(answer)

        pattern = self._pattern_key(query)

        if pattern:
            self._success_patterns[pattern] += 1

        if (
            self.learning is not None
            and hasattr(self.learning, "learn")
        ):
            try:
                await self.learning.learn(
                    f"Successful response. Q: {query} A: {answer}",
                    source="reflection_success",
                )
            except Exception:
                logger.exception(
                    "[SelfReflection] Success learning operation failed."
                )

    # =========================================================
    # DUPLICATE KNOWLEDGE DETECTION
    # =========================================================

    async def detect_duplicates(self):
        """
        Detect duplicate knowledge through the knowledge database.

        If the database exposes a dedicated duplicate detector,
        use it. Otherwise safely report that only snapshot-level
        inspection is available.
        """

        if self.database is None:
            return {
                "checked": 0,
                "duplicates": 0,
                "status": "database_unavailable",
            }

        # Prefer a real database duplicate detector when available.
        for method_name in (
            "detect_duplicates",
            "find_duplicates",
            "find_duplicate_records",
        ):
            method = getattr(
                self.database,
                method_name,
                None,
            )

            if not callable(method):
                continue

            try:
                result = method()

                if hasattr(result, "__await__"):
                    result = await result

                if isinstance(result, dict):
                    duplicates = result.get(
                        "duplicates",
                        result.get("count", 0),
                    )

                    try:
                        duplicates = int(duplicates)
                    except (TypeError, ValueError):
                        duplicates = 0

                    self.statistics[
                        "duplicates_detected"
                    ] += max(0, duplicates)

                    return result

                if isinstance(result, (list, tuple, set)):
                    duplicates = len(result)

                    self.statistics[
                        "duplicates_detected"
                    ] += duplicates

                    return {
                        "checked": duplicates,
                        "duplicates": duplicates,
                        "status": "duplicate_detection_complete",
                    }

            except Exception:
                logger.exception(
                    "[SelfReflection] Dedicated duplicate detection failed."
                )

        if not hasattr(self.database, "snapshot"):
            return {
                "checked": 0,
                "duplicates": 0,
                "status": "duplicate_detection_unavailable",
            }

        try:
            snapshot = self.database.snapshot()

            if hasattr(snapshot, "__await__"):
                snapshot = await snapshot

            if not isinstance(snapshot, dict):
                snapshot = {}

            return {
                "checked": snapshot.get(
                    "total_records",
                    0,
                ),
                "duplicates": 0,
                "status": "snapshot_only_no_duplicate_detector",
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
    # GRAPH IMPROVEMENT
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
            # Support future graph builders that expose an explicit
            # reflection/reinforcement operation.
            for method_name in (
                "review",
                "reflect",
                "reinforce",
                "consolidate",
            ):
                method = getattr(
                    self.graph_builder,
                    method_name,
                    None,
                )

                if not callable(method):
                    continue

                result = method()

                if hasattr(result, "__await__"):
                    result = await result

                self.statistics[
                    "graph_improvements"
                ] += 1

                return {
                    "status": "graph_improvement_complete",
                    "method": method_name,
                    "result": result,
                }

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
    # DAILY REFLECTION — ARIA'S "SLEEP"
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

        recent = list(self._recent_reviews)

        low_quality = sum(
            1
            for item in recent
            if item.get("quality") == "low"
        )

        repeated_failures = [
            {
                "pattern": pattern,
                "count": count,
            }
            for pattern, count
            in self._failure_patterns.most_common(10)
            if count >= 2
        ]

        return {
            "type": "daily_reflection",
            "duplicates": duplicate_result,
            "graph": graph_result,
            "recent_review_count": len(recent),
            "recent_low_quality_reviews": low_quality,
            "repeated_failure_patterns": repeated_failures,
            "statistics": dict(
                self.statistics
            ),
            "generated_at": self._now(),
        }

    # =========================================================
    # WEEKLY REVIEW
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

        repeated_failures = [
            {
                "pattern": pattern,
                "count": count,
            }
            for pattern, count
            in self._failure_patterns.most_common(20)
            if count >= 2
        ]

        successful_patterns = [
            {
                "pattern": pattern,
                "count": count,
            }
            for pattern, count
            in self._success_patterns.most_common(20)
            if count >= 2
        ]

        return {
            "type": "