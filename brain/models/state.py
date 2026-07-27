from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
from brain.models.intent import Intent
from brain.models.decision import Decision

class CognitiveState(BaseModel):
    """The unified runtime state of the operating system during an execution cycle."""
    session_id: str = Field(..., description="Active session identifier")
    current_focus: Optional[str] = Field(default=None, description="The primary topic or entity currently under analysis")
    active_project: Optional[str] = Field(default=None, description="The broader project context (e.g., 'ARIA 2.0', 'Portfolio')")
    current_intent: Optional[Intent] = Field(default=None, description="The resolved structured intent for the current turn")
    current_decision: Optional[Decision] = Field(default=None, description="The active execution strategy")
    open_blockers: List[str] = Field(default_factory=list, description="Unresolved questions or missing parameters preventing execution")
    recent_thoughts: List[str] = Field(default_factory=list, description="Trace of reasoning steps taken during this cycle")
    confidence_score: float = Field(default=1.0, ge=0.0, le=1.0, description="Overall system confidence in the current execution path")
    working_memory_snapshot: Dict[str, Any] = Field(default_factory=dict, description="Snapshot of temporary variables and active artifacts")
