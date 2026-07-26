from dataclasses import dataclass, field
from typing import List, Optional

@dataclass
class ConversationState:
    greeting_sent: bool = False
    conversation_length: int = 0
    previous_topic: Optional[str] = None
    pending_clarification: Optional[str] = None
    history: List[str] = field(default_factory=list)

class ConversationEngine:
    def __init__(self):
        self.sessions: dict[str, ConversationState] = {}

    def get_state(self, session_id: str) -> ConversationState:
        if session_id not in self.sessions:
            self.sessions[session_id] = ConversationState()
        return self.sessions[session_id]

    def record_turn(self, session_id: str, user_text: str, topic: Optional[str] = None):
        state = self.get_state(session_id)
        state.conversation_length += 1
        state.history.append(user_text)
        if topic:
            state.previous_topic = topic
        if not state.greeting_sent:
            state.greeting_sent = True
