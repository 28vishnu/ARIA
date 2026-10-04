"""
ARIA Experience / Outcome Learning Engine
==========================================

Phase 1 - Step 13

Purpose
-------
Convert execution experiences into compact, reusable learning signals.

This module is intentionally separate from the existing:
    brain/learning.py
    brain/knowledge/learning_engine.py
    brain/learning/autonomous_learning.py

Those components already handle general knowledge learning.

This engine focuses specifically on:

    plan/task experience
    execution outcomes
    success/failure patterns
    retries
    verification results
    correction signals
    reusable lessons

Design goals
------------
- deterministic
- bounded storage
- async-friendly
- MongoDB compatible
- no LLM dependency
- no execution side effects
- no duplicate LearningEngine
- safe when MongoDB is unavailable
"""

from __future__ import annotations

import hashlib
import logging
import re

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


logger = logging.getLogger("aria")


# ============================================================================
# CONSTANTS
# ============================================================================

MAX_TEXT_LENGTH = 4000
MAX_LESSON_LENGTH = 3000
MAX_METADATA_ITEMS = 30
MAX_HISTORY_RESULTS = 50


# ============================================================================
# HELPERS
# ============================================================================

def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_text(
    value: Any,
    limit: int = MAX_TEXT_LENGTH,
) -> str:
    """
    Convert arbitrary values to bounded text.
    """

    if value is None:
        return ""

    if isinstance(value, str):
        text = value.strip()
    else:
        text = str(value).strip()

    if len(text) <= limit:
        return text

    return (
        text[:limit]
        + "\n[TRUNCATED]"
    )


def _safe_dict(
    value: Any,
    max_items: int = MAX_METADATA_ITEMS,
) -> Dict[str, Any]:
    """
    Keep metadata small and serialization-safe.
    """

    if not isinstance(value, dict):
        return {}

    result: Dict[str, Any] = {}

    for index, (key, item) in enumerate(value.items()):

        if index >= max_items:
            break

        safe_key = _safe_text(
            key,
            200,
        )

        if isinstance(item, dict):
            result[safe_key] = _safe_dict(
                item,
                max_items=15,
            )

        elif isinstance(item, (list, tuple, set)):
            result[safe_key] = [
                _safe_text(x, 500)
                for x in list(item)[:15]
            ]

        elif isinstance(item, (str, int, float, bool)) or item is None:
            if isinstance(item, str):
                result[safe_key] = _safe_text(
                    item,
                    1000,
                )
            else:
                result[safe_key] = item

        else:
            result[safe_key] = _safe_text(
                item,
                1000,
            )

    return result


def _fingerprint(
    *values: Any,
) -> str:
    """
    Generate a deterministic fingerprint for an experience.
    """

    normalized = "|".join(
        _safe_text(value, 1000).lower()
        for value in values
    )

    return hashlib.sha256(
        normalized.encode(
            "utf-8",
            errors="ignore",
        )
    ).hexdigest()[:24]


# ============================================================================
# DATA MODELS
# ============================================================================

