from dataclasses import dataclass, field
from datetime import datetime, timezone
import copy
import logging
import uuid
from typing import List, Optional, Dict, Any

logger = logging.getLogger("aria")


def _utcnow() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


def _parse_datetime(value: Any) -> datetime:
    """Safely restore persisted timestamps, including legacy naive values."""
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str):
        try:
            result = datetime.fromisoformat(value)
        except (TypeError, ValueError):
            return _utcnow()
    else:
        return _utcnow()

    if result.tzinfo is None:
        return result.replace(tzinfo=timezone.utc)

    return result.astimezone(timezone.utc)


def _clamp_progress(value: Any) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = 0.0

    if numeric != numeric:
        numeric = 0.0

    return max(0.0, min(100.0, numeric))


@dataclass
class SubGoal:
    title: str
    status: str = "pending"
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)


@dataclass
class Goal:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    title: str = ""
    status: str = "active"
    progress: float = 0.0
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)
    subgoals: List[SubGoal] = field(default_factory=list)


class GoalManager:
    """
    Phase-11 autonomous goal lifecycle manager.

    CognitiveCore remains the orchestration owner. GoalManager owns only
    goal state, persistence, progress and goal-scoped observations.

    No LLM, tool execution or local intelligence is introduced here.
    """

    VERSION = "11.10"
    MAX_GOALS = 200
    MAX_SUBGOALS_PER_GOAL = 50
    VALID_STATUSES = {
        "active",
        "paused",
        "completed",
        "failed",
        "cancelled",
    }
    VALID_SUBGOAL_STATUSES = {
        "pending",
        "active",
        "completed",
        "failed",
        "cancelled",
        "paused",
    }

    def __init__(self, working_memory=None):
        self.goals: List[Goal] = []
        self.working_memory = working_memory
        self._restore_goals()

    # =========================================================
    # NORMALIZATION / SAFETY
    # =========================================================

    @staticmethod
    def _safe_metadata(value: Any) -> Dict[str, Any]:
        if not isinstance(value, dict):
            return {}
        try:
            return copy.deepcopy(value)
        except Exception:
            return dict(value)

    @classmethod
    def _normalize_status(
        cls,
        value: Any,
        default: str = "active",
    ) -> str:
        status = str(value or default).strip().lower()
        return (
            status
            if status in cls.VALID_STATUSES
            else default
        )

    @classmethod
    def _normalize_subgoal_status(
        cls,
        value: Any,
        default: str = "pending",
    ) -> str:
        status = str(value or default).strip().lower()
        return (
            status
            if status in cls.VALID_SUBGOAL_STATUSES
            else default
        )

    @staticmethod
    def _normalize_title(title: Any) -> str:
        return str(title or "").strip()

    @staticmethod
    def _touch_goal(goal: Goal):
        goal.updated_at = _utcnow()

    @staticmethod
    def _touch_subgoal(subgoal: SubGoal):
        subgoal.updated_at = _utcnow()

    def _trim_goals(self):
        if len(self.goals) <= self.MAX_GOALS:
            return

        # Keep active/paused goals first, then newest historical goals.
        self.goals.sort(
            key=lambda goal: (
                goal.status not in {"active", "paused"},
                goal.updated_at,
            ),
            reverse=False,
        )

        retained = self.goals[:self.MAX_GOALS]
        self.goals = retained

    # =========================================================
    # PERSISTENCE
    # =========================================================

    def _persist_goal(self, goal: Goal):
        """
        Best-effort persistence through semantic memory.

        Persistence failures never break the cognitive pipeline.
        """
        if self.working_memory is None:
            return

        try:
            semantic = self.working_memory.semantic()

            if semantic is None:
                return

            metadata = self._safe_metadata(
                goal.metadata
            )

            metadata.update(
                {
                    "goal_state": "persisted",
                    "status": goal.status,
                    "progress": goal.progress,
                    "created_at": goal.created_at.isoformat(),
                    "updated_at": goal.updated_at.isoformat(),
                    "subgoals": [
                        {
                            "title": subgoal.title,
                            "status": subgoal.status,
                            "metadata": self._safe_metadata(
                                subgoal.metadata
                            ),
                            "created_at": subgoal.created_at.isoformat(),
                            "updated_at": subgoal.updated_at.isoformat(),
                        }
                        for subgoal in goal.subgoals[
                            : self.MAX_SUBGOALS_PER_GOAL
                        ]
                    ],
                }
            )

            semantic.add_node(
                node_id=goal.id,
                node_type="goal",
                value=goal.title,
                metadata=metadata,
            )

            logger.debug(
                "[GoalManager] Persisted goal: %s (%s)",
                goal.title,
                goal.id,
            )

        except Exception:
            logger.exception(
                "[GoalManager] Failed to persist goal: %s",
                goal.title,
            )

    def _restore_goals(self):
        """
        Restore only explicitly persisted goal nodes.

        Supports dict/list node containers and legacy naive timestamps.
        """
        if self.working_memory is None:
            return

        try:
            semantic = self.working_memory.semantic()

            if semantic is None:
                return

            nodes = getattr(
                semantic,
                "nodes",
                None,
            )

            if isinstance(nodes, dict):
                iterable = list(nodes.values())
            elif isinstance(nodes, list):
                iterable = list(nodes)
            else:
                return

            restored = 0

            for node in iterable:
                if restored >= self.MAX_GOALS:
                    break

                try:
                    if isinstance(node, dict):
                        node_type = node.get("node_type")
                        metadata = node.get(
                            "metadata",
                            {},
                        )
                        node_id = (
                            node.get("node_id")
                            or node.get("id")
                        )
                        title = (
                            node.get("value")
                            or node.get("title")
                        )
                    else:
                        node_type = getattr(
                            node,
                            "node_type",
                            None,
                        )
                        metadata = getattr(
                            node,
                            "metadata",
                            {},
                        )
                        node_id = (
                            getattr(
                                node,
                                "node_id",
                                None,
                            )
                            or getattr(
                                node,
                                "id",
                                None,
                            )
                        )
                        title = (
                            getattr(
                                node,
                                "value",
                                None,
                            )
                            or getattr(
                                node,
                                "title",
                                None,
                            )
                        )

                    if node_type != "goal":
                        continue

                    if not isinstance(metadata, dict):
                        continue

                    if metadata.get(
                        "goal_state"
                    ) != "persisted":
                        continue

                    title = self._normalize_title(
                        title
                    )

                    if not node_id or not title:
                        continue

                    goal_id = str(node_id)

                    if any(
                        goal.id == goal_id
                        for goal in self.goals
                    ):
                        continue

                    subgoals: List[SubGoal] = []

                    raw_subgoals = metadata.get(
                        "subgoals",
                        [],
                    )

                    if isinstance(
                        raw_subgoals,
                        list,
                    ):
                        for item in raw_subgoals[
                            : self.MAX_SUBGOALS_PER_GOAL
                        ]:
                            if not isinstance(
                                item,
                                dict,
                            ):
                                continue

                            subgoal_title = (
                                self._normalize_title(
                                    item.get(
                                        "title",
                                        "",
                                    )
                                )
                            )

                            if not subgoal_title:
                                continue

                            subgoals.append(
                                SubGoal(
                                    title=subgoal_title,
                                    status=self._normalize_subgoal_status(
                                        item.get(
                                            "status",
                                            "pending",
                                        )
                                    ),
                                    metadata=self._safe_metadata(
                                        item.get(
                                            "metadata",
                                            {},
                                        )
                                    ),
                                    created_at=_parse_datetime(
                                        item.get(
                                            "created_at"
                                        )
                                    ),
                                    updated_at=_parse_datetime(
                                        item.get(
                                            "updated_at"
                                        )
                                    ),
                                )
                            )

                    goal_metadata = {
                        key: copy.deepcopy(value)
                        for key, value in metadata.items()
                        if key not in {
                            "goal_state",
                            "status",
                            "progress",
                            "created_at",
                            "updated_at",
                            "subgoals",
                        }
                    }

                    goal = Goal(
                        id=goal_id,
                        title=title,
                        status=self._normalize_status(
                            metadata.get(
                                "status",
                                "active",
                            )
                        ),
                        progress=_clamp_progress(
                            metadata.get(
                                "progress",
                                0.0,
                            )
                        ),
                        created_at=_parse_datetime(
                            metadata.get(
                                "created_at"
                            )
                        ),
                        updated_at=_parse_datetime(
                            metadata.get(
                                "updated_at"
                            )
                        ),
                        metadata=self._safe_metadata(
                            goal_metadata
                        ),
                        subgoals=subgoals,
                    )

                    self.goals.append(goal)
                    restored += 1

                except Exception:
                    logger.exception(
                        "[GoalManager] Failed to restore one goal."
                    )

            if restored:
                logger.info(
                    "[GoalManager] Restored %d goal(s).",
                    restored,
                )

        except Exception:
            logger.exception(
                "[GoalManager] Goal restoration skipped."
            )

    # =========================================================
    # SUBGOAL GENERATION
    # =========================================================

    def generate_subgoals(
        self,
        title: str,
    ) -> List[SubGoal]:
        title_lower = title.lower()

        if "weather app" in title_lower:
            result = [
                SubGoal("Research libraries"),
                SubGoal("Design roadmap"),
                SubGoal("Create backend"),
                SubGoal("Create frontend"),
                SubGoal("Deploy application"),
                SubGoal("Testing"),
            ]

        elif "telegram ai" in title_lower:
            result = [
                SubGoal("Research architecture"),
                SubGoal("Memory system"),
                SubGoal("Reasoning engine"),
                SubGoal("Planner"),
                SubGoal("Deployment"),
                SubGoal("Optimization"),
            ]

        else:
            result = [
                SubGoal("Understand objective"),
                SubGoal("Plan required actions"),
                SubGoal("Execute planned actions"),
                SubGoal("Verify results"),
            ]

        return result[
            : self.MAX_SUBGOALS_PER_GOAL
        ]

    # =========================================================
    # GOAL CREATION
    # =========================================================

    def add_goal(
        self,
        title: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Goal]:
        title = self._normalize_title(title)

        if not title:
            return None

        active = self.current_goal()

        if active and active.title.lower() == title.lower():
            return active

        goal = Goal(
            title=title,
            metadata=self._safe_metadata(
                metadata
            ),
            subgoals=self.generate_subgoals(
                title
            ),
        )

        self.goals.append(goal)
        self._trim_goals()

        logger.info(
            "[GoalManager] Created new goal: %s (%s)",
            goal.title,
            goal.id,
        )

        self._persist_goal(goal)

        return goal

    create_goal = add_goal

    # =========================================================
    # GOAL LOOKUP
    # =========================================================

    def get_goal(
        self,
        goal_id: str,
    ) -> Optional[Goal]:
        if not goal_id:
            return None

        target = str(goal_id)

        for goal in self.goals:
            if goal.id == target:
                return goal

        return None

    def current_goal(self) -> Optional[Goal]:
        for goal in reversed(self.goals):
            if goal.status == "active":
                return goal

        return None

    def list_active_goals(self) -> List[Goal]:
        return [
            goal
            for goal in self.goals
            if goal.status == "active"
        ]

    # =========================================================
    # GOAL LIFECYCLE
    # =========================================================

    def complete_goal(
        self,
        goal_id: str,
    ) -> Optional[Goal]:
        goal = self.get_goal(goal_id)

        if not goal:
            return None

        goal.status = "completed"
        goal.progress = 100.0
        self._touch_goal(goal)

        # Any unfinished subgoals become completed when the parent
        # goal is explicitly completed.
        for subgoal in goal.subgoals:
            if subgoal.status not in {
                "completed",
                "cancelled",
            }:
                subgoal.status = "completed"
                self._touch_subgoal(subgoal)

        self._persist_goal(goal)

        logger.info(
            "[GoalManager] Completed goal: %s",
            goal.title,
        )

        return goal

    def pause_goal(
        self,
        goal_id: str,
    ) -> Optional[Goal]:
        goal = self.get_goal(goal_id)

        if not goal:
            return None

        if goal.status in {
            "completed",
            "failed",
            "cancelled",
        }:
            return goal

        goal.status = "paused"
        self._touch_goal(goal)

        self._persist_goal(goal)

        return goal

    def resume_goal(
        self,
        goal_id: str,
    ) -> Optional[Goal]:
        goal = self.get_goal(goal_id)

        if not goal:
            return None

        if goal.status in {
            "completed",
            "cancelled",
        }:
            return goal

        goal.status = "active"
        self._touch_goal(goal)

        self._persist_goal(goal)

        return goal

    def fail_goal(
        self,
        goal_id: str,
        reason: str = "",
    ) -> Optional[Goal]:
        goal = self.get_goal(goal_id)

        if not goal:
            return None

        goal.status = "failed"
        self._touch_goal(goal)

        if reason:
            goal.metadata[
                "failure_reason"
            ] = str(reason)

        self._persist_goal(goal)

        return goal

    def cancel_goal(
        self,
        goal_id: str,
    ) -> Optional[Goal]:
        goal = self.get_goal(goal_id)

        if not goal:
            return None

        goal.status = "cancelled"
        self._touch_goal(goal)

        self._persist_goal(goal)

        return goal

    # =========================================================
    # PROGRESS
    # =========================================================

    def update_progress(
        self,
        goal_id: str,
        progress: Any,
    ) -> Optional[Goal]:
        goal = self.get_goal(goal_id)

        if not goal:
            return None

        goal.progress = _clamp_progress(
            progress
        )
        self._touch_goal(goal)

        if goal.progress >= 100.0:
            return self.complete_goal(
                goal.id
            )

        self._persist_goal(goal)

        logger.info(
            "[GoalManager] Updated goal '%s' progress to %.1f%%",
            goal.title,
            goal.progress,
        )

        return goal

    # =========================================================
    # SUBGOALS
    # =========================================================

    def next_subgoal(
        self,
        goal: Optional[Goal] = None,
    ) -> Optional[SubGoal]:
        target = goal or self.current_goal()

        if not target:
            return None

        if target.status != "active":
            return None

        for subgoal in target.subgoals:
            if subgoal.status == "pending":
                return subgoal

        return None

    get_next_subgoal = next_subgoal

    def complete_subgoal(
        self,
        goal: Goal,
        title: str,
    ) -> Optional[SubGoal]:
        if not isinstance(
            goal,
            Goal,
        ):
            return None

        target_title = self._normalize_title(
            title
        ).lower()

        if not target_title:
            return None

        for subgoal in goal.subgoals:
            if (
                subgoal.title.lower()
                != target_title
            ):
                continue

            if subgoal.status == "completed":
                return subgoal

            subgoal.status = "completed"
            self._touch_subgoal(subgoal)

            completed = sum(
                1
                for item in goal.subgoals
                if item.status == "completed"
            )

            if goal.subgoals:
                goal.progress = _clamp_progress(
                    (
                        completed
                        / len(goal.subgoals)
                    )
                    * 100.0
                )

            self._touch_goal(goal)

            if goal.progress >= 100.0:
                self.complete_goal(
                    goal.id
                )
            else:
                self._persist_goal(goal)

            logger.info(
                "[GoalManager] Completed subgoal '%s' "
                "for goal '%s' | %.1f%%",
                subgoal.title,
                goal.title,
                goal.progress,
            )

            return subgoal

        return None

    def update_subgoal(
        self,
        goal_id: str,
        title: str,
        status: str,
    ) -> Optional[SubGoal]:
        goal = self.get_goal(goal_id)

        if not goal:
            return None

        target_title = self._normalize_title(
            title
        ).lower()

        normalized_status = (
            self._normalize_subgoal_status(
                status
            )
        )

        for subgoal in goal.subgoals:
            if (
                subgoal.title.lower()
                != target_title
            ):
                continue

            subgoal.status = normalized_status
            self._touch_subgoal(subgoal)

            if normalized_status == "completed":
                completed = sum(
                    1
                    for item in goal.subgoals
                    if item.status == "completed"
                )
                if goal.subgoals:
                    goal.progress = _clamp_progress(
                        (
                            completed
                            / len(goal.subgoals)
                        )
                        * 100.0
                    )

            self._touch_goal(goal)

            if goal.progress >= 100.0:
                self.complete_goal(
                    goal.id
                )
            else:
                self._persist_goal(goal)

            return subgoal

        return None

    # =========================================================
    # CONTEXT
    # =========================================================

    def get_goal_context(
        self,
        goal_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        goal = (
            self.get_goal(goal_id)
            if goal_id
            else self.current_goal()
        )

        if not goal:
            return None

        next_goal = self.next_subgoal(
            goal
        )

        return {
            "goal_id": goal.id,
            "title": goal.title,
            "goal_title": goal.title,
            "status": goal.status,
            "goal_status": goal.status,
            "progress": goal.progress,
            "subgoals": [
                {
                    "title": subgoal.title,
                    "status": subgoal.status,
                    "metadata": self._safe_metadata(
                        subgoal.metadata
                    ),
                }
                for subgoal in goal.subgoals
            ],
            "next_subgoal": (
                next_goal.title
                if next_goal
                else None
            ),
            "metadata": self._safe_metadata(
                goal.metadata
            ),
            "manager_version": self.VERSION,
        }

    # =========================================================
    # OBSERVATION
    # =========================================================

    async def observe(
        self,
        query,
        context=None,
    ):
        """
        Observe explicit goal-related user signals.

        This method intentionally avoids inferring arbitrary goals from
        unrelated conversation and performs only deterministic state
        transitions.
        """
        query_lower = str(
            query or ""
        ).lower().strip()

        if not query_lower:
            return self.current_goal()

        if query_lower in {
            "finished",
            "done",
            "complete",
            "completed",
            "it's done",
            "it is done",
        }:
            active = self.current_goal()

            if active:
                return self.complete_goal(
                    active.id
                )

            return None

        building_phrases = [
            "i'm building",
            "im building",
            "i am building",
            "i'm creating",
            "im creating",
            "i am creating",
            "i'm making",
            "im making",
            "i am making",
            "i want to build",
            "i want to create",
            "let's build",
            "lets build",
            "start a project",
        ]

        matched_title = None

        for phrase in building_phrases:
            if phrase not in query_lower:
                continue

            idx = (
                query_lower.find(
                    phrase
                )
                + len(phrase)
            )

            subject = str(
                query[idx:]
            ).strip(
                " .!?"
            )

            if subject:
                matched_title = (
                    "Build "
                    + subject[:1].upper()
                    + subject[1:]
                )
            else:
                matched_title = (
                    "New Project Goal"
                )

            break

        if matched_title:
            return self.add_goal(
                matched_title
            )

        active = self.current_goal()

        if active:
            mapping = {
                "roadmap": "Design roadmap",
                "library": "Research libraries",
                "libraries": "Research libraries",
                "backend": "Create backend",
                "frontend": "Create frontend",
                "deploy": "Deploy application",
                "test": "Testing",
            }

            for keyword, task in mapping.items():
                if keyword in query_lower:
                    self.complete_subgoal(
                        active,
                        task,
                    )
                    break

        return active

    # =========================================================
    # SERIALIZATION / STATUS
    # =========================================================

    def serialize_goal(
        self,
        goal: Goal,
    ) -> Dict[str, Any]:
        if not isinstance(
            goal,
            Goal,
        ):
            return {}

        return {
            "id": goal.id,
            "title": goal.title,
            "status": goal.status,
            "progress": goal.progress,
            "created_at": goal.created_at.isoformat(),
            # Preserve the legacy typo key for compatibility.
            "created_z": goal.created_at.isoformat(),
            "updated_at": goal.updated_at.isoformat(),
            "metadata": self._safe_metadata(
                goal.metadata
            ),
            "subgoals": [
                {
                    "title": subgoal.title,
                    "status": subgoal.status,
                    "metadata": self._safe_metadata(
                        subgoal.metadata
                    ),
                    "created_at": subgoal.created_at.isoformat(),
                    "updated_at": subgoal.updated_at.isoformat(),
                }
                for subgoal in goal.subgoals
            ],
        }

    def list_goals(self) -> List[Dict[str, Any]]:
        return [
            self.serialize_goal(goal)
            for goal in self.goals
        ]

    def health(self) -> Dict[str, Any]:
        return {
            "status": "healthy",
            "version": self.VERSION,
            "goal_count": len(self.goals),
            "active_goals": len(
                self.list_active_goals()
            ),
            "current_goal_id": (
                self.current_goal().id
                if self.current_goal()
                else None
            ),
        }
