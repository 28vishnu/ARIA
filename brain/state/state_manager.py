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

    def clear_state(self, session_id: str):
        self._sessions.pop(session_id, None)