import asyncio
import logging
from collections import defaultdict

logger = logging.getLogger("aria")


class EventBus:
    """
    Central communication system.

    Every subsystem communicates through EventBus.

    Nobody talks directly anymore.
    """

    def __init__(self):

        self.listeners = defaultdict(list)

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

    async def publish(
        self,
        event,
    ):
        self.history.append(event)

        if len(self.history) > self.max_history:
            self.history.pop(0)

        self.statistics["events"] += 1

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
        self.history.clear()

        self.statistics["listeners"] = 0

    ####################################################

    def summary(self):

        return {
            **self.statistics,
            "history_size": len(self.history),
        }


# =========================================================
# WORKFLOW & REPLAN EVENT CONSTANTS
# =========================================================

TASK_STARTED = "TASK_STARTED"
TASK_FINISHED = "TASK_FINISHED"
TASK_RETRY = "TASK_RETRY"
TASK_FAILED = "TASK_FAILED"

WORKFLOW_PROGRESS = "WORKFLOW_PROGRESS"

PLAN_UPDATED = "PLAN_UPDATED"

GOAL_COMPLETED = "GOAL_COMPLETED"

GOAL_FAILED = "GOAL_FAILED"

REPLAN_STARTED = "REPLAN_STARTED"

REPLAN_FINISHED = "REPLAN_FINISHED"
