from dataclasses import dataclass, field
from typing import List, Dict, Any

@dataclass
class Goal:
    id: str
    title: str
    description: str = ""
    priority: str = "normal"
    status: str = "pending"
    progress: float = 0.0
    dependencies: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = 0.0
