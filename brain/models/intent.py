from dataclasses import dataclass, field
from typing import List, Dict, Any

@dataclass
class Intent:
    original_query: str
    normalized_query: str
    intent_type: str
    confidence: float
    entities: List[Dict[str, Any]] = field(default_factory=list)
    requires_memory: bool = False
    requires_documents: bool = False
    requires_web: bool = False
    requires_reasoning: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = 0.0
