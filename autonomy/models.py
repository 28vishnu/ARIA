from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

@dataclass
class Goal:
    id: str
    description: str
    status: str = "pending"  # pending, active, paused, completed, cancelled, failed
    priority: int = 5  # 1 (highest) to 10 (lowest)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    deadline: Optional[datetime] = None
    active_plan_id: Optional[str] = None
    progress_percentage: float = 0.0

@dataclass
class ReflectionRecord:
    goal_id: str
    success: bool
    duration_seconds: float
    failures: int
    retry_count: int
    observations: List[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

@dataclass
class LearningRule:
    rule_key: str
    directive: str
    source_feedback: str
    active: bool = True
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

@dataclass
class RuntimeMetrics:
    planner_latency_ms: float = 0.0
    skill_latency_ms: float = 0.0
    action_latency_ms: float = 0.0
    success_count: int = 0
    failure_count: int = 0
    retry_count: int = 0
    average_confidence: float = 1.0
    llm_calls_avoided: int = 0
