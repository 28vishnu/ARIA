"""
ARIA Goal / Intent Manager
==========================

Phase 1 - Step 16

Provides a deterministic goal and intent management layer for ARIA.

Responsibilities
----------------
- represent user goals
- normalize incoming requests
- classify broad intent categories
- track goal lifecycle
- maintain priorities
- maintain constraints
- maintain parent/child goals
- identify active goals
- mark goals completed/failed/cancelled
- provide planner-friendly goal context

Design constraints
------------------
- no LLM dependency
- no task execution
- bounded memory
- deterministic fallback classification
- safe to use before the planning layer
"""

from __future__ import annotations

import hashlib
import logging
import re

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


logger = logging.getLogger("aria")


# ============================================================================
# CONSTANTS
# ============================================================================

MAX_GOALS = 100

MAX_TEXT_LENGTH = 4000
MAX_CONSTRAINTS = 20
MAX_TAGS = 20
MAX_CHILDREN = 20

VALID_STATUSES = {
    "pending",
    "active",
    "blocked",
    "completed",
    "failed",
    "cancelled",
}

VALID_PRIORITIES = {
    "low",
    "normal",
    "high",
    "critical",
}


# ============================================================================
# HELPERS
# ============================================================================

def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _text(
    value: Any,
    limit: int = MAX_TEXT_LENGTH,
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
    normalized = "|".join(
        _text(
            value,
            1000,
        ).lower()
        for value in values
    )

    return hashlib.sha256(
        normalized.encode(
            "utf-8",
            errors="ignore",
        )
    ).hexdigest()[:24]


def _bounded_list(
    values: Any,
    limit: int,
    item_limit: int = 500,
) -> List[str]:
    if values is None:
        return []

    if isinstance(values, str):
        values = [
            values
        ]

    if not isinstance(
        values,
        (list, tuple, set),
    ):
        return []

    result = []

    for value in values:

        value = _text(
            value,
            item_limit,
        )

        if not value:
            continue

        if value in result:
            continue

        result.append(
            value
        )

        if len(result) >= limit:
            break

    return result


# ============================================================================
# DATA MODEL
# ============================================================================

@dataclass
class Goal:
    """
    Structured ARIA goal.
    """

    goal_id: str

    request: str

    objective: str = ""

    intent: str = "general"

    status: str = "pending"

    priority: str = "normal"

    parent_goal_id: Optional[str] = None

    child_goal_ids: List[str] = field(
        default_factory=list
    )

    constraints: List[str] = field(
        default_factory=list
    )

    tags: List[str] = field(
        default_factory=list
    )

    success_criteria: List[str] = field(
        default_factory=list
    )

    context: Dict[str, Any] = field(
        default_factory=dict
    )

    progress: float = 0.0

    created_at: datetime = field(
        default_factory=_utc_now
    )

    updated_at: datetime = field(
        default_factory=_utc_now
    )

    completed_at: Optional[datetime] = None

    failure_reason: str = ""

    cancellation_reason: str = ""

    metadata: Dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "goal_id": self.goal_id,
            "request": self.request,
            "objective": self.objective,
            "intent": self.intent,
            "status": self.status,
            "priority": self.priority,
            "parent_goal_id": self.parent_goal_id,
            "child_goal_ids": list(
                self.child_goal_ids
            ),
            "constraints": list(
                self.constraints
            ),
            "tags": list(
                self.tags
            ),
            "success_criteria": list(
                self.success_criteria
            ),
            "context": dict(
                self.context
            ),
            "progress": self.progress,
            "created_at": (
                self.created_at.isoformat()
            ),
            "updated_at": (
                self.updated_at.isoformat()
            ),
            "completed_at": (
                self.completed_at.isoformat()
                if self.completed_at
                else None
            ),
            "failure_reason": (
                self.failure_reason
            ),
            "cancellation_reason": (
                self.cancellation_reason
            ),
            "metadata": dict(
                self.metadata
            ),
        }


# ============================================================================
# GOAL MANAGER
# ============================================================================

