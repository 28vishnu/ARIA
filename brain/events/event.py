from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict
import uuid


@dataclass
class Event:
    """
    Universal event flowing inside ARIA.

    Everything becomes an Event.

    Examples:
        Chat Completed
        Document Uploaded
        Memory Stored
        Web Search Finished
        Plan Executed
    """

    type: str

    source: str

    data: Dict[str, Any] = field(default_factory=dict)

    priority: int = 5

    timestamp: datetime = field(
        default_factory=datetime.utcnow
    )

    event_id: str = field(
        default_factory=lambda: str(uuid.uuid4())
    )