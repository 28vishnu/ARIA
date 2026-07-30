from typing import Dict, Any


class StateManager:
    """
    Tracks ARIA's current execution state for each session.
    """

    def __init__(self):
        self._sessions: Dict[str, Dict[str, Any]] = {}

    def get_state(self, session_id: str) -> Dict[str, Any]:
        return self._sessions.setdefault(session_id, {})

    def update_state(self, session_id: str, **kwargs):
        state = self.get_state(session_id)
        state.update(kwargs)

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
        Resets document mode after deleting or closing documents.
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

    def clear_state(self, session_id: str):
        self._sessions.pop(session_id, None)
