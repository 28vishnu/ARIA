from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict

@dataclass
class Message:
    session_id: str
    modality: str  # text, voice, image, document, audio
    content: Any
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
