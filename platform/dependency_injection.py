import logging
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger("aria")

class ServiceRegistry:
    def __init__(self):
        self._services: dict[str, Any] = {}

    def register(self, name: str, instance: Any):
        self._services[name] = instance
        logger.info("[ServiceRegistry] Registered service: '%s'", name)

    def get(self, name: str) -> Any:
        if name not in self._services:
            raise KeyError(f"Service '{name}' is not registered in the container.")
        return self._services[name]

    def has(self, name: str) -> bool:
        return name in self._services

@dataclass
class RequestContext:
    session_id: str
    request_id: str
    session_manager: Any
    memory_engine: Any
    skill_manager: Any
    action_manager: Any
    planner: Any
    executor: Any
    personality_engine: Any
    context_manager: Any
    event_bus: Any
