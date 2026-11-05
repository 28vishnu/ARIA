from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from brain.models.intent import Intent

@dataclass
class Context:
    intent: Optional[Intent] = None
    session_id: str = ""
    user_id: str = ""
    conversation_history: List[Dict[str, Any]] = field(default_factory=list)
    working_memory: Dict[str, Any] = field(default_factory=dict)
    documents: List[Dict[str, Any]] = field(default_factory=list)
    profile: Dict[str, Any] = field(default_factory=dict)
    environment: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = 0.0