class GoalManager:
    """
    Manages the lifecycle and structure of ARIA goals.

    This component intentionally does not execute goals.
    It prepares structured objectives for the planning/orchestration layer.
    """

    INTENT_KEYWORDS = {
        "coding": {
            "code",
            "coding",
            "program",
            "programming",
            "script",
            "debug",
            "debugging",
            "implement",
            "implementation",
            "function",
            "class",
            "api",
            "repository",
            "repo",
            "software",
            "application",
            "app",
        },
        "information": {
            "what",
            "why",
            "how",
            "explain",
            "meaning",
            "define",
            "tell",
            "information",
            "learn",
            "understand",
            "research",
        },
        "search": {
            "search",
            "find",
            "look",
            "lookup",
            "latest",
            "news",
            "web",
            "online",
        },
        "creation": {
            "create",
            "make",
            "build",
            "generate",
            "design",
            "write",
            "draft",
            "prepare",
        },
        "editing": {
            "edit",
            "modify",
            "change",
            "update",
            "replace",
            "rewrite",
            "fix",
            "improve",
        },
        "automation": {
            "automate",
            "automation",
            "schedule",
            "scheduled",
            "monitor",
            "remind",
            "reminder",
            "watch",
            "periodically",
        },
        "analysis": {
            "analyze",
            "analysis",
            "compare",
            "comparison",
            "evaluate",
            "review",
            "inspect",
            "check",
            "calculate",
        },
        "navigation": {
            "open",
            "launch",
            "go",
            "navigate",
            "visit",
            "website",
            "page",
        },
        "communication": {
            "send",
            "message",
            "email",
            "reply",
            "contact",
            "notify",
        },
    }

    def __init__(
        self,
        max_goals: int = MAX_GOALS,
        storage=None,
    ):
        self.max_goals = max(
            10,
            int(max_goals),
        )

        self.storage = storage

        self._goals: Dict[
            str,
            Goal,
        ] = {}

        self._active_goal_id: Optional[
            str
        ] = None

        self.statistics = {
            "created": 0,
            "activated": 0,
            "completed": 0,
            "failed": 0,
            "cancelled": 0,
            "blocked": 0,
            "updated": 0,
        }

    # ========================================================================
    # INTENT CLASSIFICATION
    # ========================================================================

    def classify_intent(
        self,
        request: str,
    ) -> str:
        """
        Deterministically classify a broad user intent.

        This is intentionally lightweight.

        A later LLM/router can provide a richer classification,
        but the GoalManager always has a working fallback.
        """

        request = _text(
            request,
            MAX_TEXT_LENGTH,
        )

        if not request:
            return "general"

        words = set(
            re.findall(
                r"[a-zA-Z0-9_+-]+",
                request.lower(),
            )
        )

        scores: Dict[
            str,
            int,
        ] = {}

        for intent, keywords in (
            self.INTENT_KEYWORDS.items()
        ):

            score = len(
                words.intersection(
                    keywords
                )
            )

            if score:
                scores[intent] = score

        if not scores:
            return "general"

        # Deterministic tie-breaking.
        priority_order = [
            "coding",
            "automation",
            "communication",
            "editing",
            "creation",
            "search",
            "analysis",
            "navigation",
            "information",
        ]

        best_intent = "general"
        best_score = 0

        for intent in priority_order:

            score = scores.get(
                intent,
                0,
            )

            if score > best_score:
                best_score = score
                best_intent = intent

        return best_intent

    # ========================================================================
    # OBJECTIVE NORMALIZATION
    # ========================================================================

    def normalize_objective(
        self,
        request: str,
    ) -> str:
        """
        Produce a concise objective from the raw request.

        This is deliberately conservative and does not attempt
        semantic rewriting.
        """

        request = _text(
            request,
            MAX_TEXT_LENGTH,
        )

        request = re.sub(
            r"\s+",
            " ",
            request,
        ).strip()

        if not request:
            return ""

        # Remove common conversational prefixes.
        prefixes = (
            "please ",
            "can you ",
            "could you ",
            "would you ",
            "i want you to ",
            "i need you to ",
            "help me ",
        )

        lowered = request.lower()

        for prefix in prefixes:

            if lowered.startswith(prefix):

                request = request[
                    len(prefix):
                ].strip()

                break

        if not request:
            return ""

        return request

    # ========================================================================
    # GOAL CREATION
    # ========================================================================

    def create_goal(
        self,
        request: str,
        objective: str = "",
        intent: str = "",
        priority: str = "normal",
        constraints: Optional[
            List[str]
        ] = None,
        tags: Optional[
            List[str]
        ] = None,
        success_criteria: Optional[
            List[str]
        ] = None,
        context: Optional[
            Dict[str, Any]
        ] = None,
        parent_goal_id: Optional[
            str
        ] = None,
        metadata: Optional[
            Dict[str, Any]
        ] = None,
    ) -> Goal:
        """
        Create and register a new goal.
        """

        request = _text(
            request,
            MAX_TEXT_LENGTH,
        )

        if not request:
            raise ValueError(
                "Goal request cannot be empty."
            )

        objective = (
            _text(
                objective,
                MAX_TEXT_LENGTH,
            )
            or self.normalize_objective(
                request
            )
        )

        intent = (
            _text(
                intent,
                100,
            ).lower()
            or self.classify_intent(
                request
            )
        )

        priority = (
            _text(
                priority,
                50,
            ).lower()
        )

        if priority not in VALID_PRIORITIES:
            priority = "normal"

        goal_id = _fingerprint(
            request,
            objective,
            _utc_now().timestamp(),
        )

        goal = Goal(
            goal_id=goal_id,
            request=request,
            objective=objective,
            intent=intent,
            priority=priority,
            parent_goal_id=(
                parent_goal_id
                if parent_goal_id
                else None
            ),
            constraints=_bounded_list(
                constraints,
                MAX_CONSTRAINTS,
            ),
            tags=_bounded_list(
                tags,
                MAX_TAGS,
            ),
            success_criteria=_bounded_list(
                success_criteria,
                MAX_CONSTRAINTS,
            ),
            context=dict(
                context or {}
            ),
            metadata=dict(
                metadata or {}
            ),
        )

        self._goals[
            goal_id
        ] = goal

        self.statistics[
            "created"
        ] += 1

        # Connect to parent.
        if parent_goal_id:

            parent = self._goals.get(
                parent_goal_id
            )

            if parent is not None:

                if (
                    goal_id
                    not in parent.child_goal_ids
                ):

                    if (
                        len(
                            parent.child_goal_ids
                        )
                        < MAX_CHILDREN
                    ):
                        parent.child_goal_ids.append(
                            goal_id
                        )

                        parent.updated_at = (
                            _utc_now()
                        )

        self._enforce_limit()

        return goal

    # ========================================================================
    # GOAL RETRIEVAL
    # ========================================================================

    def get(
        self,
        goal_id: str,
    ) -> Optional[Goal]:
        return self._goals.get(
            _text(
                goal_id,
                200,
            )
        )

    def active_goal(
        self,
    ) -> Optional[Goal]:
        if not self._active_goal_id:
            return None

        return self._goals.get(
            self._active_goal_id
        )

    def list_goals(
        self,
        status: Optional[
            str
        ] = None,
        limit: int = 20,
    ) -> List[Goal]:
        """
        Return goals newest first.
        """

        limit = max(
            1,
            min(
                int(limit),
                self.max_goals,
            ),
        )

        status = (
            status.lower()
            if isinstance(
                status,
                str,
            )
            else None
        )

        goals = list(
            self._goals.values()
        )

        goals.sort(
            key=lambda item: (
                item.updated_at,
                item.created_at,
            ),
            reverse=True,
        )

        results = []

        for goal in goals:

            if (
                status
                and goal.status
                != status
            ):
                continue

            results.append(
                goal
            )

            if len(results) >= limit:
                break

        return results

    # ========================================================================
    # ACTIVATION
    # ========================================================================

    def activate(
        self,
        goal_id: str,
    ) -> Goal:
        """
        Mark a goal active.

        Only one goal is treated as the primary active goal.
        """

        goal = self.get(
            goal_id
        )

        if goal is None:
            raise KeyError(
                f"Unknown goal: {goal_id}"
            )

        if goal.status in {
            "completed",
            "cancelled",
        }:
            raise ValueError(
                "Completed/cancelled goals cannot be activated."
            )

        # Deactivate previous primary goal.
        if (
            self._active_goal_id
            and self._active_goal_id
            != goal_id
        ):

            previous = self._goals.get(
                self._active_goal_id
            )

            if (
                previous is not None
                and previous.status == "active"
            ):
                previous.status = "pending"
                previous.updated_at = (
                    _utc_now()
                )

        goal.status = "active"

        goal.updated_at = (
            _utc_now()
        )

        self._active_goal_id = (
            goal_id
        )

        self.statistics[
            "activated"
        ] += 1

        return goal

    # ========================================================================
    # PROGRESS
    # ========================================================================

    def update_progress(
        self,
        goal_id: str,
        progress: float,
    ) -> Goal:
        goal = self.get(
            goal_id
        )

        if goal is None:
            raise KeyError(
                f"Unknown goal: {goal_id}"
            )

        progress = max(
            0.0,
            min(
                1.0,
                float(progress),
            ),
        )

        goal.progress = round(
            progress,
            4,
        )

        goal.updated_at = (
            _utc_now()
        )

        self.statistics[
            "updated"
        ] += 1

        return goal

    # ========================================================================
    # STATUS MANAGEMENT
    # ========================================================================

    def complete(
        self,
        goal_id: str,
    ) -> Goal:
        goal = self.get(
            goal_id
        )

        if goal is None:
            raise KeyError(
                f"Unknown goal: {goal_id}"
            )

        goal.status = "completed"

        goal.progress = 1.0

        goal.completed_at = (
            _utc_now()
        )

        goal.updated_at = (
            _utc_now()
        )

        if (
            self._active_goal_id
            == goal_id
        ):
            self._active_goal_id = None

        self.statistics[
            "completed"
        ] += 1

        return goal

    def fail(
        self,
        goal_id: str,
        reason: str = "",
    ) -> Goal:
        goal = self.get(
            goal_id
        )

        if goal is None:
            raise KeyError(
                f"Unknown goal: {goal_id}"
            )

        goal.status = "failed"

        goal.failure_reason = _text(
            reason,
            2000,
        )

        goal.updated_at = (
            _utc_now()
        )

        if (
            self._active_goal_id
            == goal_id
        ):
            self._active_goal_id = None

        self.statistics[
            "failed"
        ] += 1

        return goal

    def block(
        self,
        goal_id: str,
        reason: str = "",
    ) -> Goal:
        goal = self.get(
            goal_id
        )

        if goal is None:
            raise KeyError(
                f"Unknown goal: {goal_id}"
            )

        goal.status = "blocked"

        if reason:
            goal.metadata[
                "blocked_reason"
            ] = _text(
                reason,
                2000,
            )

        goal.updated_at = (
            _utc_now()
        )

        self.statistics[
            "blocked"
        ] += 1

        return goal

    def unblock(
        self,
        goal_id: str,
    ) -> Goal:
        goal = self.get(
            goal_id
        )

        if goal is None:
            raise KeyError(
                f"Unknown goal: {goal_id}"
            )

        if goal.status == "blocked":
            goal.status = "pending"

        goal.updated_at = (
            _utc_now()
        )

        return goal

    def cancel(
        self,
        goal_id: str,
        reason: str = "",
    ) -> Goal:
        goal = self.get(
            goal_id
        )

        if goal is None:
            raise KeyError(
                f"Unknown goal: {goal_id}"
            )

        goal.status = "cancelled"

        goal.cancellation_reason = _text(
            reason,
            2000,
        )

        goal.updated_at = (
            _utc_now()
        )

        if (
            self._active_goal_id
            == goal_id
        ):
            self._active_goal_id = None

        self.statistics[
            "cancelled"
        ] += 1

        return goal

    # ========================================================================
    # CHILD GOALS
    # ========================================================================

    def add_child(
        self,
        parent_goal_id: str,
        request: str,
        **kwargs: Any,
    ) -> Goal:
        """
        Create a child goal linked to a parent.
        """

        parent = self.get(
            parent_goal_id
        )

        if parent is None:
            raise KeyError(
                f"Unknown parent goal: "
                f"{parent_goal_id}"
            )

        if (
            len(
                parent.child_goal_ids
            )
            >= MAX_CHILDREN
        ):
            raise ValueError(
                "Maximum child goals reached."
            )

        return self.create_goal(
            request=request,
            parent_goal_id=parent_goal_id,
            **kwargs,
        )

    def children(
        self,
        goal_id: str,
    ) -> List[Goal]:
        goal = self.get(
            goal_id
        )

        if goal is None:
            return []

        results = []

        for child_id in (
            goal.child_goal_ids
        ):

            child = self.get(
                child_id
            )

            if child is not None:
                results.append(
                    child
                )

        return results

    # ========================================================================
    # PLANNER CONTEXT
    # ========================================================================

    def planner_context(
        self,
        goal_id: Optional[
            str
        ] = None,
    ) -> Dict[str, Any]:
        """
        Return compact goal information suitable for the planner.
        """

        goal = (
            self.get(goal_id)
            if goal_id
            else self.active_goal()
        )

        if goal is None:
            return {
                "has_goal": False,
                "goal": None,
            }

        child_context = []

        for child in self.children(
            goal.goal_id
        ):

            child_context.append(
                {
                    "goal_id": child.goal_id,
                    "objective": child.objective,
                    "intent": child.intent,
                    "status": child.status,
                    "priority": child.priority,
                    "progress": child.progress,
                }
            )

        return {
            "has_goal": True,
            "goal": {
                "goal_id": goal.goal_id,
                "request": goal.request,
                "objective": goal.objective,
                "intent": goal.intent,
                "status": goal.status,
                "priority": goal.priority,
                "constraints": list(
                    goal.constraints
                ),
                "tags": list(
                    goal.tags
                ),
                "success_criteria": list(
                    goal.success_criteria
                ),
                "progress": goal.progress,
                "children": child_context,
                "context": dict(
                    goal.context
                ),
            },
        }

    # ========================================================================
    # REQUEST → GOAL
    # ========================================================================

    def from_request(
        self,
        request: str,
        *,
        priority: str = "normal",
        constraints: Optional[
            List[str]
        ] = None,
        tags: Optional[
            List[str]
        ] = None,
        success_criteria: Optional[
            List[str]
        ] = None,
        context: Optional[
            Dict[str, Any]
        ] = None,
    ) -> Goal:
        """
        Convert a raw user request into a structured goal.
        """

        return self.create_goal(
            request=request,
            objective=self.normalize_objective(
                request
            ),
            intent=self.classify_intent(
                request
            ),
            priority=priority,
            constraints=constraints,
            tags=tags,
            success_criteria=success_criteria,
            context=context,
        )

    # ========================================================================
    # LIMIT MANAGEMENT
    # ========================================================================

    def _enforce_limit(
        self,
    ) -> None:
        if (
            len(self._goals)
            <= self.max_goals
        ):
            return

        removable = [
            goal
            for goal in self._goals.values()
            if goal.status
            in {
                "completed",
                "cancelled",
                "failed",
            }
            and goal.goal_id
            != self._active_goal_id
        ]

        removable.sort(
            key=lambda item: (
                item.updated_at,
                item.created_at,
            )
        )

        while (
            len(self._goals)
            > self.max_goals
            and removable
        ):

            goal = removable.pop(
                0
            )

            self._goals.pop(
                goal.goal_id,
                None,
            )

    # ========================================================================
    # HEALTH / DESCRIPTION
    # ========================================================================

    def health(self) -> Dict[str, Any]:
        return {
            "component": "goal_manager",
            "status": "healthy",
            "goal_count": len(
                self._goals
            ),
            "active_goal_id": (
                self._active_goal_id
            ),
            "statistics": dict(
                self.statistics
            ),
        }

    def describe(self) -> Dict[str, Any]:
        return {
            "component": "GoalManager",
            "purpose": (
                "Manage structured user goals, "
                "intent and goal lifecycle."
            ),
            "llm_required": False,
            "execution_side_effects": False,
            "max_goals": self.max_goals,
            "supported_statuses": sorted(
                VALID_STATUSES
            ),
            "supported_priorities": sorted(
                VALID_PRIORITIES
            ),
            "features": [
                "request normalization",
                "intent classification",
                "goal creation",
                "goal activation",
                "progress tracking",
                "goal completion",
                "goal failure",
                "goal cancellation",
                "goal blocking",
                "parent-child goals",
                "planner context",
                "bounded goal storage",
            ],
        }