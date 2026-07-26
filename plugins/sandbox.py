import logging
import asyncio
import time
from typing import Callable, Any

logger = logging.getLogger("aria")

class PluginSandbox:
    def __init__(self, timeout_seconds: float = 10.0):
        self.timeout = timeout_seconds

    async def execute_isolated(self, plugin_id: str, func: Callable[..., Any], *args, **kwargs) -> Any:
        """Executes plugin code with strict timeout limits and exception containment."""
        start_time = time.perf_counter()
        try:
            async def _run():
                return await func(*args, **kwargs)

            result = await asyncio.wait_for(_run(), timeout=self.timeout)
            return result
        except asyncio.TimeoutError:
            logger.error("[PluginSandbox] Plugin '%s' execution timed out after %.1fs", plugin_id, self.timeout)
            raise RuntimeError(f"Plugin execution timeout: {plugin_id}")
        except Exception as e:
            logger.exception("[PluginSandbox ERROR] Plugin '%s' crashed during execution: %s", plugin_id, e)
            raise e
