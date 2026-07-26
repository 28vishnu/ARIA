from dataclasses import dataclass, field
from typing import Any, Dict, Optional

@dataclass
class SystemResponse:
    success: bool
    confidence: float
    data: Any = None
    source: str = "core"
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
