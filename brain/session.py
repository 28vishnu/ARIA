from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from brain.state_models import WorldState
from brain.plan import ExecutionPlan

@dataclass
class Session:
    session_id: str
    world_state: WorldState = field(default_factory=WorldState)
    history: List[Dict[str, str]] = field(default_factory=list)
    active_plan: Optional[ExecutionPlan] = None

class SessionManager:
    def __init__(self, context_manager):
        self.context_manager = context_manager
        self.sessions: Dict[str, Session] = {}

    def get_or_create_session(self, session_id: str) -> Session:
        """Retrieves or provisions the unified Session container."""
        if session_id not in self.sessions:
            world_state = self.context_manager.get_state(session_id)
            self.sessions[session_id] = Session(session_id=session_id, world_state=world_state)
        return self.sessions[session_id]
