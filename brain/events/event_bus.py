import asyncio
import logging
from collections import defaultdict

logger = logging.getLogger("aria")


# =========================================================
# EVENT NAME CONSTANTS
# =========================================================

GOAL_CREATED = "goal_created"
PLAN_CREATED = "plan_created"
AGENT_SELECTED = "agent_selected"
TASK_STARTED = "TASK_STARTED"
TASK_COMPLETED = "TASK_COMPLETED"
TASK_FAILED = "TASK_FAILED"
TASK_RETRY = "TASK_RETRY"
GOAL_COMPLETED = "GOAL_COMPLETED"

TASK_FINISHED = "TASK_FINISHED"
WORKFLOW_PROGRESS = "WORKFLOW_PROGRESS"
PLAN_UPDATED = "PLAN_UPDATED"
GOAL_FAILED = "GOAL_FAILED"
REPLAN_STARTED = "REPLAN_STARTED"
REPLAN_FINISHED = "REPLAN_FINISHED"


class EventBus:
    """
    Central communication system.

    Every subsystem communicates through EventBus.

    Nobody talks directly anymore.
    """

    def __init__(self):

        self.listeners = defaultdict(list)
        self._subscribers = defaultdict(list)

        self.history = []
        self.max_history = 1000

        self.statistics = {

            "events": 0,

            "errors": 0,

            "listeners": 0,

        }

    ####################################################

    def register_listener(
        self,
        event_type,
        listener,
    ):

        if listener not in self.listeners[event_type]:

            self.listeners[event_type].append(listener)

            self.statistics["listeners"] += 1

            logger.info(
                "[EventBus] Registered %s -> %s",
                listener.__class__.__name__,
                event_type,
            )

    ####################################################

    def unregister_listener(
        self,
        event_type,
        listener,
    ):

        if listener in self.listeners[event_type]:

            self.listeners[event_type].remove(listener)

            self.statistics["listeners"] -= 1

    ####################################################

    def publish_safe(self, event_name: str, payload=None):
        """
        Safe synchronous publish method for dictionary payloads and simple handlers.
        """
        payload = payload or {}

        logger.info(
            "[EventBus] %s",
            event_name
        )

        handlers = self._subscribers.get(event_name, [])

        for handler in handlers:
            try:
                handler(payload)
            except Exception as e:
                logger.exception(
                    "Event handler failed for %s: %s",
                    event_name,
                    e
                )

    ####################################################

    async def publish(
        self,
        event,
    ):
        self.history.append(event)

        if len(self.history) > self.max_history:
            self.history.pop(0)

        self.statistics["events"] += 1

        logger.info(
            "[EventBus] %s",
            getattr(event, "type", str(event))
        )

        listeners = self.listeners.get(
            event.type,
            [],
        )

        for listener in listeners:

            try:

                handler = getattr(listener, "handle", None)

                if callable(handler):
                    await handler(event)
                else:
                    logger.debug(
                        "%s ignored for event %s (no handle())",
                        listener.__class__.__name__,
                        event.type,
                    )

            except Exception as e:

                self.statistics["errors"] += 1

                logger.exception("[EventBus] Listener failed: %s", e)

    ####################################################

    async def publish_parallel(
        self,
        event,
    ):
        self.history.append(event)

        if len(self.history) > self.max_history:
            self.history.pop(0)

        self.statistics["events"] += 1

        logger.info(
            "[EventBus] %s",
            getattr(event, "type", str(event))
        )

        listeners = self.listeners.get(
            event.type,
            [],
        )

        tasks = []
        for listener in listeners:
            handler = getattr(listener, "handle", None)
            if callable(handler):
                tasks.append(asyncio.create_task(handler(event)))
            else:
                logger.debug(
                    "%s ignored for event %s (no handle())",
                    listener.__class__.__name__,
                    event.type,
                )

        if not tasks:
            return

        try:

            results = await asyncio.gather(
                *tasks,
                return_exceptions=True,
            )
            for res in results:
                if isinstance(res, Exception):
                    self.statistics["errors"] += 1
                    logger.exception("[EventBus] Listener failed: %s", res)

        except Exception as e:

            self.statistics["errors"] += 1

            logger.exception("[EventBus] Listener failed: %s", e)

    ####################################################

    def get_recent_events(self, limit=100):
        return self.history[-limit:]

    ####################################################

    def clear(self):

        self.listeners.clear()
        self._subscribers.clear()
        self.history.clear()

        self.statistics["listeners"] = 0

    ####################################################

    def summary(self):

        return {
            **self.statistics,
            "history_size": len(self.history),
        }