@dataclass
class ExperienceOutcome:
    """
    Compact representation of one execution experience.
    """

    experience_id: str

    goal: str = ""

    task_id: str = ""

    task_name: str = ""

    task_type: str = ""

    action_name: str = ""

    status: str = ""

    success: bool = False

    attempts: int = 0

    retry_count: int = 0

    duration_ms: float = 0.0

    error: str = ""

    error_type: str = ""

    lesson: str = ""

    correction: str = ""

    verification_status: str = ""

    plan_fingerprint: str = ""

    task_fingerprint: str = ""

    metadata: Dict[str, Any] = field(
        default_factory=dict
    )

    created_at: datetime = field(
        default_factory=_utc_now
    )

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the experience to a MongoDB-friendly dictionary.
        """

        data = asdict(self)

        if isinstance(
            data.get("created_at"),
            datetime,
        ):
            data["created_at"] = data[
                "created_at"
            ].isoformat()

        return data


# ============================================================================
# EXPERIENCE ENGINE
# ============================================================================

class ExperienceEngine:
    """
    Structured execution experience and outcome learner.

    The engine can work with or without MongoDB.

    When MongoDB is available:
        experiences are stored in `aria_experiences`.

    When MongoDB is unavailable:
        recent experiences remain in bounded in-memory storage.

    The engine does not execute tasks and does not call an LLM.
    """

    COLLECTION_NAME = "aria_experiences"

    def __init__(
        self,
        mongo_db=None,
        learning_engine=None,
        knowledge_database=None,
        max_memory: int = 200,
    ):
        self.db = mongo_db

        self.learning_engine = learning_engine

        self.knowledge_database = (
            knowledge_database
        )

        self.max_memory = max(
            10,
            int(max_memory),
        )

        self.collection = None

        if self.db is not None:
            try:
                self.collection = self.db[
                    self.COLLECTION_NAME
                ]
            except Exception:
                logger.exception(
                    "[ExperienceEngine] "
                    "Could not initialize MongoDB collection."
                )

        self._memory: List[
            ExperienceOutcome
        ] = []

        self.statistics = {
            "recorded": 0,
            "successes": 0,
            "failures": 0,
            "duplicates": 0,
            "lessons": 0,
            "corrections": 0,
            "verification_failures": 0,
            "memory_records": 0,
            "database_records": 0,
        }

    # ========================================================================
    # NORMALIZATION
    # ========================================================================

    def _extract(
        self,
        data: Any,
        key: str,
        default: Any = None,
    ) -> Any:
        """
        Read a value from either a dictionary or object.
        """

        if data is None:
            return default

        if isinstance(data, dict):
            return data.get(
                key,
                default,
            )

        return getattr(
            data,
            key,
            default,
        )

    def _build_lesson(
        self,
        success: bool,
        status: str,
        error: str,
        verification_status: str,
        correction: str,
    ) -> str:
        """
        Produce a deterministic lesson from an outcome.
        """

        if correction:
            return _safe_text(
                correction,
                MAX_LESSON_LENGTH,
            )

        if not success:

            parts = []

            if status:
                parts.append(
                    f"Execution ended with status '{status}'."
                )

            if error:
                parts.append(
                    f"Failure signal: {error}"
                )

            if verification_status:
                parts.append(
                    "Verification did not confirm the expected result."
                )

            if parts:
                return _safe_text(
                    " ".join(parts),
                    MAX_LESSON_LENGTH,
                )

            return (
                "Execution failed; future attempts "
                "should verify prerequisites and outputs."
            )

        if verification_status in {
            "failed",
            "invalid",
            "rejected",
        }:
            return (
                "Execution completed, but verification "
                "did not confirm the expected result."
            )

        return (
            "Execution completed successfully; "
            "the observed execution path can be reused."
        )

    def _create_outcome(
        self,
        execution: Any,
        plan: Any = None,
        task: Any = None,
        verification: Any = None,
        correction: str = "",
    ) -> ExperienceOutcome:
        """
        Convert runtime objects into a compact outcome.
        """

        goal = _safe_text(
            self._extract(
                plan,
                "goal",
                self._extract(
                    execution,
                    "goal",
                    "",
                ),
            ),
            2000,
        )

        task_id = _safe_text(
            self._extract(
                task,
                "id",
                self._extract(
                    execution,
                    "task_id",
                    "",
                ),
            ),
            200,
        )

        task_name = _safe_text(
            self._extract(
                task,
                "name",
                self._extract(
                    execution,
                    "task_name",
                    "",
                ),
            ),
            500,
        )

        task_type = _safe_text(
            self._extract(
                task,
                "task_type",
                self._extract(
                    execution,
                    "task_type",
                    "",
                ),
            ),
            100,
        )

        action_name = _safe_text(
            self._extract(
                task,
                "action_name",
                self._extract(
                    execution,
                    "action_name",
                    "",
                ),
            ),
            300,
        )

        status = _safe_text(
            self._extract(
                execution,
                "status",
                self._extract(
                    task,
                    "status",
                    "",
                ),
            ),
            100,
        )

        success = bool(
            self._extract(
                execution,
                "success",
                status in {
                    "completed",
                    "success",
                    "successful",
                },
            )
        )

        attempts = int(
            self._extract(
                execution,
                "attempts",
                0,
            )
            or 0
        )

        retry_count = int(
            self._extract(
                execution,
                "retry_count",
                self._extract(
                    task,
                    "retry_count",
                    0,
                ),
            )
            or 0
        )

        duration_ms = float(
            self._extract(
                execution,
                "duration_ms",
                self._extract(
                    execution,
                    "execution_time_ms",
                    0.0,
                ),
            )
            or 0.0
        )

        error = _safe_text(
            self._extract(
                execution,
                "error",
                self._extract(
                    task,
                    "error",
                    "",
                ),
            ),
            2000,
        )

        error_type = _safe_text(
            self._extract(
                execution,
                "error_type",
                "",
            ),
            300,
        )

        verification_status = _safe_text(
            self._extract(
                verification,
                "status",
                self._extract(
                    verification,
                    "verification_status",
                    self._extract(
                        execution,
                        "verification_status",
                        "",
                    ),
                ),
            ),
            200,
        )

        correction_text = _safe_text(
            correction,
            MAX_LESSON_LENGTH,
        )

        lesson = self._build_lesson(
            success=success,
            status=status,
            error=error,
            verification_status=verification_status,
            correction=correction_text,
        )

        plan_fingerprint = _fingerprint(
            goal,
            self._extract(
                plan,
                "metadata",
                {},
            ),
        )

        task_fingerprint = _fingerprint(
            task_type,
            task_name,
            action_name,
        )

        experience_id = _fingerprint(
            plan_fingerprint,
            task_fingerprint,
            status,
            success,
            error_type,
        )

        metadata = _safe_dict(
            self._extract(
                execution,
                "metadata",
                {},
            )
        )

        return ExperienceOutcome(
            experience_id=experience_id,
            goal=goal,
            task_id=task_id,
            task_name=task_name,
            task_type=task_type,
            action_name=action_name,
            status=status,
            success=success,
            attempts=attempts,
            retry_count=retry_count,
            duration_ms=duration_ms,
            error=error,
            error_type=error_type,
            lesson=lesson,
            correction=correction_text,
            verification_status=verification_status,
            plan_fingerprint=plan_fingerprint,
            task_fingerprint=task_fingerprint,
            metadata=metadata,
        )

    # ========================================================================
    # STORAGE
    # ========================================================================

    async def _store_database(
        self,
        outcome: ExperienceOutcome,
    ) -> bool:
        """
        Store an experience in MongoDB when available.
        """

        if self.collection is None:
            return False

        try:

            document = outcome.to_dict()

            existing = await self.collection.find_one(
                {
                    "experience_id":
                        outcome.experience_id
                }
            )

            if existing:
                self.statistics[
                    "duplicates"
                ] += 1

                await self.collection.update_one(
                    {
                        "experience_id":
                            outcome.experience_id
                    },
                    {
                        "$set": {
                            **document,
                            "updated_at":
                                _utc_now().isoformat(),
                        }
                    },
                )

            else:

                await self.collection.insert_one(
                    document
                )

            self.statistics[
                "database_records"
            ] += 1

            return True

        except Exception:

            logger.exception(
                "[ExperienceEngine] "
                "MongoDB experience storage failed."
            )

            return False

    def _store_memory(
        self,
        outcome: ExperienceOutcome,
    ) -> None:
        """
        Maintain bounded in-memory experience history.
        """

        # Replace same experience instead of growing duplicates.
        self._memory = [
            item
            for item in self._memory
            if item.experience_id
            != outcome.experience_id
        ]

        self._memory.append(
            outcome
        )

        if len(self._memory) > self.max_memory:
            overflow = (
                len(self._memory)
                - self.max_memory
            )

            del self._memory[
                :overflow
            ]

        self.statistics[
            "memory_records"
        ] = len(self._memory)

    # ========================================================================
    # PUBLIC RECORDING API
    # ========================================================================

    async def record(
        self,
        execution: Any,
        plan: Any = None,
        task: Any = None,
        verification: Any = None,
        correction: str = "",
    ) -> ExperienceOutcome:
        """
        Record one execution experience.

        This is the primary API for later execution integration.
        """

        outcome = self._create_outcome(
            execution=execution,
            plan=plan,
            task=task,
            verification=verification,
            correction=correction,
        )

        self._store_memory(
            outcome
        )

        await self._store_database(
            outcome
        )

        self.statistics[
            "recorded"
        ] += 1

        if outcome.success:
            self.statistics[
                "successes"
            ] += 1
        else:
            self.statistics[
                "failures"
            ] += 1

        if outcome.correction:
            self.statistics[
                "corrections"
            ] += 1

        if outcome.lesson:
            self.statistics[
                "lessons"
            ] += 1

        if outcome.verification_status in {
            "failed",
            "invalid",
            "rejected",
        }:
            self.statistics[
                "verification_failures"
            ] += 1

        # Optionally forward the compact lesson into the existing
        # knowledge-learning system.
        if (
            self.learning_engine is not None
            and outcome.lesson
        ):
            try:

                learn_method = getattr(
                    self.learning_engine,
                    "learn",
                    None,
                )

                if learn_method is not None:

                    await learn_method(
                        outcome.lesson,
                        source=(
                            "execution_experience"
                        ),
                    )

            except Exception:

                logger.exception(
                    "[ExperienceEngine] "
                    "Knowledge-learning forwarding failed."
                )

        return outcome

    async def record_success(
        self,
        execution: Any,
        plan: Any = None,
        task: Any = None,
        verification: Any = None,
    ) -> ExperienceOutcome:
        """
        Convenience API for successful outcomes.
        """

        if isinstance(execution, dict):
            execution = {
                **execution,
                "success": True,
            }

        return await self.record(
            execution=execution,
            plan=plan,
            task=task,
            verification=verification,
        )

    async def record_failure(
        self,
        execution: Any,
        plan: Any = None,
        task: Any = None,
        verification: Any = None,
        correction: str = "",
    ) -> ExperienceOutcome:
        """
        Convenience API for failed outcomes.
        """

        if isinstance(execution, dict):
            execution = {
                **execution,
                "success": False,
            }

        return await self.record(
            execution=execution,
            plan=plan,
            task=task,
            verification=verification,
            correction=correction,
        )

    # ========================================================================
    # EXPERIENCE RETRIEVAL
    # ========================================================================

    async def recent(
        self,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        Return recent experiences.
        """

        limit = max(
            1,
            min(
                int(limit),
                MAX_HISTORY_RESULTS,
            ),
        )

        if self.collection is not None:

            try:

                cursor = (
                    self.collection
                    .find({})
                    .sort(
                        "created_at",
                        -1,
                    )
                    .limit(limit)
                )

                results = []

                async for document in cursor:
                    document.pop(
                        "_id",
                        None,
                    )
                    results.append(
                        document
                    )

                if results:
                    return results

            except Exception:

                logger.exception(
                    "[ExperienceEngine] "
                    "Recent experience query failed."
                )

        return [
            item.to_dict()
            for item in reversed(
                self._memory[-limit:]
            )
        ]

    async def find_similar(
        self,
        task_name: str = "",
        task_type: str = "",
        action_name: str = "",
        success_only: bool = False,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Find previously observed experiences using deterministic
        task/action matching.

        No semantic model or LLM is required.
        """

        limit = max(
            1,
            min(
                int(limit),
                MAX_HISTORY_RESULTS,
            ),
        )

        target_name = _safe_text(
            task_name,
            500,
        ).lower()

        target_type = _safe_text(
            task_type,
            100,
        ).lower()

        target_action = _safe_text(
            action_name,
            300,
        ).lower()

        matches = []

        for outcome in reversed(
            self._memory
        ):

            if success_only and not outcome.success:
                continue

            if (
                target_name
                and target_name
                not in outcome.task_name.lower()
            ):
                continue

            if (
                target_type
                and target_type
                != outcome.task_type.lower()
            ):
                continue

            if (
                target_action
                and target_action
                != outcome.action_name.lower()
            ):
                continue

            matches.append(
                outcome.to_dict()
            )

            if len(matches) >= limit:
                return matches

        # If MongoDB is available and memory did not provide enough
        # records, query the deterministic fingerprint fields.
        if (
            self.collection is not None
            and len(matches) < limit
        ):

            query: Dict[str, Any] = {}

            if target_type:
                query[
                    "task_type"
                ] = target_type

            if target_action:
                query[
                    "action_name"
                ] = target_action

            if success_only:
                query[
                    "success"
                ] = True

            try:

                cursor = (
                    self.collection
                    .find(query)
                    .sort(
                        "created_at",
                        -1,
                    )
                    .limit(limit)
                )

                async for document in cursor:

                    document.pop(
                        "_id",
                        None,
                    )

                    if (
                        document
                        not in matches
                    ):
                        matches.append(
                            document
                        )

                    if len(matches) >= limit:
                        break

            except Exception:

                logger.exception(
                    "[ExperienceEngine] "
                    "Similar experience query failed."
                )

        return matches[:limit]

    # ========================================================================
    # LEARNING SIGNALS
    # ========================================================================

    async def success_rate(
        self,
        task_type: str = "",
        action_name: str = "",
    ) -> float:
        """
        Calculate observed success rate from bounded local history.
        """

        experiences = await self.find_similar(
            task_type=task_type,
            action_name=action_name,
            limit=MAX_HISTORY_RESULTS,
        )

        if not experiences:
            return 0.0

        successes = sum(
            1
            for item in experiences
            if bool(
                item.get(
                    "success",
                    False,
                )
            )
        )

        return round(
            successes
            / len(experiences),
            4,
        )

    async def get_lessons(
        self,
        task_type: str = "",
        action_name: str = "",
        limit: int = 10,
    ) -> List[str]:
        """
        Return reusable lessons from prior experiences.
        """

        experiences = await self.find_similar(
            task_type=task_type,
            action_name=action_name,
            limit=limit,
        )

        lessons = []

        seen = set()

        for item in experiences:

            lesson = _safe_text(
                item.get(
                    "lesson",
                    "",
                ),
                MAX_LESSON_LENGTH,
            )

            if not lesson:
                continue

            normalized = re.sub(
                r"\s+",
                " ",
                lesson.lower(),
            )

            if normalized in seen:
                continue

            seen.add(
                normalized
            )

            lessons.append(
                lesson
            )

        return lessons

    # ========================================================================
    # HEALTH / DEBUGGING
    # ========================================================================

    def health(self) -> Dict[str, Any]:
        """
        Return lightweight engine health information.
        """

        return {
            "component": "experience_engine",
            "status": "healthy",
            "database_available": (
                self.collection is not None
            ),
            "memory_records": len(
                self._memory
            ),
            "statistics": dict(
                self.statistics
            ),
        }

    def describe(self) -> Dict[str, Any]:
        """
        Return a machine-readable component description.
        """

        return {
            "component": "ExperienceEngine",
            "purpose": (
                "Structured execution outcome and "
                "experience learning"
            ),
            "collection": self.COLLECTION_NAME,
            "llm_required": False,
            "execution_side_effects": False,
            "bounded_memory": self.max_memory,
            "features": [
                "success learning",
                "failure learning",
                "retry tracking",
                "verification outcomes",
                "correction signals",
                "lesson extraction",
                "experience history",
                "similar experience retrieval",
                "success-rate analysis",
            ],
        }