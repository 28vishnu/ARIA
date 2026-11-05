"""
ARIA Experience Memory Consolidator
===================================

Phase 1 - Step 15

Converts repeated execution experiences into compact, durable
memory patterns.

Responsibilities
----------------
- group similar experiences
- calculate stable success/failure patterns
- identify repeated lessons
- identify reliable actions
- identify problematic actions
- produce compact memory records
- optionally forward consolidated knowledge to an existing
  knowledge database / learning engine

Design constraints
------------------
- deterministic
- bounded
- no LLM dependency
- no execution
- no modification of existing memories
- safe when external storage is unavailable
"""

from __future__ import annotations

import hashlib
import logging

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


logger = logging.getLogger("aria")


# ============================================================================
# CONSTANTS
# ============================================================================

MAX_EXPERIENCES = 200
MAX_GROUPS = 100
MAX_LESSONS_PER_GROUP = 5
MAX_MEMORY_RECORDS = 100

STABLE_SUCCESS_THRESHOLD = 0.75
STABLE_FAILURE_THRESHOLD = 0.60

MIN_PATTERN_SAMPLES = 2


# ============================================================================
# HELPERS
# ============================================================================

def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _text(
    value: Any,
    limit: int = 2000,
) -> str:
    if value is None:
        return ""

    value = str(value).strip()

    if len(value) <= limit:
        return value

    return value[:limit] + "\n[TRUNCATED]"


def _fingerprint(
    *values: Any,
) -> str:
    raw = "|".join(
        _text(
            value,
            500,
        ).lower()
        for value in values
    )

    return hashlib.sha256(
        raw.encode(
            "utf-8",
            errors="ignore",
        )
    ).hexdigest()[:24]


# ============================================================================
# DATA MODEL
# ============================================================================

@dataclass
class ConsolidatedMemory:
    """
    Compact representation of a repeated execution pattern.
    """

    memory_id: str

    task_type: str = ""

    action_name: str = ""

    task_name: str = ""

    sample_count: int = 0

    success_count: int = 0

    failure_count: int = 0

    success_rate: float = 0.0

    failure_rate: float = 0.0

    average_attempts: float = 0.0

    average_retries: float = 0.0

    strategy: str = "unknown"

    reliability: str = "unknown"

    lessons: List[str] = field(
        default_factory=list
    )

    common_errors: List[str] = field(
        default_factory=list
    )

    recommendation: str = ""

    created_at: datetime = field(
        default_factory=_utc_now
    )

    updated_at: datetime = field(
        default_factory=_utc_now
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "task_type": self.task_type,
            "action_name": self.action_name,
            "task_name": self.task_name,
            "sample_count": self.sample_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "success_rate": self.success_rate,
            "failure_rate": self.failure_rate,
            "average_attempts": self.average_attempts,
            "average_retries": self.average_retries,
            "strategy": self.strategy,
            "reliability": self.reliability,
            "lessons": list(self.lessons),
            "common_errors": list(
                self.common_errors
            ),
            "recommendation": self.recommendation,
            "created_at": (
                self.created_at.isoformat()
            ),
            "updated_at": (
                self.updated_at.isoformat()
            ),
        }


# ============================================================================
# CONSOLIDATOR
# ============================================================================

