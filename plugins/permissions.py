import logging

logger = logging.getLogger("aria")

class PluginPermissionManager:
    def __init__(self):
        # Permitted system scopes per plugin ID
        self.granted_permissions: dict[str, set[str]] = {}

    def grant_permission(self, plugin_id: str, permission: str):
        if plugin_id not in self.granted_permissions:
            self.granted_permissions[plugin_id] = set()
        self.granted_permissions[plugin_id].add(permission)
        logger.info("[PluginPermissions] Granted '%s' to plugin '%s'", permission, plugin_id)

    def verify(self, plugin_id: str, requested_permission: str) -> bool:
        allowed = requested_permission in self.granted_permissions.get(plugin_id, set())
        if not allowed:
            logger.warning("[PluginPermissions] BLOCKED: Plugin '%s' attempted ungranted permission '%s'", plugin_id, requested_permission)
        return allowed
