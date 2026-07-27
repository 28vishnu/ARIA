from dataclasses import dataclass, field
from typing import List, Dict, Any

@dataclass
class Decision:
    action: str
    confidence: float
    requires_planning: bool = False
    requires_execution: bool = False
    requires_response: bool = True
    selected_skills: List[str] = field(default_factory=list)
    selected_tools: List[str] = field(default_factory=list)
    selected_plugins: List[str] = field(default_factory=list)
    priority: str = "normal"
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = 0.0
