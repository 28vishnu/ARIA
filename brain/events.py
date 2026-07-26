import asyncio
from typing import Callable, Dict, List

class EventBus:
    def __init__(self):
        self._listeners: Dict[str, List[Callable]] = {}

    def subscribe(self, event_type: str, callback: Callable):
        if event_type not in self._listeners:
            self._listeners[event_type] = []
        self._listeners[event_type].append(callback)

    async def emit(self, event_type: str, data: dict):
        if event_type in self._listeners:
            await asyncio.gather(*(cb(data) for cb in self._listeners[event_type]))
