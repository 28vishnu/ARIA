from dataclasses import dataclass, field
from datetime import datetime
import uuid
import logging
from typing import List, Optional, Dict, Any

logger = logging.getLogger("aria")


@dataclass
class SubGoal:
    title: str
    status: str = "pending"
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Goal:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    title: str = ""
    status: str = "active"
    progress: float = 0.0
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)
    subgoals: List[SubGoal] = field(default_factory=list)


class GoalManager:

    def __init__(self, working_memory=None):
        self.goals: List[Goal] = []
        self.working_memory = working_memory

        # Restore previously persisted goals when possible.
        self._restore_goals()

    # =========================================================
    # PERSISTENCE
    # =========================================================

    def _persist_goal(self, goal: Goal):
        """
        Persist the complete goal state through semantic memory.

        Persistence is best-effort and must never break the
        cognitive pipeline.
        """
        if not self.working_memory:
            return

        try:
            semantic = self.working_memory.semantic()

            metadata = dict(goal.metadata or {})

            metadata.update({
                "goal_state": "persisted",
                "status": goal.status,
                "progress": goal.progress,
                "created_at": goal.created_at.isoformat(),
                "updated_at": goal.updated_at.isoformat(),
                "subgoals": [
                    {
                        "title": subgoal.title,
                        "status": subgoal.status,
                        "metadata": dict(subgoal.metadata or {}),
                        "created_at": subgoal.created_at.isoformat(),
                        "updated_at": subgoal.updated_at.isoformat(),
                    }
                    for subgoal in goal.subgoals
                ],
            })

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
        Restore persisted goals from semantic memory.

        Older goal nodes without complete goal_state metadata
        are safely ignored.
        """
        if not self.working_memory:
            return

        try:
            semantic = self.working_memory.semantic()

            nodes = getattr(semantic, "nodes", None)

            if isinstance(nodes, dict):
                iterable = nodes.values()
            elif isinstance(nodes, list):
                iterable = nodes
            else:
                return

            restored = 0

            for node in iterable:
                try:
                    if isinstance(node, dict):
                        node_type = node.get("node_type")
                        metadata = node.get("metadata", {})
                        node_id = node.get("node_id") or node.get("id")
                        title = node.get("value") or node.get("title")
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
                        node_id = getattr(
                            node,
                            "node_id",
                            None,
                        ) or getattr(
                            node,
                            "id",
                            None,
                        )
                        title = getattr(
                            node,
                            "value",
                            None,
                        ) or getattr(
                            node,
                            "title",
                            None,
                        )

                    if node_type != "goal":
                        continue

                    if not isinstance(metadata, dict):
                        continue

                    if metadata.get("goal_state") != "persisted":
                        continue

                    if not node_id or not title:
                        continue

                    if any(
                        goal.id == str(node_id)
                        for goal in self.goals
                    ):
                        continue

                    subgoals = []

                    for item in metadata.get(
                        "subgoals",
                        [],
                    ):
                        if not isinstance(item, dict):
                            continue

                        subgoal = SubGoal(
                            title=str(
                                item.get(
                                    "title",
                                    "",
                                )
                            ),
                            status=str(
                                item.get(
                                    "status",
                                    "pending",
                                )
                            ),
                            metadata=dict(
                                item.get(
                                    "metadata",
                                    {},
                                )
                                or {}
                            ),
                        )

                        subgoals.append(subgoal)

                    goal = Goal(
                        id=str(node_id),
                        title=str(title),
                        status=str(
                            metadata.get(
                                "status",
                                "active",
                            )
                        ),
                        progress=float(
                            metadata.get(
                                "progress",
                                0.0,
                            )
                            or 0.0
                        ),
                        metadata={
                            key: value
                            for key, value in metadata.items()
                            if key not in {
                                "goal_state",
                                "status",
                                "progress",
                                "created_at",
                                "updated_at",
                                "subgoals",
                            }
                        },
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

    def generate_subgoals(self, title: str):
        title_lower = title.lower()

        if "weather app" in title_lower:
            return [
                SubGoal("Research libraries"),
                SubGoal("Design roadmap"),
                SubGoal("Create backend"),
                SubGoal("Create frontend"),
                SubGoal("Deploy application"),
                SubGoal("Testing"),
            ]

        if "telegram ai" in title_lower:
            return [
                SubGoal("Research architecture"),
                SubGoal("Memory system"),
                SubGoal("Reasoning engine"),
                SubGoal("Planner"),
                SubGoal("Deployment"),
                SubGoal("Optimization"),
            ]

        return [
            SubGoal("Understand objective"),
            SubGoal("Plan required actions"),
            SubGoal("Execute planned actions"),
            SubGoal("Verify results"),
        ]

    # =========================================================
    # GOAL CREATION
    # =========================================================

    def add_goal(
        self,
        title: str,
        metadata=None,
    ):
        active = self.current_goal()

        if active and active.title.lower() == title.lower():
            return active

        goal = Goal(
            title=title,
            metadata=dict(metadata or {}),
            subgoals=self.generate_subgoals(title),
        )

        self.goals.append(goal)

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
        for goal in self.goals:
            if goal.id == goal_id:
                return goal

        return None

    def current_goal(self):
        for goal in reversed(self.goals):
            if goal.status == "active":
                return goal

        return None

    def list_active_goals(self):
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
    ):
        goal = self.get_goal(goal_id)

        if not goal:
            return None

        goal.status = "completed"
        goal.progress = 100.0
        goal.updated_at = datetime.utcnow()

        self._persist_goal(goal)

        logger.info(
            "[GoalManager] Completed goal: %s",
            goal.title,
        )

        return goal

    def pause_goal(
        self,
        goal_id: str,
    ):
        goal = self.get_goal(goal_id)

        if not goal:
            return None

        goal.status = "paused"
        goal.updated_at = datetime.utcnow()

        self._persist_goal(goal)

        return goal

    def resume_goal(
        self,
        goal_id: str,
    ):
        goal = self.get_goal(goal_id)

        if not goal:
            return None

        goal.status = "active"
        goal.updated_at = datetime.utcnow()

        self._persist_goal(goal)

        return goal

    def fail_goal(
        self,
        goal_id: str,
        reason: str = "",
    ):
        goal = self.get_goal(goal_id)

        if not goal:
            return None

        goal.status = "failed"
        goal.updated_at = datetime.utcnow()

        if reason:
            goal.metadata["failure_reason"] = reason

        self._persist_goal(goal)

        return goal

    def cancel_goal(
        self,
        goal_id: str,
    ):
        goal = self.get_goal(goal_id)

        if not goal:
            return None

        goal.status = "cancelled"
        goal.updated_at = datetime.utcnow()

        self._persist_goal(goal)

        return goal

    # =========================================================
    # PROGRESS
    # =========================================================

    def update_progress(
        self,
        goal_id,
        progress,
    ):
        goal = self.get_goal(goal_id)

        if not goal:
            return None

        goal.progress = max(
            0.0,
            min(
                100.0,
                float(progress),
            ),
        )

        goal.updated_at = datetime.utcnow()

        if goal.progress >= 100.0:
            return self.complete_goal(goal.id)

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

    def next_subgoal(self, goal=None):
        """
        Return the next pending subgoal for the supplied goal.

        If no goal is supplied, use the current active goal.
        This keeps subgoal selection scoped correctly when multiple
        autonomous goals exist.
        """

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
        goal,
        title,
    ):
        for subgoal in goal.subgoals:

            if subgoal.title.lower() != title.lower():
                continue

            subgoal.status = "completed"
            subgoal.updated_at = datetime.utcnow()

            completed = sum(
                1
                for item in goal.subgoals
                if item.status == "completed"
            )

            if goal.subgoals:
                goal.progress = (
                    completed / len(goal.subgoals)
                ) * 100.0

            goal.updated_at = datetime.utcnow()

            if goal.progress >= 100.0:
                self.complete_goal(goal.id)
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
    ):
        goal = self.get_goal(goal_id)

        if not goal:
            return None

        for subgoal in goal.subgoals:

            if subgoal.title.lower() != title.lower():
                continue

            subgoal.status = status
            subgoal.updated_at = datetime.utcnow()

            self._persist_goal(goal)

            return subgoal

        return None

    # =========================================================
    # CONTEXT
    # =========================================================

    def get_goal_context(
        self,
        goal_id: Optional[str] = None,
    ):
        goal = (
            self.get_goal(goal_id)
            if goal_id
            else self.current_goal()
        )

        if not goal:
            return None

        next_goal = self.next_subgoal(goal)

        return {
            "goal_id": goal.id,
            "goal_title": goal.title,
            "goal_status": goal.status,
            "progress": goal.progress,
            "subgoals": [
                {
                    "title": subgoal.title,
                    "status": subgoal.status,
                    "metadata": subgoal.metadata,
                }
                for subgoal in goal.subgoals
            ],
            "next_subgoal": (
                next_goal.title
                if next_goal
                else None
            ),
            "metadata": goal.metadata,
        }

    # =========================================================
    # OBSERVATION
    # =========================================================

    async def observe(
        self,
        query,
        context,
    ):
        query_lower = str(
            query
        ).lower().strip()

        if query_lower in [
            "finished",
            "done",
            "complete",
            "completed",
            "it's done",
            "it is done",
        ]:
            active = self.current_goal()

            if active:
                self.complete_goal(active.id)

            return

        building_phrases = [
            "i'm building",
            "im building",
            "i am building",
            "i'm creating",
            "im creating",
            "i am creating",
            "i'm making",
            "im making",
            "i want to build",
            "i want to create",
            "let's build",
            "lets build",
            "start a project",
        ]

        matched_title = None

        for phrase in building_phrases:

            if phrase in query_lower:
                idx = (
                    query_lower.find(phrase)
                    + len(phrase)
                )

                subject = query[idx:].strip(
                    " .!?"
                )

                if subject:
                    matched_title = (
                        f"Build {subject.capitalize()}"
                    )
                else:
                    matched_title = "New Project Goal"

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
    # SERIALIZATION
    # =========================================================

    def serialize_goal(
        self,
        goal: Goal,
    ):
        return {
            "id": goal.id,
            "title": goal.title,
            "status": goal.status,
            "progress": goal.progress,
            "created_at": goal.created_at.isoformat(),
            "updated_at": goal.updated_at.isoformat(),
            "metadata": goal.metadata,
            "subgoals": [
                {
                    "title": subgoal.title,
                    "status": subgoal.status,
                    "metadata": subgoal.metadata,
                    "created_at": subgoal.created_at.isoformat(),
                    "updated_at": subgoal.updated_at.isoformat(),
                }
                for subgoal in goal.subgoals
            ],
        }
