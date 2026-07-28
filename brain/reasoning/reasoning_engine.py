from dataclasses import dataclass, field
from typing import List, Dict, Any


@dataclass
class ReasoningResult:
    """
    Represents the reasoning outcome before execution.
    """

    primary_action: str
    secondary_actions: List[str] = field(default_factory=list)
    confidence: float = 1.0
    reasoning: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)