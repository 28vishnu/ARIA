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

        self.statistics["events"] += 1

        listeners = self.listeners.get(
            event.type,
            [],
        )

        for listener in listeners:

            try:

                if hasattr(listener, "handle"):
                    await listener.handle(event)
                else:
                    logger.warning(
                        "%s has no handle() method",
                        listener.__class__.__name__,
                    )

            except Exception as e:

                self.statistics["errors"] += 1

                logger.exception("[EventBus] Listener failed: %s", e)

    ####################################################

    async def publish_parallel(
        self,
        event,
    ):

        self.statistics["events"] += 1

        listeners = self.listeners.get(
            event.type,
            [],
        )

        tasks = []
        for listener in listeners:
            if hasattr(listener, "handle"):
                tasks.append(listener.handle(event))
            else:
                logger.warning(
                    "%s has no handle() method",
                    listener.__class__.__name__,
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

    def clear(self):

        self.listeners.clear()

        self.statistics["listeners"] = 0

    ####################################################

    def summary(self):

        return self.statistics
