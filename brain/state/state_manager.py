from typing import Dict, Any, Optional, List
import asyncio
import copy
import logging
import time

logger = logging.getLogger("aria")


class StateManager:
    """
    Phase-11 canonical runtime state manager.

    Owns ephemeral session state only:
    - conversational context
    - document-selection state
    - direct-action confirmation state
    - suspended workflow state
    - workflow confirmation/progress
    - execution metadata

    Persistent memory remains owned by the memory systems, and autonomous
    goal state remains owned by GoalManager.

    No LLM, tool execution, or local intelligence is performed here.
    """

    VERSION = "11.12"
    DEFAULT_MAX_TURNS = 20
    MAX_TURNS = 100
    MAX_HISTORY_SESSIONS = 1000
    MAX_WORKFLOW_OUTPUTS = 200
    MAX_LIST_ITEMS = 500

    def __init__(self):
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    # =========================================================
    # NORMALIZATION / SAFETY
    # =========================================================

    @staticmethod
    def _session_key(session_id: Any) -> str:
        return str(session_id or "").strip()

    @classmethod
    def _bounded_limit(
        cls,
        value: Any,
        default: int,
        maximum: int,
    ) -> int:
        try:
            limit = int(value)
        except (TypeError, ValueError):
            limit = default

        return max(1, min(limit, maximum))

    @staticmethod
    def _safe_copy(value: Any) -> Any:
        try:
            return copy.deepcopy(value)
        except Exception:
            if isinstance(value, dict):
                return dict(value)
            if isinstance(value, list):
                return list(value)
            return value

    @classmethod
    def _safe_dict(
        cls,
        value: Any,
    ) -> Dict[str, Any]:
        if not isinstance(value, dict):
            return {}

        return cls._safe_copy(value)

    @classmethod
    def _safe_list(
        cls,
        value: Any,
    ) -> List[Any]:
        if not isinstance(value, list):
            return []

        return cls._safe_copy(value)

    def _trim_sessions(self):
        """
        Bound retained session state.

        Active runtime state is preferred over the oldest inactive state.
        """
        if len(self._sessions) <= self.MAX_HISTORY_SESSIONS:
            return

        items = list(
            self._sessions.items()
        )

        items.sort(
            key=lambda item: float(
                item[1].get(
                    "_last_access",
                    0.0,
                )
            ),
            reverse=True,
        )

        self._sessions = dict(
            items[
                : self.MAX_HISTORY_SESSIONS
            ]
        )

    # =========================================================
    # BASIC SESSION STATE
    # =========================================================

    def get_state(
        self,
        session_id: str,
    ) -> Dict[str, Any]:
        """
        Return mutable runtime state for a session.

        A session is created automatically when absent.
        """
        key = self._session_key(session_id)

        if not key:
            # Preserve compatibility while preventing all empty/None
            # callers from accidentally sharing one persistent session.
            key = "__anonymous__"

        state = self._sessions.setdefault(
            key,
            {},
        )

        state["_last_access"] = time.time()
        self._trim_sessions()

        return state

    def update_state(
        self,
        session_id: str,
        **kwargs,
    ):
        """
        Update arbitrary runtime state values.

        Values are copied where possible so external mutable objects do not
        silently mutate state after insertion.
        """
        state = self.get_state(
            session_id
        )

        for key, value in kwargs.items():
            if key == "_last_access":
                continue

            state[key] = self._safe_copy(
                value
            )

        state["_last_access"] = time.time()

    def get_value(
        self,
        session_id: str,
        key: str,
        default: Any = None,
    ) -> Any:
        """Read one value from session state."""
        value = self.get_state(
            session_id
        ).get(
            key,
            default,
        )

        return self._safe_copy(
            value
        )

    # =========================================================
    # CONVERSATION STATE
    # =========================================================

    def add_conversation_turn(
        self,
        session_id: str,
        user_message: str,
        assistant_message: str,
        max_turns: int = DEFAULT_MAX_TURNS,
    ):
        """
        Store a bounded rolling conversation history.

        This is short-term working context, not persistent long-term memory.
        """
        limit = self._bounded_limit(
            max_turns,
            self.DEFAULT_MAX_TURNS,
            self.MAX_TURNS,
        )

        state = self.get_state(
            session_id
        )

        history = self._safe_list(
            state.get(
                "conversation_history",
                [],
            )
        )

        history.append(
            {
                "user": str(
                    user_message or ""
                ).strip(),
                "assistant": str(
                    assistant_message or ""
                ).strip(),
            }
        )

        history = history[-limit:]

        self.update_state(
            session_id,
            conversation_history=history,
            last_query=str(
                user_message or ""
            ).strip(),
            last_assistant_response=str(
                assistant_message or ""
            ).strip(),
        )

    def append_conversation_history(
        self,
        session_id: str,
        user: str,
        assistant: str,
    ):
        """Compatibility wrapper used by CognitiveCore."""
        self.add_conversation_turn(
            session_id=session_id,
            user_message=user,
            assistant_message=assistant,
        )

    def get_conversation_history(
        self,
        session_id: str,
        limit: int = DEFAULT_MAX_TURNS,
    ) -> List[Dict[str, str]]:
        """Return a safe copy of recent conversation turns."""
        bounded = self._bounded_limit(
            limit,
            self.DEFAULT_MAX_TURNS,
            self.MAX_TURNS,
        )

        history = self.get_state(
            session_id
        ).get(
            "conversation_history",
            [],
        )

        if not isinstance(history, list):
            return []

        return self._safe_copy(
            history[-bounded:]
        )

    def get_last_assistant_response(
        self,
        session_id: str,
    ) -> Optional[str]:
        """Return ARIA's previous response for this session."""
        value = self.get_value(
            session_id,
            "last_assistant_response",
        )

        if not value:
            return None

        return str(value)

    def clear_conversation_history(
        self,
        session_id: str,
    ):
        """Clear conversational context without touching workflows."""
        self.update_state(
            session_id,
            conversation_history=[],
            last_query=None,
            last_assistant_response=None,
        )

    # =========================================================
    # DOCUMENT STATE
    # =========================================================

    def set_pending_document_action(
        self,
        session_id: str,
        action: str,
        documents: list,
    ):
        """Remember a pending document-selection operation."""
        self.update_state(
            session_id,
            pending_document_action=str(
                action or ""
            ).strip(),
            pending_document_selection=True,
            pending_documents=self._safe_list(
                documents
            ),
        )

    def clear_pending_document_action(
        self,
        session_id: str,
    ):
        """Clear a pending document-selection operation."""
        self.update_state(
            session_id,
            pending_document_action=None,
            pending_document_selection=False,
            pending_documents=[],
        )

    def clear_document_context(
        self,
        session_id: str,
    ):
        """Reset document mode without clearing workflow state."""
        self.update_state(
            session_id,
            active_document=False,
            document_uploaded=False,
            current_document=None,
            current_document_summary=None,
            last_document_question=None,
            last_document_answer=None,
            pending_document_action=None,
            pending_document_selection=False,
            pending_documents=[],
        )

    # =========================================================
    # SINGLE ACTION CONFIRMATION
    # =========================================================

    def set_pending_action(
        self,
        session_id: str,
        action_name: str,
        action_params: Dict[str, Any],
    ):
        """Store a direct executable action awaiting confirmation."""
        self.update_state(
            session_id,
            pending_action_confirmation=True,
            pending_action_name=str(
                action_name or ""
            ).strip(),
            pending_action_params=self._safe_dict(
                action_params
            ),
        )

    def get_pending_action(
        self,
        session_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Return the currently pending direct action."""
        state = self.get_state(
            session_id
        )

        if not state.get(
            "pending_action_confirmation"
        ):
            return None

        action_name = state.get(
            "pending_action_name"
        )

        if not action_name:
            return None

        return {
            "action_name": str(
                action_name
            ),
            "action_params": self._safe_dict(
                state.get(
                    "pending_action_params",
                    {},
                )
            ),
        }

    def clear_pending_action(
        self,
        session_id: str,
    ):
        """Clear a direct action confirmation."""
        self.update_state(
            session_id,
            pending_action_confirmation=False,
            pending_action_name=None,
            pending_action_params={},
        )

    # =========================================================
    # MULTI-STEP WORKFLOW STATE
    # =========================================================

    def set_pending_workflow(
        self,
        session_id: str,
        plan: Any,
        task_id: Optional[str] = None,
        task_outputs: Optional[Dict[str, Any]] = None,
        completed_tasks: Optional[List[str]] = None,
        failed_tasks: Optional[List[str]] = None,
        skipped_tasks: Optional[List[str]] = None,
    ):
        """
        Store a suspended ExecutionPlan and its exact resumable progress.

        The plan remains an in-memory object for compatibility with the
        existing Executor; serialized task progress is separately bounded.
        """
        outputs = self._safe_dict(
            task_outputs
        )

        if len(outputs) > self.MAX_WORKFLOW_OUTPUTS:
            outputs = dict(
                list(outputs.items())[
                    -self.MAX_WORKFLOW_OUTPUTS :
                ]
            )

        completed = self._safe_list(
            completed_tasks
        )[
            : self.MAX_LIST_ITEMS
        ]

        failed = self._safe_list(
            failed_tasks
        )[
            : self.MAX_LIST_ITEMS
        ]

        skipped = self._safe_list(
            skipped_tasks
        )[
            : self.MAX_LIST_ITEMS
        ]

        self.update_state(
            session_id,
            workflow_active=True,
            workflow_paused=True,
            pending_workflow=plan,
            pending_workflow_task_id=(
                str(task_id)
                if task_id is not None
                else None
            ),
            workflow_task_outputs=outputs,
            workflow_completed_tasks=completed,
            workflow_failed_tasks=failed,
            workflow_skipped_tasks=skipped,
            pending_workflow_confirmation=bool(
                task_id
            ),
            workflow_last_status="paused",
            workflow_last_error=None,
        )

    def get_pending_workflow(
        self,
        session_id: str,
    ) -> Any:
        """Return the currently suspended ExecutionPlan."""
        state = self.get_state(
            session_id
        )

        if not state.get(
            "workflow_active"
        ):
            return None

        return state.get(
            "pending_workflow"
        )

    def has_pending_workflow(
        self,
        session_id: str,
    ) -> bool:
        """Return whether a suspended workflow exists."""
        state = self.get_state(
            session_id
        )

        return bool(
            state.get("workflow_active")
            and state.get("pending_workflow") is not None
        )

    # =========================================================
    # WORKFLOW CONFIRMATION
    # =========================================================

    def set_workflow_confirmation(
        self,
        session_id: str,
        task_id: str,
    ):
        """Mark a workflow task as waiting for confirmation."""
        self.update_state(
            session_id,
            workflow_active=True,
            workflow_paused=True,
            pending_workflow_confirmation=True,
            pending_workflow_task_id=str(
                task_id
            ),
            workflow_last_status="awaiting_confirmation",
        )

    def get_pending_workflow_task_id(
        self,
        session_id: str,
    ) -> Optional[str]:
        """Return the workflow task currently awaiting approval."""
        state = self.get_state(
            session_id
        )

        if not state.get(
            "pending_workflow_confirmation"
        ):
            return None

        task_id = state.get(
            "pending_workflow_task_id"
        )

        return (
            str(task_id)
            if task_id is not None
            else None
        )

    def clear_workflow_confirmation(
        self,
        session_id: str,
    ):
        """Remove workflow confirmation without deleting the workflow."""
        self.update_state(
            session_id,
            pending_workflow_confirmation=False,
            pending_workflow_task_id=None,
        )

    # =========================================================
    # WORKFLOW EXECUTION PROGRESS
    # =========================================================

    def update_workflow_progress(
        self,
        session_id: str,
        task_outputs: Optional[Dict[str, Any]] = None,
        completed_tasks: Optional[List[str]] = None,
        failed_tasks: Optional[List[str]] = None,
        skipped_tasks: Optional[List[str]] = None,
    ):
        """Save bounded workflow execution progress."""
        updates: Dict[str, Any] = {}

        if task_outputs is not None:
            outputs = self._safe_dict(
                task_outputs
            )
            if len(outputs) > self.MAX_WORKFLOW_OUTPUTS:
                outputs = dict(
                    list(outputs.items())[
                        -self.MAX_WORKFLOW_OUTPUTS :
                    ]
                )

            updates[
                "workflow_task_outputs"
            ] = outputs

        if completed_tasks is not None:
            updates[
                "workflow_completed_tasks"
            ] = self._safe_list(
                completed_tasks
            )[
                : self.MAX_LIST_ITEMS
            ]

        if failed_tasks is not None:
            updates[
                "workflow_failed_tasks"
            ] = self._safe_list(
                failed_tasks
            )[
                : self.MAX_LIST_ITEMS
            ]

        if skipped_tasks is not None:
            updates[
                "workflow_skipped_tasks"
            ] = self._safe_list(
                skipped_tasks
            )[
                : self.MAX_LIST_ITEMS
            ]

        if updates:
            self.update_state(
                session_id,
                **updates,
            )

    def get_workflow_progress(
        self,
        session_id: str,
    ) -> Dict[str, Any]:
        """Return a safe copy of saved workflow progress."""
        state = self.get_state(
            session_id
        )

        return {
            "task_outputs": self._safe_dict(
                state.get(
                    "workflow_task_outputs",
                    {},
                )
            ),
            "completed": self._safe_list(
                state.get(
                    "workflow_completed_tasks",
                    [],
                )
            ),
            "failed": self._safe_list(
                state.get(
                    "workflow_failed_tasks",
                    [],
                )
            ),
            "skipped": self._safe_list(
                state.get(
                    "workflow_skipped_tasks",
                    [],
                )
            ),
        }

    # =========================================================
    # WORKFLOW LIFECYCLE
    # =========================================================

    def mark_workflow_resumed(
        self,
        session_id: str,
    ):
        """Mark a suspended workflow as running again."""
        self.update_state(
            session_id,
            workflow_active=True,
            workflow_paused=False,
            pending_workflow_confirmation=False,
            workflow_last_status="running",
            workflow_last_error=None,
        )

    def mark_workflow_completed(
        self,
        session_id: str,
    ):
        """Mark workflow execution as successfully completed."""
        self.update_state(
            session_id,
            workflow_active=False,
            workflow_paused=False,
            workflow_last_status="completed",
            workflow_last_error=None,
            pending_workflow=None,
            pending_workflow_task_id=None,
            pending_workflow_confirmation=False,
            workflow_task_outputs={},
            workflow_completed_tasks=[],
            workflow_failed_tasks=[],
            workflow_skipped_tasks=[],
        )

    def mark_workflow_failed(
        self,
        session_id: str,
        error: Optional[str] = None,
    ):
        """Mark the active workflow as failed."""
        self.update_state(
            session_id,
            workflow_active=False,
            workflow_paused=False,
            workflow_last_status="failed",
            workflow_last_error=(
                str(error)
                if error is not None
                else None
            ),
            pending_workflow=None,
            pending_workflow_task_id=None,
            pending_workflow_confirmation=False,
            workflow_task_outputs={},
            workflow_completed_tasks=[],
            workflow_failed_tasks=[],
            workflow_skipped_tasks=[],
        )

    def cancel_workflow(
        self,
        session_id: str,
    ):
        """Cancel and discard the currently suspended workflow."""
        self.update_state(
            session_id,
            workflow_active=False,
            workflow_paused=False,
            workflow_last_status="cancelled",
            workflow_last_error=None,
            pending_workflow=None,
            pending_workflow_task_id=None,
            pending_workflow_confirmation=False,
            workflow_task_outputs={},
            workflow_completed_tasks=[],
            workflow_failed_tasks=[],
            workflow_skipped_tasks=[],
        )

    def clear_workflow(
        self,
        session_id: str,
    ):
        """Completely reset workflow state."""
        self.update_state(
            session_id,
            workflow_active=False,
            workflow_paused=False,
            workflow_last_status=None,
            workflow_last_error=None,
            pending_workflow=None,
            pending_workflow_task_id=None,
            pending_workflow_confirmation=False,
            workflow_task_outputs={},
            workflow_completed_tasks=[],
            workflow_failed_tasks=[],
            workflow_skipped_tasks=[],
        )

    # =========================================================
    # SESSION SNAPSHOT / HEALTH
    # =========================================================

    def get_session_snapshot(
        self,
        session_id: str,
    ) -> Dict[str, Any]:
        """
        Return a defensive snapshot of the session without exposing the
        mutable internal dictionary.
        """
        state = self.get_state(
            session_id
        )

        snapshot = self._safe_copy(
            state
        )

        snapshot.pop(
            "_last_access",
            None,
        )

        return snapshot

    def session_exists(
        self,
        session_id: str,
    ) -> bool:
        key = self._session_key(
            session_id
        )

        if not key:
            key = "__anonymous__"

        return key in self._sessions

    def clear_state(
        self,
        session_id: str,
    ):
        """Completely remove a session and its runtime state."""
        key = self._session_key(
            session_id
        )

        if not key:
            key = "__anonymous__"

        self._sessions.pop(
            key,
            None,
        )

    def clear_all(
        self,
    ):
        """Clear every in-memory runtime session."""
        self._sessions.clear()

    def health(self) -> Dict[str, Any]:
        """Return non-sensitive runtime state statistics."""
        return {
            "status": "healthy",
            "version": self.VERSION,
            "session_count": len(
                self._sessions
            ),
            "max_sessions": self.MAX_HISTORY_SESSIONS,
        }
