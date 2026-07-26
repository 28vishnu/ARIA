import logging
import asyncio
from typing import Callable, Coroutine

logger = logging.getLogger("aria")

class BackgroundScheduler:
    def __init__(self):
        self.tasks = []

    def schedule_recurring(self, interval_seconds: float, coro_func: Callable[..., Coroutine], *args, **kwargs):
        """Schedules recurring background maintenance or monitoring jobs."""
        async def _wrapper():
            while True:
                await asyncio.sleep(interval_seconds)
                try:
                    await coro_func(*args, **kwargs)
                except Exception:
                    logger.exception("[BackgroundScheduler] Error in recurring job")

        task = asyncio.create_task(_wrapper())
        self.tasks.append(task)
        logger.info("[BackgroundScheduler] Scheduled recurring job (interval: %.1fs)", interval_seconds)
