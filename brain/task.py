from dataclasses import dataclass, field
from typing import Dict, Any, List

@dataclass
class Task:
    id: str
    name: str
    skill: str
    input: Dict[str, Any] = field(default_factory=dict)
    depends_on: List[str] = field(default_factory=list)
    status: str = "pending"  # pending, running, completed, failed, skipped
    max_retries: int = 2
    retry_count: int = 0