class ExperienceConsolidator:
    """
    Consolidates execution experiences into reusable long-term patterns.
    """

    COLLECTION_NAME = "aria_consolidated_memory"

    def __init__(
        self,
        experience_engine=None,
        knowledge_database=None,
        learning_engine=None,
        mongo_db=None,
        max_memory_records: int = MAX_MEMORY_RECORDS,
    ):
        self.experience_engine = (
            experience_engine
        )

        self.knowledge_database = (
            knowledge_database
        )

        self.learning_engine = (
            learning_engine
        )

        self.max_memory_records = max(
            10,
            int(max_memory_records),
        )

        self.collection = None

        if mongo_db is not None:
            try:
                self.collection = mongo_db[
                    self.COLLECTION_NAME
                ]
            except Exception:
                logger.exception(
                    "[ExperienceConsolidator] "
                    "MongoDB collection initialization failed."
                )

        self._memory: List[
            ConsolidatedMemory
        ] = []

        self.statistics = {
            "consolidations": 0,
            "patterns_created": 0,
            "stable_success_patterns": 0,
            "stable_failure_patterns": 0,
            "knowledge_forwarded": 0,
            "memory_records": 0,
        }

    # ========================================================================
    # EXPERIENCE LOADING
    # ========================================================================

    async def _load_experiences(
        self,
        limit: int = MAX_EXPERIENCES,
    ) -> List[Dict[str, Any]]:
        """
        Load bounded recent experiences.
        """

        limit = max(
            1,
            min(
                int(limit),
                MAX_EXPERIENCES,
            ),
        )

        if self.experience_engine is None:
            return []

        try:

            return await self.experience_engine.recent(
                limit=limit
            )

        except Exception:

            logger.exception(
                "[ExperienceConsolidator] "
                "Could not load experiences."
            )

            return []

    # ========================================================================
    # GROUPING
    # ========================================================================

    def _group_key(
        self,
        experience: Dict[str, Any],
    ) -> str:
        """
        Group experiences by task type and action.

        Task name is included only as a secondary discriminator.
        """

        task_type = _text(
            experience.get(
                "task_type",
                "",
            ),
            100,
        ).lower()

        action_name = _text(
            experience.get(
                "action_name",
                "",
            ),
            300,
        ).lower()

        task_name = _text(
            experience.get(
                "task_name",
                "",
            ),
            300,
        ).lower()

        return _fingerprint(
            task_type,
            action_name,
            task_name,
        )

    def _group_experiences(
        self,
        experiences: List[Dict[str, Any]],
    ) -> Dict[str, List[Dict[str, Any]]]:
        groups: Dict[
            str,
            List[Dict[str, Any]],
        ] = defaultdict(list)

        for experience in experiences:

            key = self._group_key(
                experience
            )

            if len(groups) >= MAX_GROUPS:
                if key not in groups:
                    continue

            groups[key].append(
                experience
            )

        return groups

    # ========================================================================
    # LESSON PROCESSING
    # ========================================================================

    def _extract_lessons(
        self,
        experiences: List[Dict[str, Any]],
    ) -> List[str]:
        """
        Return unique lessons ranked by occurrence.
        """

        counter = Counter()

        for experience in experiences:

            lesson = _text(
                experience.get(
                    "lesson",
                    "",
                ),
                1500,
            )

            if not lesson:
                continue

            normalized = " ".join(
                lesson.lower().split()
            )

            counter[
                normalized
            ] += 1

        lessons = []

        for normalized, _count in counter.most_common(
            MAX_LESSONS_PER_GROUP
        ):

            original = None

            for experience in experiences:

                lesson = _text(
                    experience.get(
                        "lesson",
                        "",
                    ),
                    1500,
                )

                if (
                    " ".join(
                        lesson.lower().split()
                    )
                    == normalized
                ):
                    original = lesson
                    break

            if original:
                lessons.append(
                    original
                )

        return lessons

    def _extract_errors(
        self,
        experiences: List[Dict[str, Any]],
    ) -> List[str]:
        """
        Identify recurring errors.
        """

        counter = Counter()

        for experience in experiences:

            error = _text(
                experience.get(
                    "error",
                    "",
                ),
                1000,
            )

            error_type = _text(
                experience.get(
                    "error_type",
                    "",
                ),
                300,
            )

            value = error or error_type

            if not value:
                continue

            normalized = " ".join(
                value.lower().split()
            )

            counter[
                normalized
            ] += 1

        return [
            value
            for value, _count in counter.most_common(
                MAX_LESSONS_PER_GROUP
            )
        ]

    # ========================================================================
    # CONSOLIDATION
    # ========================================================================

    def _consolidate_group(
        self,
        experiences: List[Dict[str, Any]],
    ) -> Optional[ConsolidatedMemory]:
        """
        Convert one experience group into one durable pattern.
        """

        if len(experiences) < MIN_PATTERN_SAMPLES:
            return None

        first = experiences[0]

        task_type = _text(
            first.get(
                "task_type",
                "",
            ),
            100,
        )

        action_name = _text(
            first.get(
                "action_name",
                "",
            ),
            300,
        )

        task_name = _text(
            first.get(
                "task_name",
                "",
            ),
            500,
        )

        success_count = sum(
            1
            for experience in experiences
            if bool(
                experience.get(
                    "success",
                    False,
                )
            )
        )

        failure_count = (
            len(experiences)
            - success_count
        )

        sample_count = len(
            experiences
        )

        success_rate = round(
            success_count
            / sample_count,
            4,
        )

        failure_rate = round(
            failure_count
            / sample_count,
            4,
        )

        attempts = [
            float(
                experience.get(
                    "attempts",
                    0,
                )
                or 0
            )
            for experience in experiences
        ]

        retries = [
            float(
                experience.get(
                    "retry_count",
                    0,
                )
                or 0
            )
            for experience in experiences
        ]

        average_attempts = round(
            sum(attempts)
            / len(attempts),
            2,
        )

        average_retries = round(
            sum(retries)
            / len(retries),
            2,
        )

        lessons = self._extract_lessons(
            experiences
        )

        errors = self._extract_errors(
            experiences
        )

        # ------------------------------------------------------------
        # Reliability classification
        # ------------------------------------------------------------

        if (
            success_rate
            >= STABLE_SUCCESS_THRESHOLD
        ):

            reliability = "reliable"

            strategy = "reuse_success"

            recommendation = (
                "Prefer previously successful "
                "execution patterns when applicable."
            )

            self.statistics[
                "stable_success_patterns"
            ] += 1

        elif (
            failure_rate
            >= STABLE_FAILURE_THRESHOLD
        ):

            reliability = "unreliable"

            strategy = "avoid_or_verify"

            recommendation = (
                "Avoid repeating known failure patterns "
                "and require verification."
            )

            self.statistics[
                "stable_failure_patterns"
            ] += 1

        else:

            reliability = "mixed"

            strategy = "verify"

            recommendation = (
                "Use normal execution with "
                "bounded verification and retries."
            )

        memory_id = _fingerprint(
            task_type,
            action_name,
            task_name,
        )

        return ConsolidatedMemory(
            memory_id=memory_id,
            task_type=task_type,
            action_name=action_name,
            task_name=task_name,
            sample_count=sample_count,
            success_count=success_count,
            failure_count=failure_count,
            success_rate=success_rate,
            failure_rate=failure_rate,
            average_attempts=average_attempts,
            average_retries=average_retries,
            strategy=strategy,
            reliability=reliability,
            lessons=lessons,
            common_errors=errors,
            recommendation=recommendation,
        )

    # ========================================================================
    # MEMORY STORAGE
    # ========================================================================

    def _store_memory(
        self,
        memory: ConsolidatedMemory,
    ) -> None:
        """
        Store/update bounded in-memory consolidated records.
        """

        self._memory = [
            item
            for item in self._memory
            if item.memory_id
            != memory.memory_id
        ]

        self._memory.append(
            memory
        )

        if (
            len(self._memory)
            > self.max_memory_records
        ):

            overflow = (
                len(self._memory)
                - self.max_memory_records
            )

            del self._memory[
                :overflow
            ]

        self.statistics[
            "memory_records"
        ] = len(self._memory)

    async def _store_database(
        self,
        memory: ConsolidatedMemory,
    ) -> bool:
        """
        Store consolidated memory in MongoDB if available.
        """

        if self.collection is None:
            return False

        try:

            document = memory.to_dict()

            await self.collection.update_one(
                {
                    "memory_id":
                        memory.memory_id
                },
                {
                    "$set": document
                },
                upsert=True,
            )

            return True

        except Exception:

            logger.exception(
                "[ExperienceConsolidator] "
                "MongoDB storage failed."
            )

            return False

    # ========================================================================
    # KNOWLEDGE FORWARDING
    # ========================================================================

    async def _forward_knowledge(
        self,
        memory: ConsolidatedMemory,
    ) -> None:
        """
        Forward durable lessons to existing learning infrastructure.

        This is intentionally best-effort.
        """

        knowledge_text = (
            f"Execution pattern for "
            f"{memory.task_type or 'unknown task'}"
        )

        if memory.action_name:
            knowledge_text += (
                f" using action "
                f"{memory.action_name}"
            )

        knowledge_text += (
            f": reliability={memory.reliability}, "
            f"success_rate={memory.success_rate}, "
            f"failure_rate={memory.failure_rate}. "
        )

        knowledge_text += (
            memory.recommendation
        )

        if memory.lessons:

            knowledge_text += (
                " Lessons: "
                + " | ".join(
                    memory.lessons
                )
            )

        # Existing LearningEngine
        if self.learning_engine is not None:

            try:

                learn_method = getattr(
                    self.learning_engine,
                    "learn",
                    None,
                )

                if learn_method is not None:

                    await learn_method(
                        knowledge_text,
                        source=(
                            "consolidated_experience"
                        ),
                    )

                    self.statistics[
                        "knowledge_forwarded"
                    ] += 1

            except Exception:

                logger.exception(
                    "[ExperienceConsolidator] "
                    "LearningEngine forwarding failed."
                )

        # Existing KnowledgeDatabase
        if self.knowledge_database is not None:

            try:

                add_method = getattr(
                    self.knowledge_database,
                    "add",
                    None,
                )

                if add_method is None:
                    add_method = getattr(
                        self.knowledge_database,
                        "store",
                        None,
                    )

                if add_method is not None:

                    result = add_method(
                        knowledge_text
                    )

                    if hasattr(
                        result,
                        "__await__",
                    ):
                        await result

            except Exception:

                logger.exception(
                    "[ExperienceConsolidator] "
                    "KnowledgeDatabase forwarding failed."
                )

    # ========================================================================
    # PUBLIC API
    # ========================================================================

    async def consolidate(
        self,
        experiences: Optional[
            List[Dict[str, Any]]
        ] = None,
        forward_knowledge: bool = True,
    ) -> List[ConsolidatedMemory]:
        """
        Consolidate recent experiences.

        If `experiences` is omitted, recent records are loaded from
        ExperienceEngine.
        """

        if experiences is None:

            experiences = (
                await self._load_experiences()
            )

        if not experiences:
            return []

        experiences = experiences[
            -MAX_EXPERIENCES:
        ]

        groups = self._group_experiences(
            experiences
        )

        consolidated = []

        for group in groups.values():

            memory = self._consolidate_group(
                group
            )

            if memory is None:
                continue

            self._store_memory(
                memory
            )

            await self._store_database(
                memory
            )

            if forward_knowledge:
                await self._forward_knowledge(
                    memory
                )

            consolidated.append(
                memory
            )

        self.statistics[
            "consolidations"
        ] += 1

        self.statistics[
            "patterns_created"
        ] += len(
            consolidated
        )

        return consolidated

    # ========================================================================
    # RETRIEVAL
    # ========================================================================

    async def get(
        self,
        task_type: str = "",
        action_name: str = "",
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve consolidated patterns.
        """

        limit = max(
            1,
            min(
                int(limit),
                MAX_MEMORY_RECORDS,
            ),
        )

        task_type = _text(
            task_type,
            100,
        ).lower()

        action_name = _text(
            action_name,
            300,
        ).lower()

        results = []

        for memory in reversed(
            self._memory
        ):

            if (
                task_type
                and memory.task_type.lower()
                != task_type
            ):
                continue

            if (
                action_name
                and memory.action_name.lower()
                != action_name
            ):
                continue

            results.append(
                memory.to_dict()
            )

            if len(results) >= limit:
                break

        if (
            self.collection is not None
            and len(results) < limit
        ):

            query: Dict[str, Any] = {}

            if task_type:
                query[
                    "task_type"
                ] = task_type

            if action_name:
                query[
                    "action_name"
                ] = action_name

            try:

                cursor = (
                    self.collection
                    .find(query)
                    .sort(
                        "updated_at",
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
                        not in results
                    ):
                        results.append(
                            document
                        )

                    if len(results) >= limit:
                        break

            except Exception:

                logger.exception(
                    "[ExperienceConsolidator] "
                    "Consolidated memory retrieval failed."
                )

        return results[:limit]

    # ========================================================================
    # HEALTH
    # ========================================================================

    def health(self) -> Dict[str, Any]:
        return {
            "component": (
                "experience_consolidator"
            ),
            "status": "healthy",
            "experience_engine_available": (
                self.experience_engine is not None
            ),
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
        return {
            "component": (
                "ExperienceConsolidator"
            ),
            "purpose": (
                "Convert repeated execution "
                "experiences into durable patterns."
            ),
            "llm_required": False,
            "execution_side_effects": False,
            "bounded_experiences": MAX_EXPERIENCES,
            "bounded_memory": (
                self.max_memory_records
            ),
            "features": [
                "experience grouping",
                "success pattern detection",
                "failure pattern detection",
                "lesson consolidation",
                "error frequency analysis",
                "reliability classification",
                "knowledge forwarding",
                "bounded persistent storage",
            ],
        }