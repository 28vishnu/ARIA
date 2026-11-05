from typing import Any, Dict, Optional
from pydantic import BaseModel, Field

class Event(BaseModel):
    """Immutable event payload broadcasted across the ARIA system bus."""
    event_type: str = Field(..., description="The event identifier (e.g., 'intent.analyzed', 'task.completed', 'state.updated')")
    timestamp: str = Field(..., description="ISO-8601 timestamp of event emission")
    source_module: str = Field(..., description="The name of the subsystem emitting the event")
    payload: Dict[str, Any] = Field(default_factory=dict, description="The typed data packet associated with the event")
    correlation_id: str = Field(..., description="The session or trace ID linking related events together")
