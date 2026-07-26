from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List

@dataclass
class WorldState:
    current_goal: Optional[str] = None
    active_document_id: Optional[str] = None
    active_project: Optional[str] = None
    active_task_id: Optional[str] = None
    active_skill: Optional[str] = None
    last_query: Optional[str] = None
    last_response: Optional[str] = None
    task_outputs: Dict[str, Any] = field(default_factory=dict)
    open_files: List[str] = field(default_factory=list)
    variables: Dict[str, Any] = field(default_factory=dict)
