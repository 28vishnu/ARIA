import logging
from typing import Dict, Any
from brain.state_models import WorldState
from brain.event import (
    EventBus, BaseEvent, TaskStarted, TaskCompleted, TaskFailed, 
    DocumentOpened, MemoryUpdated, SkillExecuted, PlanCreated
)

logger = logging.getLogger("aria")

class ContextManager:
    def __init__(self, event_bus: EventBus):
        self.states: Dict[str, WorldState] = {}
        self.event_bus = event_bus
        self._register_event_listeners()

    def get_state(self, session_id: str) -> WorldState:
        """Retrieves or initializes the lightweight WorldState for a given session."""
        if session_id not in self.states:
            self.states[session_id] = WorldState()
        return self.states[session_id]

    def _register_event_listeners(self):
        self.event_bus.subscribe(TaskStarted, self._on_task_started)
        self.event_bus.subscribe(TaskCompleted, self._on_task_completed)
        self.event_bus.subscribe(TaskFailed, self._on_task_failed)
        self.event_bus.subscribe(DocumentOpened, self._on_document_opened)
        self.event_bus.subscribe(MemoryUpdated, self._on_memory_updated)
        self.event_bus.subscribe(SkillExecuted, self._on_skill_executed)
        self.event_bus.subscribe(PlanCreated, self._on_plan_created)

    async def _on_task_started(self, event: TaskStarted):
        state = self.get_state(event.session_id)
        state.active_task_id = event.task_id
        state.active_skill = event.skill
        logger.info("[ContextManager] State updated: Active Task -> %s (%s)", event.task_id, event.task_name)

    async def _on_task_completed(self, event: TaskCompleted):
        state = self.get_state(event.session_id)
        state.task_outputs[event.task_id] = event.output
        state.active_task_id = None
        logger.info("[ContextManager] State updated: Task Completed -> %s", event.task_id)

    async def _on_task_failed(self, event: TaskFailed):
        state = self.get_state(event.session_id)
        state.active_task_id = None
        logger.info("[ContextManager] State updated: Task Failed -> %s (%s)", event.task_id, event.error)

    async def _on_document_opened(self, event: DocumentOpened):
        state = self.get_state(event.session_id)
        state.active_document_id = event.document_id
        if event.filename not in state.open_files:
            state.open_files.append(event.filename)
        logger.info("[ContextManager] State updated: Active Document -> %s", event.filename)

    async def _on_memory_updated(self, event: MemoryUpdated):
        state = self.get_state(event.session_id)
        state.variables[event.key] = event.value
        logger.info("[ContextManager] State updated: Memory Variable -> %s", event.key)

    async def _on_skill_executed(self, event: SkillExecuted):
        state = self.get_state(event.session_id)
        state.active_skill = event.skill_name

    async def _on_plan_created(self, event: PlanCreated):
        state = self.get_state(event.session_id)
        state.current_goal = event.goal
        logger.info("[ContextManager] State updated: Current Goal -> %s", event.goal)
