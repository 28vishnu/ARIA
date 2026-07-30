from typing import Dict, Any, Optional, List


class StateManager:
    """
    Tracks ARIA's runtime state for each conversation/session.

    Responsibilities:
    - conversational/session state
    - document state
    - single-action confirmation state
    - multi-step workflow state
    - workflow confirmation/resume state
    - task outputs and execution progress
    """

    def __init__(self):
        self._sessions: Dict[str, Dict[str, Any]] = {}

    # =========================================================
    # BASIC SESSION STATE
    # =========================================================

    def get_state(self, session_id: str) -> Dict[str, Any]:
        """
        Return the state dictionary for a session.

        A session is created automatically when it does not exist.
        """
        return self._sessions.setdefault(session_id, {})

    def update_state(
        self,
        session_id: str,
        **kwargs
    ):
        """
        Update arbitrary session state values.
        """
        state = self.get_state(session_id)
        state.update(kwargs)

    def get_value(
        self,
        session_id: str,
        key: str,
        default: Any = None
    ) -> Any:
        """
        Read one value from session state.
        """
        return self.get_state(
            session_id
        ).get(
            key,
            default
        )

    # =========================================================
    # DOCUMENT STATE
    # =========================================================

    def set_pending_document_action(
        self,
        session_id: str,
        action: str,
        documents: list
    ):
        """
        Remember that ARIA is waiting for the user to select
        one document from a previous document operation.
        """
        self.update_state(
            session_id,
            pending_document_action=action,
            pending_document_selection=True,
            pending_documents=documents
        )

    def clear_pending_document_action(
        self,
        session_id: str
    ):
        """
        Clear a pending document-selection operation.
        """
        self.update_state(
            session_id,
            pending_document_action=None,
            pending_document_selection=False,
            pending_documents=[]
        )

    def clear_document_context(
        self,
        session_id: str
    ):
        """
        Reset document mode after deleting or closing documents.
        """
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
            pending_documents=[]
        )

    # =========================================================
    # SINGLE ACTION CONFIRMATION
    # =========================================================

    def set_pending_action(
        self,
        session_id: str,
        action_name: str,
        action_params: Dict[str, Any]
    ):
        """
        Store an executable action waiting for explicit
        user confirmation.

        This remains separate from workflow confirmation so
        existing direct actions continue working.
        """
        self.update_state(
            session_id,
            pending_action_confirmation=True,
            pending_action_name=action_name,
            pending_action_params=dict(
                action_params or {}
            )
        )

    def get_pending_action(
        self,
        session_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Return the currently pending direct action.
        """
        state = self.get_state(session_id)

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
            "action_name": action_name,
            "action_params": dict(
                state.get(
                    "pending_action_params",
                    {}
                )
            )
        }

    def clear_pending_action(
        self,
        session_id: str
    ):
        """
        Clear an action after confirmation, rejection,
        cancellation, or execution.
        """
        self.update_state(
            session_id,
            pending_action_confirmation=False,
            pending_action_name=None,
            pending_action_params={}
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
        Store an ExecutionPlan that has been suspended.

        Usually this happens because one of its tasks requires
        user confirmation.

        The actual plan object is retained in memory so execution
        can resume without regenerating the plan.
        """
        self.update_state(
            session_id,

            workflow_active=True,
            workflow_paused=True,

            pending_workflow=plan,
            pending_workflow_task_id=task_id,

            workflow_task_outputs=dict(
                task_outputs or {}
            ),

            workflow_completed_tasks=list(
                completed_tasks or []
            ),

            workflow_failed_tasks=list(
                failed_tasks or []
            ),

            workflow_skipped_tasks=list(
                skipped_tasks or []
            ),

            pending_workflow_confirmation=bool(
                task_id
            )
        )

    def get_pending_workflow(
        self,
        session_id: str
    ) -> Any:
        """
        Return the currently suspended ExecutionPlan.
        """
        state = self.get_state(session_id)

        if not state.get("workflow_active"):
            return None

        return state.get(
            "pending_workflow"
        )

    def has_pending_workflow(
        self,
        session_id: str
    ) -> bool:
        """
        Check whether a suspended workflow exists.
        """
        state = self.get_state(session_id)

        return bool(
            state.get("workflow_active")
            and state.get("pending_workflow")
        )

    # =========================================================
    # WORKFLOW CONFIRMATION
    # =========================================================

    def set_workflow_confirmation(
        self,
        session_id: str,
        task_id: str
    ):
        """
        Mark a workflow task as waiting for confirmation.
        """
        self.update_state(
            session_id,
            workflow_active=True,
            workflow_paused=True,
            pending_workflow_confirmation=True,
            pending_workflow_task_id=task_id
        )

    def get_pending_workflow_task_id(
        self,
        session_id: str
    ) -> Optional[str]:
        """
        Return the workflow task currently waiting for approval.
        """
        state = self.get_state(session_id)

        if not state.get(
            "pending_workflow_confirmation"
        ):
            return None

        return state.get(
            "pending_workflow_task_id"
        )

    def clear_workflow_confirmation(
        self,
        session_id: str
    ):
        """
        Remove workflow confirmation state without deleting
        the entire workflow.
        """
        self.update_state(
            session_id,
            pending_workflow_confirmation=False,
            pending_workflow_task_id=None
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
        skipped_tasks: Optional[List[str]] = None
    ):
        """
        Save workflow execution progress.

        This allows ARIA to continue from the exact point at
        which execution was paused.
        """
        updates: Dict[str, Any] = {}

        if task_outputs is not None:
            updates[
                "workflow_task_outputs"
            ] = dict(task_outputs)

        if completed_tasks is not None:
            updates[
                "workflow_completed_tasks"
            ] = list(completed_tasks)

        if failed_tasks is not None:
            updates[
                "workflow_failed_tasks"
            ] = list(failed_tasks)

        if skipped_tasks is not None:
            updates[
                "workflow_skipped_tasks"
            ] = list(skipped_tasks)

        if updates:
            self.update_state(
                session_id,
                **updates
            )

    def get_workflow_progress(
        self,
        session_id: str
    ) -> Dict[str, Any]:
        """
        Return saved execution progress for a suspended workflow.
        """
        state = self.get_state(session_id)

        return {
            "task_outputs": dict(
                state.get(
                    "workflow_task_outputs",
                    {}
                )
            ),
            "completed": list(
                state.get(
                    "workflow_completed_tasks",
                    []
                )
            ),
            "failed": list(
                state.get(
                    "workflow_failed_tasks",
                    []
                )
            ),
            "skipped": list(
                state.get(
                    "workflow_skipped_tasks",
                    []
                )
            )
        }

    # =========================================================
    # WORKFLOW LIFECYCLE
    # =========================================================

    def mark_workflow_resumed(
        self,
        session_id: str
    ):
        """
        Mark a previously suspended workflow as running again.
        """
        self.update_state(
            session_id,
            workflow_active=True,
            workflow_paused=False,
            pending_workflow_confirmation=False
        )

    def mark_workflow_completed(
        self,
        session_id: str
    ):
        """
        Mark workflow execution as successfully completed.
        """
        self.update_state(
            session_id,
            workflow_active=False,
            workflow_paused=False,
            workflow_last_status="completed",
            pending_workflow=None,
            pending_workflow_task_id=None,
            pending_workflow_confirmation=False,
            workflow_task_outputs={},
            workflow_completed_tasks=[],
            workflow_failed_tasks=[],
            workflow_skipped_tasks=[]
        )

    def mark_workflow_failed(
        self,
        session_id: str,
        error: Optional[str] = None
    ):
        """
        Mark the active workflow as failed.
        """
        self.update_state(
            session_id,
            workflow_active=False,
            workflow_paused=False,
            workflow_last_status="failed",
            workflow_last_error=error,
            pending_workflow=None,
            pending_workflow_task_id=None,
            pending_workflow_confirmation=False,
            workflow_task_outputs={},
            workflow_completed_tasks=[],
            workflow_failed_tasks=[],
            workflow_skipped_tasks=[]
        )

    def cancel_workflow(
        self,
        session_id: str
    ):
        """
        Cancel and discard the currently suspended workflow.
        """
        self.update_state(
            session_id,
            workflow_active=False,
            workflow_paused=False,
            workflow_last_status="cancelled",
            pending_workflow=None,
            pending_workflow_task_id=None,
            pending_workflow_confirmation=False,
            workflow_task_outputs={},
            workflow_completed_tasks=[],
            workflow_failed_tasks=[],
            workflow_skipped_tasks=[]
        )

    def clear_workflow(
        self,
        session_id: str
    ):
        """
        Completely reset workflow state.
        """
        self.update_state(
            session_id,
            workflow_active=False,
            workflow_paused=False,
            pending_workflow=None,
            pending_workflow_task_id=None,
            pending_workflow_confirmation=False,
            workflow_task_outputs={},
            workflow_completed_tasks=[],
            workflow_failed_tasks=[],
            workflow_skipped_tasks=[]
        )

    # =========================================================
    # GLOBAL SESSION CLEANUP
    # =========================================================

    def clear_state(
        self,
        session_id: str
    ):
        """
        Completely remove a session and all associated runtime state.
        """
        self._sessions.pop(
            session_id,
            None
        )