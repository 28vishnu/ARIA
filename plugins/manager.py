import logging
from typing import Dict, Any, List
from plugins.base import BasePlugin
from plugins.registry import CapabilityRegistry
from plugins.permissions import PluginPermissionManager
from plugins.sandbox import PluginSandbox
from plugins.lifecycle import LifecycleManager
from plugins.loader import DependencyResolver

logger = logging.getLogger("aria")

class PluginManager:
    def __init__(self):
        self.plugins: Dict[str, BasePlugin] = {}
        self.registry = CapabilityRegistry()
        self.permissions = PluginPermissionManager()
        self.sandbox = PluginSandbox()
        self.failure_counts: Dict[str, int] = {}

    async def register_and_load(self, plugin: BasePlugin, context: Dict[str, Any]) -> bool:
        """Discovers, validates permissions, and loads a plugin into the ecosystem."""
        pid = plugin.manifest.id
        self.plugins[pid] = plugin

        # Grant declared permissions automatically or via policy prompt
        for perm in plugin.manifest.permissions:
            self.permissions.grant_permission(pid, perm)

        # Transition state to loaded then running
        if await LifecycleManager.transition_state(plugin, "loaded"):
            if await LifecycleManager.transition_state(plugin, "running", context):
                # Register capabilities
                for cap in plugin.manifest.capabilities:
                    self.registry.register_capability(cap, plugin)
                return True
        return False

    async def execute_plugin_action(self, plugin_id: str, action_func, *args, **kwargs) -> Any:
        """Executes plugin actions inside a secure sandbox with failure tracking and auto-disable policies."""
        if plugin_id not in self.plugins:
            raise KeyError(f"Plugin '{plugin_id}' not loaded.")

        if self.failure_counts.get(plugin_id, 0) >= 3:
            logger.error("[PluginManager] Plugin '%s' disabled due to repeated operational failures.", plugin_id)
            await LifecycleManager.transition_state(self.plugins[plugin_id], "disabled")
            raise RuntimeError(f"Plugin {plugin_id} is disabled due to instability.")

        try:
            result = await self.sandbox.execute_isolated(plugin_id, action_func, *args, **kwargs)
            # Reset failure counter on successful execution
            self.failure_counts[plugin_id] = 0
            return result
        except Exception:
            self.failure_counts[plugin_id] = self.failure_counts.get(plugin_id, 0) + 1
            raise
