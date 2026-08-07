from dataclasses import dataclass, field
from typing import List


@dataclass
class ActionNode:
    id: str
    name: str
    description: str

    status: str = "pending"

    tool: str | None = None

    depends_on: List[str] = field(default_factory=list)

    result: dict | None = None
