import logging
import math
from collections import Counter, deque
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("aria")


class SelfReflection:
    """
    ARIA's internal self-reflection and improvement coordinator.

    Phase 10 responsibilities:
    - Evaluate response quality.
    - Evaluate plans and observable reasoning metadata.
    - Detect knowledge gaps, execution failures, and repeated failures.
    - Track confidence and outcome trends.
    - Generate deterministic, actionable improvement recommendations.
    - Feed validated success/failure patterns into the learning subsystem.
    - Preserve bounded telemetry for daily/weekly reviews.
    - Provide a single reflection entry point for CognitiveCore,
      execution systems, and the event bus.

    This class observes outcomes and coordinates improvement.
    It does not expose hidden chain-of-thought and does not directly
    modify source code, permissions, credentials, or safety controls.
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
            "execution_reviews": 0,
            "reasoning_reviews": 0,
            "verified_outcomes": 0,
            "unverified_outcomes": 0,
        }

        # Bounded telemetry only. Reflection must never become
        # an unbounded memory consumer.
        self._recent_reviews = deque(maxlen=100)
        self._recent_improvements = deque(maxlen=100)
        self._failure_patterns = Counter()
        self._success_patterns = Counter()

    # =========================================================
    # INTERNAL UTILITIES
    # =========================================================

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _clamp(
        value: Any,
        minimum: float = 0.0,
        maximum: float = 1.0,
    ) -> float:
        try:
            value = float(value)
        except (TypeError, ValueError):
            value = minimum

        if not math.isfinite(value):
            value = minimum

        return max(minimum, min(value, maximum))

    @staticmethod
    def _normalise_text(value: Any) -> str:
        return str(value or "").strip()

    @staticmethod
    def _pattern_key(query: str) -> str:
        text = " ".join(
            str(query or "").lower().split()
        )

        if not text:
            return ""

        return " ".join(text.split()[:12])

    @staticmethod
    def _as_list(value: Any) -> List[Any]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value] if value.strip() else []
        if isinstance(value, (list, tuple, set)):
            return list(value)
        return [value]

    async def _has_results(self, result: Any) -> bool:
        """
        Safely inspect database results without blindly calling bool()
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
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Deterministically evaluate observable response quality.

        Upstream systems can provide explicit outcome signals through
        context. No LLM or hidden chain-of-thought is required.
        """
        self.statistics["reflection_evaluations"] += 1

        context = context or {}
        text = self._normalise_text(response)
        issues: List[str] = []

        if not text:
            issues.append("empty_response")
        elif len(text) < 10:
            issues.append("too_short")

        query = self._normalise_text(context.get("query", ""))
        resolved_query = self._normalise_text(
            context.get("resolved_query", query)
        )

        if query and not resolved_query:
            issues.append("missing_resolved_context")

        confidence = self._clamp(
            context.get("confidence", 0.5)
        )

        # Explicit upstream outcome signals.
        signal_map = (
            ("failed", "execution_failure"),
            ("tool_error", "tool_error"),
            ("timeout", "timeout"),
            ("low_confidence", "low_confidence_signal"),
        )

        for key, issue in signal_map:
            if context.get(key) is True:
                issues.append(issue)

        # Verification is optional, but if an upstream verifier explicitly
        # says the result failed, reflection must record that outcome.
        verified = context.get("verified")
        verification_failed = context.get("verification_failed")

        if verification_failed is True:
            issues.append("verification_failure")

        quality_score = 1.0

        penalties = {
            "empty_response": 0.45,
            "too_short": 0.15,
            "missing_resolved_context": 0.15,
            "execution_failure": 0.30,
            "tool_error": 0.25,
            "timeout": 0.25,
            "low_confidence_signal": 0.10,
            "verification_failure": 0.35,
        }

        for issue in issues:
            quality_score -= penalties.get(issue, 0.0)

        if confidence < 0.25:
            quality_score -= 0.10
        elif confidence >= 0.85 and not issues:
            quality_score += 0.03

        quality_score = self._clamp(quality_score)

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

        if verified is True:
            self.statistics["verified_outcomes"] += 1
        elif verified is False:
            self.statistics["unverified_outcomes"] += 1

        evaluation = {
            "quality": quality,
            "quality_score": round(quality_score, 3),
            "complete": not bool(issues),
            "issues": list(dict.fromkeys(issues)),
            "confidence": round(confidence, 3),
            "query": query,
            "resolved_query": resolved_query,
            "response_length": len(text),
            "verified": verified,
            "evaluated_at": self._now(),
        }

        self._recent_reviews.append(evaluation)
        return evaluation

    # =========================================================
    # EXECUTION / ACTION REFLECTION
    # =========================================================

    async def reflect_on_execution(
        self,
        execution_result: Any,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Evaluate observable execution results.

        This is intentionally separate from plan reflection so computer
        control, tools, actions, and automation can report whether their
        intended outcome was actually verified.
        """
        self.statistics["execution_reviews"] += 1

        context = context or {}

        if isinstance(execution_result, dict):
            data = dict(execution_result)
        else:
            data = {
                "success": getattr(
                    execution_result,
                    "success",
                    False,
                ),
                "error": getattr(
                    execution_result,
                    "error",
                    None,
                ),
                "result": getattr(
                    execution_result,
                    "result",
                    None,
                ),
            }

        success = data.get("success")
        if success is None:
            success = data.get("ok")

        errors = self._as_list(data.get("errors"))
        error = data.get("error")
        if error:
            errors.append(error)

        verification = data.get("verified")
        if verification is None:
            verification = data.get("verification")

        verification_failed = (
            verification is False
            or data.get("verification_failed") is True
        )

        if success is None:
            success = not bool(errors) and not verification_failed

        duration = data.get(
            "duration_seconds",
            data.get("duration"),
        )

        try:
            duration = (
                float(duration)
                if duration is not None
                else None
            )
        except (TypeError, ValueError):
            duration = None

        issues: List[str] = []

        if not bool(success):
            issues.append("execution_failure")

        if errors:
            issues.append("execution_error")

        if verification_failed:
            issues.append("verification_failure")

        if duration is not None and duration > 30:
            issues.append("slow_execution")

        if data.get("retry_count", 0):
            issues.append("retry_required")

        if not verification and bool(success):
            issues.append("unverified_success")

        if not issues:
            quality = "high"
        elif "execution_failure" in issues or "verification_failure" in issues:
            quality = "low"
        else:
            quality = "medium"

        improvements = await self.suggest_improvements(
            {
                "issues": issues,
                "execution": True,
                "duration_seconds": duration,
            }
        )

        return {
            "success": bool(success),
            "quality": quality,
            "issues": list(dict.fromkeys(issues)),
            "errors": [self._normalise_text(item) for item in errors],
            "duration_seconds": duration,
            "verified": verification,
            "improvements": improvements,
            "context": {
                "task_id": context.get("task_id"),
                "session_id": context.get("session_id"),
            },
            "evaluated_at": self._now(),
        }

    # =========================================================
    # PLAN REFLECTION
    # =========================================================

    async def reflect_on_plan(
        self,
        plan: Any,
        execution_results: Dict[str, Any],
    ) -> Dict[str, Any]:
        execution_results = execution_results or {}

        success = bool(
            execution_results.get(
                "success",
                execution_results.get("ok", False),
            )
        )

        errors = self._as_list(
            execution_results.get("errors")
        )

        duration = execution_results.get(
            "duration",
            execution_results.get("duration_seconds"),
        )

        try:
            duration = (
                float(duration)
                if duration is not None
                else None
            )
        except (TypeError, ValueError):
            duration = None

        bottlenecks: List[str] = []

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

        if execution_results.get("verification_failed") is True:
            bottlenecks.append(
                "Execution verification failed"
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
        Inspect only observable reasoning metadata.

        Hidden chain-of-thought is never requested, stored, or returned.
        """
        self.statistics["reasoning_reviews"] += 1

        if reasoning_result is None:
            return {
                "reasoning_soundness": "unknown",
                "confidence_assessment": 0.0,
                "reasoning_available": False,
            }

        if isinstance(reasoning_result, dict):
            conf = reasoning_result.get(
                "confidence",
                0.5,
            )
            contradictions = self._as_list(
                reasoning_result.get("contradictions")
            )
        else:
            conf = getattr(
                reasoning_result,
                "confidence",
                0.5,
            )
            contradictions = self._as_list(
                getattr(
                    reasoning_result,
                    "contradictions",
                    None,
                )
            )

        conf = self._clamp(conf)

        if contradictions:
            soundness = "weak"
        elif conf >= 0.80:
            soundness = "strong"
        elif conf >= 0.50:
            soundness = "moderate"
        else:
            soundness = "weak"

        return {
            "reasoning_soundness": soundness,
            "confidence_assessment": round(conf, 3),
            "contradictions_detected": len(contradictions),
            "reasoning_available": True,
        }

    # =========================================================
    # REPEATED FAILURE DETECTION
    # =========================================================

    async def detect_repeated_mistakes(
        self,
        query: str,
    ) -> bool:
        query = self._normalise_text(query)

        if not query:
            return False

        pattern = self._pattern_key(query)

        if pattern and self._failure_patterns.get(pattern, 0) > 0:
            return True

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
        evaluation_data = evaluation_data or {}

        suggestions: List[str] = []
        issues = self._as_list(
            evaluation_data.get("issues")
        )

        mapping = {
            "empty_response":
                "Verify response generation before returning the result.",
            "too_short":
                "Increase response completeness when the task requires explanation.",
            "missing_resolved_context":
                "Preserve resolved query context through the reasoning pipeline.",
            "execution_failure":
                "Inspect failed execution steps and use an appropriate bounded fallback.",
            "execution_error":
                "Capture structured tool/action errors and validate inputs before retrying.",
            "tool_error":
                "Validate tool availability and improve tool-failure recovery.",
            "timeout":
                "Reduce unnecessary work or apply a bounded fallback when execution times out.",
            "low_confidence_signal":
                "Prefer stronger evidence or retrieval before committing to an answer.",
            "verification_failure":
                "Do not treat an action as complete until its observable outcome is verified.",
            "unverified_success":
                "Add an explicit verification step before marking the operation successful.",
            "slow_execution":
                "Reduce unnecessary execution steps and use bounded timeouts.",
            "retry_required":
                "Prefer bounded retries with backoff instead of repeated blind retries.",
        }

        for issue in issues:
            recommendation = mapping.get(str(issue))
            if recommendation:
                suggestions.append(recommendation)

        if not suggestions:
            suggestions.append(
                "Continue reinforcing successful retrieval and execution pathways."
            )

        suggestions = list(dict.fromkeys(suggestions))
        self.statistics["improvement_suggestions"] += len(
            suggestions
        )

        self._recent_improvements.append(
            {
                "suggestions": suggestions,
                "issues": [str(item) for item in issues],
                "created_at": self._now(),
            }
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

        if not answer:
            self.statistics["mistakes"] += 1

            pattern = self._pattern_key(query)
            repeated = False

            if pattern:
                self._failure_patterns[pattern] += 1
                repeated = self._failure_patterns[pattern] > 1

                if repeated:
                    self.statistics["repeated_mistakes"] += 1
                    self.statistics["failure_patterns"] += 1

            await self.learn_from_failure(
                query,
                pattern_already_recorded=bool(pattern),
            )

            return {
                "success": False,
                "reason": "empty_response",
                "query": query,
                "repeated": repeated,
            }

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
                previous_count = self._failure_patterns.get(
                    pattern,
                    0,
                )
                self._failure_patterns[pattern] += 1

                if previous_count > 0:
                    self.statistics["failure_patterns"] += 1

            if (
                self.database is not None
                and hasattr(self.database, "store")
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

            await self.learn_from_failure(
                query,
                pattern_already_recorded=bool(pattern),
            )

            return {
                "success": False,
                "reason": "knowledge_gap",
                "repeated": repeated,
                "query": query,
                "pattern": pattern,
            }

        pattern = self._pattern_key(query)

        if pattern:
            self._success_patterns[pattern] += 1

        await self.learn_from_success(
            query,
            answer,
            pattern_already_recorded=bool(pattern),
        )

        return {
            "success": True,
            "reason": "successful_response",
            "query": query,
        }

    # =========================================================
    # CONFIDENCE MANAGEMENT
    # =========================================================

    async def improve_confidence(self, knowledge_id):
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
            self.statistics["confidence_updates"] += 1
            return True
        except Exception:
            logger.exception(
                "[SelfReflection] Failed to increase confidence."
            )
            return False

    async def reduce_confidence(self, knowledge_id):
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
            self.statistics["confidence_updates"] += 1
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
        pattern_already_recorded: bool = False,
    ):
        self.statistics["improvements"] += 1

        query = self._normalise_text(query)
        pattern = self._pattern_key(query)

        if pattern and not pattern_already_recorded:
            previous_count = self._failure_patterns.get(
                pattern,
                0,
            )
            self._failure_patterns[pattern] += 1

            if previous_count > 0:
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
        pattern_already_recorded: bool = False,
    ):
        self.statistics["improvements"] += 1

        query = self._normalise_text(query)
        answer = self._normalise_text(answer)
        pattern = self._pattern_key(query)

        if pattern and not pattern_already_recorded:
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
        if self.database is None:
            return {
                "checked": 0,
                "duplicates": 0,
                "status": "database_unavailable",
            }

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
        if self.graph_builder is None:
            return {
                "status": "graph_builder_unavailable",
            }

        try:
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
    # DAILY REVIEW
    # =========================================================

    async def daily_review(self):
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
            for pattern, count in self._failure_patterns.most_common(10)
            if count >= 2
        ]

        improvement_items = list(
            self._recent_improvements
        )[-10:]

        return {
            "type": "daily_reflection",
            "duplicates": duplicate_result,
            "graph": graph_result,
            "recent_review_count": len(recent),
            "recent_low_quality_reviews": low_quality,
            "repeated_failure_patterns": repeated_failures,
            "recent_improvements": improvement_items,
            "statistics": dict(self.statistics),
            "generated_at": self._now(),
        }

    # =========================================================
    # WEEKLY REVIEW
    # =========================================================

    async def weekly_review(self):
        self.statistics["weekly_reviews"] += 1

        duplicate_result = await self.detect_duplicates()
        graph_result = await self.improve_graph()

        repeated_failures = [
            {
                "pattern": pattern,
                "count": count,
            }
            for pattern, count in self._failure_patterns.most_common(20)
            if count >= 2
        ]

        successful_patterns = [
            {
                "pattern": pattern,
                "count": count,
            }
            for pattern, count in self._success_patterns.most_common(20)
            if count >= 2
        ]

        return {
            "type": "weekly_reflection",
            "duplicates": duplicate_result,
            "graph": graph_result,
            "repeated_failure_patterns": repeated_failures,
            "successful_patterns": successful_patterns,
            "statistics": dict(self.statistics),
            "generated_at": self._now(),
        }

    # =========================================================
    # SUMMARY
    # =========================================================

    def summary(self):
        return {
            **self.statistics,
            "recent_reviews_buffer": len(
                self._recent_reviews
            ),
            "recent_improvements_buffer": len(
                self._recent_improvements
            ),
            "tracked_failure_patterns": len(
                self._failure_patterns
            ),
            "tracked_success_patterns": len(
                self._success_patterns
            ),
            "top_failure_patterns": [
                {
                    "pattern": pattern,
                    "count": count,
                }
                for pattern, count
                in self._failure_patterns.most_common(10)
            ],
            "top_success_patterns": [
                {
                    "pattern": pattern,
                    "count": count,
                }
                for pattern, count
                in self._success_patterns.most_common(10)
            ],
        }

    # =========================================================
    # UNIVERSAL ENTRY POINT
    # =========================================================

    async def reflect(self, event: str, **kwargs):
        event = self._normalise_text(event).lower()

        if event == "review":
            return await self.review(
                kwargs.get("query"),
                kwargs.get("answer"),
                kwargs.get("source"),
            )

        if event == "evaluate_response":
            return await self.evaluate_response(
                kwargs.get("response"),
                kwargs.get("context", {}),
            )

        if event == "execution":
            return await self.reflect_on_execution(
                kwargs.get("execution_result"),
                kwargs.get("context", {}),
            )

        if event == "plan":
            return await self.reflect_on_plan(
                kwargs.get("plan"),
                kwargs.get("execution_results", {}),
            )

        if event == "reasoning":
            return await self.reflect_on_reasoning(
                kwargs.get("reasoning_result"),
            )

        if event == "failure":
            return await self.learn_from_failure(
                kwargs.get("query"),
            )

        if event == "success":
            return await self.learn_from_success(
                kwargs.get("query"),
                kwargs.get("answer"),
            )

        if event == "daily":
            return await self.daily_review()

        if event == "weekly":
            return await self.weekly_review()

        if event == "duplicates":
            return await self.detect_duplicates()

        if event == "graph":
            return await self.improve_graph()

        if event == "summary":
            return self.summary()

        return {
            "success": False,
            "error": "unknown_reflection_event",
            "event": event,
        }

    async def handle(self, event):
        """
        Event-bus compatible entry point.

        Supports event.data as a mapping and safely handles events
        that do not provide data.
        """
        data = getattr(
            event,
            "data",
            {},
        ) or {}

        if not isinstance(data, dict):
            data = {}

        return await self.reflect(
            getattr(event, "type", ""),
            **data,
        )
