import logging
from typing import Callable, Dict, List, Coroutine, Any
from brain.models.event import Event

logger = logging.getLogger("aria")

# Define an asynchronous callback type for event listeners
EventListener = Callable[[Event], Coroutine[Any, Any, None]]

class EventBus:
    """Decoupled asynchronous publish/subscribe system bus for ARIA 2.0."""
    def __init__(self):
        self._subscribers: Dict[str, List[EventListener]] = {}

    def subscribe(self, event_type: str, listener: EventListener) -> None:
        """Registers an asynchronous callback listener for a specific event type."""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        if listener not in self._subscribers[event_type]:
            self._subscribers[event_type].append(listener)
            logger.debug("[EventBus] Listener %s subscribed to '%s'", listener.__name__, event_type)

    def unsubscribe(self, event_type: str, listener: EventListener) -> None:
        """Removes a listener from a specific event subscription."""
        if event_type in self._subscribers and listener in self._subscribers[event_type]:
            self._subscribers[event_type].remove(listener)
            logger.debug("[EventBus] Listener %s unsubscribed from '%s'", listener.__name__, event_type)

    async def publish(self, event: Event) -> None:
        """Broadcasts an immutable event to all registered subscribers asynchronously."""
        logger.info("[EventBus] Publishing event: '%s' from module: '%s'", event.event_type, event.source_module)
        
        listeners = self._subscribers.get(event.event_type, [])
        # Also trigger wildcard listeners if we want global observers (like logging or debugging traces)
        wildcard_listeners = self._subscribers.get("*", [])
        
        all_listeners = listeners + wildcard_listeners
        
        if not all_listeners:
            logger.debug("[EventBus] No subscribers found for event: '%s'", event.event_type)
            return

        for listener in all_listeners:
            try:
                await listener(event)
            except Exception as e:
                logger.exception(
                    "[EventBus ERROR] Listener '%s' failed processing event '%s': %s", 
                    getattr(listener, "__name__", str(listener)), 
                    event.event_type, 
                    e
                )
