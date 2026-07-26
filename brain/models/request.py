from dataclasses import dataclass, field
from datetime import datetime, timezone

@dataclass
class BrainRequest:
    query: str
    user_id: str = "default_user"
    session_id: str = "default_session"
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    intent: str = "general"
    metadata: dict = field(default_factory=dict)
  
