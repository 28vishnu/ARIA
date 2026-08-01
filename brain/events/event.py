from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict


@dataclass
class Event:
    """
    Represents a single event inside ARIA.

    Every subsystem communicates by publishing Event objects
    through the EventBus.

    Example:

    Event(
        type=TASK_COMPLETED,
        source="executor",
        data={
            "task": "search_web",
            "result": "...",
        }
    )
    """

    # Event type (TASK_COMPLETED, RESPONSE_GENERATED, etc.)
    type: str

    # Which subsystem generated it
    source: str

    # Payload
    data: Dict[str, Any] = field(default_factory=dict)

    # Time of creation
    timestamp: datetime = field(default_factory=datetime.utcnow)

    # Optional session
    session_id: str | None = None

    # Optional user
    user_id: str | None = None

    # Unique event id
    event_id: str | None = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "type": self.type,
            "source": self.source,
            "data": self.data,
            "timestamp": self.timestamp.isoformat(),
            "session_id": self.session_id,
            "user_id": self.user_id,
        }
