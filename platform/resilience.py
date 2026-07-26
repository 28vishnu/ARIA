import logging
import asyncio
from functools import wraps
from typing import Callable, Any

logger = logging.getLogger("aria")

def resilient_async_call(retries: int = 3, backoff_factor: float = 1.5):
    """Decorator providing exponential backoff retry logic for external API calls and resource reads."""
    def decorator(func: Callable[..., Any]):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            attempt = 0
            delay = 1.0
            while attempt < retries:
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    attempt += 1
                    if attempt >= retries:
                        logger.error("[Resilience] Operation '%s' failed after %d attempts. Error: %s", func.__name__, retries, e)
                        raise e
                    logger.warning("[Resilience] Operation '%s' failed (Attempt %d/%d). Retrying in %.1fs...", func.__name__, attempt, retries, delay)
                    await asyncio.sleep(delay)
                    delay *= backoff_factor
        return wrapper
    return decorator
