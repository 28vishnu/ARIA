from dataclasses import dataclass
from typing import Callable, Dict, List, Any

@dataclass
class BaseEvent:
    session_id: str

@dataclass
class TaskStarted(BaseEvent):
    task_id: str
    task_name: str
    skill: str

@dataclass
class TaskCompleted(BaseEvent):
    task_id: str
    output: Any

@dataclass
class TaskFailed(BaseEvent):
    task_id: str
    error: str

@dataclass
class DocumentOpened(BaseEvent):
    document_id: str
    filename: str

@dataclass
class MemoryUpdated(BaseEvent):
    key: str
    value: Any

@dataclass
class SkillExecuted(BaseEvent):
    skill_name: str
    confidence: float

@dataclass
class PlanCreated(BaseEvent):
    goal: str
    task_count: int

class EventBus:
    def __init__(self):
        self._listeners: Dict[type, List[Callable]] = {}

    def subscribe(self, event_type: type, callback: Callable):
        if event_type not in self._listeners:
            self._listeners[event_type] = []
        self._listeners[event_type].append(callback)

    async def emit(self, event: BaseEvent):
        event_type = type(event)
        if event_type in self._listeners:
            for callback in self._listeners[event_type]:
                await callback(event)
