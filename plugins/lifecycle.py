import logging
from typing import Dict
from plugins.base import BasePlugin

logger = logging.getLogger("aria")

class LifecycleManager:
    @staticmethod
    async def transition_state(plugin: BasePlugin, target_state: str, context: Dict[str, Any] = None) -> bool:
        """Manages strict state transitions (installed -> loaded -> running -> paused -> disabled)."""
        current = plugin.status
        try:
            if target_state == "loaded" and current == "installed":
                plugin.status = "loaded"
                logger.info("[Lifecycle] Plugin '%s' loaded.", plugin.manifest.id)
                return True
            elif target_state == "running" and current in ["loaded", "paused"]:
                success = await plugin.initialize(context or {})
                if success:
                    plugin.status = "running"
                    logger.info("[Lifecycle] Plugin '%s' running.", plugin.manifest.id)
                    return True
            elif target_state == "paused" and current == "running":
                plugin.status = "paused"
                logger.info("[Lifecycle] Plugin '%s' paused.", plugin.manifest.id)
                return True
            elif target_state == "disabled" and current in ["running", "paused", "loaded"]:
                await plugin.shutdown()
                plugin.status = "disabled"
                logger.info("[Lifecycle] Plugin '%s' disabled.", plugin.manifest.id)
                return True
        except Exception as e:
            plugin.status = "error"
            logger.exception("[Lifecycle ERROR] Transition failed for plugin '%s': %s", plugin.manifest.id, e)
        return False
