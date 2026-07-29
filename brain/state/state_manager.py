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
            last_document_answer=None
        )

    def clear_state(self, session_id: str):
        self._sessions.pop(session_id, None)
