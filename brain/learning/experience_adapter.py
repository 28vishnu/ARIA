"""
ARIA Experience Adapter
=======================

Phase 1 - Step 14

Uses historical execution experiences to produce bounded,
deterministic adaptation recommendations.

This module:
- reads ExperienceEngine history
- identifies success/failure patterns
- recommends retry limits
- recommends verification requirements
- recommends strategy changes
- produces planning hints

It does NOT:
- execute tasks
- modify tasks directly
- call an LLM
- make unrestricted autonomous decisions
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List


logger = logging.getLogger("aria")


# ============================================================================
# CONSTANTS
# ============================================================================

DEFAULT_HISTORY_LIMIT = 20
MAX_HISTORY_LIMIT = 50

DEFAULT_RETRY_LIMIT = 2
MIN_RETRY_LIMIT = 0
MAX_RETRY_LIMIT = 5

HIGH_FAILURE_RATE = 0.60
MEDIUM_FAILURE_RATE = 0.35
HIGH_RETRY_RATE = 0.50


# ============================================================================
# DATA MODEL
# ============================================================================

@dataclass
class AdaptationRecommendation:
    """
    Bounded recommendation generated from previous experiences.
    """

    task_type: str = ""

    action_name: str = ""

    success_rate: float = 0.0

    failure_rate: float = 0.0

    sample_size: int = 0

    recommended_retry_limit: int = DEFAULT_RETRY_LIMIT

    require_verification: bool = False

    prefer_previous_success: bool = False

    avoid_previous_failure: bool = False

    confidence: float = 0.0

    strategy: str = "standard"

    reasons: List[str] = field(
        default_factory=list
    )

    lessons: List[str] = field(
        default_factory=list
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_type": self.task_type,
            "action_name": self.action_name,
            "success_rate": self.success_rate,
            "failure_rate": self.failure_rate,
            "sample_size": self.sample_size,
            "recommended_retry_limit": (
                self.recommended_retry_limit
            ),
            "require_verification": (
                self.require_verification
            ),
            "prefer_previous_success": (
                self.prefer_previous_success
            ),
            "avoid_previous_failure": (
                self.avoid_previous_failure
            ),
            "confidence": self.confidence,
            "strategy": self.strategy,
            "reasons": list(self.reasons),
            "lessons": list(self.lessons),
        }


# ============================================================================
# ADAPTER
# ============================================================================

class ExperienceAdapter:
    """
    Converts historical execution experience into deterministic
    planning/execution recommendations.
    """

    def __init__(
        self,
        experience_engine=None,
        default_retry_limit: int = DEFAULT_RETRY_LIMIT,
    ):
        self.experience_engine = (
            experience_engine
        )

        self.default_retry_limit = max(
            MIN_RETRY_LIMIT,
            min(
                int(default_retry_limit),
                MAX_RETRY_LIMIT,
            ),
        )

        self.statistics = {
            "recommendations": 0,
            "high_failure_patterns": 0,
            "verification_recommendations": 0,
            "retry_recommendations": 0,
        }

    # ========================================================================
    # HELPERS
    # ========================================================================

    @staticmethod
    def _text(
        value: Any,
        limit: int = 500,
    ) -> str:
        if value is None:
            return ""

        value = str(value).strip()

        return value[:limit]

    @staticmethod
    def _clamp(
        value: float,
        minimum: float = 0.0,
        maximum: float = 1.0,
    ) -> float:
        return max(
            minimum,
            min(
                maximum,
                float(value),
            ),
        )

    @staticmethod
    def _success_rate(
        records: List[Dict[str, Any]],
    ) -> float:
        if not records:
            return 0.0

        successes = sum(
            1
            for item in records
            if bool(
                item.get(
                    "success",
                    False,
                )
            )
        )

        return round(
            successes / len(records),
            4,
        )

    @staticmethod
    def _failure_rate(
        records: List[Dict[str, Any]],
    ) -> float:
        if not records:
            return 0.0

        failures = sum(
            1
            for item in records
            if not bool(
                item.get(
                    "success",
                    False,
                )
            )
        )

        return round(
            failures / len(records),
            4,
        )

    # ========================================================================
    # EXPERIENCE ACCESS
    # ========================================================================

    async def _get_experiences(
        self,
        task_type: str = "",
        action_name: str = "",
        limit: int = DEFAULT_HISTORY_LIMIT,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve historical experiences safely.
        """

        if self.experience_engine is None:
            return []

        limit = max(
            1,
            min(
                int(limit),
                MAX_HISTORY_LIMIT,
            ),
        )

        try:

            return await self.experience_engine.find_similar(
                task_type=task_type,
                action_name=action_name,
                limit=limit,
            )

        except Exception:

            logger.exception(
                "[ExperienceAdapter] "
                "Could not retrieve experiences."
            )

            return []

    # ========================================================================
    # RECOMMENDATION
    # ========================================================================

    async def recommend(
        self,
        task_type: str = "",
        action_name: str = "",
        limit: int = DEFAULT_HISTORY_LIMIT,
    ) -> AdaptationRecommendation:
        """
        Generate an adaptation recommendation from prior outcomes.
        """

        task_type = self._text(
            task_type,
            100,
        )

        action_name = self._text(
            action_name,
            300,
        )

        records = await self._get_experiences(
            task_type=task_type,
            action_name=action_name,
            limit=limit,
        )

        sample_size = len(records)

        if sample_size == 0:

            return AdaptationRecommendation(
                task_type=task_type,
                action_name=action_name,
                success_rate=0.0,
                failure_rate=0.0,
                sample_size=0,
                recommended_retry_limit=(
                    self.default_retry_limit
                ),
                require_verification=False,
                prefer_previous_success=False,
                avoid_previous_failure=False,
                confidence=0.0,
                strategy="standard",
                reasons=[
                    "No previous experience is available."
                ],
            )

        success_rate = self._success_rate(
            records
        )

        failure_rate = self._failure_rate(
            records
        )

        confidence = self._clamp(
            sample_size / 10.0
        )

        recommendation = AdaptationRecommendation(
            task_type=task_type,
            action_name=action_name,
            success_rate=success_rate,
            failure_rate=failure_rate,
            sample_size=sample_size,
            recommended_retry_limit=(
                self.default_retry_limit
            ),
            confidence=round(
                confidence,
                4,
            ),
        )

        # ------------------------------------------------------------
        # High failure pattern
        # ------------------------------------------------------------

        if failure_rate >= HIGH_FAILURE_RATE:

            recommendation.strategy = (
                "cautious"
            )

            recommendation.require_verification = True

            recommendation.avoid_previous_failure = True

            recommendation.recommended_retry_limit = min(
                self.default_retry_limit,
                1,
            )

            recommendation.reasons.append(
                "Historical failure rate is high."
            )

            recommendation.reasons.append(
                "Avoid repeating previously unsuccessful execution paths."
            )

            recommendation.reasons.append(
                "Verify the result before considering the task complete."
            )

            self.statistics[
                "high_failure_patterns"
            ] += 1

        # ------------------------------------------------------------
        # Medium failure pattern
        # ------------------------------------------------------------

        elif failure_rate >= MEDIUM_FAILURE_RATE:

            recommendation.strategy = (
                "verified_retry"
            )

            recommendation.require_verification = True

            recommendation.recommended_retry_limit = min(
                self.default_retry_limit + 1,
                MAX_RETRY_LIMIT,
            )

            recommendation.reasons.append(
                "Historical failures are significant."
            )

            recommendation.reasons.append(
                "Allow bounded retry with verification."
            )

        # ------------------------------------------------------------
        # Strong success pattern
        # ------------------------------------------------------------

        elif success_rate >= 0.75:

            recommendation.strategy = (
                "reuse_success"
            )

            recommendation.prefer_previous_success = True

            recommendation.recommended_retry_limit = min(
                self.default_retry_limit,
                2,
            )

            recommendation.reasons.append(
                "Historical success rate is strong."
            )

            recommendation.reasons.append(
                "Prefer previously successful execution patterns."
            )

        # ------------------------------------------------------------
        # Normal pattern
        # ------------------------------------------------------------

        else:

            recommendation.strategy = (
                "standard"
            )

            recommendation.reasons.append(
                "Historical outcomes do not indicate a strong pattern."
            )

        # ------------------------------------------------------------
        # Retry analysis
        # ------------------------------------------------------------

        retry_records = [
            item
            for item in records
            if int(
                item.get(
                    "retry_count",
                    0,
                )
                or 0
            ) > 0
        ]

        if retry_records:

            retry_rate = (
                len(retry_records)
                / sample_size
            )

            if retry_rate >= HIGH_RETRY_RATE:

                recommendation.require_verification = True

                recommendation.reasons.append(
                    "Previous executions frequently required retries."
                )

                self.statistics[
                    "retry_recommendations"
                ] += 1

        # ------------------------------------------------------------
        # Verification analysis
        # ------------------------------------------------------------

        verification_failures = [
            item
            for item in records
            if str(
                item.get(
                    "verification_status",
                    "",
                )
            ).lower()
            in {
                "failed",
                "invalid",
                "rejected",
            }
        ]

        if verification_failures:

            recommendation.require_verification = True

            recommendation.reasons.append(
                "Previous executions contain verification failures."
            )

            self.statistics[
                "verification_recommendations"
            ] += 1

        # ------------------------------------------------------------
        # Lessons
        # ------------------------------------------------------------

        seen_lessons = set()

        for item in records:

            lesson = self._text(
                item.get(
                    "lesson",
                    "",
                ),
                1000,
            )

            if not lesson:
                continue

            normalized = lesson.lower()

            if normalized in seen_lessons:
                continue

            seen_lessons.add(
                normalized
            )

            recommendation.lessons.append(
                lesson
            )

            if len(
                recommendation.lessons
            ) >= 5:
                break

        recommendation.confidence = round(
            self._clamp(
                (
                    confidence
                    * 0.7
                )
                + (
                    min(
                        sample_size / 20.0,
                        1.0,
                    )
                    * 0.3
                )
            ),
            4,
        )

        self.statistics[
            "recommendations"
        ] += 1

        return recommendation

    # ========================================================================
    # PLAN HINTS
    # ========================================================================

    async def planning_hints(
        self,
        task_type: str = "",
        action_name: str = "",
        limit: int = DEFAULT_HISTORY_LIMIT,
    ) -> Dict[str, Any]:
        """
        Produce a compact structure suitable for a planner.
        """

        recommendation = await self.recommend(
            task_type=task_type,
            action_name=action_name,
            limit=limit,
        )

        return {
            "strategy": recommendation.strategy,
            "retry_limit": (
                recommendation.recommended_retry_limit
            ),
            "require_verification": (
                recommendation.require_verification
            ),
            "prefer_previous_success": (
                recommendation.prefer_previous_success
            ),
            "avoid_previous_failure": (
                recommendation.avoid_previous_failure
            ),
            "success_rate": (
                recommendation.success_rate
            ),
            "failure_rate": (
                recommendation.failure_rate
            ),
            "confidence": (
                recommendation.confidence
            ),
            "lessons": list(
                recommendation.lessons
            ),
            "reasons": list(
                recommendation.reasons
            ),
        }

    # ========================================================================
    # EXECUTION HINTS
    # ========================================================================

    async def execution_hints(
        self,
        task_type: str = "",
        action_name: str = "",
    ) -> Dict[str, Any]:
        """
        Produce bounded hints for the autonomous execution layer.

        These are recommendations only.
        The executor remains responsible for enforcing limits.
        """

        recommendation = await self.recommend(
            task_type=task_type,
            action_name=action_name,
        )

        return {
            "retry_limit": max(
                MIN_RETRY_LIMIT,
                min(
                    recommendation.recommended_retry_limit,
                    MAX_RETRY_LIMIT,
                ),
            ),
            "verify_after_execution": (
                recommendation.require_verification
            ),
            "strategy": (
                recommendation.strategy
            ),
            "confidence": (
                recommendation.confidence
            ),
        }

    # ========================================================================
    # LESSONS
    # ========================================================================

    async def lessons(
        self,
        task_type: str = "",
        action_name: str = "",
        limit: int = 10,
    ) -> List[str]:
        """
        Return reusable lessons from historical experience.
        """

        if self.experience_engine is None:
            return []

        try:

            return await self.experience_engine.get_lessons(
                task_type=task_type,
                action_name=action_name,
                limit=limit,
            )

        except Exception:

            logger.exception(
                "[ExperienceAdapter] "
                "Could not retrieve lessons."
            )

            return []

    # ========================================================================
    # HEALTH
    # ========================================================================

    def health(self) -> Dict[str, Any]:
        return {
            "component": "experience_adapter",
            "status": "healthy",
            "experience_engine_available": (
                self.experience_engine is not None
            ),
            "statistics": dict(
                self.statistics
            ),
        }

    def describe(self) -> Dict[str, Any]:
        return {
            "component": "ExperienceAdapter",
            "purpose": (
                "Convert historical execution outcomes "
                "into bounded adaptation recommendations."
            ),
            "llm_required": False,
            "execution_side_effects": False,
            "max_retry_limit": MAX_RETRY_LIMIT,
            "features": [
                "failure-pattern detection",
                "success-pattern detection",
                "retry recommendations",
                "verification recommendations",
                "planning hints",
                "execution hints",
                "lesson reuse",
                "confidence scoring",
            ],
        }