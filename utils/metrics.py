import time
import asyncio
import functools
import logging

logger = logging.getLogger("aria")

def timed_stage(stage_name: str):
    """Decorator to measure and log execution timing using structured logging."""
    def decorator(func):
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                res = await func(*args, **kwargs)
                elapsed = (time.perf_counter() - start) * 1000
                logger.info("[%s] .......... %.1f ms", stage_name, elapsed)
                return res
            except Exception:
                elapsed = (time.perf_counter() - start) * 1000
                logger.exception("[%s ERROR] (%.1f ms) Failed execution", stage_name, elapsed)
                raise
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                res = func(*args, **kwargs)
                elapsed = (time.perf_counter() - start) * 1000
                logger.info("[%s] .......... %.1f ms", stage_name, elapsed)
                return res
            except Exception:
                elapsed = (time.perf_counter() - start) * 1000
                logger.exception("[%s ERROR] (%.1f ms) Failed execution", stage_name, elapsed)
                raise
        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
    return decorator
